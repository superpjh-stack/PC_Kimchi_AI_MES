"""
꽃순이김치 제조AI MES — AI 대시보드 API 라우터
프로젝트: SF26179540 / 로뎀솔루션

prefix: /api/v1/dashboard
대상 모듈: AI 대시보드 (생산현황 / 품질현황 / 발효상태 / 출하현황 분석)

대상 객체 (db_dashboard_schema.sql):
    VIEW   v_production_daily       — 일별 공정별 생산량/불량률
    VIEW   v_fermentation_status    — 활성 발효 LOT별 현재 상태(최신 1행)
    VIEW   v_quality_trend_7d       — 7일 품질 추세(일별 불량률)
    VIEW   v_shipping_daily         — 일별 출하량/포장량
    TABLE  dashboard_alert_summary  — 대시보드 알림 요약(읽음 처리)
참조 테이블: process_result, fermentation_timeseries, process_alarm

KPI 목표 (CLAUDE.md):
    시간당 생산량 2,750 → 3,000 kg/h (+9.1%)
    완제품 불량률 1.5% → 1.0% (-26.8%)
    발효 품질 예측 정확도 ≥ 80%

설계 원칙 (fastapi-mes 스킬):
    1. 모든 조회 엔드포인트는 날짜/LOT/필터 기반 파라미터 지원
    2. 비동기(async/await + asyncpg) 기본
    3. Pydantic v2 모델로 응답 스키마 정의
    4. ML/RAG 결과는 별도 /api/v1/ai/* 로 분리 (본 라우터는 집계/현황만 담당)

app/main.py 에서:  app.include_router(dashboard.router)
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

# 프로젝트 공통 DB 컨텍스트 (app/database.py)
from app.database import get_db

router = APIRouter(prefix="/api/v1/dashboard", tags=["AI대시보드"])


# =====================================================================
# 공통 정의
# =====================================================================
# 발효 상태 코드 → 한글 라벨
FERMENT_STATUS_LABEL: dict[str, str] = {
    "NORMAL": "정상",
    "WARNING": "주의",
    "ABNORMAL": "이상",
}

# 공정 코드 → 한글 공정명 (생산/출하 현황 표시용)
PROCESS_NAME: dict[str, str] = {
    "PROC01": "입고/보관", "PROC02": "절단/전처리", "PROC03": "세척/절임",
    "PROC04": "세척/선별", "PROC05": "탈수", "PROC06": "혼합",
    "PROC07": "숙성/발효", "PROC08": "금속검출", "PROC09": "포장/출하",
}

# KPI 목표값 (대시보드 KPI 요약 비교 기준)
TARGET_PRODUCTION_KG_H = 3000.0   # 시간당 생산량 목표 (kg/h)
TARGET_DEFECT_RATE_PCT = 1.0      # 완제품 불량률 목표 (%)
TARGET_FERMENT_ACCURACY = 80.0    # 발효 품질 예측 정확도 목표 (%)
DAILY_WORKING_HOURS = 8.0         # 일 근무시간 (시간당 생산량 환산용)


def _f(value: Any, default: float = 0.0) -> float:
    """asyncpg Decimal/None 값을 안전하게 float 로 변환."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# =====================================================================
# Pydantic 응답 모델 (v2)
# =====================================================================
class TodaySummary(BaseModel):
    """오늘 핵심 지표 4종."""
    production_kg: float = Field(..., description="오늘 총 생산량(kg)")
    defect_rate_pct: float = Field(..., description="오늘 불량률(%)")
    active_fermentation_lots: int = Field(..., description="현재 발효중 LOT 수")
    shipping_kg: float = Field(..., description="오늘 출하량(kg)")
    report_date: date = Field(..., description="기준 일자")


class DailyProductionRow(BaseModel):
    work_date: date
    output_kg: float
    input_kg: float
    defect_kg: float
    defect_rate_pct: float | None = None


class QualityTrendRow(BaseModel):
    work_date: date
    output_kg: float
    defect_kg: float
    defect_rate_pct: float | None = None


class ActiveFermentationRow(BaseModel):
    lot_id: str
    recorded_at: datetime
    temperature: float | None = None
    acidity: float | None = None
    salinity: float | None = None
    ph: float | None = None
    dissolved_oxygen: float | None = None
    ferment_status: str
    ferment_status_label: str


class FermentationStatusDist(BaseModel):
    """발효 상태 분포 (정상/주의/이상 count)."""
    normal: int = 0
    warning: int = 0
    abnormal: int = 0
    total: int = 0


class ShippingDailyRow(BaseModel):
    work_date: date
    shipment_count: int
    packaging_kg: float
    shipping_kg: float


