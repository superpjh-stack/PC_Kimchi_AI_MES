"""
꽃순이김치 제조AI MES — 포장출하관리 API 라우터
프로젝트: SF26179540 / 로뎀솔루션

prefix: /api/v1/shipping
대상 테이블: packaging_lot, packaging_inspection, shipping_order,
            shipping_lot_mapping, claim_record  (db_shipping_schema.sql)

설계 원칙 (fastapi-mes 스킬):
  1. 모든 조회 엔드포인트는 LOT ID / 날짜 / 상태 기반 필터링을 지원한다
  2. 비동기(async/await + asyncpg) 기본
  3. Pydantic v2 모델로 요청/응답 스키마 정의
  4. 출하 승인(approve)은 MANAGER/ADMIN 권한 필요 (require_role 의존성)
  5. LOT 역추적(/trace)은 packaging_lot → process_result(발효/절임) →
     raw_material_lot 체인을 통합 조회한다

app/main.py 에서:  app.include_router(shipping.router)
"""
from __future__ import annotations

import json
from datetime import date, datetime
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

# 프로젝트 공통 DB 컨텍스트 (app/database.py)
from app.database import get_db
from app.auth import require_role  # 실제 JWT + RBAC 검증

router = APIRouter(prefix="/api/v1/shipping", tags=["포장출하관리"])


# =====================================================================
# 공통 정의 / 상수
# =====================================================================
class ProductCode(str, Enum):
    BC300 = "KIM-BC-300"
    BC500 = "KIM-BC-500"
    BC1000 = "KIM-BC-1000"
    BC2000 = "KIM-BC-2000"
    BC5000 = "KIM-BC-5000"


# 제품 코드별 메타데이터 (단위 중량 g / 표준 단가 KRW) — 출하 금액 환산에 사용
PRODUCT_META: dict[str, dict[str, Any]] = {
    "KIM-BC-300":  {"name": "배추김치 300g",  "unit_weight_g": 300,  "unit_price": 4500},
    "KIM-BC-500":  {"name": "배추김치 500g",  "unit_weight_g": 500,  "unit_price": 6900},
    "KIM-BC-1000": {"name": "배추김치 1kg",   "unit_weight_g": 1000, "unit_price": 12900},
    "KIM-BC-2000": {"name": "배추김치 2kg",   "unit_weight_g": 2000, "unit_price": 23900},
    "KIM-BC-5000": {"name": "배추김치 5kg",   "unit_weight_g": 5000, "unit_price": 54000},
}

LOT_STATUS = ("PACKED", "INSPECTED", "SHIPPED", "HOLD")
ORDER_STATUS = ("PENDING", "PICKING", "SHIPPED", "DELIVERED", "CANCELLED")
QC_RESULT = ("PASS", "FAIL", "HOLD")
CLAIM_TYPE = ("QUALITY", "DELIVERY", "FOREIGN", "LABELING", "OTHER")
CLAIM_STATUS = ("OPEN", "INVESTIGATING", "RESOLVED", "CLOSED")
SEVERITY = ("MINOR", "NORMAL", "MAJOR", "CRITICAL")


def _enrich_product(d: dict[str, Any]) -> dict[str, Any]:
    """제품 코드에 제품명/단위중량/단가 메타 부가."""
    meta = PRODUCT_META.get(d.get("product_code", ""), {})
    d["product_name"] = meta.get("name")
    d["unit_weight_g"] = meta.get("unit_weight_g")
    d["unit_price"] = meta.get("unit_price")
    return d


# =====================================================================
# Pydantic 모델
# =====================================================================
class PackagingLotCreate(BaseModel):
    lot_id: str = Field(..., max_length=30, description="PK-YYYYMMDD-NNN")
    source_lot_id: str | None = Field(None, max_length=30, description="발효 LOT")
    packaging_date: date | None = None
    product_code: ProductCode
    line_no: str | None = None
    operator: str | None = None
    input_qty_kg: float = Field(..., ge=0)
    output_units: int = Field(..., ge=0)
    defect_units: int = Field(0, ge=0)
    metal_detection: bool = False
    lot_status: str = "PACKED"
    barcode: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "PackagingLotCreate":
        if self.lot_status not in LOT_STATUS:
            raise ValueError(f"lot_status 는 {LOT_STATUS} 중 하나여야 합니다")
        return self


class PackagingLotResponse(BaseModel):
    lot_id: str
    source_lot_id: str | None = None
    packaging_date: date
    product_code: str
    product_name: str | None = None
    unit_weight_g: int | None = None
    unit_price: int | None = None
    line_no: str | None = None
    operator: str | None = None
    input_qty_kg: float
    output_units: int
    defect_units: int | None = None
    metal_detection: bool
    lot_status: str
    barcode: str | None = None
    created_at: datetime


