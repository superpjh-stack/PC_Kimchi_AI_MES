# =============================================================================
# 꽃순이김치 제조AI MES — KPI관리 화면 (pages/07_kpi.py)
# Project: SF26179540  |  참조 목업: docs/02-design/mockups/08-kpi.html
# 참조 기획: docs/01-plan/features/pm3-process-data-kpi-system.plan.md (섹션 6)
#
# 탭: KPI 현황 / 생산성 분석 / 품질 분석 / KPI 설정 / 리포트
#   - 색상코딩: >=100% green, 90~99% yellow, 70~89% orange, <70% red
#   - 생산성 분석: 목표선(3,000 kg/h) + Prophet 30일 예측 오버레이
#   - 품질 분석: 불량률 트렌드(목표선 1.0%) + 공정별 불량 파이
# =============================================================================
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta

from utils.api_client import get_client
from utils.auth_helper import check_login
from components.nav import activate_tab
from components.styles import apply_styles, style_plotly, COLORWAY, COLORS
from components.sidebar import render_sidebar

st.set_page_config(page_title="KPI관리", layout="wide")
apply_styles()
render_sidebar(current="kpi")
check_login()
st.title("KPI관리")

# 색상코딩 매핑 (FastAPI get_achievement_color 와 일치)
COLOR_HEX = {"green": "#4C9B52", "yellow": "#7A8C3C", "orange": "#D97A2B", "red": "#C53D2E"}
TARGET_PRODUCTION = 3000.0
TARGET_DEFECT = 1.0


# -----------------------------------------------------------------------------
# 공통 헬퍼
# -----------------------------------------------------------------------------
def api_get(path: str, params: dict | None = None):
    try:
        r = get_client().get(path, params=params or {})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.warning(f"API 호출 실패 ({path}): {e}")
        return None


def api_put(path: str, payload: dict):
    try:
        r = get_client().put(path, json=payload)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"저장 실패 ({path}): {e}")
        return None


def api_post(path: str, payload: dict):
    try:
        r = get_client().post(path, json=payload)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"요청 실패 ({path}): {e}")
        return None


def gauge_figure(item: dict) -> go.Figure:
    """KPI 게이지 — 달성률 색상으로 바 색상 결정"""
    color = COLOR_HEX.get(item.get("color", "red"), "#C53D2E")
    actual = item.get("actual") or 0
    target = item.get("target") or 0
    # 게이지 축: 목표 대비 1.5배 범위 (불량률·MAE는 목표의 2배까지)
    axis_max = max(actual, target) * (2 if not item.get("higher_is_better", True) else 1.5)
    axis_max = axis_max or 1
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=actual,
        number={"suffix": f" {item.get('unit', '')}", "font": {"size": 22}},
        title={"text": f"{item['label']}<br><span style='font-size:11px;color:#888'>"
                       f"목표 {target} {item.get('unit', '')} · 달성 {item.get('achievement_rate', 0)}%</span>"},
        gauge={
            "axis": {"range": [0, axis_max]},
            "bar": {"color": color},
            "threshold": {"line": {"color": "#888", "width": 2}, "thickness": 0.75, "value": target},
        },
    ))
    style_plotly(fig, height=220, legend=False)
    fig.update_layout(margin=dict(l=20, r=20, t=60, b=10))
    return fig


# -----------------------------------------------------------------------------
# 탭 구성
# -----------------------------------------------------------------------------
tab_status, tab_prod, tab_qual, tab_config, tab_report = st.tabs(
    ["KPI 현황", "생산성 분석", "품질 분석", "KPI 설정", "리포트"]
)
activate_tab()

