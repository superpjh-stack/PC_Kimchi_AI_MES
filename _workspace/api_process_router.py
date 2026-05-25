"""
꽃순이김치 제조AI MES — 공정관리 API 라우터
프로젝트: SF26179540 / 로뎀솔루션

prefix: /api/v1/process
대상 테이블: process_result, process_recipe, recipe_ingredient,
            recipe_process, process_alarm  (db_process_schema.sql)

설계 원칙 (fastapi-mes 스킬):
  1. 모든 조회 엔드포인트는 LOT/공정코드/날짜 기반 필터링 지원
  2. 비동기(async/await + asyncpg) 기본
  3. Pydantic v2 모델로 요청/응답 스키마 정의
  4. 공정코드별 필수 필드 검증 (ProcessResultCreate validator)
  5. 레시피 등록/수정은 공장장/관리자 권한 (require_role 의존성)

app/main.py 에서:  app.include_router(process.router)
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

# 프로젝트 공통 DB 컨텍스트 (app/database.py)
from app.database import get_db
from app.auth import get_current_user, get_user_roles, require_role

router = APIRouter(prefix="/api/v1/process", tags=["공정관리"])


# =====================================================================
# 공통 정의
# =====================================================================
class ProcessCode(str, Enum):
    PROC01 = "PROC01"  # 입고/보관
    PROC02 = "PROC02"  # 절단/전처리
    PROC03 = "PROC03"  # 세척/절임
    PROC04 = "PROC04"  # 세척/선별
    PROC05 = "PROC05"  # 탈수
    PROC06 = "PROC06"  # 혼합
    PROC07 = "PROC07"  # 숙성/발효
    PROC08 = "PROC08"  # 금속검출
    PROC09 = "PROC09"  # 포장/출하


PROCESS_NAME = {
    "PROC01": "입고/보관", "PROC02": "절단/전처리", "PROC03": "세척/절임",
    "PROC04": "세척/선별", "PROC05": "탈수", "PROC06": "혼합",
    "PROC07": "숙성/발효", "PROC08": "금속검출", "PROC09": "포장/출하",
}

# 공정코드별 details(JSONB) 필수 측정 항목 — 공정별 입력 검증에 사용
REQUIRED_DETAIL_FIELDS: dict[str, list[str]] = {
    "PROC01": ["supplier_code", "material_code", "origin", "qc_pass"],
    "PROC02": ["work_minutes"],
    "PROC03": ["salt_temp", "salt_density", "salt_ph", "salt_hours", "salt_input_kg"],
    "PROC04": ["wash_count"],
    "PROC05": ["weight_before_kg", "weight_after_kg"],
    "PROC06": ["recipe_code", "mix_minutes"],
    "PROC07": ["ferment_room", "init_temp", "init_ph", "init_acidity", "target_hours"],
    "PROC08": ["inspect_qty_kg", "abnormal_count", "detector_code"],
    "PROC09": ["product_code", "package_unit_g", "package_qty", "weight_pass_rate"],
}


# =====================================================================
# Pydantic 모델
# =====================================================================
class ProcessResultCreate(BaseModel):
    process_code: ProcessCode
    lot_id: str = Field(..., max_length=30)
    source_lot_id: str | None = Field(None, max_length=30)
    product_code: str | None = None
    recipe_id: int | None = None
    input_qty_kg: float | None = Field(None, ge=0)
    output_qty_kg: float | None = Field(None, ge=0)
    defect_qty_kg: float = Field(0, ge=0)
    defect_code: str | None = None
    worker: str | None = None
    equipment_code: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    status: str = "IN_PROGRESS"
    details: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "ProcessResultCreate":
        # 공정코드별 필수 details 필드 검증
        required = REQUIRED_DETAIL_FIELDS.get(self.process_code.value, [])
        missing = [f for f in required if f not in self.details or self.details[f] in (None, "")]
        if missing:
            raise ValueError(
                f"{self.process_code.value}({PROCESS_NAME[self.process_code.value]}) "
                f"필수 항목 누락: {missing}"
            )
        # 산출 수량은 투입 수량을 초과할 수 없다
        if (self.input_qty_kg is not None and self.output_qty_kg is not None
                and self.output_qty_kg > self.input_qty_kg):
            raise ValueError("산출 수량은 투입 수량을 초과할 수 없습니다")
        # 종료 시각은 시작 시각 이후
        if self.end_time is not None and self.end_time < self.start_time:
            raise ValueError("종료 시각은 시작 시각 이후여야 합니다")
        # 불량 사유 코드: 불량 수량 > 0 이면 필수
        if self.defect_qty_kg and self.defect_qty_kg > 0 and not self.defect_code:
            raise ValueError("불량 수량이 있으면 불량 사유 코드가 필요합니다")
        return self


class ProcessResultResponse(BaseModel):
    result_id: int
    process_code: str
    process_name: str | None = None
    lot_id: str
    source_lot_id: str | None = None
    input_qty_kg: float | None = None
    output_qty_kg: float | None = None
    defect_qty_kg: float | None = None
    yield_rate: float | None = None
    worker: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    status: str
    details: dict[str, Any] | None = None


class AlarmResponse(BaseModel):
    alarm_id: int
    lot_id: str | None = None
    process_code: str
    process_name: str | None = None
    alarm_level: str
    alarm_type: str
    message: str
    measured_value: float | None = None
    threshold_value: str | None = None
    status: str
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime


class AlarmResolve(BaseModel):
    resolved_by: str
    resolve_note: str | None = None


class RecipeIngredientIn(BaseModel):
    material_code: str
    material_name: str
    standard_ratio: float = Field(..., ge=0, le=100)
    min_ratio: float | None = None
    max_ratio: float | None = None
    unit: str = "kg"


class RecipeProcessIn(BaseModel):
    process_code: ProcessCode
    pickling_salt_rate: float | None = None
    pickling_temp_min: float | None = None
    pickling_temp_max: float | None = None
    pickling_time_hour: float | None = None
    fermentation_temp: float | None = None
    fermentation_time_hour: float | None = None


class RecipeCreate(BaseModel):
    recipe_code: str
    product_code: str
    recipe_name: str
    version: str
    valid_from: date | None = None
    created_by: str
    notes: str | None = None
    ingredients: list[RecipeIngredientIn] = Field(default_factory=list)
    processes: list[RecipeProcessIn] = Field(default_factory=list)


# =====================================================================
# 1. 공정 실적 등록
# =====================================================================
@router.post("/results", response_model=ProcessResultResponse, status_code=201)
async def create_process_result(data: ProcessResultCreate):
    """공정 실적 등록. 공정코드별 필수 필드는 Pydantic validator 에서 검증."""
    # 수율 자동 계산
    yield_rate = None
    if data.input_qty_kg and data.input_qty_kg > 0 and data.output_qty_kg is not None:
        yield_rate = round(data.output_qty_kg / data.input_qty_kg * 100, 2)

    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO process_result
                (process_code, lot_id, source_lot_id, product_code, recipe_id,
                 input_qty_kg, output_qty_kg, defect_qty_kg, defect_code, yield_rate,
                 worker, equipment_code, start_time, end_time, status, details, remark)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb,$17)
            RETURNING *
            """,
            data.process_code.value, data.lot_id, data.source_lot_id, data.product_code,
            data.recipe_id, data.input_qty_kg, data.output_qty_kg, data.defect_qty_kg,
            data.defect_code, yield_rate, data.worker, data.equipment_code,
            data.start_time, data.end_time, data.status,
            __import__("json").dumps(data.details), data.remark,
        )
    result = dict(row)
    result["process_name"] = PROCESS_NAME.get(result["process_code"])
    result["details"] = __import__("json").loads(result["details"]) if isinstance(result.get("details"), str) else result.get("details")
    return result


