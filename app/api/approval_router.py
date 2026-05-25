"""
꽃순이김치 제조AI MES — AI 추천 / 의사결정 승인 워크플로우 API
Project: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션

prefix: /api/v1/approval

CLAUDE.md 원칙:
    "AI는 조회·분석·추천·경고. 작업자 승인 후 공정 반영 (파일럿 검증 단계)"

Shadow Mode 3단계 게이트:
    AI 추천 생성  →  사람 승인  →  공정 반영

이 라우터의 책임:
    - AI 모듈(발효 ML / RAG Agent / 품질)이 생성한 추천을 승인 대기열(approval_item)에 등록
    - 작업자/관리자가 승인 또는 거절 (거절 사유 필수, 완전한 감사 추적)
    - 24시간 미처리 항목 자동 만료(EXPIRED) 처리
    - Shadow Mode 상태 조회 / 토글(ADMIN 전용)

설계 원칙 (fastapi-mes 스킬):
    1. 모든 조회 엔드포인트는 LOT ID 기반 필터링을 지원한다 (lot_id 쿼리 파라미터)
    2. ML/RAG 관련 승인은 본 워크플로우 prefix(/api/v1/approval)로 분리한다
    3. 비동기(async/await + asyncpg) 기본
    4. Pydantic v2 모델로 요청/응답 스키마 정의
    5. 상태 가드 + 만료 자동처리로 멱등성·정합성 보장

app/main.py 에서:  app.include_router(approval_router)
"""
from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.database import get_db
from app.auth import CurrentUser, get_current_user, require_role
from app.middleware.shadow_mode import is_shadow_mode_enabled, set_shadow_mode

router = APIRouter(prefix="/api/v1/approval", tags=["승인워크플로우"])


# =====================================================================
# 도메인 Enum
# =====================================================================
class ItemType(str, Enum):
    FERMENTATION_CONDITION = "FERMENTATION_CONDITION"  # 절임/발효 조건 변경 추천
    SHIPPING_APPROVAL = "SHIPPING_APPROVAL"            # 출하 승인
    QUALITY_OVERRIDE = "QUALITY_OVERRIDE"              # 품질 기준 예외 처리
    LOT_STATUS_CHANGE = "LOT_STATUS_CHANGE"            # LOT 상태 변경


class SourceModule(str, Enum):
    FERMENTATION = "FERMENTATION"
    SHIPPING = "SHIPPING"
    INTAKE = "INTAKE"


class ItemStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


# 승인 권한 매핑 (docs/shadow-mode-guide.md 와 동기화)
#   PLANT_MANAGER(공장장), MANAGER(관리자), QC(품질담당자)
APPROVAL_AUTHORITY: dict[str, tuple[str, ...]] = {
    ItemType.FERMENTATION_CONDITION.value: ("PLANT_MANAGER", "MANAGER", "ADMIN"),
    ItemType.SHIPPING_APPROVAL.value: ("PLANT_MANAGER", "MANAGER", "ADMIN"),
    ItemType.QUALITY_OVERRIDE.value: ("PLANT_MANAGER", "ADMIN"),
    ItemType.LOT_STATUS_CHANGE.value: ("QC", "MANAGER", "ADMIN"),
}


