"""
꽃순이김치 제조AI MES — pgvector 기반 Vector Store
프로젝트: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션

역할:
    - OpenAI text-embedding-3-small (1536차원) 임베딩 생성
    - pgvector 코사인 유사도 검색 (ivfflat 인덱스, embedding <=> query)
    - 문서 타입(doc_type)별 필터링 검색
    - 문서 청킹 → 임베딩 → document_embeddings 적재

대상 테이블 (db/init.sql 14번):
    document_embeddings(
        doc_id BIGINT PK, doc_name VARCHAR(200), doc_type VARCHAR(30),
        version VARCHAR(10), chunk_index INT, content TEXT,
        embedding VECTOR(1536), created_at TIMESTAMP)
    인덱스: ivfflat (embedding vector_cosine_ops), idx_doc_type

환경변수:
    VECTOR_DB_URL   pgvector DSN
                    예) postgresql://mes_user:mes_pass@vector-db:5432/vector_db
    OPENAI_API_KEY  OpenAI API 키 (임베딩 생성)
    EMBEDDING_MODEL 임베딩 모델 (기본 text-embedding-3-small)

설계 원칙 (CLAUDE.md / rag-agent-mes 스킬):
    1. 모든 검색은 doc_type 필터 적용 가능 (관련 없는 문서 검색 방지)
    2. 코사인 거리 → 유사도 점수 변환 (score = 1 - distance)
    3. score_threshold 미만 결과 제거 (환각 방지: 근거 약한 문서 배제)
    4. OpenAI 호출 실패 시 명확한 예외 → Agent 단에서 fallback 처리
"""
from __future__ import annotations

import logging
import os
from typing import Any

import asyncpg

logger = logging.getLogger("rag.vector_store")

# ─── 환경변수 ──────────────────────────────────────────────────────────────
VECTOR_DB_URL = os.getenv(
    "VECTOR_DB_URL",
    "postgresql://mes_user:mes_pass@vector-db:5432/vector_db",
)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = 1536  # text-embedding-3-small 차원

# document_embeddings.doc_type 표준 어휘 (ai_document_index 기준)
#   SOP            작업표준서
#   QUALITY_STANDARD 품질기준서 / 출하 승인 기준서
#   HACCP          HACCP CCP 관리 문서
#   MANUAL         설비 운영 매뉴얼
#   CLAIM          클레임 대응 매뉴얼
VALID_DOC_TYPES = ("SOP", "QUALITY_STANDARD", "HACCP", "MANUAL", "CLAIM")