# =====================================================================
# 2. 공정 실적 목록
# =====================================================================
@router.get("/results", response_model=list[ProcessResultResponse])
async def list_process_results(
    process_code: ProcessCode | None = None,
    work_date: date | None = Query(None, alias="date"),
    lot_id: str | None = None,
    limit: int = Query(100, le=500),
):
    """공정 실적 목록 (process_code / date / lot_id 필터)."""
    clauses: list[str] = []
    params: list[Any] = []
    if process_code:
        params.append(process_code.value)
        clauses.append(f"process_code = ${len(params)}")
    if work_date:
        params.append(work_date)
        clauses.append(f"DATE(start_time) = ${len(params)}")
    if lot_id:
        params.append(lot_id)
        clauses.append(f"(lot_id = ${len(params)} OR source_lot_id = ${len(params)})")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT * FROM process_result
            {where}
            ORDER BY start_time DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    out = []
    for r in rows:
        d = dict(r)
        d["process_name"] = PROCESS_NAME.get(d["process_code"])
        out.append(d)
    return out


# =====================================================================
# 3. LOT별 전 공정 이력 (타임라인)
# =====================================================================
@router.get("/results/{lot_id}/history")
async def get_lot_process_history(lot_id: str):
    """LOT 의 전 공정 이력 타임라인. lot_id 또는 source_lot_id 로 체인 추적."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            WITH RECURSIVE chain AS (
                SELECT * FROM process_result
                WHERE lot_id = $1 OR source_lot_id = $1
                UNION
                SELECT pr.* FROM process_result pr
                JOIN chain c
                  ON pr.lot_id = c.source_lot_id OR pr.source_lot_id = c.lot_id
            )
            SELECT DISTINCT result_id, process_code, lot_id, source_lot_id,
                   input_qty_kg, output_qty_kg, defect_qty_kg, yield_rate,
                   worker, start_time, end_time, status
            FROM chain
            ORDER BY process_code, start_time
            """,
            lot_id,
        )
    if not rows:
        raise HTTPException(status_code=404, detail=f"LOT {lot_id} 공정 이력 없음")

    timeline = []
    for r in rows:
        d = dict(r)
        d["process_name"] = PROCESS_NAME.get(d["process_code"])
        timeline.append(d)
    return {"lot_id": lot_id, "step_count": len(timeline), "timeline": timeline}


