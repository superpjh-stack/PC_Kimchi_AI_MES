"""
꽃순이김치 제조AI MES — 숙성발효관리 API 라우터
프로젝트: SF26179540 / 로뎀솔루션

prefix: /api/v1/fermentation
대상 테이블 (db_fermentation_schema.sql):
    fermentation_lot                 — 발효 LOT 마스터
    fermentation_quality_prediction  — ML 예측 결과 (XGBoost/RF/SVR/LSTM + SHAP)
    fermentation_anomaly_alert       — 이상발효 알림
    optimal_condition_recommendation — 최적 절임/발효 조건 추천
참조 테이블 (재정의 금지):
    process_result (process_code='PROC07'), fermentation_timeseries

설계 원칙 (fastapi-mes 스킬):
  1. 모든 조회 엔드포인트는 LOT ID 기반 필터링을 지원한다
  2. ML 예측 결과 적재(POST /predictions)는 AI Server → MES 프록시 경로
  3. 비동기(async/await + asyncpg) 기본
  4. Pydantic v2 모델로 요청/응답 스키마 정의
  5. ON CONFLICT / 상태 가드로 멱등성·정합성 보장

app/main.py 에서:  app.include_router(fermentation.router)
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

# 프로젝트 공통 DB 컨텍스트 (app/database.py)
from app.database import get_db
from app.auth import require_role

router = APIRouter(prefix="/api/v1/fermentation", tags=["숙성발효관리"])


# =====================================================================
# 공통 정의 — 센서 임계값 상수 (db_fermentation_schema.sql 주석과 동기화)
# =====================================================================
TEMP_WARNING = 20.0          # ℃ 주의 임계
TEMP_CRITICAL = 25.0         # ℃ 위험 임계
TEMP_LOW_WARNING = 8.0       # ℃ 저온 주의 임계
ACIDITY_MIN = 0.40           # % 정상 산도 하한
ACIDITY_MAX = 0.90           # % 정상 산도 상한
SALINITY_MIN = 1.8           # % 정상 염도 하한
SALINITY_MAX = 3.2           # % 정상 염도 상한
PH_MIN = 4.0                 # 정상 pH 하한
PH_MAX = 6.5                 # 정상 pH 상한

# AI 성능 목표 (CLAUDE.md §AI 모듈) — summary/분석 응답에 동봉
AI_TARGETS = {
    "quality_accuracy": 0.80,        # 발효 품질 예측 정확도 >= 80%
    "completion_mae_hours": 2.0,     # 발효 완료 시점 예측 MAE <= 2h
    "anomaly_accuracy": 0.85,        # 이상발효 탐지 정확도 >= 85%
    "risk_recall": 0.85,             # 품질 리스크 재현율 >= 85%
    "r2": 0.85,                      # R^2 >= 0.85
}

QUALITY_ICON = {"NORMAL": "🟢", "CAUTION": "🟡", "ABNORMAL": "🔴"}


class LotStatus(str, Enum):
    FERMENTING = "FERMENTING"
    COMPLETED = "COMPLETED"
    ABNORMAL = "ABNORMAL"
    CANCELLED = "CANCELLED"


class ModelType(str, Enum):
    XGBOOST = "XGBOOST"
    RANDOM_FOREST = "RANDOM_FOREST"
    SVR = "SVR"
    LSTM = "LSTM"


class QualityClass(str, Enum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    ABNORMAL = "ABNORMAL"


class AlertType(str, Enum):
    TEMP_HIGH = "TEMP_HIGH"
    TEMP_LOW = "TEMP_LOW"
    ACIDITY_DRIFT = "ACIDITY_DRIFT"
    SALINITY_OOB = "SALINITY_OOB"
    SENSOR_MISSING = "SENSOR_MISSING"


class Severity(str, Enum):
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


def _jsonb(value: Any) -> Any:
    """asyncpg 가 JSONB 를 str 로 반환하는 경우 dict 로 파싱."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


