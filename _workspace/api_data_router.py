"""
꽃순이김치 제조AI MES — 데이터관리 모듈 API 라우터
Project: SF26179540 / 로뎀솔루션 주식회사 / 2026

prefix: /api/v1/data
참조: pm3-process-data-kpi-system.plan.md §5, db_data_schema.sql

엔드포인트 (12개):
  파이프라인 모니터링
    GET  /pipeline/status                파이프라인 6단계 상태
    GET  /pipeline/devices               Edge Collector 장치 목록
    GET  /pipeline/etl-logs              ETL 작업 이력
  데이터 조회
    GET  /query/structured               정형 데이터 조회
    GET  /query/timeseries               센서 시계열 조회
    GET  /query/lot-integrated/{lot_id}  LOT 통합 데이터 조회
  데이터 다운로드
    GET  /download                       데이터 다운로드 (excel/csv/json)
  AI 학습 데이터
    GET  /ai/datasets                    AI 학습 데이터셋 목록
    POST /ai/labels                      라벨 등록
    PUT  /ai/labels/{label_id}/approve   라벨 승인
  데이터 품질
    GET  /quality/checks                 DQ 검증 결과 목록
    POST /quality/run                    DQ 검증 실행 (백그라운드 7개 규칙)

개발 원칙 (fastapi-mes 스킬):
  - async/await + asyncpg
  - Pydantic v2 모델
  - 조회는 LOT ID / 필터 기반
  - 멱등성 (ON CONFLICT)
"""
from __future__ import annotations

import io
import csv
import json
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.database import get_db  # asyncpg 풀 컨텍스트 매니저
from app.auth import require_role, CurrentUser  # JWT + RBAC

router = APIRouter(prefix="/api/v1/data", tags=["데이터관리"])

# 정형 데이터 조회 허용 테이블 (SQL 인젝션 방지를 위한 화이트리스트)
ALLOWED_TABLES = {
    "raw_material_intake",
    "salting_process",
    "fermentation_process",
    "fermentation_timeseries",
    "shipping",
    "quality_inspection",
    "production_kpi",
    "etl_log",
    "edge_device_status",
    "data_label",
    "data_quality_check",
}

PIPELINE_STAGES = ["EDGE", "MQTT", "KAFKA", "DATALAKE", "ETL", "POSTGRESQL"]

# DQ 검증 규칙 (plan §5.3)
DQ_RULES = [
    ("DQ-001", "fermentation_timeseries", "센서 값 범위 초과 (IQR)"),
    ("DQ-002", "fermentation_timeseries", "결측값 비율 > 5%"),
    ("DQ-003", "salting_process",         "LOT 연결 끊김 (FK 검증)"),
    ("DQ-004", "fermentation_timeseries", "시계열 시간 역전"),
    ("DQ-005", "fermentation_timeseries", "중복 레코드 (LOT+Timestamp)"),
    ("DQ-006", "shipping",                "공정 순서 이상"),
    ("DQ-007", "edge_device_status",      "센서 무신호 30분"),
]


# ============================================================================
# Pydantic 모델
# ============================================================================
class PipelineStageStatus(BaseModel):
    stage: str
    status: str
    last_updated: datetime | None = None
    message: str | None = None
    records_per_sec: float = 0


class EdgeDevice(BaseModel):
    device_id: str
    device_name: str
    protocol: str
    ip_address: str | None = None
    last_heartbeat: datetime | None = None
    is_connected: bool = False
    records_today: int = 0


class EtlLog(BaseModel):
    id: int
    job_name: str
    start_time: datetime
    end_time: datetime | None = None
    status: str
    records_processed: int = 0
    error_message: str | None = None


class AiDataset(BaseModel):
    id: int
    dataset_name: str
    data_type: str
    start_date: date | None = None
    end_date: date | None = None
    total_records: int = 0
    labeled_count: int = 0
    labeling_progress: float = 0  # 라벨링 진행률(%) — 응답 시 계산
    is_finalized: bool = False


class LabelCreate(BaseModel):
    lot_id: str = Field(..., max_length=50)
    data_type: Literal["FERMENTATION", "INTAKE", "QUALITY"]
    label_value: str = Field(..., max_length=50)
    labeled_by: str | None = None


class LabelResponse(BaseModel):
    id: int
    lot_id: str
    data_type: str
    label_value: str
    labeled_by: str | None = None
    reviewed_by: str | None = None
    is_approved: bool = False
    created_at: datetime
    approved_at: datetime | None = None