class LotStatusUpdate(BaseModel):
    lot_status: str

    @model_validator(mode="after")
    def _validate(self) -> "LotStatusUpdate":
        if self.lot_status not in LOT_STATUS:
            raise ValueError(f"lot_status 는 {LOT_STATUS} 중 하나여야 합니다")
        return self


class InspectionCreate(BaseModel):
    lot_id: str = Field(..., max_length=30)
    inspector: str
    inspection_date: date | None = None
    salinity_pct: float | None = None
    acidity_ph: float | None = None
    appearance_score: int | None = Field(None, ge=1, le=5)
    fermentation_level: str | None = None
    net_weight_g: float | None = None
    packaging_integrity: bool = True
    qc_result: str
    fail_reason: str | None = None
    corrective_action: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "InspectionCreate":
        if self.qc_result not in QC_RESULT:
            raise ValueError(f"qc_result 는 {QC_RESULT} 중 하나여야 합니다")
        if self.fermentation_level and self.fermentation_level not in (
            "FRESH", "MILD", "RIPE", "OVERRIPE"
        ):
            raise ValueError("fermentation_level 은 FRESH/MILD/RIPE/OVERRIPE")
        # 불합격(FAIL/HOLD)이면 사유 필수
        if self.qc_result in ("FAIL", "HOLD") and not self.fail_reason:
            raise ValueError("FAIL/HOLD 판정 시 fail_reason(불합격 사유)이 필요합니다")
        return self


class ShippingOrderCreate(BaseModel):
    order_no: str = Field(..., max_length=30, description="SO-YYYYMMDD-NNN")
    customer_name: str
    customer_code: str | None = None
    ship_date: date
    delivery_address: str | None = None
    product_code: ProductCode
    ordered_units: int = Field(..., gt=0)
    shipping_company: str | None = None
    tracking_no: str | None = None
    created_by: str | None = None


class OrderShip(BaseModel):
    shipped_units: int = Field(..., ge=0)
    shipping_company: str | None = None
    tracking_no: str | None = None


class LotAllocation(BaseModel):
    lot_id: str = Field(..., max_length=30)
    allocated_units: int = Field(..., gt=0)


class ClaimCreate(BaseModel):
    claim_no: str | None = Field(None, max_length=30)
    order_id: int | None = None
    lot_id: str | None = Field(None, max_length=30)
    claim_date: date | None = None
    customer_name: str | None = None
    claim_type: str
    claim_content: str
    severity: str = "NORMAL"

    @model_validator(mode="after")
    def _validate(self) -> "ClaimCreate":
        if self.claim_type not in CLAIM_TYPE:
            raise ValueError(f"claim_type 는 {CLAIM_TYPE} 중 하나여야 합니다")
        if self.severity not in SEVERITY:
            raise ValueError(f"severity 는 {SEVERITY} 중 하나여야 합니다")
        return self


class ClaimUpdate(BaseModel):
    root_cause: str | None = None
    corrective_action: str | None = None
    recurrence_prevention: str | None = None
    severity: str | None = None
    status: str | None = None
    resolved_by: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "ClaimUpdate":
        if self.status and self.status not in CLAIM_STATUS:
            raise ValueError(f"status 는 {CLAIM_STATUS} 중 하나여야 합니다")
        if self.severity and self.severity not in SEVERITY:
            raise ValueError(f"severity 는 {SEVERITY} 중 하나여야 합니다")
        return self


# =====================================================================
# 1. 포장 LOT 등록
# =====================================================================
@router.post("/packaging/lots", response_model=PackagingLotResponse, status_code=201)
async def create_packaging_lot(data: PackagingLotCreate):
    """포장 LOT 등록. lot_id 중복 시 409 반환."""
    async with get_db() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM packaging_lot WHERE lot_id = $1", data.lot_id
        )
        if exists:
            raise HTTPException(status_code=409, detail=f"포장 LOT {data.lot_id} 이미 존재")
        row = await conn.fetchrow(
            """
            INSERT INTO packaging_lot
                (lot_id, source_lot_id, packaging_date, product_code, line_no, operator,
                 input_qty_kg, output_units, defect_units, metal_detection, lot_status, barcode)
            VALUES ($1,$2, COALESCE($3, CURRENT_DATE), $4,$5,$6,$7,$8,$9,$10,$11,$12)
            RETURNING *
            """,
            data.lot_id, data.source_lot_id, data.packaging_date, data.product_code.value,
            data.line_no, data.operator, data.input_qty_kg, data.output_units,
            data.defect_units, data.metal_detection, data.lot_status, data.barcode,
        )
    return _enrich_product(dict(row))