class AlertRow(BaseModel):
    alert_id: int
    alert_type: str
    severity: str
    message: str
    module: str | None = None
    is_read: bool
    created_at: datetime


class KpiSummary(BaseModel):
    """KPI 핵심 현황 (달성률 포함)."""
    production_achievement: float = Field(..., description="시간당 생산량 달성률(%)")
    hourly_production_kg: float = Field(..., description="추정 시간당 생산량(kg/h)")
    defect_rate: float = Field(..., description="완제품 불량률(%)")
    defect_rate_target: float = Field(..., description="불량률 목표(%)")
    fermentation_accuracy: float = Field(..., description="발효 품질 예측 정확도(%)")
    report_date: date


# =====================================================================
# 1. 오늘 핵심 지표 4종
# =====================================================================
@router.get("/summary/today", response_model=TodaySummary)
async def get_today_summary():
    """오늘 생산량/불량률/발효중 LOT수/출하량 핵심 지표 4개.

    - 생산량/불량률: process_result 의 오늘자 집계
    - 발효중 LOT 수: v_fermentation_status 의 행 수(활성 발효)
    - 출하량: PROC09 양품 합계(오늘자)
    """
    async with get_db() as conn:
        # 오늘 생산 집계 (전 공정 투입/산출/불량)
        prod = await conn.fetchrow(
            """
            -- 오늘자 생산량 및 불량률 집계
            SELECT
                COALESCE(SUM(output_qty_kg), 0)                  AS production_kg,
                ROUND(100.0 * COALESCE(SUM(defect_qty_kg), 0)
                      / NULLIF(SUM(input_qty_kg), 0), 2)         AS defect_rate_pct
            FROM process_result
            WHERE DATE(start_time) = CURRENT_DATE
            """
        )
        # 오늘 출하량 (PROC09 양품 = 산출 - 불량)
        ship = await conn.fetchrow(
            """
            -- 오늘자 출하량(양품 기준) 집계
            SELECT COALESCE(SUM(output_qty_kg - COALESCE(defect_qty_kg, 0)), 0) AS shipping_kg
            FROM process_result
            WHERE process_code = 'PROC09'
              AND DATE(start_time) = CURRENT_DATE
            """
        )
        # 현재 발효중 LOT 수 (v_fermentation_status 의 활성 LOT)
        active = await conn.fetchval(
            "SELECT COUNT(*) FROM v_fermentation_status"
        )

    return TodaySummary(
        production_kg=_f(prod["production_kg"]) if prod else 0.0,
        defect_rate_pct=_f(prod["defect_rate_pct"]) if prod else 0.0,
        active_fermentation_lots=int(active or 0),
        shipping_kg=_f(ship["shipping_kg"]) if ship else 0.0,
        report_date=date.today(),
    )


