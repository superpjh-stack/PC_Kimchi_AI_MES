"""
꽃순이김치 제조AI MES — 데이터관리 화면 (Streamlit)
Project: SF26179540 / 로뎀솔루션 주식회사 / 2026

참조: docs/02-design/mockups/05-data-management.html, api_data_router.py
탭: 파이프라인 모니터링 / 데이터 조회 / 데이터 시각화 / 데이터 다운로드 / AI 학습 데이터

개발 원칙 (streamlit-dashboard 스킬):
  - 모든 API 호출은 try/except, 실패 시 st.warning + 데모 데이터 폴백
  - 차트는 Plotly, use_container_width=True
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import io
import json
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:  # 데모 환경 폴백
    _HAS_HTTPX = False

from utils.auth_helper import check_login, get_auth_headers
from components.nav import activate_tab
from components.styles import apply_styles, style_plotly, COLORWAY, COLORS
from components.sidebar import render_sidebar

API_BASE = "http://localhost:8000/api/v1/data"

st.set_page_config(page_title="데이터관리 — 꽃순이김치 MES", layout="wide")
apply_styles()
render_sidebar(current="data")
check_login()

# 조회/다운로드 가능 테이블 (api ALLOWED_TABLES와 일치)
TABLE_OPTIONS = {
    "공정 실적 (raw_material_intake)": "raw_material_intake",
    "절임 공정 (salting_process)": "salting_process",
    "발효 공정 (fermentation_process)": "fermentation_process",
    "센서 시계열 (fermentation_timeseries)": "fermentation_timeseries",
    "포장/출하 (shipping)": "shipping",
    "품질 검사 (quality_inspection)": "quality_inspection",
    "ETL 로그 (etl_log)": "etl_log",
}
STAGE_LABELS = {
    "EDGE": "Edge Collector", "MQTT": "MQTT", "KAFKA": "Kafka",
    "DATALAKE": "Data Lake", "ETL": "ETL 처리", "POSTGRESQL": "PostgreSQL\n+pgvector",
}
STATUS_ICON = {"OK": "🟢", "WARNING": "🟡", "ERROR": "🔴"}


# ============================================================================
# API 헬퍼 (실패 시 데모 데이터 반환)
# ============================================================================
def _get(path: str, params: dict | None = None):
    if not _HAS_HTTPX:
        return None
    try:
        r = httpx.get(f"{API_BASE}{path}", params=params or {}, headers=get_auth_headers(), timeout=15.0)
        r.raise_for_status()
        return r.json()
    except Exception as exc:  # noqa: BLE001
        st.session_state["_api_error"] = str(exc)
        return None


def _post(path: str, payload: dict):
    if not _HAS_HTTPX:
        return None
    try:
        r = httpx.post(f"{API_BASE}{path}", json=payload, headers=get_auth_headers(), timeout=15.0)
        r.raise_for_status()
        return r.json()
    except Exception as exc:  # noqa: BLE001
        st.warning(f"등록 실패: {exc}")
        return None


def _put(path: str, params: dict):
    if not _HAS_HTTPX:
        return None
    try:
        r = httpx.put(f"{API_BASE}{path}", params=params, headers=get_auth_headers(), timeout=15.0)
        r.raise_for_status()
        return r.json()
    except Exception as exc:  # noqa: BLE001
        st.warning(f"승인 실패: {exc}")
        return None


# --- 데모 데이터 (API 미연결 시) ---
DEMO_PIPELINE = [
    {"stage": "EDGE", "status": "OK", "message": "3/3 장치 연결됨", "records_per_sec": 3},
    {"stage": "MQTT", "status": "OK", "message": "스트리밍 정상", "records_per_sec": 42},
    {"stage": "KAFKA", "status": "OK", "message": "스트리밍 정상", "records_per_sec": 42},
    {"stage": "DATALAKE", "status": "OK", "message": "Raw Zone 저장중 (8s)", "records_per_sec": 40},
    {"stage": "ETL", "status": "OK", "message": "배치 실행중", "records_per_sec": 0},
    {"stage": "POSTGRESQL", "status": "OK", "message": "DB 응답 45ms", "records_per_sec": 0},
]
DEMO_DEVICES = [
    {"device_id": "GW-001", "device_name": "AI Data Gateway", "protocol": "OPC_UA",
     "is_connected": True, "last_heartbeat": "2026-05-24T14:35:22", "records_today": 28470},
    {"device_id": "PAD-001", "device_name": "SmartPad #1 (입고)", "protocol": "MQTT",
     "is_connected": True, "last_heartbeat": "2026-05-24T14:34:50", "records_today": 156},
    {"device_id": "PAD-002", "device_name": "SmartPad #2 (발효)", "protocol": "MQTT",
     "is_connected": True, "last_heartbeat": "2026-05-24T14:35:01", "records_today": 312},
    {"device_id": "PAD-003", "device_name": "SmartPad #3 (출하)", "protocol": "MQTT",
     "is_connected": True, "last_heartbeat": "2026-05-24T14:33:45", "records_today": 89},
]
DEMO_ETL = [
    {"job_name": "발효센서 ETL", "start_time": "2026-05-24T14:30:00", "status": "SUCCESS", "records_processed": 2847},
    {"job_name": "LOT 데이터 ETL", "start_time": "2026-05-24T14:00:00", "status": "SUCCESS", "records_processed": 156},
    {"job_name": "품질 데이터 ETL", "start_time": "2026-05-24T13:30:00", "status": "SUCCESS", "records_processed": 89},
    {"job_name": "공정실적 ETL", "start_time": "2026-05-24T13:00:00", "status": "SUCCESS", "records_processed": 42},
]
DEMO_DATASETS = [
    {"dataset_name": "발효품질학습셋_v3", "data_type": "FERMENTATION", "total_records": 2847,
     "labeled_count": 2847, "labeling_progress": 100.0, "is_finalized": True},
    {"dataset_name": "발효완료예측셋_v2", "data_type": "FERMENTATION", "total_records": 1523,
     "labeled_count": 1523, "labeling_progress": 100.0, "is_finalized": True},
    {"dataset_name": "이상발효탐지셋_v1", "data_type": "FERMENTATION", "total_records": 876,
     "labeled_count": 631, "labeling_progress": 72.0, "is_finalized": False},
    {"dataset_name": "절임조건최적화셋_v2", "data_type": "FERMENTATION", "total_records": 934,
     "labeled_count": 542, "labeling_progress": 58.0, "is_finalized": False},
]
DEMO_LABELS = [
    {"id": 1, "lot_id": "LOT-20260521-003", "data_type": "FERMENTATION", "label_value": "주의", "labeled_by": "박품질"},
    {"id": 2, "lot_id": "LOT-20260522-005", "data_type": "FERMENTATION", "label_value": "정상", "labeled_by": "박품질"},
    {"id": 3, "lot_id": "LOT-20260523-001", "data_type": "INTAKE", "label_value": "합격", "labeled_by": "박품질"},
]
DEMO_DQ = [
    {"rule_id": "DQ-001", "target_table": "fermentation_timeseries", "check_result": "WARNING", "issue_count": 3},
    {"rule_id": "DQ-002", "target_table": "fermentation_timeseries", "check_result": "PASS", "issue_count": 0},
    {"rule_id": "DQ-003", "target_table": "salting_process", "check_result": "PASS", "issue_count": 0},
    {"rule_id": "DQ-004", "target_table": "fermentation_timeseries", "check_result": "PASS", "issue_count": 0},
    {"rule_id": "DQ-005", "target_table": "fermentation_timeseries", "check_result": "WARNING", "issue_count": 5},
    {"rule_id": "DQ-006", "target_table": "shipping", "check_result": "PASS", "issue_count": 0},
    {"rule_id": "DQ-007", "target_table": "edge_device_status", "check_result": "PASS", "issue_count": 0},
]


# ============================================================================
st.title("데이터관리")
st.caption("데이터 통합 파이프라인 · 조회 · 시각화 · 다운로드 · AI 학습 데이터")

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["파이프라인 모니터링", "데이터 조회", "데이터 시각화", "데이터 다운로드", "AI 학습 데이터"]
)
activate_tab()


# ----------------------------------------------------------------------------
# 탭 1: 파이프라인 모니터링
# ----------------------------------------------------------------------------
with tab1:
    st.subheader("데이터 통합 파이프라인 현황")

    pipeline = _get("/pipeline/status") or DEMO_PIPELINE
    by_stage = {p["stage"]: p for p in pipeline}
    order = ["EDGE", "MQTT", "KAFKA", "DATALAKE", "ETL", "POSTGRESQL"]

    # 파이프라인 흐름 시각화: 6개 상태 카드 (화살표로 연결)
    cols = st.columns(11)  # 6 카드 + 5 화살표
    for i, stage in enumerate(order):
        p = by_stage.get(stage, {"status": "ERROR", "message": "-", "records_per_sec": 0})
        with cols[i * 2]:
            icon = STATUS_ICON.get(p["status"], "⚪")
            st.markdown(f"**{STAGE_LABELS[stage]}**")
            st.markdown(f"{icon} `{p['status']}`")
            st.caption(p.get("message") or "")
            rps = p.get("records_per_sec") or 0
            if rps:
                st.caption(f"{rps:g} rec/s")
        if i < len(order) - 1:
            with cols[i * 2 + 1]:
                st.markdown("<div style='text-align:center;font-size:24px;margin-top:18px'>➜</div>",
                            unsafe_allow_html=True)

    st.divider()
    left, right = st.columns(2)

    with left:
        st.markdown("**Edge Collector 연결 장치**")
        devices = _get("/pipeline/devices") or DEMO_DEVICES
        df_dev = pd.DataFrame(devices)
        if not df_dev.empty:
            df_dev["연결"] = df_dev["is_connected"].map(lambda x: "🟢 연결됨" if x else "🔴 끊김")
            show = df_dev[["device_id", "device_name", "protocol", "연결",
                           "last_heartbeat", "records_today"]]
            show.columns = ["장치ID", "장치명", "프로토콜", "상태", "마지막 수신", "금일 수집"]
            st.dataframe(show, use_container_width=True, hide_index=True)
        connected = sum(1 for d in devices if d.get("is_connected"))
        st.metric("Edge 연결", f"{connected} / {len(devices)}")

    with right:
        st.markdown("**ETL 작업 이력**")
        etl = _get("/pipeline/etl-logs", {"limit": 50}) or DEMO_ETL
        df_etl = pd.DataFrame(etl)
        if not df_etl.empty:
            keep = [c for c in ["job_name", "start_time", "records_processed", "status"]
                    if c in df_etl.columns]
            show = df_etl[keep].copy()
            show.columns = ["작업명", "실행시간", "처리건수", "상태"][:len(keep)]
            st.dataframe(show, use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------------
# 탭 2: 데이터 조회
# ----------------------------------------------------------------------------
with tab2:
    st.subheader("데이터 조회")
    mode = st.radio("조회 모드", ["정형 데이터", "LOT 통합 검색"], horizontal=True)

    if mode == "정형 데이터":
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        with c1:
            table_label = st.selectbox("테이블 선택", list(TABLE_OPTIONS.keys()))
        with c2:
            d_from = st.date_input("시작일", value=date(2026, 5, 1), key="q_from")
        with c3:
            d_to = st.date_input("종료일", value=date.today(), key="q_to")
        with c4:
            limit = st.number_input("표시 건수", 10, 1000, 20, step=10)

        if st.button("🔍 조회", type="primary"):
            table = TABLE_OPTIONS[table_label]
            res = _get("/query/structured", {"table_name": table, "limit": int(limit), "offset": 0})
            if res and res.get("rows"):
                st.caption(f"총 **{res['total']:,}건** 조회 (상위 {limit}건 표시)")
                st.dataframe(pd.DataFrame(res["rows"]), use_container_width=True, hide_index=True)
            else:
                st.info("API 미연결 또는 데이터 없음 — 데모 표시")
                st.dataframe(pd.DataFrame(DEMO_ETL), use_container_width=True, hide_index=True)

    else:  # LOT 통합 검색
        lot_id = st.text_input("LOT ID 입력", placeholder="LOT-20260523-003")
        if st.button("🔍 LOT 통합 조회", type="primary") and lot_id:
            res = _get(f"/query/lot-integrated/{lot_id}")
            if res and res.get("integrated"):
                integ = res["integrated"]
                st.success(f"LOT {lot_id} 통합 추적 결과")
                steps = [
                    ("입고", integ.get("intake_lot_id"), integ.get("intake_status")),
                    ("절임", integ.get("salting_lot_id"), f"염도 {integ.get('actual_salinity')}%"),
                    ("발효", integ.get("fermentation_lot_id"), integ.get("ml_quality_prediction")),
                    ("출하", integ.get("shipping_lot_id"), integ.get("ship_status")),
                ]
                scols = st.columns(4)
                for col, (name, lot, status) in zip(scols, steps):
                    with col:
                        st.markdown(f"**{name}**")
                        st.code(lot or "-")
                        st.caption(str(status or "-"))
                with st.expander("상세 데이터"):
                    st.json(integ)
            else:
                st.warning(f"LOT {lot_id} 추적 불가 (API 미연결 또는 미존재)")


# ----------------------------------------------------------------------------
# 탭 3: 데이터 시각화
# ----------------------------------------------------------------------------
with tab3:
    st.subheader("데이터 시각화")

    # 시각화용 데모/조회 데이터 (LOT 시계열)
    sample = pd.DataFrame({
        "날짜": pd.date_range("2026-05-17", periods=7),
        "발효실1": [4.2, 4.5, 4.1, 4.3, 4.8, 4.6, 4.2],
        "발효실2": [5.0, 5.8, 6.5, 7.2, 7.8, 8.5, 9.1],
        "발효실3": [4.8, 5.0, 4.9, 5.1, 5.0, 4.8, 3.8],
        "pH": [4.3, 4.2, 4.4, 4.1, 4.0, 4.2, 4.1],
    })

    c1, c2, c3 = st.columns(3)
    with c1:
        chart_type = st.selectbox("차트 유형", ["라인", "바", "산포도"])
    with c2:
        x_axis = st.selectbox("X축", ["날짜", "발효실1", "발효실2", "발효실3", "pH"])
    with c3:
        y_options = [c for c in sample.columns if c != x_axis]
        y_axis = st.selectbox("Y축", y_options)

    if chart_type == "라인":
        fig = px.line(sample, x=x_axis, y=y_axis, markers=True, title=f"{y_axis} 트렌드")
    elif chart_type == "바":
        fig = px.bar(sample, x=x_axis, y=y_axis, title=f"{y_axis} 분포")
    else:  # 산포도
        fig = px.scatter(sample, x=x_axis, y=y_axis, title=f"{x_axis} vs {y_axis}")

    st.plotly_chart(style_plotly(fig, height=420), use_container_width=True)

    # 통계 요약
    st.markdown("**통계 요약**")
    num_cols = sample.select_dtypes("number")
    st.dataframe(
        num_cols.agg(["mean", "min", "max", "std"]).round(2).T.rename(
            columns={"mean": "평균", "min": "최솟값", "max": "최댓값", "std": "표준편차"}),
        use_container_width=True,
    )


# ----------------------------------------------------------------------------
# 탭 4: 데이터 다운로드
# ----------------------------------------------------------------------------
with tab4:
    st.subheader("데이터 다운로드")

    c1, c2 = st.columns([1, 1])
    with c1:
        dl_label = st.selectbox("데이터 유형", list(TABLE_OPTIONS.keys()), key="dl_table")
        dc1, dc2 = st.columns(2)
        with dc1:
            dl_from = st.date_input("시작일", value=date(2026, 5, 1), key="dl_from")
        with dc2:
            dl_to = st.date_input("종료일", value=date.today(), key="dl_to")
        fmt = st.radio("파일 형식", ["excel", "csv", "json"], horizontal=True)

        table = TABLE_OPTIONS[dl_label]
        ext = {"excel": "xlsx", "csv": "csv", "json": "json"}[fmt]
        fname = f"kimchi_{table}_{dl_from}_{dl_to}.{ext}"
        st.info(f"생성될 파일명: `{fname}`")

    with c2:
        st.markdown("**다운로드**")
        st.caption("서버 `/download` 엔드포인트 경유 — 대용량(CSV 최대 100만건) 지원.")

        # D-L5 수정: 클라이언트 측 파일 생성 → 서버 /download 엔드포인트 직접 호출.
        # plan §5.4의 행수 제한(excel 10만/csv 100만/json 1만)을 서버에서 보장.
        dl_params = {"table": table, "format": fmt,
                     "date_from": str(dl_from), "date_to": str(dl_to)}
        mime_map = {
            "csv":   "text/csv",
            "json":  "application/json",
            "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        try:
            resp = httpx.get(f"{API_BASE}/download", params=dl_params, timeout=60.0)
            resp.raise_for_status()
            data = resp.content
            mime = resp.headers.get("content-type", mime_map.get(fmt, "application/octet-stream"))
            row_hint = ""
        except Exception as e:  # noqa: BLE001
            st.warning(f"서버 다운로드 실패 ({e}), 클라이언트 폴백 사용")
            # 폴백: /query/structured로 1,000건 제한 조회 후 클라이언트 변환
            res = _get("/query/structured", {"table_name": table, "limit": 1000, "offset": 0})
            df_dl = pd.DataFrame(res["rows"]) if res and res.get("rows") else pd.DataFrame(DEMO_ETL)
            data = ("﻿" + df_dl.to_csv(index=False)).encode("utf-8")
            mime = "text/csv"
            row_hint = f" (폴백 {len(df_dl):,}건)"

        st.download_button(
            f"⬇️ {fmt.upper()} 다운로드", data=data, file_name=fname, mime=mime,
            use_container_width=True,
        )
        if row_hint:
            st.caption(row_hint)


# ----------------------------------------------------------------------------
# 탭 5: AI 학습 데이터
# ----------------------------------------------------------------------------
with tab5:
    st.subheader("AI 학습 데이터 관리")

    dtype_filter = st.selectbox(
        "데이터 유형 필터", ["전체", "FERMENTATION", "INTAKE", "QUALITY"])
    params = {} if dtype_filter == "전체" else {"data_type": dtype_filter}
    datasets = _get("/ai/datasets", params) or DEMO_DATASETS

    # 데이터셋 현황 카드
    total_ds = len(datasets)
    finalized = sum(1 for d in datasets if d.get("is_finalized"))
    total_rec = sum(d.get("total_records", 0) for d in datasets)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("전체 데이터셋", f"{total_ds}개")
    m2.metric("확정 완료", f"{finalized}개")
    m3.metric("미확정", f"{total_ds - finalized}개")
    m4.metric("총 샘플 수", f"{total_rec:,}건")

    st.divider()

    # 데이터셋 목록 + 라벨링 진행률 progress bar
    st.markdown("**데이터셋 목록 (라벨링 진행률)**")
    for d in datasets:
        prog = d.get("labeling_progress", 0) / 100.0
        c1, c2 = st.columns([3, 5])
        with c1:
            badge = "✅ 확정" if d.get("is_finalized") else "⏳ 진행중"
            st.markdown(f"**{d['dataset_name']}** `{d['data_type']}` {badge}")
            st.caption(f"{d.get('labeled_count', 0):,} / {d.get('total_records', 0):,}건")
        with c2:
            st.progress(min(prog, 1.0), text=f"{d.get('labeling_progress', 0):.0f}%")

    st.divider()

    # 미승인 라벨 목록 + 승인 버튼
    st.markdown("**미승인 라벨 (승인 대기)**")
    labels = _get("/ai/labels", {"approved": False}) or DEMO_LABELS
    if not labels:
        st.success("승인 대기 중인 라벨이 없습니다.")
    else:
        reviewer = st.text_input("승인자(관리자)", value="최관리", key="reviewer")
        for lb in labels:
            c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
            c1.write(f"`{lb['lot_id']}`")
            c2.write(lb["data_type"])
            c3.write(f"라벨: **{lb['label_value']}**")
            if c4.button("승인", key=f"approve_{lb['id']}"):
                res = _put(f"/ai/labels/{lb['id']}/approve", {"reviewed_by": reviewer})
                if res:
                    st.success(f"라벨 {lb['id']} 승인 완료")
                    st.rerun()
                else:
                    st.info("API 미연결 — 승인 시뮬레이션")

    st.divider()

    # DQ 검증 결과 테이블 + 실행 버튼
    st.markdown("**데이터 품질(DQ) 검증 결과**")
    dq_col1, dq_col2 = st.columns([3, 1])
    with dq_col2:
        if st.button("🔄 DQ 검증 실행", type="primary"):
            res = _post("/quality/run", {})
            if res:
                st.success("DQ 검증을 백그라운드로 실행합니다 (7개 규칙)")
            else:
                st.info("API 미연결 — 데모 결과 표시")

    dq = _get("/quality/checks", {"limit": 50}) or DEMO_DQ
    df_dq = pd.DataFrame(dq)
    if not df_dq.empty:
        keep = [c for c in ["rule_id", "target_table", "check_result", "issue_count"]
                if c in df_dq.columns]
        show = df_dq[keep].copy()
        show.columns = ["규칙ID", "대상 테이블", "검증 결과", "이상 건수"][:len(keep)]

        def _style(val):
            return {"PASS": "color:#4C9B52", "WARNING": "color:#D97A2B",
                    "FAIL": "color:#C53D2E"}.get(val, "")

        st.dataframe(
            show.style.map(_style, subset=["검증 결과"]) if "검증 결과" in show.columns else show,
            use_container_width=True, hide_index=True,
        )