# =====================================================================
# 2. 포장 LOT 목록
# =====================================================================
@router.get("/packaging/lots", response_model=list[PackagingLotResponse])
async def list_packaging_lots(
    date_from: date | None = None,
    product_code: ProductCode | None = None,
    lot_status: str | None = Query(None),
    lot_id: str | None = None,
    limit: int = Query(50, le=500),
):
    """포장 LOT 목록 (date_from / product_code / lot_status / lot_id 필터)."""
    clauses: list[str] = []
    params: list[Any] = []
    if date_from:
        params.append(date_from)
        clauses.append(f"packaging_date >= ${len(params)}")
    if product_code:
        params.append(product_code.value)
        clauses.append(f"product_code = ${len(params)}")
    if lot_status:
        if lot_status not in LOT_STATUS:
            raise HTTPException(status_code=400, detail=f"lot_status 는 {LOT_STATUS}")
        params.append(lot_status)
        clauses.append(f"lot_status = ${len(params)}")
    if lot_id:
        params.append(lot_id)
        clauses.append(f"(lot_id = ${len(params)} OR source_lot_id = ${len(params)})")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT * FROM packaging_lot
            {where}
            ORDER BY packaging_date DESC, created_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return [_enrich_product(dict(r)) for r in rows]


# =====================================================================
# 3. 포장 LOT 상세
# =====================================================================
@router.get("/packaging/lots/{lot_id}")
async def get_packaging_lot(lot_id: str):
    """포장 LOT 상세 + 해당 LOT 검사 이력 + 매핑된 출하 주문."""
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT * FROM packaging_lot WHERE lot_id = $1", lot_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"포장 LOT {lot_id} 없음")
        inspections = await conn.fetch(
            "SELECT * FROM packaging_inspection WHERE lot_id = $1 ORDER BY inspection_date DESC",
            lot_id,
        )
        orders = await conn.fetch(
            """
            SELECT m.order_id, m.allocated_units, o.order_no, o.customer_name, o.order_status
            FROM shipping_lot_mapping m
            JOIN shipping_order o ON o.order_id = m.order_id
            WHERE m.lot_id = $1
            """,
            lot_id,
        )
    result = _enrich_product(dict(row))
    result["inspections"] = [dict(i) for i in inspections]
    result["shipping_orders"] = [dict(o) for o in orders]
    return result


# =====================================================================
# 4. 포장 LOT 상태 변경
# =====================================================================
@router.patch("/packaging/lots/{lot_id}/status", response_model=PackagingLotResponse)
async def update_packaging_lot_status(lot_id: str, data: LotStatusUpdate):
    """포장 LOT 상태 변경 (PACKED/INSPECTED/SHIPPED/HOLD)."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            "UPDATE packaging_lot SET lot_status = $2 WHERE lot_id = $1 RETURNING *",
            lot_id, data.lot_status,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"포장 LOT {lot_id} 없음")
    return _enrich_product(dict(row))


# =====================================================================
# 5. 포장 검사 등록
# =====================================================================
@router.post("/inspections", status_code=201)
async def create_inspection(data: InspectionCreate):
    """포장 검사 등록. PASS 시 LOT 상태 INSPECTED, FAIL/HOLD 시 HOLD 로 자동 갱신."""
    async with get_db() as conn:
        lot = await conn.fetchval(
            "SELECT 1 FROM packaging_lot WHERE lot_id = $1", data.lot_id
        )
        if not lot:
            raise HTTPException(status_code=404, detail=f"포장 LOT {data.lot_id} 없음")
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO packaging_inspection
                    (lot_id, inspector, inspection_date, salinity_pct, acidity_ph,
                     appearance_score, fermentation_level, net_weight_g, packaging_integrity,
                     qc_result, fail_reason, corrective_action)
                VALUES ($1,$2, COALESCE($3, CURRENT_DATE),$4,$5,$6,$7,$8,$9,$10,$11,$12)
                RETURNING *
                """,
                data.lot_id, data.inspector, data.inspection_date, data.salinity_pct,
                data.acidity_ph, data.appearance_score, data.fermentation_level,
                data.net_weight_g, data.packaging_integrity, data.qc_result,
                data.fail_reason, data.corrective_action,
            )
            new_status = "INSPECTED" if data.qc_result == "PASS" else "HOLD"
            await conn.execute(
                "UPDATE packaging_lot SET lot_status = $2 WHERE lot_id = $1",
                data.lot_id, new_status,
            )
    result = dict(row)
    result["lot_status_updated"] = new_status
    return result


