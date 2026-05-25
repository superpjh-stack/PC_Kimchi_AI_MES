"""
꽃순이김치 제조AI MES — 원재료관리 API 라우터
프로젝트: SF26179540 / 로뎀솔루션

prefix: /api/v1/material
대상 테이블: supplier, raw_material_lot, incoming_inspection,
            material_selection, supplier_quality_score  (db_material_schema.sql)

설계 원칙 (fastapi-mes 스킬):
  1. 모든 조회 엔드포인트는 LOT ID / 날짜 / 공급처 기반 필터링 지원
  2. ML/RAG 결과는 별도 /api/v1/agent/* 프록시로 분리 (본 라우터 외)
  3. 비동기(async/await + asyncpg) 기본
  4. Pydantic v2 모델로 요청/응답 스키마 정의
  5. LOT 체인 무결성: raw_material_lot.lot_id 가 후속 공정의 source_lot_id 로 참조됨

app/main.py 에서:  app.include_router(material.router)
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

# 프로젝트 공통 DB 컨텍스트 (app/database.py)
from app.database import get_db
from app.auth import require_role, CurrentUser  # JWT + RBAC

router = APIRouter(prefix="/api/v1/material", tags=["원재료관리"])


# =====================================================================
# 공통 정의 (Enum / 상수)
# =====================================================================
class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    INSPECTING = "INSPECTING"
    PASSED = "PASSED"
    REJECTED = "REJECTED"
    CONSUMED = "CONSUMED"


class QCResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    CONDITIONAL = "CONDITIONAL"


class CabbageSize(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    XLARGE = "XLARGE"


# 상태 전이 규칙 (PATCH /lots/{lot_id}/status 검증용)
ALLOWED_STATUS_TRANSITION: dict[str, set[str]] = {
    "RECEIVED": {"INSPECTING", "PASSED", "REJECTED"},
    "INSPECTING": {"PASSED", "REJECTED"},
    "PASSED": {"CONSUMED"},
    "REJECTED": set(),
    "CONSUMED": set(),
}


def _to_dict(row) -> dict[str, Any]:
    """asyncpg Record -> dict (None 안전)."""
    return dict(row) if row is not None else {}


# =====================================================================
# Pydantic 모델 — 원재료 LOT
# =====================================================================
class RawMaterialLotCreate(BaseModel):
    lot_id: str = Field(..., max_length=30, description="RM-YYYYMMDD-NNN")
    intake_date: date
    supplier_code: str = Field(..., max_length=20)
    material_code: str = Field(..., max_length=20)
    origin: str | None = Field(None, max_length=50)
    quantity_kg: float = Field(..., gt=0)
    unit_price: float | None = Field(None, ge=0)
    vehicle_no: str | None = Field(None, max_length=20)
    driver_name: str | None = Field(None, max_length=50)
    received_by: str | None = Field(None, max_length=50)
    lot_status: LotStatus = LotStatus.RECEIVED
    notes: str | None = None


class RawMaterialLotResponse(BaseModel):
    lot_id: str
    intake_date: date
    supplier_code: str
    supplier_name: str | None = None
    material_code: str
    origin: str | None = None
    quantity_kg: float
    unit_price: float | None = None
    vehicle_no: str | None = None
    driver_name: str | None = None
    received_by: str | None = None
    lot_status: str
    notes: str | None = None
    created_at: datetime | None = None


class LotStatusUpdate(BaseModel):
    lot_status: LotStatus
    changed_by: str | None = None
    note: str | None = None


# =====================================================================
# Pydantic 모델 — 입고 검사
# =====================================================================
class InspectionCreate(BaseModel):
    lot_id: str = Field(..., max_length=30)
    inspector: str = Field(..., max_length=50)
    inspection_date: date | None = None
    cabbage_size: CabbageSize | None = None
    weight_avg_kg: float | None = Field(None, ge=0)
    appearance_grade: str | None = Field(None, pattern="^[ABC]$")
    water_content_pct: float | None = Field(None, ge=0, le=100)
    freshness_score: int | None = Field(None, ge=1, le=10)
    qc_result: QCResult
    rejection_reason: str | None = None
    corrective_action: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "InspectionCreate":
        # 불합격(FAIL)이면 사유 필수
        if self.qc_result == QCResult.FAIL and not self.rejection_reason:
            raise ValueError("불합격(FAIL) 판정 시 rejection_reason 은 필수입니다")
        return self


class InspectionResponse(BaseModel):
    inspection_id: int
    lot_id: str
    inspector: str
    inspection_date: date
    cabbage_size: str | None = None
    weight_avg_kg: float | None = None
    appearance_grade: str | None = None
    water_content_pct: float | None = None
    freshness_score: int | None = None
    qc_result: str
    rejection_reason: str | None = None
    corrective_action: str | None = None
    created_at: datetime | None = None


# =====================================================================
# Pydantic 모델 — 선별 데이터
# =====================================================================
class SelectionCreate(BaseModel):
    lot_id: str = Field(..., max_length=30)
    selection_date: date | None = None
    operator: str | None = Field(None, max_length=50)
    input_qty_kg: float = Field(..., ge=0)
    selected_qty_kg: float = Field(..., ge=0)
    reject_qty_kg: float = Field(..., ge=0)
    reject_reason: str | None = Field(None, max_length=100)
    notes: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "SelectionCreate":
        if self.selected_qty_kg > self.input_qty_kg:
            raise ValueError("선별 통과량은 투입량을 초과할 수 없습니다")
        # 통과량 + 제거량은 투입량과 일치(±0.5kg 오차 허용)
        if abs((self.selected_qty_kg + self.reject_qty_kg) - self.input_qty_kg) > 0.5:
            raise ValueError("통과량 + 제거량이 투입량과 일치해야 합니다(±0.5kg)")
        return self


class SelectionResponse(BaseModel):
    selection_id: int
    lot_id: str
    selection_date: date
    operator: str | None = None
    input_qty_kg: float
    selected_qty_kg: float
    reject_qty_kg: float
    selection_rate_pct: float | None = None
    reject_reason: str | None = None
    notes: str | None = None
    created_at: datetime | None = None


# =====================================================================
# 1. 원재료 LOT 등록
# =====================================================================
@router.post("/lots", response_model=RawMaterialLotResponse, status_code=201)
async def create_lot(
    data: RawMaterialLotCreate,
    _: CurrentUser = Depends(require_role("OPERATOR", "MANAGER", "ADMIN")),
):
    """원재료 LOT 등록. lot_id 는 RM-YYYYMMDD-NNN 형식."""
    async with get_db() as conn:
        # 공급처 존재 검증
        exists = await conn.fetchval(
            "SELECT 1 FROM supplier WHERE supplier_code = $1", data.supplier_code
        )
        if not exists:
            raise HTTPException(
                status_code=400, detail=f"공급처 {data.supplier_code} 가 등록되어 있지 않습니다"
            )
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO raw_material_lot
                    (lot_id, intake_date, supplier_code, material_code, origin,
                     quantity_kg, unit_price, vehicle_no, driver_name, received_by,
                     lot_status, notes)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                RETURNING *
                """,
                data.lot_id, data.intake_date, data.supplier_code, data.material_code,
                data.origin, data.quantity_kg, data.unit_price, data.vehicle_no,
                data.driver_name, data.received_by, data.lot_status.value, data.notes,
            )
        except Exception as e:  # noqa: BLE001 — UniqueViolation 등
            raise HTTPException(
                status_code=409, detail=f"LOT 등록 실패(중복 가능): {e}"
            ) from e
    return _to_dict(row)