def _jsonb(value: Any) -> Any:
    """asyncpg 가 JSONB 를 str 로 반환하는 경우 dict 로 파싱."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def _row_out(row) -> dict[str, Any]:
    """레코드 → dict 변환 + JSONB 필드 파싱."""
    d = dict(row)
    d["current_state"] = _jsonb(d.get("current_state"))
    d["proposed_change"] = _jsonb(d.get("proposed_change"))
    return d


async def _expire_overdue(conn) -> int:
    """expires_at 경과한 PENDING 항목을 EXPIRED 로 일괄 전환. 만료 건수 반환."""
    expired = await conn.fetch(
        """
        UPDATE approval_item
        SET status = 'EXPIRED'
        WHERE status = 'PENDING' AND expires_at < NOW()
        RETURNING item_id
        """
    )
    return len(expired)


# =====================================================================
# Pydantic v2 모델
# =====================================================================
class ApprovalItemCreate(BaseModel):
    item_type: ItemType = Field(..., description="승인 항목 유형")
    title: str = Field(..., min_length=1, max_length=200)
    ai_recommendation: str = Field(..., min_length=1, description="AI 추천 내용")
    current_state: dict[str, Any] | None = Field(None, description="현재 공정 상태")
    proposed_change: dict[str, Any] | None = Field(None, description="AI 제안 변경 사항")
    confidence: float | None = Field(None, ge=0, le=1, description="AI 신뢰도 0~1")
    lot_id: str | None = Field(None, max_length=30, description="연관 LOT ID")
    source_module: SourceModule = Field(..., description="요청 모듈")
    requested_by: str = Field("AI_MODULE", max_length=50, description="요청 주체(AI 모듈명)")
    expires_in_hours: int = Field(24, ge=1, le=168, description="만료 시간(기본 24h)")


class ApprovalItemResponse(BaseModel):
    item_id: int
    item_type: str
    title: str
    ai_recommendation: str
    current_state: dict[str, Any] | None = None
    proposed_change: dict[str, Any] | None = None
    confidence: float | None = None
    lot_id: str | None = None
    source_module: str | None = None
    status: str
    requested_by: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    approval_note: str | None = None
    rejection_reason: str | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None


class ApproveRequest(BaseModel):
    approved_by: str = Field(..., min_length=1, max_length=50, description="승인 처리자")
    approval_note: str | None = Field(None, description="승인 메모")


class RejectRequest(BaseModel):
    approved_by: str = Field(..., min_length=1, max_length=50, description="거절 처리자")
    rejection_reason: str = Field(..., min_length=1, description="거절 사유(필수)")


class ShadowModeUpdate(BaseModel):
    enabled: bool = Field(..., description="True=Shadow Mode ON / False=OFF")


# =====================================================================
# 1. 승인 항목 등록 (AI 모듈 → 승인 대기열)
# =====================================================================
@router.post("/items", response_model=ApprovalItemResponse, status_code=201)
async def create_approval_item(data: ApprovalItemCreate):
    """
    AI 추천을 승인 대기열에 등록한다.
    발효 ML / RAG Agent / 품질 모듈이 추천을 생성하면 이 엔드포인트로 적재한다.
    Shadow Mode 가 OFF 인 경우에도 등록은 가능하나, 즉시 반영 여부는 호출 모듈이 판단한다.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO approval_item
                (item_type, title, ai_recommendation, current_state, proposed_change,
                 confidence, lot_id, source_module, status, requested_by, expires_at)
            VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6,$7,$8,'PENDING',$9,
                    NOW() + ($10 || ' hours')::INTERVAL)
            RETURNING *
            """,
            data.item_type.value,
            data.title,
            data.ai_recommendation,
            json.dumps(data.current_state) if data.current_state is not None else None,
            json.dumps(data.proposed_change) if data.proposed_change is not None else None,
            data.confidence,
            data.lot_id,
            data.source_module.value,
            data.requested_by,
            str(data.expires_in_hours),
        )
    return _row_out(row)


# =====================================================================
# 2. 승인 대기 목록
# =====================================================================
@router.get("/items", response_model=list[ApprovalItemResponse])
async def list_approval_items(
    status: ItemStatus | None = Query(None, description="기본 미지정 시 PENDING"),
    item_type: ItemType | None = Query(None),
    source_module: SourceModule | None = Query(None),
    lot_id: str | None = Query(None, description="연관 LOT ID 필터"),
    limit: int = Query(50, le=500),
):
    """
    승인 항목 목록.
    - status 미지정 시 PENDING 만 반환(승인 대기열 기본 뷰).
    - 조회 전 만료 항목을 EXPIRED 로 정리한다.
    - 우선순위: 미처리(PENDING) → 신뢰도 높은 순 → 만료 임박 순.
    """
    conds: list[str] = []
    params: list[Any] = []
    idx = 1

    target_status = status.value if status else ItemStatus.PENDING.value
    conds.append(f"status = ${idx}"); params.append(target_status); idx += 1

    if item_type:
        conds.append(f"item_type = ${idx}"); params.append(item_type.value); idx += 1
    if source_module:
        conds.append(f"source_module = ${idx}"); params.append(source_module.value); idx += 1
    if lot_id:
        conds.append(f"lot_id = ${idx}"); params.append(lot_id); idx += 1

    where = f"WHERE {' AND '.join(conds)}"
    params.append(limit)

    async with get_db() as conn:
        await _expire_overdue(conn)
        rows = await conn.fetch(
            f"""
            SELECT * FROM approval_item
            {where}
            ORDER BY (status = 'PENDING') DESC,
                     confidence DESC NULLS LAST,
                     expires_at ASC
            LIMIT ${idx}
            """,
            *params,
        )
    return [_row_out(r) for r in rows]


# =====================================================================
# 3. 승인 항목 상세
# =====================================================================
@router.get("/items/{item_id}", response_model=ApprovalItemResponse)
async def get_approval_item(item_id: int):
    """승인 항목 상세 조회 (조회 시 만료 항목 정리 포함)."""
    async with get_db() as conn:
        await _expire_overdue(conn)
        row = await conn.fetchrow(
            "SELECT * FROM approval_item WHERE item_id = $1", item_id
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"승인 항목 {item_id} 없음")
    return _row_out(row)


# =====================================================================
# 4. 승인 처리 (MANAGER / ADMIN / 공장장 — 유형별 권한)
# =====================================================================
@router.post(
    "/items/{item_id}/approve",
    response_model=ApprovalItemResponse,
    dependencies=[Depends(require_role("PLANT_MANAGER", "MANAGER", "QC", "ADMIN"))],
)
async def approve_item(item_id: int, data: ApproveRequest):
    """
    승인 처리.
    - PENDING 상태에서만 승인 가능(이미 처리/만료 시 409).
    - 유형별 승인 권한(APPROVAL_AUTHORITY)을 검증한다.
    - 승인 시 status=APPROVED, approved_by/approved_at/approval_note 기록(감사 추적).
    - 승인 후 공정 반영은 호출 모듈/배치가 status=APPROVED 항목을 폴링해 수행한다.
    """
    async with get_db() as conn:
        await _expire_overdue(conn)
        item = await conn.fetchrow(
            "SELECT item_type, status FROM approval_item WHERE item_id = $1", item_id
        )
        if not item:
            raise HTTPException(status_code=404, detail=f"승인 항목 {item_id} 없음")
        if item["status"] != ItemStatus.PENDING.value:
            raise HTTPException(
                status_code=409,
                detail=f"처리 불가: 현재 상태 {item['status']} (PENDING 만 승인 가능)",
            )
        # 유형별 승인 권한 검증
        authority = APPROVAL_AUTHORITY.get(item["item_type"], ("ADMIN",))
        roles = await get_user_roles((await get_current_user()).user_id)
        if roles and not any(r in authority for r in roles):
            raise HTTPException(
                status_code=403,
                detail=f"{item['item_type']} 승인 권한 없음 (필요: {', '.join(authority)})",
            )

        row = await conn.fetchrow(
            """
            UPDATE approval_item
            SET status = 'APPROVED',
                approved_by = $2,
                approved_at = NOW(),
                approval_note = $3
            WHERE item_id = $1 AND status = 'PENDING'
            RETURNING *
            """,
            item_id, data.approved_by, data.approval_note,
        )
    if not row:
        raise HTTPException(status_code=409, detail="처리 중 상태가 변경되었습니다")
    return _row_out(row)


# =====================================================================
# 5. 거절 처리 (거절 사유 필수)
# =====================================================================
@router.post(
    "/items/{item_id}/reject",
    response_model=ApprovalItemResponse,
    dependencies=[Depends(require_role("PLANT_MANAGER", "MANAGER", "QC", "ADMIN"))],
)
async def reject_item(item_id: int, data: RejectRequest):
    """
    거절 처리. 거절 사유(rejection_reason)는 필수다.
    PENDING 상태에서만 가능하며, status=REJECTED 로 전환하고 사유를 기록한다.
    """
    async with get_db() as conn:
        await _expire_overdue(conn)
        item = await conn.fetchrow(
            "SELECT status FROM approval_item WHERE item_id = $1", item_id
        )
        if not item:
            raise HTTPException(status_code=404, detail=f"승인 항목 {item_id} 없음")
        if item["status"] != ItemStatus.PENDING.value:
            raise HTTPException(
                status_code=409,
                detail=f"처리 불가: 현재 상태 {item['status']} (PENDING 만 거절 가능)",
            )
        row = await conn.fetchrow(
            """
            UPDATE approval_item
            SET status = 'REJECTED',
                approved_by = $2,
                approved_at = NOW(),
                rejection_reason = $3
            WHERE item_id = $1 AND status = 'PENDING'
            RETURNING *
            """,
            item_id, data.approved_by, data.rejection_reason,
        )
    if not row:
        raise HTTPException(status_code=409, detail="처리 중 상태가 변경되었습니다")
    return _row_out(row)


# =====================================================================
# 6. 승인 이력
# =====================================================================
@router.get("/history", response_model=list[ApprovalItemResponse])
async def get_approval_history(
    date_from: datetime | None = Query(None, description="처리 시작일시"),
    approver: str | None = Query(None, description="승인/거절 처리자"),
    item_type: ItemType | None = Query(None),
    lot_id: str | None = Query(None, description="연관 LOT ID 필터"),
    status: ItemStatus | None = Query(None, description="APPROVED/REJECTED/EXPIRED"),
    limit: int = Query(100, le=1000),
):
    """승인 이력 — 처리 완료(APPROVED/REJECTED/EXPIRED) 항목 (기간/승인자/유형/LOT 필터)."""
    conds: list[str] = ["status <> 'PENDING'"]
    params: list[Any] = []
    idx = 1
    if date_from:
        conds.append(f"COALESCE(approved_at, created_at) >= ${idx}"); params.append(date_from); idx += 1
    if approver:
        conds.append(f"approved_by = ${idx}"); params.append(approver); idx += 1
    if item_type:
        conds.append(f"item_type = ${idx}"); params.append(item_type.value); idx += 1
    if lot_id:
        conds.append(f"lot_id = ${idx}"); params.append(lot_id); idx += 1
    if status:
        conds.append(f"status = ${idx}"); params.append(status.value); idx += 1
    where = f"WHERE {' AND '.join(conds)}"
    params.append(limit)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT * FROM approval_item
            {where}
            ORDER BY COALESCE(approved_at, created_at) DESC
            LIMIT ${idx}
            """,
            *params,
        )
    return [_row_out(r) for r in rows]