# =====================================================================
# 6. 포장 검사 목록
# =====================================================================
@router.get("/inspections")
async def list_inspections(
    lot_id: str | None = None,
    qc_result: str | None = None,
    limit: int = Query(50, le=500),
):
    """포장 검사 목록 (lot_id / qc_result 필터)."""
    clauses: list[str] = []
    params: list[Any] = []
    if lot_id:
        params.append(lot_id)
        clauses.append(f"lot_id = ${len(params)}")
    if qc_result:
        if qc_result not in QC_RESULT:
            raise HTTPException(status_code=400, detail=f"qc_result 는 {QC_RESULT}")
        params.append(qc_result)
        clauses.append(f"qc_result = ${len(params)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT * FROM packaging_inspection
            {where}
            ORDER BY inspection_date DESC, inspection_id DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return [dict(r) for r in rows]


# =====================================================================
# 7. 출하 주문 등록
# =====================================================================
@router.post("/orders", status_code=201)
async def create_order(data: ShippingOrderCreate):
    """출하 주문 등록. order_no 중복 시 409."""
    async with get_db() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM shipping_order WHERE order_no = $1", data.order_no
        )
        if exists:
            raise HTTPException(status_code=409, detail=f"주문번호 {data.order_no} 이미 존재")
        row = await conn.fetchrow(
            """
            INSERT INTO shipping_order
                (order_no, customer_name, customer_code, ship_date, delivery_address,
                 product_code, ordered_units, shipping_company, tracking_no, created_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            RETURNING *
            """,
            data.order_no, data.customer_name, data.customer_code, data.ship_date,
            data.delivery_address, data.product_code.value, data.ordered_units,
            data.shipping_company, data.tracking_no, data.created_by,
        )
    return _enrich_product(dict(row))


# =====================================================================
# 8. 출하 주문 목록
# =====================================================================
@router.get("/orders")
async def list_orders(
    order_status: str | None = None,
    ship_date: date | None = None,
    customer_code: str | None = None,
    limit: int = Query(50, le=500),
):
    """출하 주문 목록 (order_status / ship_date / customer_code 필터)."""
    clauses: list[str] = []
    params: list[Any] = []
    if order_status:
        if order_status not in ORDER_STATUS:
            raise HTTPException(status_code=400, detail=f"order_status 는 {ORDER_STATUS}")
        params.append(order_status)
        clauses.append(f"order_status = ${len(params)}")
    if ship_date:
        params.append(ship_date)
        clauses.append(f"ship_date = ${len(params)}")
    if customer_code:
        params.append(customer_code)
        clauses.append(f"customer_code = ${len(params)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT * FROM shipping_order
            {where}
            ORDER BY ship_date DESC, created_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return [_enrich_product(dict(r)) for r in rows]


# =====================================================================
# 9. 출하 주문 상세 (매핑된 LOT 목록 포함)
# =====================================================================
@router.get("/orders/{order_id}")
async def get_order(order_id: int):
    """출하 주문 상세 + 매핑된 포장 LOT 목록."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM shipping_order WHERE order_id = $1", order_id
        )
        if not row:
            raise HTTPException(status_code=404, detail=f"주문 {order_id} 없음")
        lots = await conn.fetch(
            """
            SELECT m.mapping_id, m.lot_id, m.allocated_units,
                   pl.product_code, pl.lot_status, pl.barcode, pl.source_lot_id
            FROM shipping_lot_mapping m
            JOIN packaging_lot pl ON pl.lot_id = m.lot_id
            WHERE m.order_id = $1
            ORDER BY m.mapping_id
            """,
            order_id,
        )
    result = _enrich_product(dict(row))
    result["allocated_lots"] = [dict(l) for l in lots]
    result["allocated_total_units"] = sum(l["allocated_units"] for l in lots)
    return result


# =====================================================================
# 10. 출하 승인 (MANAGER/ADMIN)
# =====================================================================
@router.patch("/orders/{order_id}/approve")
async def approve_order(
    order_id: int,
    _role: str = Depends(require_role("MANAGER", "ADMIN")),
):
    """출하 승인. PENDING/PICKING 상태에서만 승인 가능, 상태를 PICKING 으로 전환."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT order_status FROM shipping_order WHERE order_id = $1", order_id
        )
        if not row:
            raise HTTPException(status_code=404, detail=f"주문 {order_id} 없음")
        if row["order_status"] not in ("PENDING", "PICKING"):
            raise HTTPException(
                status_code=409,
                detail=f"승인 불가 상태: {row['order_status']} (PENDING/PICKING 만 승인 가능)",
            )
        updated = await conn.fetchrow(
            """
            UPDATE shipping_order
            SET approved_by = $2, approved_at = NOW(),
                order_status = 'PICKING'
            WHERE order_id = $1
            RETURNING order_id, order_no, order_status, approved_by, approved_at
            """,
            order_id, _role,
        )
    return {"message": "출하 승인 완료", **dict(updated)}