# =====================================================================
# 2. 일별 생산량 추세
# =====================================================================
@router.get("/production/daily", response_model=list[DailyProductionRow])
async def get_production_daily(
    days: int = Query(7, ge=7, le=30, description="조회 일수(7~30)"),
):
    """일별 생산량 추세 (전 공정 통합, 최근 N일).

    v_production_daily(공정별)를 일자 기준으로 재집계하여 반환한다.
    """
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            -- 최근 N일 일별 생산량/불량률 (공정 통합)
            SELECT
                work_date,
                SUM(output_kg)                                   AS output_kg,
                SUM(input_kg)                                    AS input_kg,
                SUM(defect_kg)                                   AS defect_kg,
                ROUND(100.0 * SUM(defect_kg)
                      / NULLIF(SUM(input_kg), 0), 2)             AS defect_rate_pct
            FROM v_production_daily
            WHERE work_date >= (CURRENT_DATE - ($1::int - 1))
            GROUP BY work_date
            ORDER BY work_date
            """,
            days,
        )
    return [
        DailyProductionRow(
            work_date=r["work_date"],
            output_kg=_f(r["output_kg"]),
            input_kg=_f(r["input_kg"]),
            defect_kg=_f(r["defect_kg"]),
            defect_rate_pct=_f(r["defect_rate_pct"]) if r["defect_rate_pct"] is not None else None,
        )
        for r in rows
    ]


# =====================================================================
# 3. 불량률 추세
# =====================================================================
@router.get("/quality/trend", response_model=list[QualityTrendRow])
async def get_quality_trend(
    days: int = Query(7, ge=7, le=30, description="조회 일수(7~30)"),
):
    """불량률 추세 (일별 통합 불량률, 최근 N일).

    days=7 인 경우 v_quality_trend_7d 뷰를 그대로 활용하고,
    그 외에는 process_result 를 직접 기간 집계한다.
    """
    async with get_db() as conn:
        if days == 7:
            rows = await conn.fetch(
                """
                -- 7일 품질 추세 전용 뷰 활용
                SELECT work_date, output_kg, defect_kg, defect_rate_pct
                FROM v_quality_trend_7d
                ORDER BY work_date
                """
            )
        else:
            rows = await conn.fetch(
                """
                -- N일(7 초과) 품질 추세 직접 집계
                SELECT
                    DATE(start_time)                                 AS work_date,
                    COALESCE(SUM(output_qty_kg), 0)                  AS output_kg,
                    COALESCE(SUM(defect_qty_kg), 0)                  AS defect_kg,
                    ROUND(100.0 * COALESCE(SUM(defect_qty_kg), 0)
                          / NULLIF(SUM(input_qty_kg), 0), 2)         AS defect_rate_pct
                FROM process_result
                WHERE start_time >= (CURRENT_DATE - ($1::int - 1))
                GROUP BY DATE(start_time)
                ORDER BY work_date
                """,
                days,
            )
    return [
        QualityTrendRow(
            work_date=r["work_date"],
            output_kg=_f(r["output_kg"]),
            defect_kg=_f(r["defect_kg"]),
            defect_rate_pct=_f(r["defect_rate_pct"]) if r["defect_rate_pct"] is not None else None,
        )
        for r in rows
    ]


# =====================================================================
# 4. 현재 발효중인 LOT 목록 + 최신 온도/산도/pH
# =====================================================================
@router.get("/fermentation/active", response_model=list[ActiveFermentationRow])
async def get_active_fermentations(
    lot_id: str | None = Query(None, description="특정 LOT 필터(부분 일치)"),
):
    """현재 발효중인 LOT 목록 + 최신 온도/산도/pH (v_fermentation_status).

    lot_id 파라미터가 주어지면 해당 LOT 로 필터링한다(LOT 기반 조회 원칙).
    """
    clauses: list[str] = []
    params: list[Any] = []
    if lot_id:
        params.append(f"%{lot_id}%")
        clauses.append(f"lot_id ILIKE ${len(params)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            -- 활성 발효 LOT별 최신 상태 (이상→주의→정상 순 정렬)
            SELECT lot_id, recorded_at, temperature, acidity, salinity,
                   ph, dissolved_oxygen, ferment_status
            FROM v_fermentation_status
            {where}
            ORDER BY
                CASE ferment_status
                    WHEN 'ABNORMAL' THEN 0
                    WHEN 'WARNING'  THEN 1
                    ELSE 2
                END,
                recorded_at DESC
            """,
            *params,
        )
    return [
        ActiveFermentationRow(
            lot_id=r["lot_id"],
            recorded_at=r["recorded_at"],
            temperature=_f(r["temperature"]) if r["temperature"] is not None else None,
            acidity=_f(r["acidity"]) if r["acidity"] is not None else None,
            salinity=_f(r["salinity"]) if r["salinity"] is not None else None,
            ph=_f(r["ph"]) if r["ph"] is not None else None,
            dissolved_oxygen=_f(r["dissolved_oxygen"]) if r["dissolved_oxygen"] is not None else None,
            ferment_status=r["ferment_status"],
            ferment_status_label=FERMENT_STATUS_LABEL.get(r["ferment_status"], r["ferment_status"]),
        )
        for r in rows
    ]