class DqCheckResult(BaseModel):
    id: int
    check_date: datetime
    rule_id: str
    target_table: str
    check_result: str
    issue_count: int = 0
    details: dict[str, Any] | None = None


# ============================================================================
# 1. 파이프라인 모니터링
# ============================================================================
@router.get("/pipeline/status", response_model=list[PipelineStageStatus])
async def get_pipeline_status():
    """파이프라인 6단계(EDGE→MQTT→KAFKA→DATALAKE→ETL→POSTGRESQL) 상태 반환."""
    async with get_db() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT ON (stage)
                   stage, status, last_updated, message, records_per_sec
            FROM pipeline_status
            ORDER BY stage, last_updated DESC
        """)
    by_stage = {r["stage"]: dict(r) for r in rows}
    # 6단계 모두 보장 (데이터 없으면 UNKNOWN)
    result: list[dict] = []
    for stage in PIPELINE_STAGES:
        if stage in by_stage:
            result.append(by_stage[stage])
        else:
            result.append({
                "stage": stage, "status": "ERROR",
                "last_updated": None, "message": "상태 데이터 없음",
                "records_per_sec": 0,
            })
    return result


@router.get("/pipeline/devices", response_model=list[EdgeDevice])
async def get_edge_devices():
    """Edge Collector / SmartPad 장치 연결 상태 목록."""
    async with get_db() as conn:
        rows = await conn.fetch("""
            SELECT device_id, device_name, protocol, ip_address,
                   last_heartbeat, is_connected, records_today
            FROM edge_device_status
            ORDER BY device_id
        """)
    return [dict(r) for r in rows]


@router.get("/pipeline/etl-logs", response_model=list[EtlLog])
async def get_etl_logs(
    limit: int = Query(50, ge=1, le=500),
    status: str | None = Query(None, description="SUCCESS/FAILED/RUNNING/WARNING"),
):
    """ETL 작업 이력 (최신순, status 필터 가능)."""
    async with get_db() as conn:
        if status:
            rows = await conn.fetch("""
                SELECT id, job_name, start_time, end_time, status,
                       records_processed, error_message
                FROM etl_log
                WHERE status = $1
                ORDER BY start_time DESC
                LIMIT $2
            """, status, limit)
        else:
            rows = await conn.fetch("""
                SELECT id, job_name, start_time, end_time, status,
                       records_processed, error_message
                FROM etl_log
                ORDER BY start_time DESC
                LIMIT $1
            """, limit)
    return [dict(r) for r in rows]


# ============================================================================
# 2. 데이터 조회
# ============================================================================
@router.get("/query/structured")
async def query_structured(
    table_name: str = Query(..., description="조회 대상 테이블 (화이트리스트)"),
    filters: str | None = Query(None, description='JSON 필터 예: {"status":"OK"}'),
    limit: int = Query(20, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """정형 데이터(PostgreSQL) 조회 — 테이블 화이트리스트 + 동적 필터 + 페이지네이션."""
    if table_name not in ALLOWED_TABLES:
        raise HTTPException(status_code=400, detail=f"허용되지 않은 테이블: {table_name}")

    where_clauses: list[str] = []
    params: list[Any] = []
    if filters:
        try:
            filter_dict = json.loads(filters)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="filters는 유효한 JSON이어야 합니다")
        for col, val in filter_dict.items():
            # 컬럼명은 식별자 검증 (영문/숫자/_ 만 허용)
            if not col.replace("_", "").isalnum():
                raise HTTPException(status_code=400, detail=f"잘못된 컬럼명: {col}")
            params.append(val)
            where_clauses.append(f"{col} = ${len(params)}")

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    params.append(limit)
    limit_idx = len(params)
    params.append(offset)
    offset_idx = len(params)

    # isalnum() 검증을 통과한 컬럼명도 해당 테이블에 없으면 SQL 오류(postgresError) 발생.
    # try/except로 캡처하여 500 대신 400으로 반환 — 사용자 친화적 오류 메시지.
    try:
        async with get_db() as conn:
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM {table_name}{where_sql}", *params[:len(where_clauses)]
            )
            rows = await conn.fetch(
                f"SELECT * FROM {table_name}{where_sql} "
                f"ORDER BY 1 DESC LIMIT ${limit_idx} OFFSET ${offset_idx}",
                *params,
            )
    except Exception as e:
        # PostgresError 등 SQL 오류 → 400 (잘못된 컬럼명·값 타입 불일치 등)
        detail = str(e).split("\n")[0]  # 첫 줄만 노출 (스택 없음)
        raise HTTPException(
            status_code=400,
            detail=f"쿼리 오류 — 컬럼명 또는 값을 확인하세요: {detail}",
        )
    return {
        "table": table_name,
        "total": total,
        "limit": limit,
        "offset": offset,
        "rows": [dict(r) for r in rows],
    }


@router.get("/query/timeseries")
async def query_timeseries(
    lot_id: str = Query(..., description="발효 LOT ID"),
    sensor_type: str = Query("temperature", description="temperature/acidity/salinity/ripeness_score"),
    start_dt: datetime = Query(...),
    end_dt: datetime = Query(...),
):
    """센서 시계열 데이터 조회 (LOT + 센서타입 + 기간)."""
    allowed_sensors = {"temperature", "acidity", "salinity", "ripeness_score",
                       "outdoor_temperature", "outdoor_humidity"}
    if sensor_type not in allowed_sensors:
        raise HTTPException(status_code=400, detail=f"허용되지 않은 센서: {sensor_type}")

    async with get_db() as conn:
        rows = await conn.fetch(f"""
            SELECT recorded_at, {sensor_type} AS value
            FROM fermentation_timeseries
            WHERE fermentation_lot_id = $1
              AND recorded_at BETWEEN $2 AND $3
            ORDER BY recorded_at
        """, lot_id, start_dt, end_dt)
    return {
        "lot_id": lot_id,
        "sensor_type": sensor_type,
        "points": [{"recorded_at": r["recorded_at"], "value": r["value"]} for r in rows],
    }


@router.get("/query/lot-integrated/{lot_id}")
async def query_lot_integrated(lot_id: str):
    """LOT 통합 데이터 조회 — 전 공정(입고→절임→발효→출하) 통합 뷰.

    입력 LOT ID는 어느 공정 LOT이든 가능. 입고 LOT 기준으로 정규화하여 체인 조회.
    """
    async with get_db() as conn:
        # 입력 LOT이 어느 공정의 LOT인지 역추적하여 intake_lot_id 확보
        intake_lot = await conn.fetchval("""
            SELECT rmi.intake_lot_id
            FROM raw_material_intake rmi
            LEFT JOIN salting_process sp        ON rmi.intake_lot_id = sp.intake_lot_id
            LEFT JOIN fermentation_process fp   ON sp.salting_lot_id = fp.salting_lot_id
            LEFT JOIN shipping s                ON fp.fermentation_lot_id = s.fermentation_lot_id
            WHERE rmi.intake_lot_id = $1
               OR sp.salting_lot_id = $1
               OR fp.fermentation_lot_id = $1
               OR s.shipping_lot_id = $1
            LIMIT 1
        """, lot_id)
        if not intake_lot:
            raise HTTPException(status_code=404, detail=f"LOT {lot_id} 추적 불가")

        row = await conn.fetchrow("""
            SELECT rmi.intake_lot_id, rmi.material_type, rmi.weight_kg, rmi.quality_status AS intake_status,
                   sp.salting_lot_id, sp.actual_salinity, sp.ph_value, sp.duration_hours,
                   fp.fermentation_lot_id, fp.ml_quality_prediction, fp.ml_quality_score,
                   fp.predicted_end_time, fp.status AS ferment_status,
                   s.shipping_lot_id, s.shipping_date, s.quality_status AS ship_status, s.defect_rate
            FROM raw_material_intake rmi
            LEFT JOIN salting_process sp      ON rmi.intake_lot_id = sp.intake_lot_id
            LEFT JOIN fermentation_process fp ON sp.salting_lot_id = fp.salting_lot_id
            LEFT JOIN shipping s              ON fp.fermentation_lot_id = s.fermentation_lot_id
            WHERE rmi.intake_lot_id = $1
        """, intake_lot)
    return {"queried_lot": lot_id, "integrated": dict(row) if row else None}


# ============================================================================
# 3. 데이터 다운로드
# ============================================================================
def _serialize(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


@router.get("/download")
async def download_data(
    format: Literal["excel", "csv", "json"] = Query("csv"),
    table: str = Query(..., description="다운로드 대상 테이블"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    """데이터 다운로드 (excel/csv/json). StreamingResponse 반환.

    날짜 컬럼이 있는 테이블은 created_at 기준 기간 필터를 적용한다.
    """
    if table not in ALLOWED_TABLES:
        raise HTTPException(status_code=400, detail=f"허용되지 않은 테이블: {table}")

    where, params = "", []
    if date_from and date_to:
        params = [date_from, date_to]
        where = " WHERE created_at::date BETWEEN $1 AND $2"

    # asyncpg 연결이 트랜잭션 컨텍스트에 있을 때 첫 쿼리 실패 시
    # 동일 연결의 재조회가 InFailedSQLTransactionError로 실패할 수 있음.
    # 별도 get_db() 컨텍스트로 새 연결을 획득하여 이 문제를 회피한다.
    try:
        async with get_db() as conn:
            rows = await conn.fetch(f"SELECT * FROM {table}{where}", *params)
    except Exception:
        if where:
            # created_at 컬럼이 없는 테이블: 날짜 필터 없이 새 연결로 재조회
            async with get_db() as conn:
                rows = await conn.fetch(f"SELECT * FROM {table}")
        else:
            raise HTTPException(status_code=500, detail="데이터 조회 중 오류가 발생했습니다")

    records = [{k: _serialize(v) for k, v in dict(r).items()} for r in rows]
    fname_base = f"kimchi_{table}_{date_from or 'all'}_{date_to or 'all'}"

    # JSON
    if format == "json":
        buf = io.BytesIO(json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8"))
        return StreamingResponse(
            buf, media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{fname_base}.json"'},
        )

    # CSV (UTF-8 BOM)
    if format == "csv":
        sio = io.StringIO()
        if records:
            writer = csv.DictWriter(sio, fieldnames=list(records[0].keys()))
            writer.writeheader()
            writer.writerows(records)
        data = ("﻿" + sio.getvalue()).encode("utf-8")
        return StreamingResponse(
            io.BytesIO(data), media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{fname_base}.csv"'},
        )

    # Excel (.xlsx) — openpyxl 사용
    try:
        from openpyxl import Workbook
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl 미설치 — Excel 다운로드 불가")
    wb = Workbook()
    ws = wb.active
    ws.title = table[:31]
    if records:
        headers = list(records[0].keys())
        ws.append(headers)
        for rec in records:
            ws.append([rec.get(h) for h in headers])
    xbuf = io.BytesIO()
    wb.save(xbuf)
    xbuf.seek(0)
    return StreamingResponse(
        xbuf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname_base}.xlsx"'},
    )


# ============================================================================
# 4. AI 학습 데이터
# ============================================================================
@router.get("/ai/datasets", response_model=list[AiDataset])
async def get_ai_datasets(
    data_type: str | None = Query(None, description="FERMENTATION/INTAKE/QUALITY"),
):
    """AI 학습 데이터셋 목록 (data_type 필터, 라벨링 진행률 계산)."""
    async with get_db() as conn:
        if data_type:
            rows = await conn.fetch("""
                SELECT id, dataset_name, data_type, start_date, end_date,
                       total_records, labeled_count, is_finalized
                FROM ai_dataset WHERE data_type = $1
                ORDER BY updated_at DESC
            """, data_type)
        else:
            rows = await conn.fetch("""
                SELECT id, dataset_name, data_type, start_date, end_date,
                       total_records, labeled_count, is_finalized
                FROM ai_dataset
                ORDER BY updated_at DESC
            """)
    result = []
    for r in rows:
        d = dict(r)
        total = d["total_records"] or 0
        d["labeling_progress"] = round(d["labeled_count"] / total * 100, 1) if total else 0.0
        result.append(d)
    return result


@router.get("/ai/labels", response_model=list[LabelResponse])
async def list_labels(
    data_type: str | None = Query(None, description="FERMENTATION/INTAKE/QUALITY"),
    is_approved: bool | None = Query(None, description="승인 여부 필터"),
    lot_id: str | None = Query(None, description="LOT ID 필터"),
    limit: int = Query(50, ge=1, le=500, description="최대 반환 건수"),
):
    """라벨 목록 조회 (data_type, is_approved, lot_id 필터)."""
    conds: list[str] = []
    params: list[Any] = []
    if data_type is not None:
        params.append(data_type)
        conds.append(f"data_type = ${len(params)}")
    if is_approved is not None:
        params.append(is_approved)
        conds.append(f"is_approved = ${len(params)}")
    if lot_id is not None:
        params.append(lot_id)
        conds.append(f"lot_id = ${len(params)}")
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    params.append(limit)
    async with get_db() as conn:
        rows = await conn.fetch(
            f"SELECT id, lot_id, data_type, label_value, labeled_by, "
            f"reviewed_by, is_approved, created_at, approved_at "
            f"FROM data_label {where} ORDER BY created_at DESC LIMIT ${len(params)}",
            *params,
        )
    return [dict(r) for r in rows]


@router.post("/ai/labels", response_model=LabelResponse, status_code=201)
async def create_label(
    data: LabelCreate,
    _: CurrentUser = Depends(require_role("QUALITY", "ADMIN", "MANAGER")),
):
    """라벨 등록 (미승인 상태로 저장)."""
    async with get_db() as conn:
        row = await conn.fetchrow("""
            INSERT INTO data_label (lot_id, data_type, label_value, labeled_by, is_approved)
            VALUES ($1, $2, $3, $4, FALSE)
            RETURNING id, lot_id, data_type, label_value, labeled_by,
                      reviewed_by, is_approved, created_at, approved_at
        """, data.lot_id, data.data_type, data.label_value, data.labeled_by)
    return dict(row)


@router.put("/ai/labels/{label_id}/approve", response_model=LabelResponse)
async def approve_label(
    label_id: int,
    reviewed_by: str = Query(..., description="승인자 (관리자)"),
    _: CurrentUser = Depends(require_role("QUALITY", "ADMIN")),
):
    """라벨 승인 — reviewed_by 기록, is_approved=TRUE, approved_at=NOW()."""
    async with get_db() as conn:
        row = await conn.fetchrow("""
            UPDATE data_label
               SET is_approved = TRUE, reviewed_by = $2, approved_at = NOW()
             WHERE id = $1
            RETURNING id, lot_id, data_type, label_value, labeled_by,
                      reviewed_by, is_approved, created_at, approved_at
        """, label_id, reviewed_by)
    if not row:
        raise HTTPException(status_code=404, detail=f"라벨 {label_id} 없음")
    return dict(row)


# ============================================================================
# 5. 데이터 품질 검증
# ============================================================================
@router.get("/quality/checks", response_model=list[DqCheckResult])
async def get_quality_checks(
    check_date: date | None = Query(None, description="검증 실행일 필터"),
    limit: int = Query(50, ge=1, le=500),
):
    """DQ 검증 결과 목록 (check_date 필터)."""
    async with get_db() as conn:
        if check_date:
            rows = await conn.fetch("""
                SELECT id, check_date, rule_id, target_table,
                       check_result, issue_count, details
                FROM data_quality_check
                WHERE check_date::date = $1
                ORDER BY check_date DESC, rule_id
                LIMIT $2
            """, check_date, limit)
        else:
            rows = await conn.fetch("""
                SELECT id, check_date, rule_id, target_table,
                       check_result, issue_count, details
                FROM data_quality_check
                ORDER BY check_date DESC, rule_id
                LIMIT $1
            """, limit)
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("details"), str):
            try:
                d["details"] = json.loads(d["details"])
            except (json.JSONDecodeError, TypeError):
                d["details"] = {}
        out.append(d)
    return out


async def _run_dq_rules() -> None:
    """7개 DQ 규칙(DQ-001~007)을 실행하고 결과를 data_quality_check에 적재.

    실제 검증 로직은 각 규칙별 SQL/통계 계산으로 확장. 여기서는 규칙 골격 + 결과 적재.
    """
    async with get_db() as conn:
        for rule_id, target_table, rule_name in DQ_RULES:
            result, issue_count = "PASS", 0

            try:
                if rule_id == "DQ-003":
                    # LOT 연결 끊김: 부모 LOT 없는 자식 레코드 수
                    issue_count = await conn.fetchval("""
                        SELECT COUNT(*) FROM salting_process sp
                        LEFT JOIN raw_material_intake rmi
                               ON sp.intake_lot_id = rmi.intake_lot_id
                        WHERE rmi.intake_lot_id IS NULL
                    """) or 0
                elif rule_id == "DQ-004":
                    # 시계열 시간 역전: 직전 레코드보다 과거 timestamp
                    issue_count = await conn.fetchval("""
                        SELECT COUNT(*) FROM (
                            SELECT recorded_at,
                                   LAG(recorded_at) OVER (
                                       PARTITION BY fermentation_lot_id
                                       ORDER BY id) AS prev_at
                            FROM fermentation_timeseries
                        ) t WHERE prev_at IS NOT NULL AND recorded_at < prev_at
                    """) or 0
                elif rule_id == "DQ-005":
                    # 중복 레코드: LOT+Timestamp 기준 중복
                    issue_count = await conn.fetchval("""
                        SELECT COALESCE(SUM(cnt - 1), 0) FROM (
                            SELECT COUNT(*) AS cnt
                            FROM fermentation_timeseries
                            GROUP BY fermentation_lot_id, recorded_at
                            HAVING COUNT(*) > 1
                        ) d
                    """) or 0
                elif rule_id == "DQ-007":
                    # 센서 무신호 30분: 마지막 수신이 30분 초과 장치 수
                    issue_count = await conn.fetchval("""
                        SELECT COUNT(*) FROM edge_device_status
                        WHERE is_connected = TRUE
                          AND last_heartbeat < NOW() - INTERVAL '30 minutes'
                    """) or 0
                elif rule_id == "DQ-001":
                    # 센서 값 범위 초과 (IQR): 최근 24시간 발효 센서 온도 IQR 이상치 탐지
                    issue_count = await conn.fetchval("""
                        WITH stats AS (
                            SELECT
                                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY temperature) AS q1,
                                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY temperature) AS q3
                            FROM fermentation_timeseries
                            WHERE recorded_at >= NOW() - INTERVAL '24 hours'
                              AND temperature IS NOT NULL
                        )
                        SELECT COUNT(*) FROM fermentation_timeseries ft, stats
                        WHERE ft.recorded_at >= NOW() - INTERVAL '24 hours'
                          AND ft.temperature IS NOT NULL
                          AND (ft.temperature < stats.q1 - 1.5 * (stats.q3 - stats.q1)
                               OR ft.temperature > stats.q3 + 1.5 * (stats.q3 - stats.q1))
                    """) or 0
                elif rule_id == "DQ-002":
                    # 결측값 비율 > 5%: 최근 24시간 핵심 센서(온도/산도/염도) NULL 비율 체크
                    null_pct = await conn.fetchval("""
                        SELECT CASE WHEN COUNT(*) = 0 THEN 0.0
                               ELSE ROUND(
                                   SUM(CASE WHEN temperature IS NULL
                                             OR acidity IS NULL
                                             OR salinity IS NULL THEN 1 ELSE 0 END)
                                   * 100.0 / COUNT(*), 2)
                               END
                        FROM fermentation_timeseries
                        WHERE recorded_at >= NOW() - INTERVAL '24 hours'
                    """) or 0.0
                    issue_count = int(null_pct) if null_pct > 5.0 else 0
                    rule_name = f"{rule_name} (결측률 {null_pct:.1f}%)"
                elif rule_id == "DQ-006":
                    # 공정 순서 이상: 후속 공정 시작이 선행 공정 종료보다 빠른 LOT 수
                    issue_count = await conn.fetchval("""
                        SELECT COUNT(DISTINCT pr1.lot_id)
                        FROM process_result pr1
                        JOIN process_result pr2
                            ON pr1.source_lot_id = pr2.lot_id
                        WHERE pr1.process_code > pr2.process_code
                          AND pr1.start_time < pr2.end_time
                          AND pr2.end_time IS NOT NULL
                          AND pr1.created_at >= NOW() - INTERVAL '7 days'
                    """) or 0
            except Exception as exc:  # noqa: BLE001
                result, issue_count = "FAIL", -1
                rule_name = f"{rule_name} (검증 오류: {exc})"

            if issue_count > 0:
                result = "WARNING" if rule_id != "DQ-007" else "FAIL"

            await conn.execute("""
                INSERT INTO data_quality_check
                    (rule_id, target_table, check_result, issue_count, details)
                VALUES ($1, $2, $3, $4, $5::jsonb)
            """, rule_id, target_table, result, max(issue_count, 0),
                json.dumps({"rule": rule_name}, ensure_ascii=False))


@router.post("/quality/run", status_code=202)
async def run_quality_check(
    background_tasks: BackgroundTasks,
    _: CurrentUser = Depends(require_role("ADMIN", "MANAGER")),
):
    """DQ 검증 실행 — 7개 규칙을 백그라운드 태스크로 실행."""
    background_tasks.add_task(_run_dq_rules)
    return {
        "status": "accepted",
        "message": "DQ 검증을 백그라운드로 실행합니다 (7개 규칙)",
        "rules": [r[0] for r in DQ_RULES],
    }