# =====================================================================
# 11. 출하 처리
# =====================================================================
@router.patch("/orders/{order_id}/ship")
async def ship_order(order_id: int, data: OrderShip):
    """출하 처리. 승인(approved_at) 되지 않은 주문은 출하 불가.
    출하 처리 시 매핑된 포장 LOT 상태를 SHIPPED 로 일괄 갱신한다."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT order_status, approved_at FROM shipping_order WHERE order_id = $1",
            order_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail=f"주문 {order_id} 없음")
        if row["approved_at"] is None:
            raise HTTPException(status_code=409, detail="미승인 주문은 출하할 수 없습니다 (먼저 승인 필요)")
        if row["order_status"] in ("SHIPPED", "DELIVERED", "CANCELLED"):
            raise HTTPException(
                status_code=409, detail=f"출하 불가 상태: {row['order_status']}"
            )
        async with conn.transaction():
            updated = await conn.fetchrow(
                """
                UPDATE shipping_order
                SET shipped_units = $2,
                    shipping_company = COALESCE($3, shipping_company),
                    tracking_no = COALESCE($4, tracking_no),
                    order_status = 'SHIPPED'
                WHERE order_id = $1
                RETURNING *
                """,
                order_id, data.shipped_units, data.shipping_company, data.tracking_no,
            )
            await conn.execute(
                """
                UPDATE packaging_lot SET lot_status = 'SHIPPED'
                WHERE lot_id IN (
                    SELECT lot_id FROM shipping_lot_mapping WHERE order_id = $1
                )
                """,
                order_id,
            )
    return {"message": "출하 처리 완료", **_enrich_product(dict(updated))}


# =====================================================================
# 12. 주문에 LOT 할당
# =====================================================================
@router.post("/orders/{order_id}/lots", status_code=201)
async def allocate_lot(order_id: int, data: LotAllocation):
    """출하 주문에 포장 LOT 할당. (order_id, lot_id) 중복 시 409."""
    async with get_db() as conn:
        order = await conn.fetchval(
            "SELECT 1 FROM shipping_order WHERE order_id = $1", order_id
        )
        if not order:
            raise HTTPException(status_code=404, detail=f"주문 {order_id} 없음")
        lot = await conn.fetchval(
            "SELECT 1 FROM packaging_lot WHERE lot_id = $1", data.lot_id
        )
        if not lot:
            raise HTTPException(status_code=404, detail=f"포장 LOT {data.lot_id} 없음")
        dup = await conn.fetchval(
            "SELECT 1 FROM shipping_lot_mapping WHERE order_id = $1 AND lot_id = $2",
            order_id, data.lot_id,
        )
        if dup:
            raise HTTPException(
                status_code=409, detail=f"이미 할당된 LOT: {data.lot_id}"
            )
        row = await conn.fetchrow(
            """
            INSERT INTO shipping_lot_mapping (order_id, lot_id, allocated_units)
            VALUES ($1,$2,$3)
            RETURNING *
            """,
            order_id, data.lot_id, data.allocated_units,
        )
    return {"message": "LOT 할당 완료", **dict(row)}


# =====================================================================
# 13. LOT 할당 취소
# =====================================================================
@router.delete("/orders/{order_id}/lots/{lot_id}")
async def deallocate_lot(order_id: int, lot_id: str):
    """출하 주문의 포장 LOT 할당 취소."""
    async with get_db() as conn:
        deleted = await conn.fetchval(
            """
            DELETE FROM shipping_lot_mapping
            WHERE order_id = $1 AND lot_id = $2
            RETURNING mapping_id
            """,
            order_id, lot_id,
        )
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"주문 {order_id} 의 LOT {lot_id} 할당 없음"
        )
    return {"message": "LOT 할당 취소 완료", "order_id": order_id, "lot_id": lot_id}


# =====================================================================
# 14. LOT 완전 역추적 (포장 → 발효 → 절임 → 입고 전체 체인)
# =====================================================================
async def _build_trace_chain(conn, packaging_lot_id: str) -> dict[str, Any]:
    """포장 LOT 을 기점으로 발효/절임/입고 LOT 체인을 통합 조회한다.

    체인 연결 규칙:
      packaging_lot.source_lot_id  -> 발효 LOT (process_result PROC07.lot_id)
      process_result(PROC07).source_lot_id -> 절임 LOT (PROC03.lot_id)
      process_result(PROC03).source_lot_id -> 입고 LOT (raw_material_lot.lot_id)
    발효/절임 물리 마스터가 없는 경우 process_result 행으로 단계를 구성한다.
    """
    pk = await conn.fetchrow(
        "SELECT * FROM packaging_lot WHERE lot_id = $1", packaging_lot_id
    )
    if not pk:
        return {}

    chain: list[dict[str, Any]] = []
    # 단계 1: 포장
    chain.append({
        "step": "PACKAGING", "step_name": "포장/출하", "lot_id": pk["lot_id"],
        "source_lot_id": pk["source_lot_id"], "product_code": pk["product_code"],
        "date": str(pk["packaging_date"]), "status": pk["lot_status"],
        "detail": {"output_units": pk["output_units"], "metal_detection": pk["metal_detection"],
                   "line_no": pk["line_no"], "operator": pk["operator"]},
    })

    # 단계 2: 발효 (process_result PROC07) — source_lot_id 로 추적
    ferment_lot = pk["source_lot_id"]
    salting_lot = None
    if ferment_lot:
        fr = await conn.fetchrow(
            """SELECT lot_id, source_lot_id, start_time, end_time, status, details
               FROM process_result
               WHERE lot_id = $1 AND process_code = 'PROC07'
               ORDER BY start_time DESC LIMIT 1""",
            ferment_lot,
        )
        if fr:
            details = fr["details"]
            details = json.loads(details) if isinstance(details, str) else details
            salting_lot = fr["source_lot_id"]
            chain.append({
                "step": "FERMENTATION", "step_name": "숙성/발효", "lot_id": fr["lot_id"],
                "source_lot_id": fr["source_lot_id"],
                "date": str(fr["start_time"]) if fr["start_time"] else None,
                "status": fr["status"], "detail": details,
            })
        else:
            # process_result 미존재 — LOT ID 만 단계로 보존(추적성 유지)
            chain.append({
                "step": "FERMENTATION", "step_name": "숙성/발효", "lot_id": ferment_lot,
                "source_lot_id": None, "date": None, "status": "UNKNOWN",
                "detail": {"note": "발효 공정 실적 데이터 없음 (LOT ID만 추적)"},
            })

    # 단계 3: 절임 (process_result PROC03)
    intake_lot = None
    if salting_lot:
        sr = await conn.fetchrow(
            """SELECT lot_id, source_lot_id, start_time, status, details
               FROM process_result
               WHERE lot_id = $1 AND process_code = 'PROC03'
               ORDER BY start_time DESC LIMIT 1""",
            salting_lot,
        )
        if sr:
            details = sr["details"]
            details = json.loads(details) if isinstance(details, str) else details
            intake_lot = sr["source_lot_id"]
            chain.append({
                "step": "SALTING", "step_name": "세척/절임", "lot_id": sr["lot_id"],
                "source_lot_id": sr["source_lot_id"],
                "date": str(sr["start_time"]) if sr["start_time"] else None,
                "status": sr["status"], "detail": details,
            })
        else:
            chain.append({
                "step": "SALTING", "step_name": "세척/절임", "lot_id": salting_lot,
                "source_lot_id": None, "date": None, "status": "UNKNOWN",
                "detail": {"note": "절임 공정 실적 데이터 없음"},
            })

    # 단계 4: 입고 (raw_material_lot) — 테이블이 없거나 행이 없으면 안전하게 스킵
    if intake_lot:
        try:
            ir = await conn.fetchrow(
                "SELECT * FROM raw_material_lot WHERE lot_id = $1", intake_lot
            )
        except Exception:  # noqa: BLE001  (raw_material_lot 미생성 환경 대비)
            ir = None
        if ir:
            d = dict(ir)
            chain.append({
                "step": "INTAKE", "step_name": "원재료 입고", "lot_id": d.get("lot_id"),
                "source_lot_id": None,
                "date": str(d.get("intake_date")) if d.get("intake_date") else None,
                "status": d.get("lot_status"),
                "detail": {k: v for k, v in d.items()
                           if k in ("supplier_code", "material_type", "origin",
                                    "weight_kg", "appearance_grade")},
            })
        else:
            chain.append({
                "step": "INTAKE", "step_name": "원재료 입고", "lot_id": intake_lot,
                "source_lot_id": None, "date": None, "status": "UNKNOWN",
                "detail": {"note": "입고 LOT 마스터 데이터 없음"},
            })

    return {
        "packaging_lot_id": packaging_lot_id,
        "step_count": len(chain),
        "chain": chain,
    }


@router.get("/trace/{lot_id}")
async def trace_lot(lot_id: str):
    """포장 LOT 기준 전체 LOT 역추적 (포장→발효→절임→입고)."""
    async with get_db() as conn:
        result = await _build_trace_chain(conn, lot_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"포장 LOT {lot_id} 없음")
    return result


# =====================================================================
# 15. 주문별 LOT 추적
# =====================================================================
@router.get("/trace/by-order/{order_id}")
async def trace_by_order(order_id: int):
    """출하 주문에 매핑된 모든 포장 LOT 의 역추적 체인 통합 조회."""
    async with get_db() as conn:
        order = await conn.fetchrow(
            "SELECT order_no, customer_name, product_code, order_status FROM shipping_order WHERE order_id = $1",
            order_id,
        )
        if not order:
            raise HTTPException(status_code=404, detail=f"주문 {order_id} 없음")
        mappings = await conn.fetch(
            "SELECT lot_id, allocated_units FROM shipping_lot_mapping WHERE order_id = $1",
            order_id,
        )
        traces = []
        for m in mappings:
            chain = await _build_trace_chain(conn, m["lot_id"])
            chain["allocated_units"] = m["allocated_units"]
            traces.append(chain)
    return {
        "order_id": order_id,
        "order_no": order["order_no"],
        "customer_name": order["customer_name"],
        "product_code": order["product_code"],
        "order_status": order["order_status"],
        "lot_count": len(traces),
        "traces": traces,
    }


# =====================================================================
# 16. 클레임 등록
# =====================================================================
@router.post("/claims", status_code=201)
async def create_claim(data: ClaimCreate):
    """클레임 등록. claim_no 미지정 시 CL-YYYYMMDD-NNN 자동 생성."""
    async with get_db() as conn:
        claim_no = data.claim_no
        if not claim_no:
            today = date.today()
            seq = await conn.fetchval(
                """SELECT COUNT(*) + 1 FROM claim_record
                   WHERE claim_date = CURRENT_DATE"""
            )
            claim_no = f"CL-{today:%Y%m%d}-{seq:03d}"
        row = await conn.fetchrow(
            """
            INSERT INTO claim_record
                (claim_no, order_id, lot_id, claim_date, customer_name,
                 claim_type, claim_content, severity)
            VALUES ($1,$2,$3, COALESCE($4, CURRENT_DATE),$5,$6,$7,$8)
            RETURNING *
            """,
            claim_no, data.order_id, data.lot_id, data.claim_date, data.customer_name,
            data.claim_type, data.claim_content, data.severity,
        )
    return dict(row)


# =====================================================================
# 17. 클레임 목록
# =====================================================================
@router.get("/claims")
async def list_claims(
    claim_type: str | None = None,
    status: str | None = None,
    lot_id: str | None = None,
    limit: int = Query(50, le=500),
):
    """클레임 목록 (claim_type / status / lot_id 필터)."""
    clauses: list[str] = []
    params: list[Any] = []
    if claim_type:
        if claim_type not in CLAIM_TYPE:
            raise HTTPException(status_code=400, detail=f"claim_type 는 {CLAIM_TYPE}")
        params.append(claim_type)
        clauses.append(f"claim_type = ${len(params)}")
    if status:
        if status not in CLAIM_STATUS:
            raise HTTPException(status_code=400, detail=f"status 는 {CLAIM_STATUS}")
        params.append(status)
        clauses.append(f"status = ${len(params)}")
    if lot_id:
        params.append(lot_id)
        clauses.append(f"lot_id = ${len(params)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT * FROM claim_record
            {where}
            ORDER BY (status IN ('OPEN','INVESTIGATING')) DESC,
                     claim_date DESC, claim_id DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return [dict(r) for r in rows]


# =====================================================================
# 18. 클레임 상세
# =====================================================================
@router.get("/claims/{claim_id}")
async def get_claim(claim_id: int):
    """클레임 상세 + 연관 주문/포장 LOT 정보."""
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT * FROM claim_record WHERE claim_id = $1", claim_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"클레임 {claim_id} 없음")
        result = dict(row)
        if row["order_id"]:
            order = await conn.fetchrow(
                "SELECT order_no, customer_name, product_code, order_status FROM shipping_order WHERE order_id = $1",
                row["order_id"],
            )
            result["order"] = dict(order) if order else None
        if row["lot_id"]:
            lot = await conn.fetchrow(
                "SELECT product_code, source_lot_id, lot_status, packaging_date FROM packaging_lot WHERE lot_id = $1",
                row["lot_id"],
            )
            result["packaging_lot"] = dict(lot) if lot else None
    return result


# =====================================================================
# 19. 클레임 업데이트 (원인분석/조치/상태)
# =====================================================================
@router.patch("/claims/{claim_id}")
async def update_claim(claim_id: int, data: ClaimUpdate):
    """클레임 업데이트. status -> RESOLVED/CLOSED 시 resolved_at 자동 기록."""
    sets: list[str] = []
    params: list[Any] = []
    for field in ("root_cause", "corrective_action", "recurrence_prevention",
                  "severity", "status", "resolved_by"):
        val = getattr(data, field)
        if val is not None:
            params.append(val)
            sets.append(f"{field} = ${len(params)}")
    if not sets:
        raise HTTPException(status_code=400, detail="변경할 필드가 없습니다")
    # 처리 완료 상태로 전환 시 resolved_at 자동 설정
    if data.status in ("RESOLVED", "CLOSED"):
        sets.append("resolved_at = NOW()")
    params.append(claim_id)

    async with get_db() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE claim_record SET {', '.join(sets)}
            WHERE claim_id = ${len(params)}
            RETURNING *
            """,
            *params,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"클레임 {claim_id} 없음")
    return dict(row)