# =====================================================================
# 5. 발효 상태 분포 (정상/주의/이상 count)
# =====================================================================
@router.get("/fermentation/status", response_model=FermentationStatusDist)
async def get_fermentation_status_dist():
    """발효 상태 분포 — 정상/주의/이상 LOT 수 집계.

    품질 등급 분포 pie chart 데이터 원천.
    """
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            -- 발효 상태별 LOT 수 집계
            SELECT ferment_status, COUNT(*) AS cnt
            FROM v_fermentation_status
            GROUP BY ferment_status
            """
        )
    counts = {r["ferment_status"]: int(r["cnt"]) for r in rows}
    normal = counts.get("NORMAL", 0)
    warning = counts.get("WARNING", 0)
    abnormal = counts.get("ABNORMAL", 0)
    return FermentationStatusDist(
        normal=normal,
        warning=warning,
        abnormal=abnormal,
        total=normal + warning + abnormal,
    )


# =====================================================================
# 6. 일별 출하량
# =====================================================================
@router.get("/shipping/daily", response_model=list[ShippingDailyRow])
async def get_shipping_daily(
    days: int = Query(7, ge=7, le=30, description="조회 일수(7~30)"),
):
    """일별 출하량/포장량 (PROC09 기준, 최근 N일) — v_shipping_daily."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            -- 최근 N일 일별 출하/포장량
            SELECT work_date, shipment_count, packaging_kg, shipping_kg
            FROM v_shipping_daily
            WHERE work_date >= (CURRENT_DATE - ($1::int - 1))
            ORDER BY work_date
            """,
            days,
        )
    return [
        ShippingDailyRow(
            work_date=r["work_date"],
            shipment_count=int(r["shipment_count"] or 0),
            packaging_kg=_f(r["packaging_kg"]),
            shipping_kg=_f(r["shipping_kg"]),
        )
        for r in rows
    ]


# =====================================================================
# 7. 대시보드 알림 목록
# =====================================================================
@router.get("/alerts", response_model=list[AlertRow])
async def list_alerts(
    is_read: bool | None = Query(None, description="읽음 여부 필터(None=전체)"),
    alert_type: str | None = Query(None, description="알림 타입 필터"),
    limit: int = Query(20, ge=1, le=100, description="최대 건수"),
):
    """대시보드 알림 목록 (is_read 필터, 최신순).

    is_read 미지정 시 전체, False 지정 시 미읽음만 조회.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if is_read is not None:
        params.append(is_read)
        clauses.append(f"is_read = ${len(params)}")
    if alert_type:
        params.append(alert_type)
        clauses.append(f"alert_type = ${len(params)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            -- 대시보드 알림 목록 (위험→경고→정보, 최신순)
            SELECT alert_id, alert_type, severity, message, module, is_read, created_at
            FROM dashboard_alert_summary
            {where}
            ORDER BY
                CASE severity
                    WHEN 'CRITICAL' THEN 0
                    WHEN 'WARNING'  THEN 1
                    ELSE 2
                END,
                created_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return [AlertRow(**dict(r)) for r in rows]


# =====================================================================
# 8. 알림 읽음 처리
# =====================================================================
@router.put("/alerts/{alert_id}/read", response_model=AlertRow)
async def mark_alert_read(alert_id: int):
    """알림 읽음 처리 (is_read -> TRUE)."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            -- 알림 읽음 처리
            UPDATE dashboard_alert_summary
            SET is_read = TRUE
            WHERE alert_id = $1
            RETURNING alert_id, alert_type, severity, message, module, is_read, created_at
            """,
            alert_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"알림 {alert_id} 없음")
    return AlertRow(**dict(row))


# =====================================================================
# 9. KPI 핵심 현황
# =====================================================================
@router.get("/kpi/summary", response_model=KpiSummary)
async def get_kpi_summary():
    """KPI 핵심 현황 — 생산성 달성률 / 불량률 / 발효 예측 정확도.

    - production_achievement: (추정 시간당 생산량 / 목표 3,000) * 100
      · 추정 시간당 생산량 = 오늘 총 생산량 / 일 근무시간(8h)
    - defect_rate: 오늘 완제품 불량률(%)
    - fermentation_accuracy: 발효 상태가 '정상'인 LOT 비율(%)을 정확도 근사로 사용
      (실제 ML 정확도는 /api/v1/ai/* 에서 제공, 본 값은 대시보드 표시용 근사)
    """
    async with get_db() as conn:
        prod = await conn.fetchrow(
            """
            -- 오늘 생산량 및 불량률
            SELECT
                COALESCE(SUM(output_qty_kg), 0)                  AS production_kg,
                ROUND(100.0 * COALESCE(SUM(defect_qty_kg), 0)
                      / NULLIF(SUM(input_qty_kg), 0), 2)         AS defect_rate_pct
            FROM process_result
            WHERE DATE(start_time) = CURRENT_DATE
            """
        )
        ferment = await conn.fetchrow(
            """
            -- 발효 정상 비율(정확도 근사)
            SELECT
                COUNT(*) FILTER (WHERE ferment_status = 'NORMAL')   AS normal_cnt,
                COUNT(*)                                            AS total_cnt
            FROM v_fermentation_status
            """
        )

    production_kg = _f(prod["production_kg"]) if prod else 0.0
    defect_rate = _f(prod["defect_rate_pct"]) if prod else 0.0
    hourly_kg = round(production_kg / DAILY_WORKING_HOURS, 1) if DAILY_WORKING_HOURS else 0.0
    achievement = round(hourly_kg / TARGET_PRODUCTION_KG_H * 100, 1) if TARGET_PRODUCTION_KG_H else 0.0

    total = int(ferment["total_cnt"]) if ferment else 0
    normal = int(ferment["normal_cnt"]) if ferment else 0
    accuracy = round(normal / total * 100, 1) if total else 0.0

    return KpiSummary(
        production_achievement=achievement,
        hourly_production_kg=hourly_kg,
        defect_rate=defect_rate,
        defect_rate_target=TARGET_DEFECT_RATE_PCT,
        fermentation_accuracy=accuracy,
        report_date=date.today(),
    )