# =====================================================================
# 4. 실시간 공정 현황
# =====================================================================
@router.get("/monitor/realtime")
async def get_realtime_monitor():
    """각 공정 최신 상태 + 활성 알림 수 (현황판 P-10)."""
    async with get_db() as conn:
        latest = await conn.fetch(
            """
            SELECT DISTINCT ON (process_code)
                   process_code, lot_id, status, output_qty_kg, yield_rate,
                   start_time, end_time, details
            FROM process_result
            ORDER BY process_code, start_time DESC
            """
        )
        alarm_rows = await conn.fetch(
            """
            SELECT alarm_level, COUNT(*) AS cnt
            FROM process_alarm
            WHERE status = 'OPEN'
            GROUP BY alarm_level
            """
        )
        in_progress = await conn.fetchval(
            "SELECT COUNT(*) FROM process_result WHERE status = 'IN_PROGRESS'"
        )

    alarm_counts = {r["alarm_level"]: r["cnt"] for r in alarm_rows}
    processes = []
    for r in latest:
        d = dict(r)
        d["process_name"] = PROCESS_NAME.get(d["process_code"])
        d["details"] = __import__("json").loads(d["details"]) if isinstance(d.get("details"), str) else d.get("details")
        processes.append(d)

    return {
        "active_process_count": in_progress or 0,
        "alarm_warning": alarm_counts.get("WARNING", 0),
        "alarm_critical": alarm_counts.get("CRITICAL", 0),
        "alarm_total": sum(alarm_counts.values()),
        "processes": processes,
    }


# =====================================================================
# 5. 이상 알림 목록
# =====================================================================
@router.get("/alarms", response_model=list[AlarmResponse])
async def list_alarms(
    status: str | None = Query(None, pattern="^(OPEN|RESOLVED)$"),
    alarm_level: str | None = Query(None, pattern="^(WARNING|CRITICAL)$"),
    limit: int = Query(100, le=500),
):
    """이상 알림 목록 (status / alarm_level 필터)."""
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        params.append(status)
        clauses.append(f"status = ${len(params)}")
    if alarm_level:
        params.append(alarm_level)
        clauses.append(f"alarm_level = ${len(params)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT * FROM process_alarm
            {where}
            ORDER BY (status='OPEN') DESC,
                     (alarm_level='CRITICAL') DESC,
                     created_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    out = []
    for r in rows:
        d = dict(r)
        d["process_name"] = PROCESS_NAME.get(d["process_code"])
        out.append(d)
    return out


# =====================================================================
# 6. 알림 처리 완료
# =====================================================================
@router.patch("/alarms/{alarm_id}/resolve", response_model=AlarmResponse)
async def resolve_alarm(alarm_id: int, data: AlarmResolve):
    """알림 처리 완료 (status -> RESOLVED)."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            UPDATE process_alarm
            SET status = 'RESOLVED',
                resolved_by = $2,
                resolve_note = $3,
                resolved_at = NOW()
            WHERE alarm_id = $1 AND status = 'OPEN'
            RETURNING *
            """,
            alarm_id, data.resolved_by, data.resolve_note,
        )
    if not row:
        raise HTTPException(
            status_code=404, detail=f"알림 {alarm_id} 없음 또는 이미 처리됨"
        )
    d = dict(row)
    d["process_name"] = PROCESS_NAME.get(d["process_code"])
    return d