# =====================================================================
# Pydantic 모델
# =====================================================================
class FermentationLotCreate(BaseModel):
    lot_id: str = Field(..., max_length=30, description="형식 FE-YYYYMMDD-NNN")
    source_lot_id: str | None = Field(None, max_length=30)
    start_time: datetime
    planned_end_time: datetime | None = None
    fermentation_temp_target: float | None = Field(None, ge=-5, le=40)
    room_id: str | None = Field(None, max_length=20)
    input_qty_kg: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _validate(self) -> "FermentationLotCreate":
        if self.planned_end_time and self.planned_end_time < self.start_time:
            raise ValueError("계획 완료 시각은 시작 시각 이후여야 합니다")
        return self


class FermentationLotResponse(BaseModel):
    lot_id: str
    source_lot_id: str | None = None
    start_time: datetime
    planned_end_time: datetime | None = None
    actual_end_time: datetime | None = None
    fermentation_temp_target: float | None = None
    room_id: str | None = None
    lot_status: str
    input_qty_kg: float | None = None
    output_qty_kg: float | None = None
    created_at: datetime | None = None


class LotStatusUpdate(BaseModel):
    lot_status: LotStatus
    output_qty_kg: float | None = Field(None, ge=0)
    actual_end_time: datetime | None = None


class PredictionCreate(BaseModel):
    lot_id: str = Field(..., max_length=30)
    model_type: ModelType
    quality_class: QualityClass | None = None
    quality_score: float | None = Field(None, ge=0, le=1)
    predicted_acidity: float | None = None
    predicted_ripeness: float | None = None
    predicted_completion_time: datetime | None = None
    completion_mae_hours: float | None = Field(None, ge=0)
    r2_score: float | None = None
    shap_features: dict[str, float] | None = None
    model_version: str = "1.0.0"


class AnomalyAlertCreate(BaseModel):
    lot_id: str = Field(..., max_length=30)
    alert_type: AlertType
    severity: Severity
    sensor_value: float | None = None
    threshold_value: float | None = None
    message: str = Field(..., min_length=1)


class AnomalyResolve(BaseModel):
    resolved_by: str = Field(..., min_length=1, max_length=50)
    action_taken: str | None = None


class RecommendationCreate(BaseModel):
    source_lot_id: str | None = Field(None, max_length=30)
    rec_salt_density_pct: float | None = Field(None, ge=0, le=20)
    rec_salt_temp_c: float | None = None
    rec_salt_hours: float | None = Field(None, ge=0)
    rec_fermentation_temp_c: float | None = None
    confidence_score: float | None = Field(None, ge=0, le=1)
    basis_lot_count: int | None = Field(None, ge=0)
    predicted_quality: str | None = Field(None, pattern="^(NORMAL|GOOD|EXCELLENT)$")
    notes: str | None = None


