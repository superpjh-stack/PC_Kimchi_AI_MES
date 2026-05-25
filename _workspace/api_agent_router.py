"""
꽃순이김치 제조AI 스마트공장 MES — AI Agent 통합관리 API 라우터
프로젝트: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션

prefix: /api/v1/agent
기획서 7장(AI Agent 통합관리) + db_agent_schema.sql 기준.

구성:
  - AI 질의       : POST /query, GET /query/history, GET /query/{id},
                    PATCH /query/{id}/feedback, PATCH /query/{id}/approve
  - 추천/의사결정 : GET /recommendations, GET /recommendations/active,
                    PATCH /recommendations/{id}/action
  - AI 상태       : GET /status, PATCH /status/{component}
  - 문서 인덱스   : GET /documents
  - 사용 통계     : GET /analytics/usage, GET /analytics/top-queries

설계 원칙:
  1. 모든 조회 엔드포인트는 LOT ID 기반 필터링을 지원한다(context_lots / lot_id).
  2. RAG/ML 결과는 본 AI 전용 prefix(/api/v1/agent)로 분리한다.
  3. 비동기(async/await + asyncpg)를 기본으로 사용한다.
  4. Pydantic v2 모델로 요청/응답 스키마를 정의한다.

✅ RAG 연동: rag.agent_router.run_rag_agent() (LangChain/LangGraph) 실연동 완료.
   AI Server(OPENAI_API_KEY, VECTOR_DB_URL) 환경변수 설정 시 즉시 동작한다.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.database import get_db
from app.auth import CurrentUser, get_current_user, require_role
from rag.agent_router import run_rag_agent  # LangChain/LangGraph RAG Agent 실연동

router = APIRouter(prefix="/api/v1/agent", tags=["AI Agent 통합관리"])

AGENT_TYPES = ("INTAKE", "SHIPPING", "INTEGRATED")
COMPONENTS = ("INTAKE_AGENT", "SHIPPING_AGENT", "ML_ENGINE", "VECTOR_DB")


# =====================================================================
# Pydantic v2 모델
# =====================================================================
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="사용자 자연어 질의")
    agent_type: Literal["INTAKE", "SHIPPING", "INTEGRATED"]
    session_id: str | None = Field(None, description="대화 세션 식별자(미지정 시 자동 생성)")
    context_lots: list[str] | None = Field(None, description="질의 연관 LOT ID 목록")


class ReferencedDoc(BaseModel):
    title: str
    doc_type: str
    score: float


class QueryResponse(BaseModel):
    query_id: int
    session_id: str
    agent_type: str
    response_text: str
    referenced_docs: list[ReferencedDoc]
    response_time_ms: int


class FeedbackRequest(BaseModel):
    feedback_score: int = Field(..., ge=1, le=5, description="만족도 1~5")


class ApproveRequest(BaseModel):
    is_approved: bool = Field(..., description="True=승인 / False=거절")
    approved_by: str = Field(..., description="승인/거절 처리자")


class ActionRequest(BaseModel):
    actioned_by: str = Field(..., description="추천 처리자")


class StatusUpdate(BaseModel):
    status: Literal["ONLINE", "OFFLINE", "ERROR", "DEGRADED"]
    avg_response_ms: int | None = None
    error_count_1h: int | None = None
    error_message: str | None = None


# =====================================================================
# RAG Agent 실연동 (rag.agent_router.run_rag_agent)
# _rag_stub 은 제거되었다. 환경변수 미설정 시 rag.agent_router 내부 fallback 동작.
# 필수 환경변수: OPENAI_API_KEY, VECTOR_DB_URL
# =====================================================================


async def _touch_component_status(conn, component: str, response_ms: int) -> None:
    """질의 처리 후 해당 Agent 컴포넌트의 last_query_at / avg_response_ms 갱신."""
    await conn.execute(
        """
        UPDATE ai_system_status
        SET last_query_at = NOW(),
            avg_response_ms = COALESCE(
                (avg_response_ms + $2) / 2, $2
            ),
            checked_at = NOW()
        WHERE component = $1
        """,
        component,
        response_ms,
    )


# =====================================================================
# AI 질의
# =====================================================================
@router.post("/query", response_model=QueryResponse, status_code=201)
async def run_query(
    data: QueryRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    AI 질의 실행.
    1) ai_query_history INSERT (응답 전 PENDING 상태로 row 생성)
    2) RAG Agent 호출 (LangChain/LangGraph 실연동 — rag.agent_router.run_rag_agent)
    3) 응답/지연/참조문서 저장 후 반환
    """
    session_id = data.session_id or f"sess-{uuid.uuid4().hex[:12]}"
    started = time.perf_counter()

    async with get_db() as conn:
        # 1) PENDING row 생성 (응답 전)
        query_id = await conn.fetchval(
            """
            INSERT INTO ai_query_history
                (session_id, user_id, agent_type, query_text, context_lots, referenced_docs)
            VALUES ($1, $2, $3, $4, $5, '[]'::jsonb)
            RETURNING query_id
            """,
            session_id,
            current_user.user_id,
            data.agent_type,
            data.query,
            data.context_lots,
        )

        # 2) RAG Agent 호출 (LangChain/LangGraph 실연동)
        #    run_rag_agent 내부에서 예외를 흡수하므로 502 가 발생하지 않는다.
        #    OPENAI_API_KEY / VECTOR_DB_URL 미설정 시 안내 문구 + 빈 출처를 반환.
        try:
            response_text, ref_docs = await run_rag_agent(
                data.query, data.agent_type, session_id
            )
        except Exception as e:  # 예상치 못한 오류만 여기서 포착
            raise HTTPException(status_code=502, detail=f"RAG Agent 호출 실패: {e}") from e

        response_ms = int((time.perf_counter() - started) * 1000)

        # 3) 응답 저장
        await conn.execute(
            """
            UPDATE ai_query_history
            SET response_text = $2,
                response_time_ms = $3,
                referenced_docs = $4::jsonb
            WHERE query_id = $1
            """,
            query_id,
            response_text,
            response_ms,
            json.dumps(ref_docs),
        )

        # 컴포넌트 상태 갱신 (best-effort)
        component = {
            "INTAKE": "INTAKE_AGENT",
            "SHIPPING": "SHIPPING_AGENT",
            "INTEGRATED": "ML_ENGINE",
        }[data.agent_type]
        await _touch_component_status(conn, component, response_ms)

    return QueryResponse(
        query_id=query_id,
        session_id=session_id,
        agent_type=data.agent_type,
        response_text=response_text,
        referenced_docs=[ReferencedDoc(**d) for d in ref_docs],
        response_time_ms=response_ms,
    )


