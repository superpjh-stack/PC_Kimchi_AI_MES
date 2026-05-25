"""
꽃순이김치 제조AI MES — 데이터베이스 연결 관리
Project: SF26179540 | 로뎀솔루션

asyncpg 커넥션 풀 기반 DB 컨텍스트 매니저.

환경변수(또는 .env) — 우선순위:
    1) DATABASE_URL  운영DB 전체 DSN (있으면 개별 DB_* 보다 우선)
       예) postgresql://mes_user:mes_pass@db:5432/kimchi_mes
    2) 개별 변수 (DATABASE_URL 미설정 시 조합)
       DB_HOST  PostgreSQL 호스트 (기본: localhost)
       DB_PORT  포트 (기본: 5432)
       DB_NAME  데이터베이스명 (기본: kimchi_mes)
       DB_USER  사용자명 (기본: mesuser)
       DB_PASS  비밀번호 (기본: mespass)

    VECTOR_DB_URL  pgvector(Vector DB) DSN — RAG 검색용 (선택)
       예) postgresql://mes_user:mes_pass@vector-db:5432/vector_db
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg

# ─── 환경변수 설정 ────────────────────────────────────────────────────────────
# 개별 DB_* 변수 (DATABASE_URL 미설정 시 조합용)
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "kimchi_mes")
DB_USER = os.getenv("DB_USER", "mesuser")
DB_PASS = os.getenv("DB_PASS", "mespass")

# 운영DB DSN: DATABASE_URL 우선, 없으면 개별 변수로 조합
DB_DSN = os.getenv(
    "DATABASE_URL",
    f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
)

# Vector DB(pgvector) DSN — RAG Agent 검색용. 미설정 시 None.
VECTOR_DB_URL = os.getenv("VECTOR_DB_URL")

# ─── 글로벌 커넥션 풀 ─────────────────────────────────────────────────────────
_pool: asyncpg.Pool | None = None          # 운영 DB 풀
_vector_pool: asyncpg.Pool | None = None   # Vector DB 풀 (선택)


def _log(msg: str) -> None:
    """Windows cp949 환경에서 안전한 콘솔 출력."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


def _mask_dsn(dsn: str) -> str:
    """로그 출력용으로 DSN의 비밀번호를 가린다."""
    try:
        # postgresql://user:pass@host:port/db → user:***@host:port/db
        head, _, tail = dsn.partition("://")
        creds, _, hostpart = tail.partition("@")
        if ":" in creds:
            user = creds.split(":", 1)[0]
            return f"{head}://{user}:***@{hostpart}"
        return dsn
    except Exception:
        return "(dsn)"


async def init_pool() -> None:
    """
    앱 시작 시 커넥션 풀 초기화 (lifespan에서 호출).

    운영 DB 풀은 필수, Vector DB 풀은 VECTOR_DB_URL이 있을 때만 생성한다.
    DB 미가동 환경에서도 앱이 기동되도록 실패를 흡수한다(엔드포인트가 503 반환).
    """
    global _pool, _vector_pool

    # ── 운영 DB ──
    try:
        _pool = await asyncpg.create_pool(
            dsn=DB_DSN,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        _log(f"[DB] 운영 DB 풀 초기화 완료: {_mask_dsn(DB_DSN)}")
    except Exception as e:
        _log(f"[DB] 운영 DB 연결 실패 (DB 없이 시작) : {type(e).__name__}")
        _pool = None

    # ── Vector DB (선택) ──
    if VECTOR_DB_URL:
        try:
            _vector_pool = await asyncpg.create_pool(
                dsn=VECTOR_DB_URL,
                min_size=1,
                max_size=5,
                command_timeout=30,
            )
            _log(f"[DB] Vector DB 풀 초기화 완료: {_mask_dsn(VECTOR_DB_URL)}")
        except Exception as e:
            _log(f"[DB] Vector DB 연결 실패 (RAG 비활성) : {type(e).__name__}")
            _vector_pool = None


async def close_pool() -> None:
    """앱 종료 시 커넥션 풀 정리."""
    global _pool, _vector_pool
    if _pool:
        await _pool.close()
        _log("[DB] 운영 DB 풀 종료")
        _pool = None
    if _vector_pool:
        await _vector_pool.close()
        _log("[DB] Vector DB 풀 종료")
        _vector_pool = None


async def ping() -> bool:
    """
    운영 DB 헬스체크용 — 'SELECT 1' 을 실행해 연결 가능 여부를 반환.
    헬스체크(GET /health)에서 사용한다. 예외는 False로 흡수한다.
    """
    if _pool is None:
        return False
    try:
        async with _pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False


@asynccontextmanager
async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    """
    DB 커넥션 컨텍스트 매니저.

    사용법:
        async with get_db() as conn:
            rows = await conn.fetch("SELECT ...")

    DB가 없으면 RuntimeError 발생 → 각 엔드포인트에서 503 처리.
    """
    if _pool is None:
        raise RuntimeError("DB 연결 없음 — PostgreSQL이 실행 중인지 확인하세요.")
    async with _pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def get_vector_db() -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Vector DB(pgvector) 커넥션 컨텍스트 매니저 — RAG 검색용.

    사용법:
        async with get_vector_db() as conn:
            rows = await conn.fetch("SELECT ... ORDER BY embedding <=> $1 ...")

    VECTOR_DB_URL 미설정/미연결 시 RuntimeError → 엔드포인트에서 503 처리.
    """
    if _vector_pool is None:
        raise RuntimeError(
            "Vector DB 연결 없음 — VECTOR_DB_URL 설정 및 pgvector 가동을 확인하세요."
        )
    async with _vector_pool.acquire() as conn:
        yield conn