# =====================================================================
# 1. 발효 LOT 목록
# =====================================================================
@router.get("/lots", response_model=list[FermentationLotResponse])
async def list_lots(
    lot_status: LotStatus | None = None,
    date_from: date | None = Query(None, alias="date_from"),
    limit: int = Query(50, le=500),
):
    """발효 LOT 목록 (lot_status / date_from 필터)."""
    clauses: list[str] = []
    params: list[Any] = []
    if lot_status:
        params.append(lot_status.value)
        clauses.append(f"lot_status = ${len(params)}")
    if date_from:
        params.append(date_from)
        clauses.append(f"start_time >= ${len(params)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT * FROM fermentation_lot
            {where}
            ORDER BY start_time DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return [dict(r) for r in rows]


# =====================================================================
# 2. 발효 LOT 상세 + 최신 센서값
# =====================================================================
@router.get("/lots/{lot_id}")
async def get_lot(lot_id: str):
    """LOT 상세 + fermentation_timeseries 최신 센서 1건."""
    async with get_db() as conn:
        lot = await conn.fetchrow(
            "SELECT * FROM fermentation_lot WHERE lot_id = $1", lot_id
        )
        if not lot:
            raise HTTPException(status_code=404, detail=f"발효 LOT {lot_id} 없음")
        sensor = await conn.fetchrow(
            """
            SELECT recorded_at, temperature, acidity, salinity, ph, dissolved_oxygen
            FROM fermentation_timeseries
            WHERE lot_id = $1
            ORDER BY recorded_at DESC
            LIMIT 1
            """,
            lot_id,
        )
    result = dict(lot)
    result["latest_sensor"] = dict(sensor) if sensor else None
    return result


# =====================================================================
# 3. 발효 LOT 등록
# =====================================================================
@router.post("/lots", response_model=FermentationLotResponse, status_code=201)
async def create_lot(data: FermentationLotCreate):
    """발효 LOT 등록. lot_id 중복 시 409."""
    async with get_db() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM fermentation_lot WHERE lot_id = $1", data.lot_id
        )
        if exists:
            raise HTTPException(status_code=409, detail=f"발효 LOT {data.lot_id} 이미 존재")
        row = await conn.fetchrow(
            """
            INSERT INTO fermentation_lot
                (lot_id, source_lot_id, start_time, planned_end_time,
                 fermentation_temp_target, room_id, lot_status, input_qty_kg)
            VALUES ($1,$2,$3,$4,$5,$6,'FERMENTING',$7)
            RETURNING *
            """,
            data.lot_id, data.source_lot_id, data.start_time, data.planned_end_time,
            data.fermentation_temp_target, data.room_id, data.input_qty_kg,
        )
    return dict(row)