@router.get("/query/history")
async def get_query_history(
    agent_type: str | None = Query(None, description="INTAKE/SHIPPING/INTEGRATED"),
    user_id: int | None = Query(None),
    lot_id: str | None = Query(None, description="연관 LOT ID 필터(context_lots 포함 검색)"),
    date_from: datetime | None = Query(None),
    limit: int = Query(50, le=500),
):
    """질의 이력 조회 (에이전트/사용자/LOT/기간 필터)."""
    conds: list[str] = []
    params: list[Any] = []
    idx = 1
    if agent_type:
        conds.append(f"agent_type = ${idx}"); params.append(agent_type); idx += 1
    if user_id is not None:
        conds.append(f"user_id = ${idx}"); params.append(user_id); idx += 1
    if lot_id:
        conds.append(f"${idx} = ANY(context_lots)"); params.append(lot_id); idx += 1
    if date_from:
        conds.append(f"created_at >= ${idx}"); params.append(date_from); idx += 1
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    params.append(limit)
    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT query_id, session_id, user_id, agent_type, query_text, response_text,
                   response_time_ms, context_lots, referenced_docs, is_approved,
                   approved_by, approved_at, feedback_score, created_at
            FROM ai_query_history
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx}
            """,
            *params,
        )
    return [dict(r) for r in rows]


@router.get("/query/{query_id}")
async def get_query_detail(query_id: int):
    """질의 상세 조회."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ai_query_history WHERE query_id = $1", query_id
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"질의 {query_id} 없음")
    return dict(row)


@router.patch("/query/{query_id}/feedback")
async def submit_feedback(query_id: int, data: FeedbackRequest):
    """질의 만족도 평가 (1~5)."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            UPDATE ai_query_history
            SET feedback_score = $2
            WHERE query_id = $1
            RETURNING query_id, feedback_score
            """,
            query_id,
            data.feedback_score,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"질의 {query_id} 없음")
    return {"query_id": row["query_id"], "feedback_score": row["feedback_score"], "message": "평가 완료"}