# =====================================================================
# 7. 승인 통계
# =====================================================================
@router.get("/stats")
async def get_approval_stats(days: int = Query(90, ge=1, le=365)):
    """
    승인 통계 — 승인율 / 평균 처리시간 / 유형별 분포.
    시범운영(3개월) 성과 검토용. AI 추천 채택률(승인율)을 추적한다.
    """
    async with get_db() as conn:
        await _expire_overdue(conn)
        totals = await conn.fetchrow(
            """
            SELECT
                COUNT(*)                                          AS total,
                COUNT(*) FILTER (WHERE status='PENDING')          AS pending,
                COUNT(*) FILTER (WHERE status='APPROVED')         AS approved,
                COUNT(*) FILTER (WHERE status='REJECTED')         AS rejected,
                COUNT(*) FILTER (WHERE status='EXPIRED')          AS expired,
                ROUND(AVG(confidence)::numeric, 4)                AS avg_confidence,
                ROUND(AVG(EXTRACT(EPOCH FROM (approved_at - created_at)) / 60.0)
                      FILTER (WHERE approved_at IS NOT NULL)::numeric, 1)
                                                                  AS avg_handle_minutes
            FROM approval_item
            WHERE created_at >= NOW() - ($1 || ' days')::INTERVAL
            """,
            str(days),
        )
        by_type = await conn.fetch(
            """
            SELECT item_type,
                   COUNT(*)                                  AS total,
                   COUNT(*) FILTER (WHERE status='APPROVED') AS approved,
                   COUNT(*) FILTER (WHERE status='REJECTED') AS rejected
            FROM approval_item
            WHERE created_at >= NOW() - ($1 || ' days')::INTERVAL
            GROUP BY item_type
            ORDER BY total DESC
            """,
            str(days),
        )
    t = dict(totals) if totals else {}
    decided = (t.get("approved") or 0) + (t.get("rejected") or 0)
    approval_rate = round((t.get("approved") or 0) / decided, 4) if decided else None
    return {
        "days": days,
        "totals": t,
        "approval_rate": approval_rate,  # 승인 / (승인+거절)
        "avg_handle_minutes": float(t["avg_handle_minutes"]) if t.get("avg_handle_minutes") is not None else None,
        "by_type": [dict(r) for r in by_type],
        "shadow_mode": is_shadow_mode_enabled(),
    }