# =====================================================================
# 20. 클레임 유형별 분석 (최근 90일)
# =====================================================================
@router.get("/claims/analysis/summary")
async def claim_analysis_summary(days: int = Query(90, ge=1, le=365)):
    """클레임 유형별 분석: 최근 N일(기본 90일) claim_type 별 건수/비율 + 월별 추세."""
    async with get_db() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM claim_record WHERE claim_date >= CURRENT_DATE - ($1 || ' days')::INTERVAL",
            str(days),
        )
        by_type = await conn.fetch(
            """
            SELECT claim_type,
                   COUNT(*)                                              AS claim_count,
                   COUNT(*) FILTER (WHERE status IN ('OPEN','INVESTIGATING')) AS open_count,
                   COUNT(*) FILTER (WHERE severity IN ('MAJOR','CRITICAL'))   AS severe_count
            FROM claim_record
            WHERE claim_date >= CURRENT_DATE - ($1 || ' days')::INTERVAL
            GROUP BY claim_type
            ORDER BY claim_count DESC
            """,
            str(days),
        )
        monthly = await conn.fetch(
            """
            SELECT TO_CHAR(DATE_TRUNC('month', claim_date), 'YYYY-MM') AS month,
                   COUNT(*) AS claim_count
            FROM claim_record
            WHERE claim_date >= CURRENT_DATE - ($1 || ' days')::INTERVAL
            GROUP BY DATE_TRUNC('month', claim_date)
            ORDER BY month
            """,
            str(days),
        )

    total = total or 0
    type_list = []
    for r in by_type:
        d = dict(r)
        d["ratio_pct"] = round(100.0 * d["claim_count"] / total, 1) if total else 0.0
        type_list.append(d)

    return {
        "period_days": days,
        "total_claims": total,
        "by_type": type_list,
        "monthly_trend": [dict(r) for r in monthly],
    }