@router.patch("/query/{query_id}/approve", dependencies=[Depends(require_role("ADMIN", "MANAGER"))])
async def approve_query(query_id: int, data: ApproveRequest):
    """의사결정 승인/거절 (MANAGER 이상)."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            UPDATE ai_query_history
            SET is_approved = $2,
                approved_by = $3,
                approved_at = NOW()
            WHERE query_id = $1
            RETURNING query_id, is_approved, approved_by, approved_at
            """,
            query_id,
            data.is_approved,
            data.approved_by,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"질의 {query_id} 없음")
    return {
        "query_id": row["query_id"],
        "is_approved": row["is_approved"],
        "approved_by": row["approved_by"],
        "approved_at": row["approved_at"],
        "message": "승인 처리 완료" if row["is_approved"] else "거절 처리 완료",
    }


# =====================================================================
# 추천 / 의사결정 지원
# =====================================================================
@router.get("/recommendations")
async def list_recommendations(
    agent_type: str | None = Query(None),
    rec_type: str | None = Query(None),
    is_actioned: bool | None = Query(None),
    priority: str | None = Query(None, description="LOW/NORMAL/HIGH/CRITICAL"),
    lot_id: str | None = Query(None, description="관련 LOT ID 필터"),
    limit: int = Query(20, le=200),
):
    """추천 목록 조회 (에이전트/유형/처리여부/우선순위/LOT 필터)."""
    conds: list[str] = []
    params: list[Any] = []
    idx = 1
    if agent_type:
        conds.append(f"agent_type = ${idx}"); params.append(agent_type); idx += 1
    if rec_type:
        conds.append(f"rec_type = ${idx}"); params.append(rec_type); idx += 1
    if is_actioned is not None:
        conds.append(f"is_actioned = ${idx}"); params.append(is_actioned); idx += 1
    if priority:
        conds.append(f"priority = ${idx}"); params.append(priority); idx += 1
    if lot_id:
        conds.append(f"lot_id = ${idx}"); params.append(lot_id); idx += 1
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    params.append(limit)
    async with get_db() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM ai_recommendation {where} ORDER BY created_at DESC LIMIT ${idx}",
            *params,
        )
    return [dict(r) for r in rows]


@router.get("/recommendations/active")
async def list_active_recommendations(limit: int = Query(20, le=200)):
    """미처리 고우선순위 추천 (priority IN HIGH/CRITICAL, is_actioned=FALSE)."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM ai_recommendation
            WHERE is_actioned = FALSE
              AND priority IN ('HIGH', 'CRITICAL')
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY
                CASE priority WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 ELSE 2 END,
                created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


@router.patch("/recommendations/{rec_id}/action")
async def action_recommendation(rec_id: int, data: ActionRequest):
    """추천 처리 완료 (is_actioned=TRUE)."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            UPDATE ai_recommendation
            SET is_actioned = TRUE,
                actioned_by = $2,
                actioned_at = NOW()
            WHERE rec_id = $1
            RETURNING rec_id, is_actioned, actioned_by, actioned_at
            """,
            rec_id,
            data.actioned_by,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"추천 {rec_id} 없음")
    return {
        "rec_id": row["rec_id"],
        "is_actioned": row["is_actioned"],
        "actioned_by": row["actioned_by"],
        "actioned_at": row["actioned_at"],
        "message": "추천 처리 완료",
    }


# =====================================================================
# AI 컴포넌트 상태
# =====================================================================
@router.get("/status")
async def get_ai_status():
    """AI 컴포넌트 상태 (4개 전체). 연결 신선도(stale) 판정 포함."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT *,
                   (last_query_at IS NOT NULL
                    AND last_query_at >= NOW() - INTERVAL '15 minutes') AS is_recent
            FROM ai_system_status
            ORDER BY
                CASE component
                    WHEN 'INTAKE_AGENT'   THEN 0
                    WHEN 'SHIPPING_AGENT' THEN 1
                    WHEN 'ML_ENGINE'      THEN 2
                    WHEN 'VECTOR_DB'      THEN 3
                END
            """
        )
    return [dict(r) for r in rows]


@router.patch("/status/{component}", dependencies=[Depends(require_role("ADMIN"))])
async def update_ai_status(component: str, data: StatusUpdate):
    """AI 컴포넌트 상태 업데이트 (AI Server → MES 헬스체크). UPSERT."""
    if component not in COMPONENTS:
        raise HTTPException(status_code=400, detail=f"알 수 없는 컴포넌트: {component}")
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO ai_system_status
                (component, status, avg_response_ms, error_count_1h, error_message, checked_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (component) DO UPDATE SET
                status = EXCLUDED.status,
                avg_response_ms = COALESCE(EXCLUDED.avg_response_ms, ai_system_status.avg_response_ms),
                error_count_1h = COALESCE(EXCLUDED.error_count_1h, ai_system_status.error_count_1h),
                error_message = EXCLUDED.error_message,
                checked_at = NOW()
            RETURNING *
            """,
            component,
            data.status,
            data.avg_response_ms,
            data.error_count_1h,
            data.error_message,
        )
    return dict(row)