# =====================================================================
# 8. Shadow Mode 상태 조회
# =====================================================================
@router.get("/shadow-mode")
async def get_shadow_mode():
    """
    현재 Shadow Mode 상태.
    - enabled=True  : AI 추천이 승인 대기열을 거쳐야 공정에 반영됨(시범운영)
    - enabled=False : AI 추천 자동 반영(미래 자동화 단계)
    """
    enabled = is_shadow_mode_enabled()
    return {
        "enabled": enabled,
        "mode": "SHADOW" if enabled else "AUTO",
        "description": (
            "AI 추천 → 사람 승인 → 공정 반영 (시범운영)"
            if enabled
            else "AI 추천 자동 반영 (자동화 단계)"
        ),
        "approval_authority": APPROVAL_AUTHORITY,
    }


# =====================================================================
# 9. Shadow Mode ON/OFF 토글 (ADMIN 전용)
# =====================================================================
@router.put("/shadow-mode", dependencies=[Depends(require_role("ADMIN"))])
async def update_shadow_mode(data: ShadowModeUpdate):
    """
    Shadow Mode 런타임 토글 (ADMIN 전용).
    시범운영 기간에는 항상 ON 을 권장한다. 성과 검토 후 OFF/자동승인 단계로 전환.
    """
    new_state = set_shadow_mode(data.enabled)
    return {
        "enabled": new_state,
        "mode": "SHADOW" if new_state else "AUTO",
        "message": f"Shadow Mode {'활성화' if new_state else '비활성화'} 완료",
    }
