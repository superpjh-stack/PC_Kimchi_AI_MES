"""
꽃순이김치 제조AI MES — 공정관리 화면 (pages/05_process.py)
프로젝트: SF26179540 / 로뎀솔루션

streamlit-dashboard 스킬 원칙:
  - 모든 API 호출은 try/except 로 감싸고 실패 시 st.warning()
  - 차트는 Plotly, use_container_width=True
  - 탭 구성: 공정실적 입력 / 실시간 모니터링 / 레시피 관리 / 공정이력 조회 / 공정데이터 분석

API: http://localhost:8000/api/v1/process  (api_process_router.py)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import time
from datetime import datetime, date, timedelta

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils.auth_helper import check_login, get_auth_headers
from components.nav import activate_tab
from components.styles import apply_styles, style_plotly, COLORWAY, COLORS
from components.sidebar import render_sidebar

st.set_page_config(page_title="공정관리 | 꽃순이김치 MES", page_icon="⚙️", layout="wide")
apply_styles()
render_sidebar(current="process")
check_login()

BASE_URL = "http://localhost:8000/api/v1/process"

# 공정 코드 정의
PROCESS_CODES = {
    "PROC01": "입고/보관", "PROC02": "절단/전처리", "PROC03": "세척/절임",
    "PROC04": "세척/선별", "PROC05": "탈수", "PROC06": "혼합",
    "PROC07": "숙성/발효", "PROC08": "금속검출", "PROC09": "포장/출하",
}
NAME_TO_CODE = {v: k for k, v in PROCESS_CODES.items()}


# ---------------------------------------------------------------------------
# API 헬퍼 — 모든 호출 try/except, 실패 시 st.warning + 기본값
# ---------------------------------------------------------------------------
def api_get(path: str, params: dict | None = None, default=None):
    try:
        r = httpx.get(f"{BASE_URL}{path}", params=params or {}, headers=get_auth_headers(), timeout=10.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        st.warning(f"API 조회 실패 ({path}): {e}")
        return default


def api_post(path: str, json: dict, params: dict | None = None):
    try:
        r = httpx.post(f"{BASE_URL}{path}", json=json, params=params or {}, headers=get_auth_headers(), timeout=10.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        # 422 등 HTTP 오류: 응답 본문의 detail 메시지 파싱하여 표시 (P-L3 수정)
        try:
            body = e.response.json()
            detail = body.get("detail", str(e))
            if isinstance(detail, list):
                # Pydantic v2 422 ValidationError: [{loc:[...], msg:...}, ...]
                msgs = "; ".join(
                    f"{'.'.join(str(x) for x in d.get('loc', []))}: {d.get('msg', '')}"
                    for d in detail
                )
                detail = f"입력값 검증 오류 — {msgs}"
        except Exception:
            detail = str(e)
        st.error(f"🚫 API 오류 ({path} · {e.response.status_code}): {detail}")
        return None
    except Exception as e:  # noqa: BLE001
        st.warning(f"API 등록 실패 ({path}): {e}")
        return None


def api_patch(path: str, json: dict):
    try:
        r = httpx.patch(f"{BASE_URL}{path}", json=json, headers=get_auth_headers(), timeout=10.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        st.warning(f"API 처리 실패 ({path}): {e}")
        return None


st.title("⚙️ 공정관리")

tabs = st.tabs(
    ["공정실적 입력", "실시간 모니터링", "레시피 관리", "공정이력 조회", "공정데이터 분석"]
)
activate_tab()

# ===========================================================================
# 탭 1: 공정실적 입력 — 공정코드별 동적 폼
# ===========================================================================
with tabs[0]:
    st.subheader("공정실적 입력")

    proc_name = st.selectbox("공정 선택", list(PROCESS_CODES.values()), index=2)
    proc_code = NAME_TO_CODE[proc_name]

    with st.form("process_result_form", clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            lot_id = st.text_input("산출 LOT ID", value=f"LOT-{date.today():%Y%m%d}-001")
            source_lot_id = st.text_input("직전 공정 LOT ID (선택)", value="")
            start_time = st.text_input("시작 일시", value=f"{datetime.now():%Y-%m-%dT%H:%M}")
        with c2:
            input_qty = st.number_input("투입 수량 (kg)", min_value=0.0, value=3200.0, step=10.0)
            output_qty = st.number_input("산출 수량 (kg)", min_value=0.0, value=2850.0, step=10.0)
            defect_qty = st.number_input("불량 수량 (kg)", min_value=0.0, value=0.0, step=1.0)
        worker = st.text_input("작업자", value="이미경")

        # --- 공정코드별 동적 입력 필드 ---
        details: dict = {}
        st.markdown(f"**[{proc_code}] {proc_name} 세부 입력**")
        if proc_code == "PROC01":  # 입고/보관
            d1, d2, d3 = st.columns(3)
            details["supplier_code"] = d1.text_input("공급업체 코드", "SUP01")
            details["material_code"] = d2.text_input("원재료 코드", "MAT-BC")
            details["origin"] = d3.text_input("원산지", "강원 평창")
            details["cabbage_size"] = d1.selectbox("배추 크기 등급", ["S", "M", "L", "XL"], 2)
            details["appearance_grade"] = d2.selectbox("외관 등급", ["A", "B", "C"])
            details["moisture_rate"] = d3.number_input("함수율 (%)", 0.0, 100.0, 92.0)
            details["qc_pass"] = d1.checkbox("품질 검사 합격", value=True)
        elif proc_code == "PROC02":  # 절단/전처리
            d1, d2 = st.columns(2)
            details["work_minutes"] = d1.number_input("작업 시간 (분)", 1, value=75)
            details["equipment"] = d2.text_input("설비 코드", "EQ-CUT-01")
            details["defect_reason"] = d1.text_input("불량 사유 코드 (선택)", "")
        elif proc_code == "PROC03":  # 세척/절임
            d1, d2, d3 = st.columns(3)
            details["salt_water_temp"] = d1.number_input("세척수 온도 (°C)", value=10.5)
            details["salt_temp"] = d2.number_input("절임 온도 (°C)", value=12.3)
            details["salt_density"] = d3.number_input("절임 염도 (%)", value=2.8)
            details["salt_ph"] = d1.number_input("절임 pH", value=5.8)
            details["salt_hours"] = d2.number_input("절임 시간 (h)", value=18.0)
            details["salt_input_kg"] = d3.number_input("소금 투입량 (kg)", value=320.0)
        elif proc_code == "PROC04":  # 세척/선별
            d1, d2 = st.columns(2)
            details["wash_count"] = d1.number_input("세척 횟수", 1, 10, 3)
            details["pass_qty_kg"] = d2.number_input("합격 수량 (kg)", value=2800.0)
            details["fail_qty_kg"] = d1.number_input("불합격 수량 (kg)", value=50.0)
            details["sel_standard_version"] = d2.text_input("선별 기준 버전", "v1.0")
        elif proc_code == "PROC05":  # 탈수
            d1, d2 = st.columns(2)
            details["weight_before_kg"] = d1.number_input("탈수 전 중량 (kg)", value=2800.0)
            details["weight_after_kg"] = d2.number_input("탈수 후 중량 (kg)", value=2300.0)
            details["dehy_minutes"] = d1.number_input("탈수 시간 (분)", 1, value=45)
            details["equipment"] = d2.text_input("탈수 설비 코드", "EQ-DEHY-01")
        elif proc_code == "PROC06":  # 혼합
            d1, d2, d3 = st.columns(3)
            details["recipe_code"] = d1.text_input("레시피 코드", "PRD-BC-500")
            details["mix_minutes"] = d2.number_input("혼합 시간 (분)", 1, value=60)
            details["cabbage_kg"] = d3.number_input("배추 투입량 (kg)", value=2100.0)
            details["pepper_kg"] = d1.number_input("고추가루 (kg)", value=143.0)
            details["garlic_kg"] = d2.number_input("마늘 (kg)", value=100.0)
        elif proc_code == "PROC07":  # 숙성/발효
            d1, d2, d3 = st.columns(3)
            details["ferment_room"] = d1.text_input("발효실 코드", "FERM-02")
            details["init_temp"] = d2.number_input("초기 발효 온도 (°C)", value=4.2)
            details["init_ph"] = d3.number_input("초기 pH", value=5.6)
            details["init_acidity"] = d1.number_input("초기 산도 (%)", value=0.45)
            details["init_salinity"] = d2.number_input("초기 염도 (%)", value=2.0)
            details["target_hours"] = d3.number_input("목표 숙성시간 (h)", value=72.0)
        elif proc_code == "PROC08":  # 금속검출
            d1, d2 = st.columns(2)
            details["inspect_qty_kg"] = d1.number_input("검사 수량 (kg)", value=2400.0)
            details["abnormal_count"] = d2.number_input("이상 감지 건수", 0, value=0)
            details["detector_code"] = d1.text_input("검출기 설비 코드", "EQ-METAL-01")
            details["calib_date"] = d2.text_input("최종 교정일", f"{date.today()}")
        elif proc_code == "PROC09":  # 포장/출하
            d1, d2, d3 = st.columns(3)
            details["product_code"] = d1.text_input("제품 코드", "KIM-BC-500")
            details["package_unit_g"] = d2.selectbox("포장 단위 (g)", [300, 500, 1000, 2000, 5000], 1)
            details["package_qty"] = d3.number_input("포장 수량 (개)", 1, value=4200)
            details["weight_pass_rate"] = d1.number_input("자동중량검사 합격률 (%)", 0.0, 100.0, 99.2)
            details["weight_defect_qty"] = d2.number_input("중량 불량 수량 (개)", 0, value=12)

        submitted = st.form_submit_button("💾 실적 저장", use_container_width=True)
        if submitted:
            payload = {
                "process_code": proc_code,
                "lot_id": lot_id,
                "source_lot_id": source_lot_id or None,
                "input_qty_kg": input_qty,
                "output_qty_kg": output_qty,
                "defect_qty_kg": defect_qty,
                "worker": worker,
                "start_time": start_time,
                "status": "COMPLETED",
                "details": details,
            }
            res = api_post("/results", json=payload)
            if res:
                st.success(f"✅ {proc_name} 실적 저장 완료 (수율 {res.get('yield_rate', '-')}%)")

    st.divider()
    st.markdown("**최근 공정 실적**")
    recent = api_get("/results", params={"limit": 10}, default=[])
    if recent:
        df = pd.DataFrame(recent)
        cols = [c for c in ["lot_id", "process_name", "start_time", "input_qty_kg",
                            "output_qty_kg", "yield_rate", "worker", "status"] if c in df.columns]
        st.dataframe(df[cols], use_container_width=True, hide_index=True)
    else:
        st.info("표시할 공정 실적이 없습니다.")

# ===========================================================================
# 탭 2: 실시간 모니터링 — 상태 카드 3열 + 알림 + 30초 자동 갱신
#   st.fragment(run_every=30) 사용 — Streamlit 1.37+ 필요
#   이전의 time.time() 기반 수동 폴링은 사용자 인터랙션 없이는 재실행되지 않으므로
#   st.fragment 방식으로 교체한다 (자동 갱신 보장).
# ===========================================================================
with tabs[1]:
    @st.fragment(run_every=30)
    def _render_realtime_monitor():
        """공정 현황 실시간 모니터링 — 30초마다 자동 갱신."""
        st.subheader("실시간 공정 현황")

        monitor = api_get("/monitor/realtime", default={})
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("운영 중 공정", monitor.get("active_process_count", 0))
        m2.metric("활성 알림", monitor.get("alarm_total", 0))
        m3.metric("위험(CRITICAL)", monitor.get("alarm_critical", 0))
        m4.metric("경고(WARNING)", monitor.get("alarm_warning", 0))

        st.markdown("#### 이상 알림")
        open_alarms = api_get("/alarms", params={"status": "OPEN"}, default=[])
        if open_alarms:
            for a in open_alarms:
                line = f"[{a['process_name']}] {a['message']} (LOT: {a.get('lot_id', '-')})"
                if a["alarm_level"] == "CRITICAL":
                    st.error(f"🔴 {line}")
                else:
                    st.warning(f"🟡 {line}")
        else:
            st.success("✅ 활성 알림 없음 — 모든 공정 정상")

        st.markdown("#### 공정별 상태")
        processes = monitor.get("processes", [])
        if processes:
            for i in range(0, len(processes), 3):
                cols = st.columns(3)
                for col, p in zip(cols, processes[i:i + 3]):
                    with col:
                        status = p.get("status", "-")
                        dot = {"COMPLETED": "🟢", "IN_PROGRESS": "🔵", "HOLD": "🟡"}.get(status, "⚪")
                        with st.container(border=True):
                            st.markdown(f"**{dot} {p.get('process_name', p.get('process_code'))}**")
                            st.caption(f"LOT: {p.get('lot_id', '-')}")
                            st.write(f"산출: {p.get('output_qty_kg', '-')} kg / 수율: {p.get('yield_rate', '-')}%")
                            d = p.get("details") or {}
                            if d:
                                metrics = " · ".join(f"{k}={v}" for k, v in list(d.items())[:3])
                                st.caption(metrics)
        else:
            st.info("공정 상태 데이터가 없습니다.")

        if st.button("🔄 수동 새로고침"):
            st.rerun()

    _render_realtime_monitor()

# ===========================================================================
# 탭 3: 레시피 관리 — 목록 테이블 + 원료 구성 expander + 신규 등록
# ===========================================================================
with tabs[2]:
    st.subheader("레시피 관리")

    filter_product = st.text_input("제품 코드 필터 (선택)", value="")
    params = {"product_code": filter_product} if filter_product else {}
    recipes = api_get("/recipes", params=params, default=[])

    if recipes:
        view = [{
            "레시피코드": r.get("recipe_code"), "제품코드": r.get("product_code"),
            "레시피명": r.get("recipe_name"), "버전": r.get("version"),
            "승인상태": r.get("approval_status"), "승인자": r.get("approved_by"),
        } for r in recipes]
        st.dataframe(pd.DataFrame(view), use_container_width=True, hide_index=True)

        for r in recipes:
            with st.expander(f"📋 {r.get('recipe_name')} ({r.get('version')}) — 원료 배합표"):
                ings = r.get("ingredients", [])
                if ings:
                    st.dataframe(pd.DataFrame(ings), use_container_width=True, hide_index=True)
                else:
                    st.caption("원료 구성 정보 없음")
    else:
        st.info("표시할 레시피가 없습니다.")

    st.divider()
    st.markdown("**신규 레시피 등록** (공장장/관리자)")
    with st.form("recipe_form"):
        c1, c2, c3 = st.columns(3)
        rc = c1.text_input("레시피 코드", "PRD-BC-500")
        pc = c2.text_input("제품 코드", "KIM-BC-500")
        rn = c3.text_input("레시피명", "배추김치 500g")
        c4, c5, c6 = st.columns(3)
        ver = c4.text_input("버전", "v1.0")
        created_by = c5.text_input("작성자", "prod01")
        role = c6.selectbox("권한", ["공장장", "관리자"])
        notes = st.text_area("비고", "")
        if st.form_submit_button("➕ 레시피 등록", use_container_width=True):
            payload = {
                "recipe_code": rc, "product_code": pc, "recipe_name": rn,
                "version": ver, "created_by": created_by, "notes": notes,
                "ingredients": [], "processes": [],
            }
            res = api_post("/recipes", json=payload, params={"role": role})
            if res:
                st.success(f"✅ 레시피 등록 완료 (ID: {res.get('recipe_id')})")

# ===========================================================================
# 탭 4: 공정이력 조회 — LOT 검색 + 단계별 progress + 공정 상세
# ===========================================================================
with tabs[3]:
    st.subheader("공정이력 조회")

    search_lot = st.text_input("LOT ID 검색", value="PICKLING-20260523-003")
    if st.button("🔍 조회", key="history_search"):
        st.session_state["history_lot"] = search_lot

    target_lot = st.session_state.get("history_lot", search_lot)
    if target_lot:
        hist = api_get(f"/results/{target_lot}/history", default=None)
        if hist and hist.get("timeline"):
            timeline = hist["timeline"]
            done_codes = {t["process_code"] for t in timeline if t.get("status") == "COMPLETED"}
            active_codes = {t["process_code"] for t in timeline if t.get("status") == "IN_PROGRESS"}

            # 단계별 진행 표시 (9개 공정 순서)
            st.markdown(f"**{target_lot} 공정 진행 단계** ({hist['step_count']}/9)")
            cols = st.columns(9)
            for col, (code, name) in zip(cols, PROCESS_CODES.items()):
                with col:
                    if code in done_codes:
                        st.markdown(f"✅<br><small>{name}</small>", unsafe_allow_html=True)
                    elif code in active_codes:
                        st.markdown(f"🔄<br><small>{name}</small>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"⏳<br><small>{name}</small>", unsafe_allow_html=True)
            st.progress(len(done_codes) / 9)

            st.markdown("**공정별 이력 상세**")
            df = pd.DataFrame(timeline)
            cols2 = [c for c in ["process_name", "lot_id", "source_lot_id", "start_time",
                                 "end_time", "input_qty_kg", "output_qty_kg", "yield_rate",
                                 "worker", "status"] if c in df.columns]
            st.dataframe(df[cols2], use_container_width=True, hide_index=True)
        else:
            st.info(f"LOT {target_lot} 의 공정 이력이 없습니다.")

# ===========================================================================
# 탭 5: 공정데이터 분석 — 기간 + Plotly 바차트/불량률 라인차트
# ===========================================================================
with tabs[4]:
    st.subheader("공정데이터 분석")

    c1, c2 = st.columns(2)
    from_date = c1.date_input("시작일", value=date.today() - timedelta(days=7))
    to_date = c2.date_input("종료일", value=date.today())

    analysis = api_get(
        "/analysis",
        params={"from": str(from_date), "to": str(to_date)},
        default=None,
    )

    if analysis:
        by_proc = analysis.get("by_process", [])
        daily = analysis.get("daily_trend", [])

        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("**공정별 생산량 (kg)**")
            if by_proc:
                fig = go.Figure(go.Bar(
                    x=[p.get("process_name", p["process_code"]) for p in by_proc],
                    y=[p.get("total_output_kg", 0) for p in by_proc],
                    marker_color=COLORS["accent"],
                ))
                st.plotly_chart(style_plotly(fig, height=340), use_container_width=True)
            else:
                st.info("생산량 데이터 없음")

        with col_b:
            st.markdown("**일별 불량률 트렌드 (%)**")
            if daily:
                fig2 = go.Figure(go.Scatter(
                    x=[d["work_date"] for d in daily],
                    y=[d.get("defect_rate_pct", 0) for d in daily],
                    mode="lines+markers", line=dict(color=COLORS["red"]),
                ))
                fig2.add_hline(y=1.0, line_dash="dash", line_color=COLORS["green"],
                               annotation_text="목표 1.0%")
                st.plotly_chart(style_plotly(fig2, height=340), use_container_width=True)
            else:
                st.info("불량률 데이터 없음")

        st.markdown("**공정별 성과 요약**")
        if by_proc:
            summary = [{
                "공정": p.get("process_name"), "LOT수": p.get("lot_count"),
                "생산량(kg)": p.get("total_output_kg"), "불량(kg)": p.get("total_defect_kg"),
                "평균수율(%)": p.get("avg_yield_rate"), "불량률(%)": p.get("defect_rate_pct"),
                "평균소요(분)": p.get("avg_minutes"),
            } for p in by_proc]
            st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True)
    else:
        st.info("분석 데이터가 없습니다.")