class KimchiVectorStore:
    """pgvector 비동기 Vector Store.

    사용법:
        store = KimchiVectorStore()
        await store.connect()
        docs = await store.similarity_search("배추 입고 기준", doc_types=["SOP"])
        await store.close()

    또는 컨텍스트 매니저:
        async with KimchiVectorStore() as store:
            docs = await store.similarity_search(...)
    """

    def __init__(
        self,
        dsn: str | None = None,
        embedding_model: str = EMBEDDING_MODEL,
    ) -> None:
        self.dsn = dsn or VECTOR_DB_URL
        self.embedding_model = embedding_model
        self._pool: asyncpg.Pool | None = None
        self._openai = None  # lazy init (AsyncOpenAI)

    # ── 연결 수명주기 ──────────────────────────────────────────────────────
    async def connect(self) -> None:
        """커넥션 풀 생성. 이미 연결돼 있으면 무시."""
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(
            dsn=self.dsn,
            min_size=1,
            max_size=5,
            command_timeout=30,
        )
        logger.info("[VectorStore] pgvector 연결 풀 초기화 완료")

    async def close(self) -> None:
        """커넥션 풀 종료."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("[VectorStore] pgvector 연결 풀 종료")

    async def __aenter__(self) -> "KimchiVectorStore":
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # ── OpenAI 임베딩 ──────────────────────────────────────────────────────
    def _get_openai(self):
        """AsyncOpenAI 클라이언트 lazy 초기화 (OPENAI_API_KEY 필요)."""
        if self._openai is None:
            from openai import AsyncOpenAI  # 지연 임포트 (테스트 시 미설치 대비)

            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY 환경변수가 없습니다 — 임베딩 생성 불가."
                )
            self._openai = AsyncOpenAI(api_key=api_key)
        return self._openai

    async def _embed(self, text: str) -> list[float]:
        """단일 텍스트 → 1536차원 임베딩 벡터.

        OpenAI API 실패 시 RuntimeError 발생 (호출부에서 fallback).
        """
        client = self._get_openai()
        try:
            resp = await client.embeddings.create(
                model=self.embedding_model,
                input=text.replace("\n", " ").strip()[:8000],  # 토큰 한도 보호
            )
        except Exception as e:  # noqa: BLE001 — OpenAI 예외 다양 → 통합 래핑
            logger.error("[VectorStore] 임베딩 생성 실패: %s", e)
            raise RuntimeError(f"임베딩 생성 실패: {e}") from e
        return resp.data[0].embedding

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """다건 텍스트 → 임베딩 벡터 목록 (적재용, 1회 API 호출)."""
        client = self._get_openai()
        cleaned = [t.replace("\n", " ").strip()[:8000] for t in texts]
        try:
            resp = await client.embeddings.create(
                model=self.embedding_model, input=cleaned
            )
        except Exception as e:  # noqa: BLE001
            logger.error("[VectorStore] 배치 임베딩 실패: %s", e)
            raise RuntimeError(f"배치 임베딩 실패: {e}") from e
        # OpenAI는 입력 순서를 보장하지만 index 기준으로 정렬해 안전 확보
        ordered = sorted(resp.data, key=lambda d: d.index)
        return [d.embedding for d in ordered]

    @staticmethod
    def _to_pgvector(vec: list[float]) -> str:
        """list[float] → pgvector 리터럴 문자열 '[0.1,0.2,...]'."""
        return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"

    # ── 유사도 검색 ────────────────────────────────────────────────────────
    async def similarity_search(
        self,
        query: str,
        doc_types: list[str] | None = None,
        k: int = 5,
        score_threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """쿼리 임베딩 → 코사인 거리 검색 (embedding <=> query).

        Args:
            query: 자연어 검색 질의
            doc_types: 검색 대상 doc_type 목록 (예: ['SOP','QUALITY_STANDARD']).
                       None이면 전체 문서 대상.
            k: 반환 문서 수
            score_threshold: 유사도(=1-거리) 하한. 미만은 제거(환각 방지).

        Returns:
            [{doc_id, title, content, doc_type, version, score, chunk_index}, ...]
            점수 내림차순 정렬. 결과 없으면 빈 리스트.
        """
        if self._pool is None:
            await self.connect()

        query_vec = await self._embed(query)
        vec_literal = self._to_pgvector(query_vec)

        # 코사인 거리(<=>): 0=동일, 2=정반대. 유사도 = 1 - 거리.
        params: list[Any] = [vec_literal]
        where = ""
        if doc_types:
            params.append(doc_types)
            where = "WHERE doc_type = ANY($2::text[])"

        params.append(k)
        limit_idx = len(params)

        sql = f"""
            SELECT
                doc_id,
                doc_name,
                doc_type,
                version,
                chunk_index,
                content,
                1 - (embedding <=> $1::vector) AS score
            FROM document_embeddings
            {where}
            ORDER BY embedding <=> $1::vector
            LIMIT ${limit_idx}
        """

        assert self._pool is not None
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        results: list[dict[str, Any]] = []
        for r in rows:
            score = float(r["score"]) if r["score"] is not None else 0.0
            if score < score_threshold:
                continue  # 근거 약한 문서 배제 (환각 방지)
            results.append(
                {
                    "doc_id": r["doc_id"],
                    "title": r["doc_name"],
                    "content": r["content"],
                    "doc_type": r["doc_type"],
                    "version": r["version"],
                    "chunk_index": r["chunk_index"],
                    "score": round(score, 4),
                }
            )
        logger.info(
            "[VectorStore] 검색 '%s' (doc_types=%s) → %d/%d건 (threshold=%.2f)",
            query[:40],
            doc_types,
            len(results),
            len(rows),
            score_threshold,
        )
        return results

    # ── 문서 적재 ──────────────────────────────────────────────────────────
    @staticmethod
    def _chunk_text(
        text: str, chunk_size: int = 500, overlap: int = 50
    ) -> list[str]:
        """문자 단위 슬라이딩 윈도우 청킹.

        한국어 문서 특성상 토큰 기반 분할 대신 문자 길이 기준 + 문단 경계
        우선 분할로 단순화한다. overlap으로 청크 경계 문맥 손실을 완화.
        """
        text = text.strip()
        if not text:
            return []
        if len(text) <= chunk_size:
            return [text]

        chunks: list[str] = []
        start = 0
        n = len(text)
        step = max(1, chunk_size - overlap)
        while start < n:
            end = min(start + chunk_size, n)
            # 가능하면 문장/문단 경계(개행, 마침표)에서 끊어 가독성 확보
            if end < n:
                window = text[start:end]
                for sep in ("\n", ". ", "다.", "음.", " "):
                    pos = window.rfind(sep)
                    if pos > chunk_size * 0.5:  # 너무 앞이면 무시
                        end = start + pos + len(sep)
                        break
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start += step
            if end >= n:
                break
        return chunks

    async def add_document(
        self,
        doc_type: str,
        title: str,
        content: str,
        source_file: str = "",
        version: str = "1.0",
    ) -> int:
        """문서 청킹 → 임베딩 → document_embeddings INSERT.

        Returns:
            적재된 청크 수.
        """
        if self._pool is None:
            await self.connect()

        if doc_type not in VALID_DOC_TYPES:
            logger.warning(
                "[VectorStore] 비표준 doc_type '%s' (허용: %s)",
                doc_type,
                VALID_DOC_TYPES,
            )

        chunks = self._chunk_text(content, chunk_size=500, overlap=50)
        if not chunks:
            logger.warning("[VectorStore] '%s' 청크 없음 — 적재 생략", title)
            return 0

        embeddings = await self._embed_batch(chunks)

        rows = [
            (
                title,
                doc_type,
                version,
                idx,
                chunk,
                self._to_pgvector(emb),
            )
            for idx, (chunk, emb) in enumerate(zip(chunks, embeddings))
        ]

        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO document_embeddings
                    (doc_name, doc_type, version, chunk_index, content, embedding)
                VALUES ($1, $2, $3, $4, $5, $6::vector)
                """,
                rows,
            )
        logger.info(
            "[VectorStore] 적재 완료: '%s' (%s) → %d 청크 [src=%s]",
            title,
            doc_type,
            len(rows),
            source_file or "-",
        )
        return len(rows)

    async def delete_document(self, title: str) -> int:
        """문서명 기준 전체 청크 삭제 (재임베딩 전 정리용). 삭제 건수 반환."""
        if self._pool is None:
            await self.connect()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM document_embeddings WHERE doc_name = $1", title
            )
        # "DELETE N" 형태 → N 파싱
        try:
            deleted = int(result.split()[-1])
        except (ValueError, IndexError):
            deleted = 0
        logger.info("[VectorStore] '%s' 청크 %d건 삭제", title, deleted)
        return deleted

    async def count_documents(self, doc_type: str | None = None) -> int:
        """적재된 청크 수 조회 (헬스체크/검증용)."""
        if self._pool is None:
            await self.connect()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            if doc_type:
                return await conn.fetchval(
                    "SELECT COUNT(*) FROM document_embeddings WHERE doc_type = $1",
                    doc_type,
                )
            return await conn.fetchval("SELECT COUNT(*) FROM document_embeddings")


# ─── 모듈 전역 싱글턴 (Agent 간 풀 공유) ────────────────────────────────────
_store: KimchiVectorStore | None = None


async def get_vector_store() -> KimchiVectorStore:
    """전역 Vector Store 싱글턴 반환 (지연 연결)."""
    global _store
    if _store is None:
        _store = KimchiVectorStore()
        await _store.connect()
    return _store