# =====================================================================
# 2. 원재료 LOT 목록
# =====================================================================
@router.get("/lots", response_model=list[RawMaterialLotResponse])
async def list_lots(
    date_from: date | None = None,
    date_to: date | None = None,
    supplier_code: str | None = None,
    lot_status: LotStatus | None = None,
    limit: int = Query(50, le=500),
):
    """원재료 LOT 목록 (date_from/date_to/supplier_code/lot_status 필터)."""
    clauses: list[str] = []
    params: list[Any] = []
    if date_from:
        params.append(date_from)
        clauses.append(f"r.intake_date >= ${len(params)}")
    if date_to:
        params.append(date_to)
        clauses.append(f"r.intake_date <= ${len(params)}")
    if supplier_code:
        params.append(supplier_code)
        clauses.append(f"r.supplier_code = ${len(params)}")
    if lot_status:
        params.append(lot_status.value)
        clauses.append(f"r.lot_status = ${len(params)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT r.*, s.supplier_name
            FROM raw_material_lot r
            LEFT JOIN supplier s ON r.supplier_code = s.supplier_code
            {where}
            ORDER BY r.intake_date DESC, r.lot_id DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return [_to_dict(r) for r in rows]


# =====================================================================
# 3. 원재료 LOT 상세 (검사 결과 포함)
# =====================================================================
@router.get("/lots/{lot_id}")
async def get_lot(lot_id: str):
    """LOT 상세 + 입고 검사 결과 + 선별 실적 요약."""
    async with get_db() as conn:
        lot = await conn.fetchrow(
            """
            SELECT r.*, s.supplier_name, s.region
            FROM raw_material_lot r
            LEFT JOIN supplier s ON r.supplier_code = s.supplier_code
            WHERE r.lot_id = $1
            """,
            lot_id,
        )
        if not lot:
            raise HTTPException(status_code=404, detail=f"LOT {lot_id} 없음")
        inspections = await conn.fetch(
            "SELECT * FROM incoming_inspection WHERE lot_id = $1 ORDER BY inspection_date DESC",
            lot_id,
        )
        selections = await conn.fetch(
            "SELECT * FROM material_selection WHERE lot_id = $1 ORDER BY selection_date DESC",
            lot_id,
        )
    return {
        "lot": _to_dict(lot),
        "inspections": [_to_dict(r) for r in inspections],
        "selections": [_to_dict(r) for r in selections],
    }


# =====================================================================
# 4. 원재료 LOT 상태 변경
# =====================================================================
@router.patch("/lots/{lot_id}/status", response_model=RawMaterialLotResponse)
async def update_lot_status(
    lot_id: str,
    data: LotStatusUpdate,
    _: CurrentUser = Depends(require_role("MANAGER", "ADMIN")),
):
    """LOT 상태 변경. 허용된 상태 전이만 가능 (RECEIVED→PASSED/REJECTED 등)."""
    async with get_db() as conn:
        current = await conn.fetchval(
            "SELECT lot_status FROM raw_material_lot WHERE lot_id = $1", lot_id
        )
        if current is None:
            raise HTTPException(status_code=404, detail=f"LOT {lot_id} 없음")
        target = data.lot_status.value
        if target != current and target not in ALLOWED_STATUS_TRANSITION.get(current, set()):
            raise HTTPException(
                status_code=400,
                detail=f"상태 전이 불가: {current} → {target} "
                       f"(허용: {sorted(ALLOWED_STATUS_TRANSITION.get(current, set()))})",
            )
        note = data.note
        if data.changed_by:
            note = f"[{data.changed_by}] {note or ''}".strip()
        row = await conn.fetchrow(
            """
            UPDATE raw_material_lot
            SET lot_status = $2,
                notes = COALESCE($3, notes)
            WHERE lot_id = $1
            RETURNING *
            """,
            lot_id, target, note,
        )
    return _to_dict(row)


# =====================================================================
# 5. 입고 검사 등록
# =====================================================================
@router.post("/inspections", response_model=InspectionResponse, status_code=201)
async def create_inspection(
    data: InspectionCreate,
    _: CurrentUser = Depends(require_role("QUALITY", "MANAGER", "ADMIN")),
):
    """입고 검사 등록. 합격(PASS) 시 LOT 상태를 자동으로 PASSED 로,
    불합격(FAIL) 시 REJECTED 로 동기화한다(트랜잭션)."""
    async with get_db() as conn:
        lot_exists = await conn.fetchval(
            "SELECT 1 FROM raw_material_lot WHERE lot_id = $1", data.lot_id
        )
        if not lot_exists:
            raise HTTPException(status_code=404, detail=f"LOT {data.lot_id} 없음")

        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO incoming_inspection
                    (lot_id, inspector, inspection_date, cabbage_size, weight_avg_kg,
                     appearance_grade, water_content_pct, freshness_score, qc_result,
                     rejection_reason, corrective_action)
                VALUES ($1,$2, COALESCE($3, CURRENT_DATE), $4,$5,$6,$7,$8,$9,$10,$11)
                RETURNING *
                """,
                data.lot_id, data.inspector, data.inspection_date,
                data.cabbage_size.value if data.cabbage_size else None,
                data.weight_avg_kg, data.appearance_grade, data.water_content_pct,
                data.freshness_score, data.qc_result.value,
                data.rejection_reason, data.corrective_action,
            )
            # 검사 결과 → LOT 상태 동기화
            new_status = {
                QCResult.PASS: "PASSED",
                QCResult.FAIL: "REJECTED",
                QCResult.CONDITIONAL: "PASSED",
            }[data.qc_result]
            await conn.execute(
                """UPDATE raw_material_lot SET lot_status = $2
                   WHERE lot_id = $1 AND lot_status IN ('RECEIVED','INSPECTING')""",
                data.lot_id, new_status,
            )
    return _to_dict(row)


# =====================================================================
# 6. 입고 검사 목록
# =====================================================================
@router.get("/inspections", response_model=list[InspectionResponse])
async def list_inspections(
    lot_id: str | None = None,
    qc_result: QCResult | None = None,
    date_from: date | None = None,
    limit: int = Query(50, le=500),
):
    """입고 검사 목록 (lot_id/qc_result/date_from 필터)."""
    clauses: list[str] = []
    params: list[Any] = []
    if lot_id:
        params.append(lot_id)
        clauses.append(f"lot_id = ${len(params)}")
    if qc_result:
        params.append(qc_result.value)
        clauses.append(f"qc_result = ${len(params)}")
    if date_from:
        params.append(date_from)
        clauses.append(f"inspection_date >= ${len(params)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT * FROM incoming_inspection
            {where}
            ORDER BY inspection_date DESC, inspection_id DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return [_to_dict(r) for r in rows]


# =====================================================================
# 7. 입고 검사 상세
# =====================================================================
@router.get("/inspections/{inspection_id}", response_model=InspectionResponse)
async def get_inspection(inspection_id: int):
    """입고 검사 상세."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM incoming_inspection WHERE inspection_id = $1", inspection_id
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"검사 {inspection_id} 없음")
    return _to_dict(row)