# =====================================================================
# 4. 발효 LOT 상태 변경
# =====================================================================
@router.patch("/lots/{lot_id}/status", response_model=FermentationLotResponse)
async def update_lot_status(lot_id: str, data: LotStatusUpdate):
    """상태 변경 (FERMENTING→COMPLETED/ABNORMAL 등).
    COMPLETED 전이 시 actual_end_time 미지정이면 NOW() 로 설정."""
    actual_end = data.actual_end_time
    if data.lot_status in (LotStatus.COMPLETED, LotStatus.ABNORMAL) and actual_end is None:
        actual_end = datetime.now().astimezone()

    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            UPDATE fermentation_lot
            SET lot_status = $2,
                output_qty_kg = COALESCE($3, output_qty_kg),
                actual_end_time = CASE
                    WHEN $2 IN ('COMPLETED','ABNORMAL') THEN COALESCE($4, actual_end_time)
                    ELSE actual_end_time END
            WHERE lot_id = $1
            RETURNING *
            """,
            lot_id, data.lot_status.value, data.output_qty_kg, actual_end,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"발효 LOT {lot_id} 없음")
    return dict(row)


# =====================================================================
# 5. 실시간 발효 현황 (발효중 LOT + 최신 센서 + 최신 예측)
# =====================================================================
@router.get("/monitor/realtime")
async def get_realtime_monitor():
    """현재 발효중 LOT 실시간 현황 (현황판 / 모니터링 탭)."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT fl.lot_id, fl.source_lot_id, fl.room_id, fl.start_time,
                   fl.planned_end_time, fl.fermentation_temp_target, fl.input_qty_kg,
                   s.recorded_at, s.temperature, s.acidity, s.salinity, s.ph,
                   s.dissolved_oxygen,
                   p.quality_class, p.quality_score, p.predicted_completion_time
            FROM fermentation_lot fl
            LEFT JOIN LATERAL (
                SELECT * FROM fermentation_timeseries ts
                WHERE ts.lot_id = fl.lot_id
                ORDER BY ts.recorded_at DESC LIMIT 1
            ) s ON TRUE
            LEFT JOIN LATERAL (
                SELECT quality_class, quality_score, predicted_completion_time
                FROM fermentation_quality_prediction qp
                WHERE qp.lot_id = fl.lot_id AND qp.quality_class IS NOT NULL
                ORDER BY qp.predicted_at DESC LIMIT 1
            ) p ON TRUE
            WHERE fl.lot_status = 'FERMENTING'
            ORDER BY fl.start_time
            """
        )
    out = []
    now = datetime.now().astimezone()
    for r in rows:
        d = dict(r)
        st = d.get("start_time")
        d["elapsed_hours"] = round((now - st).total_seconds() / 3600, 1) if st else None
        temp = d.get("temperature")
        if temp is None:
            d["temp_level"] = "UNKNOWN"
        elif temp >= TEMP_CRITICAL or temp <= TEMP_LOW_WARNING:
            d["temp_level"] = "CRITICAL"
        elif temp >= TEMP_WARNING:
            d["temp_level"] = "WARNING"
        else:
            d["temp_level"] = "NORMAL"
        d["quality_icon"] = QUALITY_ICON.get(d.get("quality_class"), "⚪")
        out.append(d)
    return {
        "active_count": len(out),
        "thresholds": {
            "temp_warning": TEMP_WARNING,
            "temp_critical": TEMP_CRITICAL,
            "acidity_range": [ACIDITY_MIN, ACIDITY_MAX],
            "salinity_range": [SALINITY_MIN, SALINITY_MAX],
        },
        "lots": out,
    }


# =====================================================================
# 6. 발효 시계열 센서 데이터
# =====================================================================
@router.get("/timeseries/{lot_id}")
async def get_timeseries(lot_id: str, hours: int = Query(24, ge=1, le=720)):
    """발효 시계열 센서 데이터 (최근 N시간, 기본 24h)."""
    async with get_db() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM fermentation_lot WHERE lot_id = $1", lot_id
        )
        if not exists:
            raise HTTPException(status_code=404, detail=f"발효 LOT {lot_id} 없음")
        rows = await conn.fetch(
            """
            SELECT recorded_at, temperature, acidity, salinity, ph, dissolved_oxygen
            FROM fermentation_timeseries
            WHERE lot_id = $1
              AND recorded_at >= NOW() - ($2 || ' hours')::INTERVAL
            ORDER BY recorded_at
            """,
            lot_id, str(hours),
        )
    return {"lot_id": lot_id, "hours": hours, "count": len(rows),
            "series": [dict(r) for r in rows]}


# =====================================================================
# 7. 예측 결과 목록
# =====================================================================
@router.get("/predictions")
async def list_predictions(
    lot_id: str | None = None,
    model_type: ModelType | None = None,
    limit: int = Query(20, le=200),
):
    """예측 결과 목록 (lot_id / model_type 필터)."""
    clauses: list[str] = []
    params: list[Any] = []
    if lot_id:
        params.append(lot_id)
        clauses.append(f"lot_id = ${len(params)}")
    if model_type:
        params.append(model_type.value)
        clauses.append(f"model_type = ${len(params)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT * FROM fermentation_quality_prediction
            {where}
            ORDER BY predicted_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    out = []
    for r in rows:
        d = dict(r)
        d["shap_features"] = _jsonb(d.get("shap_features"))
        out.append(d)
    return out


# =====================================================================
# 8. 특정 LOT 최신 예측 (모델별 최신 1건씩)
# =====================================================================
@router.get("/predictions/{lot_id}/latest")
async def get_latest_predictions(lot_id: str):
    """특정 LOT 의 모델별 최신 예측 1건씩 (DISTINCT ON model_type)."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (model_type) *
            FROM fermentation_quality_prediction
            WHERE lot_id = $1
            ORDER BY model_type, predicted_at DESC
            """,
            lot_id,
        )
    if not rows:
        raise HTTPException(status_code=404, detail=f"LOT {lot_id} 예측 결과 없음")
    by_model: dict[str, Any] = {}
    for r in rows:
        d = dict(r)
        d["shap_features"] = _jsonb(d.get("shap_features"))
        by_model[d["model_type"]] = d
    return {"lot_id": lot_id, "models": by_model}


# =====================================================================
# 9. ML 예측 결과 저장 (AI Server → MES)
# =====================================================================
@router.post("/predictions", status_code=201)
async def create_prediction(data: PredictionCreate):
    """ML 예측 결과 적재. lot_id 가 fermentation_lot 에 존재해야 한다."""
    async with get_db() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM fermentation_lot WHERE lot_id = $1", data.lot_id
        )
        if not exists:
            raise HTTPException(status_code=404, detail=f"발효 LOT {data.lot_id} 없음")
        prediction_id = await conn.fetchval(
            """
            INSERT INTO fermentation_quality_prediction
                (lot_id, model_type, quality_class, quality_score,
                 predicted_acidity, predicted_ripeness, predicted_completion_time,
                 completion_mae_hours, r2_score, shap_features, model_version)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11)
            RETURNING prediction_id
            """,
            data.lot_id, data.model_type.value,
            data.quality_class.value if data.quality_class else None,
            data.quality_score, data.predicted_acidity, data.predicted_ripeness,
            data.predicted_completion_time, data.completion_mae_hours, data.r2_score,
            json.dumps(data.shap_features) if data.shap_features is not None else None,
            data.model_version,
        )
    return {"prediction_id": prediction_id, "message": "예측 결과 저장 완료"}


# =====================================================================
# 10. 이상발효 알림 목록
# =====================================================================
@router.get("/anomalies")
async def list_anomalies(
    lot_id: str | None = None,
    severity: Severity | None = None,
    is_resolved: bool | None = None,
    limit: int = Query(50, le=500),
):
    """이상발효 알림 목록 (lot_id / severity / is_resolved 필터). 미해소·심각도 우선 정렬."""
    clauses: list[str] = []
    params: list[Any] = []
    if lot_id:
        params.append(lot_id)
        clauses.append(f"lot_id = ${len(params)}")
    if severity:
        params.append(severity.value)
        clauses.append(f"severity = ${len(params)}")
    if is_resolved is not None:
        params.append(is_resolved)
        clauses.append(f"is_resolved = ${len(params)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT * FROM fermentation_anomaly_alert
            {where}
            ORDER BY (is_resolved = FALSE) DESC,
                     (severity = 'CRITICAL') DESC,
                     detected_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return [dict(r) for r in rows]


# =====================================================================
# 11. 이상발효 알림 등록
# =====================================================================
@router.post("/anomalies", status_code=201)
async def create_anomaly(data: AnomalyAlertCreate):
    """이상발효 알림 등록 (ETL/ML 탐지 결과 또는 수동 등록)."""
    async with get_db() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM fermentation_lot WHERE lot_id = $1", data.lot_id
        )
        if not exists:
            raise HTTPException(status_code=404, detail=f"발효 LOT {data.lot_id} 없음")
        alert_id = await conn.fetchval(
            """
            INSERT INTO fermentation_anomaly_alert
                (lot_id, alert_type, severity, sensor_value, threshold_value, message)
            VALUES ($1,$2,$3,$4,$5,$6)
            RETURNING alert_id
            """,
            data.lot_id, data.alert_type.value, data.severity.value,
            data.sensor_value, data.threshold_value, data.message,
        )
    return {"alert_id": alert_id, "message": "이상발효 알림 등록 완료"}


# =====================================================================
# 12. 이상 해소 처리
# =====================================================================
@router.patch("/anomalies/{alert_id}/resolve")
async def resolve_anomaly(alert_id: int, data: AnomalyResolve):
    """이상 해소 처리 (is_resolved=TRUE, resolved_at=NOW())."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            UPDATE fermentation_anomaly_alert
            SET is_resolved = TRUE,
                resolved_at = NOW(),
                resolved_by = $2,
                action_taken = $3
            WHERE alert_id = $1 AND is_resolved = FALSE
            RETURNING *
            """,
            alert_id, data.resolved_by, data.action_taken,
        )
    if not row:
        raise HTTPException(
            status_code=404, detail=f"알림 {alert_id} 없음 또는 이미 해소됨"
        )
    return dict(row)


# =====================================================================
# 13. SHAP 영향 요인 분석 (최신 예측의 shap_features)
# =====================================================================
@router.get("/analysis/shap/{lot_id}")
async def get_shap_analysis(lot_id: str):
    """SHAP 영향 요인 분석 — LOT 의 shap_features 보유 최신 예측에서 추출.
    상위 기여 요인을 내림차순 정렬하여 반환한다."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT prediction_id, model_type, predicted_at, quality_class, shap_features
            FROM fermentation_quality_prediction
            WHERE lot_id = $1 AND shap_features IS NOT NULL
            ORDER BY predicted_at DESC
            LIMIT 1
            """,
            lot_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"LOT {lot_id} SHAP 분석 결과 없음")
    features = _jsonb(row["shap_features"]) or {}
    ranked = sorted(features.items(), key=lambda kv: abs(kv[1]), reverse=True)
    return {
        "lot_id": lot_id,
        "model_type": row["model_type"],
        "predicted_at": row["predicted_at"],
        "quality_class": row["quality_class"],
        "factors": [
            {"feature": k, "contribution": v, "direction": "positive" if v >= 0 else "negative"}
            for k, v in ranked
        ],
    }


# =====================================================================
# 14. 공정조건 분석 (절임 조건 vs 발효 품질 상관, 최근 30일)
# =====================================================================
@router.get("/analysis/condition")
async def get_condition_analysis(days: int = Query(30, ge=1, le=365)):
    """공정조건 분석: 발효 LOT 의 절임 조건(PROC03 details)과 예측 품질을 결합.
    절임 LOT 의 염도/온도/시간을 process_result(PROC03)에서 가져와 발효 품질등급과 매핑한다."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT fl.lot_id,
                   fl.source_lot_id,
                   fl.fermentation_temp_target,
                   (pr.details->>'salt_density')::NUMERIC AS salt_density,
                   (pr.details->>'salt_temp')::NUMERIC    AS salt_temp,
                   (pr.details->>'salt_hours')::NUMERIC   AS salt_hours,
                   p.quality_class,
                   p.quality_score,
                   p.predicted_acidity,
                   p.predicted_ripeness
            FROM fermentation_lot fl
            LEFT JOIN process_result pr
                   ON pr.lot_id = fl.source_lot_id AND pr.process_code = 'PROC03'
            LEFT JOIN LATERAL (
                SELECT quality_class, quality_score, predicted_acidity, predicted_ripeness
                FROM fermentation_quality_prediction qp
                WHERE qp.lot_id = fl.lot_id
                ORDER BY (qp.quality_class IS NOT NULL) DESC, qp.predicted_at DESC
                LIMIT 1
            ) p ON TRUE
            WHERE fl.start_time >= NOW() - ($1 || ' days')::INTERVAL
            ORDER BY fl.start_time DESC
            """,
            str(days),
        )
    points = [dict(r) for r in points_to_list(rows)]
    # 품질등급별 평균 절임 조건 요약
    summary: dict[str, dict[str, Any]] = {}
    for p in points:
        cls = p.get("quality_class") or "UNKNOWN"
        bucket = summary.setdefault(cls, {"count": 0, "salt_density_sum": 0.0,
                                          "salt_temp_sum": 0.0, "salt_hours_sum": 0.0,
                                          "_d": 0, "_t": 0, "_h": 0})
        bucket["count"] += 1
        if p.get("salt_density") is not None:
            bucket["salt_density_sum"] += float(p["salt_density"]); bucket["_d"] += 1
        if p.get("salt_temp") is not None:
            bucket["salt_temp_sum"] += float(p["salt_temp"]); bucket["_t"] += 1
        if p.get("salt_hours") is not None:
            bucket["salt_hours_sum"] += float(p["salt_hours"]); bucket["_h"] += 1
    summary_out = {}
    for cls, b in summary.items():
        summary_out[cls] = {
            "count": b["count"],
            "avg_salt_density": round(b["salt_density_sum"] / b["_d"], 2) if b["_d"] else None,
            "avg_salt_temp": round(b["salt_temp_sum"] / b["_t"], 2) if b["_t"] else None,
            "avg_salt_hours": round(b["salt_hours_sum"] / b["_h"], 1) if b["_h"] else None,
        }
    return {"days": days, "point_count": len(points),
            "points": points, "by_quality": summary_out}


def points_to_list(rows):
    """fetch 결과를 list 로 정규화(가독성 헬퍼)."""
    return list(rows)


# =====================================================================
# 18. ML 모델 재학습 트리거 (공장장/관리자 전용, 비동기)
# =====================================================================

# 재학습 태스크 상태 저장소 (프로세스 메모리 — 운영 시 Redis 또는 DB 로 교체 권장)
_retrain_tasks: dict[str, dict[str, Any]] = {}


@router.post("/ml/retrain", status_code=202, summary="ML 모델 재학습 트리거")
async def trigger_ml_retrain(
    model_type: Literal["all", "xgboost", "rf", "svr", "lstm", "anomaly"] = "all",
    use_synthetic: bool = False,
    current_user=Depends(require_role("ADMIN", "MANAGER")),
):
    """
    ML 모델 재학습 트리거 (비동기, 공장장/관리자 전용).

    - 즉시 202 Accepted 를 반환한다.
    - 실제 학습은 AI Server 에서 백그라운드로 실행된다.
    - 학습 상태는 GET /fermentation/ml/retrain/status 로 확인한다.

    파라미터:
      model_type   — 재학습 대상 모델 (all/xgboost/rf/svr/lstm/anomaly)
      use_synthetic — 합성 데이터 포함 여부 (학습 데이터 부족 시 사용)
    """
    task_id = f"retrain-{model_type}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    _retrain_tasks[task_id] = {
        "task_id": task_id,
        "model_type": model_type,
        "use_synthetic": use_synthetic,
        "status": "ACCEPTED",
        "triggered_by": current_user.username,
        "triggered_at": datetime.now().isoformat(),
        "completed_at": None,
        "return_code": None,
        "error": None,
    }

    async def _run_train() -> None:
        _retrain_tasks[task_id]["status"] = "RUNNING"
        cmd = [sys.executable, "ml/train.py", "--model", model_type]
        if use_synthetic:
            cmd.append("--synthetic")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            _retrain_tasks[task_id]["return_code"] = proc.returncode
            _retrain_tasks[task_id]["status"] = "COMPLETED" if proc.returncode == 0 else "FAILED"
            if proc.returncode != 0:
                _retrain_tasks[task_id]["error"] = stderr.decode(errors="replace")[:500]
        except Exception as exc:
            _retrain_tasks[task_id]["status"] = "FAILED"
            _retrain_tasks[task_id]["error"] = str(exc)
        _retrain_tasks[task_id]["completed_at"] = datetime.now().isoformat()

    asyncio.create_task(_run_train())

    return {
        "task_id": task_id,
        "model_type": model_type,
        "use_synthetic": use_synthetic,
        "status": "ACCEPTED",
        "message": "재학습이 백그라운드에서 시작되었습니다.",
        "status_url": f"/api/v1/fermentation/ml/retrain/status?task_id={task_id}",
    }


@router.get("/ml/retrain/status", summary="ML 재학습 상태 조회")
async def get_retrain_status(
    task_id: str | None = Query(None, description="task_id 미지정 시 전체 목록 반환"),
):
    """
    ML 재학습 태스크 상태 조회.

    - task_id 지정: 해당 태스크 단건 조회
    - task_id 미지정: 전체 태스크 목록 (최신순 최대 20건)
    """
    if task_id:
        info = _retrain_tasks.get(task_id)
        if not info:
            raise HTTPException(status_code=404, detail=f"재학습 태스크 {task_id} 없음")
        return info
    # 전체 목록 — 최신순 정렬 후 최대 20건
    all_tasks = sorted(
        _retrain_tasks.values(),
        key=lambda t: t.get("triggered_at", ""),
        reverse=True,
    )
    return {"count": len(all_tasks), "tasks": all_tasks[:20]}


# =====================================================================
# 15. 최신 최적 절임 조건 추천
# =====================================================================
@router.get("/recommendations/latest")
async def get_latest_recommendations(limit: int = Query(5, le=50)):
    """최신 최적 절임/발효 조건 추천 목록."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM optimal_condition_recommendation
            ORDER BY recommended_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