# =============================================================================
# 탭 1 — KPI 현황 (6개 KPI 카드 2행 3열 + 목표 대비 실적 테이블)
# =============================================================================
with tab_status:
    summary = api_get("/kpi/summary/today")
    if summary and summary.get("items"):
        items = summary["items"]
        c1, c2, c3 = st.columns(3)
        c4, c5, c6 = st.columns(3)
        slots = [c1, c2, c3, c4, c5, c6]
        for slot, item in zip(slots, items[:6]):
            with slot:
                st.plotly_chart(gauge_figure(item), use_container_width=True)

        st.divider()
        ach = summary.get("achieved_count", 0)
        tot = summary.get("total_count", len(items))
        m1, m2, m3 = st.columns(3)
        m1.metric("달성 항목", f"{ach} / {tot}")
        m2.metric("미달 항목", f"{tot - ach}")
        m3.metric("전체 KPI 달성률", f"{summary.get('overall_rate', 0)}%")

        st.subheader("목표 대비 실적")
        df = pd.DataFrame([{
            "KPI": i["label"],
            "실적": f"{i['actual']} {i['unit']}",
            "목표": f"{i['target']} {i['unit']}" if i["target"] is not None else "-",
            "기준값": f"{i['baseline']} {i['unit']}" if i.get("baseline") is not None else "-",
            "달성률": f"{i['achievement_rate']}%",
            "달성여부": "✅ 달성" if i["achieved"] else "⚠️ 미달",
        } for i in items])

        def _row_color(row):
            it = next(x for x in items if x["label"] == row["KPI"])
            bg = {"green": "#DFF0E0", "yellow": "#EDF2DD", "orange": "#FEF3C7", "red": "#FCE5E1"}.get(it["color"], "")
            return [f"background-color:{bg}"] * len(row)

        st.dataframe(df.style.apply(_row_color, axis=1), use_container_width=True, hide_index=True)
    else:
        st.info("오늘 KPI 집계 데이터가 없습니다.")