# =====================================================================
# 21. 오늘 포장/출하 현황
# =====================================================================
@router.get("/summary/today")
async def summary_today():
    """오늘 기준 포장/출하 핵심 현황 (현황판/대시보드용)."""
    async with get_db() as conn:
        packaging = await conn.fetchrow(
            """
            SELECT COUNT(*)                              AS lot_count,
                   COALESCE(SUM(output_units), 0)        AS total_units,
                   COALESCE(SUM(defect_units), 0)        AS defect_units,
                   COALESCE(SUM(input_qty_kg), 0)        AS input_kg,
                   COUNT(*) FILTER (WHERE lot_status = 'HOLD') AS hold_count
            FROM packaging_lot
            WHERE packaging_date = CURRENT_DATE
            """
        )
        orders = await conn.fetchrow(
            """
            SELECT COUNT(*)                                          AS order_count,
                   COUNT(*) FILTER (WHERE order_status = 'PENDING')  AS pending_count,
                   COUNT(*) FILTER (WHERE order_status = 'SHIPPED')  AS shipped_count,
                   COALESCE(SUM(shipped_units), 0)                   AS shipped_units
            FROM shipping_order
            WHERE ship_date = CURRENT_DATE
            """
        )
        open_claims = await conn.fetchval(
            "SELECT COUNT(*) FROM claim_record WHERE status IN ('OPEN','INVESTIGATING')"
        )
        pkg = dict(packaging) if packaging else {}
        units = (pkg.get("total_units") or 0) + (pkg.get("defect_units") or 0)
        defect_rate = round(100.0 * (pkg.get("defect_units") or 0) / units, 2) if units else 0.0

    return {
        "date": str(date.today()),
        "packaging": {**pkg, "defect_rate_pct": defect_rate},
        "shipping": dict(orders) if orders else {},
        "open_claims": open_claims or 0,
    }