# =====================================================================
# 7. 레시피 목록
# =====================================================================
@router.get("/recipes")
async def list_recipes(product_code: str | None = None):
    """레시피 목록 (product_code 필터, 현행 is_active=TRUE 만)."""
    clauses = ["is_active = TRUE"]
    params: list[Any] = []
    if product_code:
        params.append(product_code)
        clauses.append(f"product_code = ${len(params)}")
    where = "WHERE " + " AND ".join(clauses)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT recipe_id, recipe_code, product_code, recipe_name, version,
                   is_active, valid_from, valid_to, approval_status,
                   created_by, approved_by, approved_at
            FROM process_recipe
            {where}
            ORDER BY product_code, recipe_code
            """,
            *params,
        )
        result = []
        for r in rows:
            d = dict(r)
            ing = await conn.fetch(
                """SELECT material_code, material_name, standard_ratio,
                          min_ratio, max_ratio, unit
                   FROM recipe_ingredient WHERE recipe_id = $1 ORDER BY sort_order""",
                d["recipe_id"],
            )
            d["ingredients"] = [dict(i) for i in ing]
            result.append(d)
    return result


# =====================================================================
# 8. 레시피 등록 (공장장/관리자)
# =====================================================================
@router.post("/recipes", status_code=201)
async def create_recipe(
    data: RecipeCreate,
    _role=Depends(require_role("ADMIN", "MANAGER")),
):
    """레시피 신규 등록. 원료 구성 + 공정 기준 함께 저장."""
    async with get_db() as conn:
        async with conn.transaction():
            recipe_id = await conn.fetchval(
                """
                INSERT INTO process_recipe
                    (recipe_code, product_code, recipe_name, version,
                     is_active, valid_from, approval_status, created_by, notes)
                VALUES ($1,$2,$3,$4, TRUE, COALESCE($5, CURRENT_DATE), 'DRAFT', $6, $7)
                RETURNING recipe_id
                """,
                data.recipe_code, data.product_code, data.recipe_name, data.version,
                data.valid_from, data.created_by, data.notes,
            )
            for idx, ing in enumerate(data.ingredients, start=1):
                await conn.execute(
                    """
                    INSERT INTO recipe_ingredient
                        (recipe_id, material_code, material_name, standard_ratio,
                         min_ratio, max_ratio, unit, sort_order)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    """,
                    recipe_id, ing.material_code, ing.material_name, ing.standard_ratio,
                    ing.min_ratio, ing.max_ratio, ing.unit, idx,
                )
            for proc in data.processes:
                await conn.execute(
                    """
                    INSERT INTO recipe_process
                        (recipe_id, process_code, pickling_salt_rate,
                         pickling_temp_min, pickling_temp_max, pickling_time_hour,
                         fermentation_temp, fermentation_time_hour)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    """,
                    recipe_id, proc.process_code.value, proc.pickling_salt_rate,
                    proc.pickling_temp_min, proc.pickling_temp_max, proc.pickling_time_hour,
                    proc.fermentation_temp, proc.fermentation_time_hour,
                )
    return {"recipe_id": recipe_id, "message": "레시피 등록 완료 (승인 대기)"}


# =====================================================================
# 9. 레시피 수정 (버전 관리: 구버전 비활성화 + 신버전 생성)
# =====================================================================
@router.put("/recipes/{recipe_id}", status_code=201)
async def update_recipe(
    recipe_id: int,
    data: RecipeCreate,
    _role=Depends(require_role("ADMIN", "MANAGER")),
):
    """레시피 수정. 기존 버전을 비활성화하고 신규 버전을 생성한다(버전 관리 정책)."""
    async with get_db() as conn:
        old = await conn.fetchrow(
            "SELECT recipe_code, product_code FROM process_recipe WHERE recipe_id = $1",
            recipe_id,
        )
        if not old:
            raise HTTPException(status_code=404, detail=f"레시피 {recipe_id} 없음")

        async with conn.transaction():
            # 구버전 비활성화
            await conn.execute(
                """UPDATE process_recipe
                   SET is_active = FALSE, valid_to = CURRENT_DATE
                   WHERE recipe_id = $1""",
                recipe_id,
            )
            # 신버전 생성
            new_id = await conn.fetchval(
                """
                INSERT INTO process_recipe
                    (recipe_code, product_code, recipe_name, version,
                     is_active, valid_from, approval_status, created_by, notes)
                VALUES ($1,$2,$3,$4, TRUE, CURRENT_DATE, 'DRAFT', $5, $6)
                RETURNING recipe_id
                """,
                data.recipe_code, data.product_code, data.recipe_name, data.version,
                data.created_by, data.notes,
            )
            for idx, ing in enumerate(data.ingredients, start=1):
                await conn.execute(
                    """INSERT INTO recipe_ingredient
                        (recipe_id, material_code, material_name, standard_ratio,
                         min_ratio, max_ratio, unit, sort_order)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                    new_id, ing.material_code, ing.material_name, ing.standard_ratio,
                    ing.min_ratio, ing.max_ratio, ing.unit, idx,
                )
            for proc in data.processes:
                await conn.execute(
                    """INSERT INTO recipe_process
                        (recipe_id, process_code, pickling_salt_rate,
                         pickling_temp_min, pickling_temp_max, pickling_time_hour,
                         fermentation_temp, fermentation_time_hour)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                    new_id, proc.process_code.value, proc.pickling_salt_rate,
                    proc.pickling_temp_min, proc.pickling_temp_max, proc.pickling_time_hour,
                    proc.fermentation_temp, proc.fermentation_time_hour,
                )
    return {
        "old_recipe_id": recipe_id,
        "new_recipe_id": new_id,
        "message": "신규 버전 생성 완료, 구버전 비활성화됨",
    }


# =====================================================================
# 10. 공정 데이터 분석 집계
# =====================================================================
@router.get("/analysis")
async def get_process_analysis(
    start_date: date = Query(..., alias="from"),
    end_date: date = Query(..., alias="to"),
    process_code: ProcessCode | None = None,
):
    """기간별 공정 분석: 공정별 생산량 / 불량률 / 평균 소요시간."""
    clauses = ["start_time >= $1", "start_time < ($2::date + 1)"]
    params: list[Any] = [start_date, end_date]
    if process_code:
        params.append(process_code.value)
        clauses.append(f"process_code = ${len(params)}")
    where = "WHERE " + " AND ".join(clauses)

    async with get_db() as conn:
        by_process = await conn.fetch(
            f"""
            SELECT process_code,
                   COUNT(*)                                   AS lot_count,
                   COALESCE(SUM(output_qty_kg), 0)            AS total_output_kg,
                   COALESCE(SUM(defect_qty_kg), 0)            AS total_defect_kg,
                   ROUND(AVG(yield_rate), 2)                  AS avg_yield_rate,
                   ROUND(100.0 * SUM(defect_qty_kg)
                         / NULLIF(SUM(input_qty_kg), 0), 2)   AS defect_rate_pct,
                   ROUND(AVG(EXTRACT(EPOCH FROM (end_time - start_time)) / 60.0), 1)
                                                              AS avg_minutes
            FROM process_result
            {where}
            GROUP BY process_code
            ORDER BY process_code
            """,
            *params,
        )
        daily = await conn.fetch(
            f"""
            SELECT DATE(start_time) AS work_date,
                   COALESCE(SUM(output_qty_kg), 0)          AS output_kg,
                   ROUND(100.0 * SUM(defect_qty_kg)
                         / NULLIF(SUM(input_qty_kg), 0), 2)  AS defect_rate_pct
            FROM process_result
            {where}
            GROUP BY DATE(start_time)
            ORDER BY work_date
            """,
            *params,
        )

    by_process_list = []
    for r in by_process:
        d = dict(r)
        d["process_name"] = PROCESS_NAME.get(d["process_code"])
        by_process_list.append(d)

    return {
        "from": str(start_date),
        "to": str(end_date),
        "by_process": by_process_list,
        "daily_trend": [dict(r) for r in daily],
    }