# =============================================================================
# 탭 2 — 생산성 분석 (트렌드 라인 + 목표선 3,000 + Prophet 30일 예측)
# =============================================================================
with tab_prod:
    cf1, cf2, cf3 = st.columns([1, 1, 2])
    period = cf1.selectbox("집계 단위", ["daily", "weekly", "monthly"],
                           format_func=lambda x: {"daily": "일별", "weekly": "주별", "monthly": "월별"}[x],
                           key="prod_period")
    count = cf2.number_input("표시 개수", min_value=7, max_value=365, value=30, step=1, key="prod_count")
    show_forecast = cf3.checkbox("Prophet 30일 예측 표시", value=True, key="prod_fc")

    trend = api_get("/kpi/production/trend", {"period": period, "count": int(count)})
    if trend and trend.get("data"):
        data = trend["data"]
        df = pd.DataFrame(data)
        df["period"] = pd.to_datetime(df["period"])
        target = trend.get("target", TARGET_PRODUCTION)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["period"], y=df["hourly_production_kg"],
            mode="lines+markers", name="시간당 생산량", line=dict(color=COLORS["accent"])))
        fig.add_hline(y=target, line_dash="dash", line_color=COLORS["orange"],
                      annotation_text=f"목표 {target:,.0f} kg/h")

        # Prophet 30일 예측 (일별 집계일 때만 의미 있음)
        if show_forecast and period == "daily" and len(df) >= 10:
            try:
                from prophet import Prophet
                pdf = df.rename(columns={"period": "ds", "hourly_production_kg": "y"})[["ds", "y"]].dropna()
                m = Prophet(yearly_seasonality=False, weekly_seasonality=True, daily_seasonality=False)
                m.fit(pdf)
                future = m.make_future_dataframe(periods=30)
                fc = m.predict(future)
                fc_future = fc[fc["ds"] > pdf["ds"].max()]
                fig.add_trace(go.Scatter(
                    x=fc_future["ds"], y=fc_future["yhat"],
                    mode="lines", name="Prophet 예측(30일)",
                    line=dict(color=COLORS["celadon"], dash="dot")))
                fig.add_trace(go.Scatter(
                    x=pd.concat([fc_future["ds"], fc_future["ds"][::-1]]),
                    y=pd.concat([fc_future["yhat_upper"], fc_future["yhat_lower"][::-1]]),
                    fill="toself", fillcolor="rgba(63,140,156,0.12)",
                    line=dict(color="rgba(0,0,0,0)"), name="예측 신뢰구간", showlegend=False))
            except ImportError:
                st.caption("Prophet 미설치 — 예측선을 생략합니다. (pip install prophet)")
            except Exception as e:
                st.caption(f"예측 생성 생략: {e}")

        style_plotly(fig, height=420)
        fig.update_layout(yaxis_title="kg/h", xaxis_title="기간",
                          legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("생산량 트렌드 데이터가 없습니다.")

# =============================================================================
# 탭 3 — 품질 분석 (불량률 트렌드 + 목표선 1.0% + 공정별 불량 파이)
# =============================================================================
with tab_qual:
    qf1, qf2 = st.columns(2)
    q_period = qf1.selectbox("집계 단위", ["daily", "weekly", "monthly"],
                             format_func=lambda x: {"daily": "일별", "weekly": "주별", "monthly": "월별"}[x],
                             key="qual_period")
    q_count = qf2.number_input("표시 개수", min_value=7, max_value=365, value=30, step=1, key="qual_count")

    col_l, col_r = st.columns(2)
    with col_l:
        st.subheader("불량률 트렌드")
        dtrend = api_get("/kpi/defect/trend", {"period": q_period, "count": int(q_count)})
        if dtrend and dtrend.get("data"):
            df = pd.DataFrame(dtrend["data"])
            df["period"] = pd.to_datetime(df["period"])
            target = dtrend.get("target", TARGET_DEFECT)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df["period"], y=df["defect_rate"],
                mode="lines+markers", name="불량률(%)",
                line=dict(color=COLORS["red"]), fill="tozeroy",
                fillcolor="rgba(197,61,46,0.1)"))
            fig.add_hline(y=target, line_dash="dash", line_color=COLORS["orange"],
                          annotation_text=f"목표 {target}%")
            style_plotly(fig, height=380)
            fig.update_layout(yaxis_title="%", xaxis_title="기간",
                              legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("불량률 트렌드 데이터가 없습니다.")

    with col_r:
        st.subheader("공정별 불량 현황")
        d_from = st.session_state.get("qual_from", date.today() - timedelta(days=30))
        d_to = st.session_state.get("qual_to", date.today())
        rng = st.date_input("기간", value=(d_from, d_to), key="qual_range")
        if isinstance(rng, tuple) and len(rng) == 2:
            d_from, d_to = rng
        by_proc = api_get("/kpi/defect/by-process",
                          {"date_from": str(d_from), "date_to": str(d_to)})
        if by_proc:
            pdf = pd.DataFrame(by_proc)
            agg = pdf.groupby("process", as_index=False)["defect_count"].sum()
            if not agg.empty and agg["defect_count"].sum() > 0:
                fig = go.Figure(go.Pie(
                    labels=agg["process"], values=agg["defect_count"], hole=0.45,
                    marker=dict(colors=COLORWAY)))
                style_plotly(fig, height=380)
                fig.update_layout(legend=dict(orientation="h", y=-0.1))
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(pdf, use_container_width=True, hide_index=True)
            else:
                st.info("해당 기간 불량 데이터가 없습니다.")
        else:
            st.info("공정별 불량 데이터가 없습니다.")

# =============================================================================
# 탭 4 — KPI 설정 (목표값 수정 + 알림 임계값, 관리자만)
# =============================================================================
with tab_config:
    role = st.session_state.get("role", "관리자")
    if role != "관리자":
        st.warning("KPI 설정은 관리자만 변경할 수 있습니다. (조회만 가능)")
    is_admin = role == "관리자"

    st.subheader("KPI 목표값")
    targets = api_get("/kpi/targets") or []
    if targets:
        st.dataframe(pd.DataFrame(targets)[
            [c for c in ["kpi_type", "label", "target_value", "unit", "baseline_value", "valid_from"]
             if c in (targets[0].keys())]
        ], use_container_width=True, hide_index=True)

        with st.form("target_form"):
            types = [t["kpi_type"] for t in targets]
            sel = st.selectbox("KPI 유형", types,
                               format_func=lambda x: next((t["label"] for t in targets if t["kpi_type"] == x), x))
            cur = next((t for t in targets if t["kpi_type"] == sel), {})
            new_target = st.number_input("목표값", value=float(cur.get("target_value") or 0), step=0.1, format="%.4f")
            new_base = st.number_input("기준값(baseline)", value=float(cur.get("baseline_value") or 0), step=0.1, format="%.4f")
            new_from = st.date_input("적용 시작일", value=date.today())
            submitted = st.form_submit_button("목표값 저장", disabled=not is_admin)
            if submitted and is_admin:
                res = api_put(f"/kpi/targets/{sel}", {
                    "target_value": new_target,
                    "baseline_value": new_base,
                    "valid_from": str(new_from),
                    "updated_by": st.session_state.get("user_id", "admin"),
                })
                if res:
                    st.success(f"{sel} 목표값이 {new_target}로 업데이트되었습니다.")
                    st.rerun()
    else:
        st.info("등록된 KPI 목표값이 없습니다.")

    st.divider()
    st.subheader("KPI 알림 임계값")
    configs = api_get("/kpi/alerts/config") or []
    if configs:
        st.dataframe(pd.DataFrame(configs)[
            [c for c in ["kpi_type", "label", "warning_threshold", "critical_threshold", "alert_channels", "is_active"]
             if c in configs[0].keys()]
        ], use_container_width=True, hide_index=True)

        with st.form("alert_form"):
            types = [c["kpi_type"] for c in configs]
            sel = st.selectbox("KPI 유형", types,
                               format_func=lambda x: next((c["label"] for c in configs if c["kpi_type"] == x), x),
                               key="alert_sel")
            cur = next((c for c in configs if c["kpi_type"] == sel), {})
            warn = st.number_input("경고 임계값", value=float(cur.get("warning_threshold") or 0), step=0.1, format="%.4f")
            crit = st.number_input("위험 임계값", value=float(cur.get("critical_threshold") or 0), step=0.1, format="%.4f")
            channels = st.multiselect("알림 채널", ["SMS", "EMAIL", "DISPLAY"],
                                      default=cur.get("alert_channels") or ["DISPLAY"])
            active = st.checkbox("활성화", value=bool(cur.get("is_active", True)))
            submitted = st.form_submit_button("임계값 저장", disabled=not is_admin)
            if submitted and is_admin:
                res = api_put(f"/kpi/alerts/config/{sel}", {
                    "warning_threshold": warn,
                    "critical_threshold": crit,
                    "alert_channels": channels,
                    "is_active": active,
                    "updated_by": st.session_state.get("user_id", "admin"),
                })
                if res:
                    st.success(f"{sel} 알림 임계값이 저장되었습니다.")
                    st.rerun()
    else:
        st.info("등록된 알림 임계값이 없습니다.")

# =============================================================================
# 탭 5 — 리포트 (유형/기간 선택 → 생성 + 다운로드 + 이력 테이블)
# =============================================================================
with tab_report:
    st.subheader("KPI 리포트 생성")
    rc1, rc2, rc3, rc4 = st.columns([1, 1, 1, 1])
    r_type = rc1.selectbox("리포트 유형", ["DAILY", "WEEKLY", "MONTHLY", "CUSTOM"],
                           format_func=lambda x: {"DAILY": "일일", "WEEKLY": "주간",
                                                  "MONTHLY": "월간", "CUSTOM": "임의 기간"}[x])
    r_start = rc2.date_input("시작일", value=date.today() - timedelta(days=7), key="rep_start")
    r_end = rc3.date_input("종료일", value=date.today(), key="rep_end")
    r_fmt = rc4.selectbox("형식", ["PDF", "XLSX"])

    if st.button("리포트 생성", type="primary"):
        if r_end < r_start:
            st.error("종료일이 시작일보다 빠릅니다.")
        else:
            res = api_post("/kpi/reports/generate", {
                "report_type": r_type,
                "period_start": str(r_start),
                "period_end": str(r_end),
                "file_format": r_fmt,
                "generated_by": st.session_state.get("user_id", "admin"),
            })
            if res:
                st.success(f"리포트 생성 완료 (ID: {res.get('id')})")
                summ = res.get("summary", {})
                if summ:
                    s1, s2 = st.columns(2)
                    s1.metric("시간당 생산량", f"{summ['production']['hourly_production_kg']} kg/h")
                    s2.metric("완제품 불량률", f"{summ['defect']['defect_rate']} %")

    st.divider()
    st.subheader("리포트 이력")
    reports = api_get("/kpi/reports", {"limit": 50}) or []
    if reports:
        rdf = pd.DataFrame(reports)
        st.dataframe(
            rdf[[c for c in ["id", "report_type", "period_start", "period_end",
                             "file_format", "status", "generated_at", "generated_by"] if c in rdf.columns]],
            use_container_width=True, hide_index=True,
        )
        dl_id = st.selectbox("다운로드할 리포트 ID", [r["id"] for r in reports])
        if st.button("다운로드"):
            try:
                resp = get_client().get(f"/kpi/reports/{dl_id}/download")
                resp.raise_for_status()
                st.download_button(
                    "파일 저장", data=resp.content,
                    file_name=f"kpi_report_{dl_id}",
                    mime=resp.headers.get("content-type", "application/octet-stream"),
                )
            except Exception as e:
                st.error(f"다운로드 실패: {e}")
    else:
        st.info("생성된 리포트가 없습니다.")