# =====================================================================
# Vector DB 문서 인덱스
# =====================================================================
@router.get("/documents")
async def list_documents(
    doc_type: str | None = Query(None, description="SOP/QUALITY_STANDARD/HACCP/MANUAL/CLAIM"),
    embed_status: str | None = Query(None, description="PENDING/PROCESSING/COMPLETED/FAILED"),
):
    """Vector DB 문서 인덱스 목록."""
    conds: list[str] = []
    params: list[Any] = []
    idx = 1
    if doc_type:
        conds.append(f"doc_type = ${idx}"); params.append(doc_type); idx += 1
    if embed_status:
        conds.append(f"embed_status = ${idx}"); params.append(embed_status); idx += 1
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    async with get_db() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM ai_document_index {where} ORDER BY updated_at DESC",
            *params,
        )
    return [dict(r) for r in rows]


# =====================================================================
# 사용 통계 / 분석
# =====================================================================
@router.get("/analytics/usage")
async def get_usage_analytics(days: int = Query(30, ge=1, le=365)):
    """사용 통계 — 일별 질의 수 / 평균 응답시간 / 평균 만족도 / 에이전트 분포."""
    async with get_db() as conn:
        daily = await conn.fetch(
            """
            SELECT DATE(created_at) AS day,
                   COUNT(*) AS query_count,
                   ROUND(AVG(response_time_ms))::int AS avg_response_ms,
                   ROUND(AVG(feedback_score)::numeric, 2) AS avg_feedback
            FROM ai_query_history
            WHERE created_at >= NOW() - ($1 || ' days')::INTERVAL
            GROUP BY DATE(created_at)
            ORDER BY day
            """,
            str(days),
        )
        by_agent = await conn.fetch(
            """
            SELECT agent_type, COUNT(*) AS query_count
            FROM ai_query_history
            WHERE created_at >= NOW() - ($1 || ' days')::INTERVAL
            GROUP BY agent_type
            ORDER BY query_count DESC
            """,
            str(days),
        )
        totals = await conn.fetchrow(
            """
            SELECT COUNT(*) AS total_queries,
                   ROUND(AVG(response_time_ms))::int AS avg_response_ms,
                   ROUND(AVG(feedback_score)::numeric, 2) AS avg_feedback,
                   COUNT(*) FILTER (WHERE is_approved IS NULL) AS pending_approvals
            FROM ai_query_history
            WHERE created_at >= NOW() - ($1 || ' days')::INTERVAL
            """,
            str(days),
        )
    return {
        "days": days,
        "totals": dict(totals) if totals else {},
        "daily": [dict(r) for r in daily],
        "by_agent": [dict(r) for r in by_agent],
    }


@router.get("/analytics/top-queries")
async def get_top_queries(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(10, le=50),
):
    """
    자주 묻는 질문 TOP N — 질의 텍스트 키워드 빈도 분석.
    한글 형태소 분석기 대신 공백 토큰화 + 길이 2 이상 + 불용어 제거로 근사한다.
    실제 운영 시 형태소 분석(KoNLPy 등)으로 정교화한다.
    """
    stopwords = {
        "있어", "알려줘", "해줘", "검토해줘", "분석해줘", "뭐야", "어때", "가능한지",
        "있는", "관련", "대해", "대한", "그리고", "이번", "최근", "오늘", "현재",
    }
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT query_text
            FROM ai_query_history
            WHERE created_at >= NOW() - ($1 || ' days')::INTERVAL
            """,
            str(days),
        )
    freq: dict[str, int] = {}
    for r in rows:
        for token in (r["query_text"] or "").split():
            tok = token.strip(".,!?:;'\"()[]").strip()
            if len(tok) < 2 or tok in stopwords:
                continue
            freq[tok] = freq.get(tok, 0) + 1
    top = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return {
        "days": days,
        "top_queries": [{"keyword": k, "count": c} for k, c in top],
    }