# =====================================================================
# 16. 추천 조건 저장
# =====================================================================
@router.post("/recommendations", status_code=201)
async def create_recommendation(data: RecommendationCreate):
    """최적 절임/발효 조건 추천 저장 (AI 분석 결과 적재)."""
    async with get_db() as conn:
        rec_id = await conn.fetchval(
            """
            INSERT INTO optimal_condition_recommendation
                (source_lot_id, rec_salt_density_pct, rec_salt_temp_c, rec_salt_hours,
                 rec_fermentation_temp_c, confidence_score, basis_lot_count,
                 predicted_quality, notes)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            RETURNING rec_id
            """,
            data.source_lot_id, data.rec_salt_density_pct, data.rec_salt_temp_c,
            data.rec_salt_hours, data.rec_fermentation_temp_c, data.confidence_score,
            data.basis_lot_count, data.predicted_quality, data.notes,
        )
    return {"rec_id": rec_id, "message": "최적 조건 추천 저장 완료"}


# =====================================================================
# 17. 오늘 발효 현황 요약
# =====================================================================
@router.get("/summary/today")
async def get_today_summary():
    """오늘 발효 현황 (발효중/완료/이상 LOT 수, 평균 품질점수, 미해소 알림)."""
    async with get_db() as conn:
        status_rows = await conn.fetch(
            """
            SELECT lot_status, COUNT(*) AS cnt
            FROM fermentation_lot
            GROUP BY lot_status
            """
        )
        avg_score = await conn.fetchval(
            """
            SELECT ROUND(AVG(quality_score), 4)
            FROM fermentation_quality_prediction
            WHERE quality_class IS NOT NULL
              AND predicted_at >= CURRENT_DATE
            """
        )
        open_alerts = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE severity='CRITICAL') AS critical,
                COUNT(*) FILTER (WHERE severity='WARNING')  AS warning
            FROM fermentation_anomaly_alert
            WHERE is_resolved = FALSE
            """
        )
        today_started = await conn.fetchval(
            "SELECT COUNT(*) FROM fermentation_lot WHERE start_time >= CURRENT_DATE"
        )
    counts = {r["lot_status"]: r["cnt"] for r in status_rows}
    return {
        "date": str(date.today()),
        "fermenting": counts.get("FERMENTING", 0),
        "completed": counts.get("COMPLETED", 0),
        "abnormal": counts.get("ABNORMAL", 0),
        "cancelled": counts.get("CANCELLED", 0),
        "today_started": today_started or 0,
        "avg_quality_score": float(avg_score) if avg_score is not None else None,
        "open_alert_critical": (open_alerts["critical"] if open_alerts else 0) or 0,
        "open_alert_warning": (open_alerts["warning"] if open_alerts else 0) or 0,
        "ai_targets": AI_TARGETS,
    }