# =====================================================================
# 8. 선별 데이터 등록
# =====================================================================
@router.post("/selections", response_model=SelectionResponse, status_code=201)
async def create_selection(
    data: SelectionCreate,
    _: CurrentUser = Depends(require_role("OPERATOR", "QUALITY", "ADMIN")),
):
    """선별 데이터 등록. selection_rate_pct 는 DB GENERATED 컬럼으로 자동 계산."""
    async with get_db() as conn:
        lot_exists = await conn.fetchval(
            "SELECT 1 FROM raw_material_lot WHERE lot_id = $1", data.lot_id
        )
        if not lot_exists:
            raise HTTPException(status_code=404, detail=f"LOT {data.lot_id} 없음")
        row = await conn.fetchrow(
            """
            INSERT INTO material_selection
                (lot_id, selection_date, operator, input_qty_kg, selected_qty_kg,
                 reject_qty_kg, reject_reason, notes)
            VALUES ($1, COALESCE($2, CURRENT_DATE), $3,$4,$5,$6,$7,$8)
            RETURNING *
            """,
            data.lot_id, data.selection_date, data.operator, data.input_qty_kg,
            data.selected_qty_kg, data.reject_qty_kg, data.reject_reason, data.notes,
        )
    return _to_dict(row)


# =====================================================================
# 9. 선별 데이터 목록
# =====================================================================
@router.get("/selections", response_model=list[SelectionResponse])
async def list_selections(
    lot_id: str | None = None,
    date_from: date | None = None,
    limit: int = Query(50, le=500),
):
    """선별 데이터 목록 (lot_id/date_from 필터)."""
    clauses: list[str] = []
    params: list[Any] = []
    if lot_id:
        params.append(lot_id)
        clauses.append(f"lot_id = ${len(params)}")
    if date_from:
        params.append(date_from)
        clauses.append(f"selection_date >= ${len(params)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT * FROM material_selection
            {where}
            ORDER BY selection_date DESC, selection_id DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return [_to_dict(r) for r in rows]


# =====================================================================
# 10. 공급처 목록
# =====================================================================
@router.get("/suppliers")
async def list_suppliers(active_only: bool = True):
    """공급처 목록 (active_only=True 면 거래 활성 공급처만)."""
    where = "WHERE is_active = TRUE" if active_only else ""
    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT supplier_code, supplier_name, contact_name, phone, email,
                   region, is_active, registered_at, notes
            FROM supplier
            {where}
            ORDER BY supplier_code
            """
        )
    return [_to_dict(r) for r in rows]


# =====================================================================
# 11. 공급처 품질 랭킹 (최근 3개월 pass_rate 기준)
#     ※ FastAPI 라우트 순서 주의: 고정 경로(/suppliers/ranking)를
#       파라미터 경로(/suppliers/{supplier_code}/quality)보다 먼저 선언해야
#       "ranking" 문자열이 supplier_code 로 캡처되지 않는다.
# =====================================================================
@router.get("/suppliers/ranking")
async def get_supplier_ranking(months: int = Query(3, ge=1, le=12)):
    """공급처 품질 랭킹 — 최근 N개월 가중 합격률 기준 내림차순."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            WITH recent AS (
                SELECT supplier_code,
                       SUM(total_lots)  AS total_lots,
                       SUM(passed_lots) AS passed_lots,
                       AVG(avg_freshness) AS avg_freshness,
                       SUM(total_kg)    AS total_kg
                FROM supplier_quality_score
                WHERE year_month >= TO_CHAR(
                    (CURRENT_DATE - ($1 || ' months')::INTERVAL), 'YYYY-MM')
                GROUP BY supplier_code
            )
            SELECT r.supplier_code, s.supplier_name, s.region,
                   r.total_lots, r.passed_lots,
                   ROUND(r.passed_lots * 100.0 / NULLIF(r.total_lots, 0), 2) AS pass_rate_pct,
                   ROUND(r.avg_freshness, 2) AS avg_freshness,
                   r.total_kg
            FROM recent r
            LEFT JOIN supplier s ON r.supplier_code = s.supplier_code
            ORDER BY pass_rate_pct DESC NULLS LAST, r.total_kg DESC
            """,
            months,
        )
    ranking = []
    for idx, r in enumerate(rows, start=1):
        d = _to_dict(r)
        d["rank"] = idx
        ranking.append(d)
    return {"months": months, "ranking": ranking}


# =====================================================================
# 13. LOT 완전 이력 (입고 → 검사 → 선별 → 공정 연계)
# =====================================================================
@router.get("/history/{lot_id}")
async def get_lot_history(lot_id: str):
    """LOT 완전 이력 타임라인.
    원재료 입고 → 입고검사 → 선별 → 후속 공정(process_result.source_lot_id) 연계.
    process_result 테이블이 없는 환경에서도 graceful 하게 동작한다."""
    async with get_db() as conn:
        lot = await conn.fetchrow(
            """
            SELECT r.*, s.supplier_name, s.region
            FROM raw_material_lot r
            LEFT JOIN supplier s ON r.supplier_code = s.supplier_code
            WHERE r.lot_id = $1
            """,
            lot_id,
        )
        if not lot:
            raise HTTPException(status_code=404, detail=f"LOT {lot_id} 없음")
        inspections = await conn.fetch(
            "SELECT * FROM incoming_inspection WHERE lot_id = $1 ORDER BY inspection_date",
            lot_id,
        )
        selections = await conn.fetch(
            "SELECT * FROM material_selection WHERE lot_id = $1 ORDER BY selection_date",
            lot_id,
        )
        # 후속 공정 연계 (process_result.source_lot_id = 본 LOT). 테이블 부재 시 무시.
        downstream: list[dict[str, Any]] = []
        try:
            ds = await conn.fetch(
                """
                SELECT process_code, lot_id, source_lot_id, output_qty_kg,
                       yield_rate, status, start_time
                FROM process_result
                WHERE source_lot_id = $1 OR lot_id = $1
                ORDER BY start_time
                """,
                lot_id,
            )
            downstream = [_to_dict(r) for r in ds]
        except Exception:  # noqa: BLE001 — process_result 미존재 환경
            downstream = []

    # 타임라인 이벤트 구성
    timeline: list[dict[str, Any]] = []
    lot_d = _to_dict(lot)
    timeline.append({
        "stage": "입고", "event": "RECEIVE", "lot_id": lot_id,
        "date": str(lot_d.get("intake_date")),
        "detail": f"공급처 {lot_d.get('supplier_name')} / {lot_d.get('quantity_kg')}kg",
        "status": lot_d.get("lot_status"),
    })
    for r in inspections:
        d = _to_dict(r)
        timeline.append({
            "stage": "입고검사", "event": "INSPECT", "lot_id": lot_id,
            "date": str(d.get("inspection_date")),
            "detail": f"검사자 {d.get('inspector')} / 외관 {d.get('appearance_grade')} "
                      f"/ 함수율 {d.get('water_content_pct')}%",
            "status": d.get("qc_result"),
        })
    for r in selections:
        d = _to_dict(r)
        timeline.append({
            "stage": "선별", "event": "SELECT", "lot_id": lot_id,
            "date": str(d.get("selection_date")),
            "detail": f"투입 {d.get('input_qty_kg')}kg → 통과 {d.get('selected_qty_kg')}kg "
                      f"(선별율 {d.get('selection_rate_pct')}%)",
            "status": None,
        })
    for d in downstream:
        timeline.append({
            "stage": "후속공정", "event": d.get("process_code"),
            "lot_id": d.get("lot_id"),
            "date": str(d.get("start_time")),
            "detail": f"산출 {d.get('output_qty_kg')}kg / 수율 {d.get('yield_rate')}%",
            "status": d.get("status"),
        })

    return {
        "lot_id": lot_id,
        "lot": lot_d,
        "step_count": len(timeline),
        "timeline": timeline,
        "downstream": downstream,
    }


# =====================================================================
# 12. 공급처 품질 분석 (월별 추세)
#     ※ /suppliers/ranking 뒤에 선언 — 고정 경로 우선 보장
# =====================================================================
@router.get("/suppliers/{supplier_code}/quality")
async def get_supplier_quality(
    supplier_code: str,
    months: int = Query(6, ge=1, le=24),
):
    """공급처 품질 분석 — 최근 N개월 월별 pass_rate / freshness / 입고량."""
    async with get_db() as conn:
        supplier = await conn.fetchrow(
            "SELECT supplier_code, supplier_name, region FROM supplier WHERE supplier_code = $1",
            supplier_code,
        )
        if not supplier:
            raise HTTPException(status_code=404, detail=f"공급처 {supplier_code} 없음")
        rows = await conn.fetch(
            """
            SELECT year_month, total_lots, passed_lots, pass_rate_pct,
                   avg_freshness, avg_water_content_pct, total_kg
            FROM supplier_quality_score
            WHERE supplier_code = $1
            ORDER BY year_month DESC
            LIMIT $2
            """,
            supplier_code, months,
        )
    monthly = [_to_dict(r) for r in reversed(rows)]  # 오래된→최신 순 정렬
    summary = {}
    if monthly:
        total_lots = sum(m["total_lots"] or 0 for m in monthly)
        passed_lots = sum(m["passed_lots"] or 0 for m in monthly)
        summary = {
            "period_months": len(monthly),
            "total_lots": total_lots,
            "passed_lots": passed_lots,
            "overall_pass_rate_pct": round(passed_lots * 100.0 / total_lots, 2)
            if total_lots else None,
            "avg_freshness": round(
                sum((m["avg_freshness"] or 0) for m in monthly) / len(monthly), 2
            ),
        }
    return {"supplier": _to_dict(supplier), "monthly": monthly, "summary": summary}


# =====================================================================
# 14. 오늘 입고 현황 요약
# =====================================================================
@router.get("/summary/today")
async def get_today_summary():
    """오늘 입고 현황 — 총 입고 LOT/kg, 검사 완료 수, 합격률."""
    async with get_db() as conn:
        lot_stat = await conn.fetchrow(
            """
            SELECT COUNT(*)                       AS total_lots,
                   COALESCE(SUM(quantity_kg), 0)  AS total_kg,
                   COUNT(*) FILTER (WHERE lot_status = 'PASSED')   AS passed_lots,
                   COUNT(*) FILTER (WHERE lot_status = 'REJECTED') AS rejected_lots,
                   COUNT(*) FILTER (WHERE lot_status = 'RECEIVED') AS pending_lots
            FROM raw_material_lot
            WHERE intake_date = CURRENT_DATE
            """
        )
        insp_stat = await conn.fetchrow(
            """
            SELECT COUNT(*) AS inspected,
                   COUNT(*) FILTER (WHERE qc_result = 'PASS') AS passed
            FROM incoming_inspection
            WHERE inspection_date = CURRENT_DATE
            """
        )
    ld = _to_dict(lot_stat)
    ins = _to_dict(insp_stat)
    inspected = ins.get("inspected", 0) or 0
    passed = ins.get("passed", 0) or 0
    return {
        "date": str(date.today()),
        "total_lots": ld.get("total_lots", 0),
        "total_kg": float(ld.get("total_kg") or 0),
        "passed_lots": ld.get("passed_lots", 0),
        "rejected_lots": ld.get("rejected_lots", 0),
        "pending_lots": ld.get("pending_lots", 0),
        "inspected_count": inspected,
        "inspection_pass_rate_pct": round(passed * 100.0 / inspected, 2) if inspected else None,
    }
