"""
꽃순이김치 제조AI MES — AI 대시보드 화면 (pages/01_dashboard.py)
프로젝트: SF26179540 / 로뎀솔루션

streamlit-dashboard 스킬 원칙:
  - 모든 API 호출은 try/except 로 감싸고 실패 시 st.warning()
  - 차트는 Plotly, use_container_width=True, 한글 레이블
  - 데이터 없을 때 st.info("데이터가 없습니다.") graceful 처리

구성:
  상단 KPI 메트릭 4개 (st.metric)
  탭 4개: 생산현황 / 품질현황 / 발효상태 / 출하현황 분석
  사이드바: 알림 패널 (미읽음 count badge)

API: http://localhost:8000/api/v1/dashboard  (api_dashboard_router.py)
"""
from __future__ import annotations

from datetime import datetime

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="AI 대시보드 | 꽃순이김치 MES",
    page_icon="📊",
    layout="wide",
)

API_BASE = "http://localhost:8000/api/v1/dashboard"

# 발효 상태 → 색상/이모지
FERMENT_COLOR = {"정상": "#10b981", "주의": "#f59e0b", "이상": "#ef4444"}
FERMENT_EMOJI = {"정상": "🟢", "주의": "🟡", "이상": "🔴"}
SEVERITY_EMOJI = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "🔵"}


# ---------------------------------------------------------------------------
# API 헬퍼 — 모든 호출 try/except, 실패 시 st.warning + 기본값
# ---------------------------------------------------------------------------
def api_get(path: str, params: dict | None = None, default=None):
    """GET 요청. 실패 시 st.warning 후 default 반환."""
    try:
        r = httpx.get(f"{API_BASE}{path}", params=params or {}, timeout=10.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        st.warning(f"API 조회 실패 ({path}): {e}")
        return default


def api_post(path: str, json: dict | None = None, params: dict | None = None):
    """POST 요청. HTTP 오류 시 detail 메시지 표시."""
    try:
        r = httpx.post(f"{API_BASE}{path}", json=json or {}, params=params or {}, timeout=10.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json().get("detail", str(e))
        except Exception:  # noqa: BLE001
            detail = str(e)
        st.error(f"🚫 API 오류 ({path} · {e.response.status_code}): {detail}")
        return None
    except Exception as e:  # noqa: BLE001
        st.warning(f"API 요청 실패 ({path}): {e}")
        return None


def api_put(path: str, json: dict | None = None):
    """PUT 요청. 실패 시 st.warning 후 None 반환."""
    try:
        r = httpx.put(f"{API_BASE}{path}", json=json or {}, timeout=10.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        st.warning(f"API 처리 실패 ({path}): {e}")
        return None


def fmt_kg(value) -> str:
    """kg 값을 천단위 콤마 문자열로 포맷."""
    try:
        return f"{float(value):,.0f} kg"
    except (TypeError, ValueError):
        return "- kg"


# ---------------------------------------------------------------------------
# 사이드바 — 알림 패널 (미읽음 count badge)
# ---------------------------------------------------------------------------
def render_sidebar_alerts() -> None:
    """사이드바 알림 패널. 미읽음 count 배지 + 읽음 처리 버튼."""
    with st.sidebar:
        st.markdown("## 🔔 알림 패널")

        unread = api_get("/alerts", params={"is_read": "false", "limit": 20}, default=[]) or []
        all_alerts = api_get("/alerts", params={"limit": 20}, default=[]) or []

        unread_cnt = len(unread)
        if unread_cnt > 0:
            st.markdown(
                f"<span style='background:#ef4444;color:#fff;border-radius:12px;"
                f"padding:2px 10px;font-weight:700;'>읽지 않음 {unread_cnt}</span>",
                unsafe_allow_html=True,
            )
        else:
            st.success("새 알림 없음")

        st.divider()

        if not all_alerts:
            st.info("표시할 알림이 없습니다.")
            return

        for a in all_alerts:
            emoji = SEVERITY_EMOJI.get(a.get("severity"), "⚪")
            read_mark = "" if a.get("is_read") else " **·NEW**"
            with st.container(border=True):
                st.markdown(f"{emoji} **[{a.get('module', '-')}]**{read_mark}")
                st.caption(a.get("message", ""))
                ts = a.get("created_at", "")[:16].replace("T", " ")
                cols = st.columns([2, 1])
                cols[0].caption(f"🕒 {ts}")
                if not a.get("is_read"):
                    if cols[1].button("읽음", key=f"read_{a['alert_id']}"):
                        api_put(f"/alerts/{a['alert_id']}/read")
                        st.rerun()


# ---------------------------------------------------------------------------
# 상단 KPI 메트릭 4개
# ---------------------------------------------------------------------------
def render_kpi_metrics() -> dict:
    """상단 핵심 지표 4개. summary/today + kpi/summary 활용."""
    summary = api_get("/summary/today", default={}) or {}
    kpi = api_get("/kpi/summary", default={}) or {}

    c1, c2, c3, c4 = st.columns(4)

    prod = summary.get("production_kg", 0)
    achievement = kpi.get("production_achievement")
    c1.metric(
        "오늘 생산량",
        fmt_kg(prod),
        delta=f"달성률 {achievement}%" if achievement is not None else None,
    )

    defect = summary.get("defect_rate_pct", 0)
    target = kpi.get("defect_rate_target", 1.0)
    # 불량률은 낮을수록 좋음 → 목표 대비 초과분을 음의 delta(inverse)로 표시
    c2.metric(
        "완제품 불량률",
        f"{defect}%",
        delta=f"목표 {target}%",
        delta_color="inverse",
    )

    active = summary.get("active_fermentation_lots", 0)
    accuracy = kpi.get("fermentation_accuracy")
    c3.metric(
        "발효중 LOT",
        f"{active} 건",
        delta=f"정상률 {accuracy}%" if accuracy is not None else None,
    )

    shipping = summary.get("shipping_kg", 0)
    c4.metric("오늘 출하량", fmt_kg(shipping))

    return summary


# ---------------------------------------------------------------------------
# 탭 1: 생산현황 분석
# ---------------------------------------------------------------------------
def render_production_tab() -> None:
    st.subheader("생산현황 분석")

    days = st.slider("조회 기간(일)", 7, 30, 7, key="prod_days")
    daily = api_get("/production/daily", params={"days": days}, default=[]) or []

    if daily:
        df = pd.DataFrame(daily)
        st.markdown("**일별 생산량 (kg)**")
        fig = go.Figure(go.Bar(
            x=df["work_date"],
            y=df["output_kg"],
            marker_color="#1a73e8",
            name="생산량",
            text=[f"{v:,.0f}" for v in df["output_kg"]],
            textposition="outside",
        ))
        fig.update_layout(
            template="plotly_white",
            height=360,
            xaxis_title="일자",
            yaxis_title="생산량(kg)",
            margin=dict(l=40, r=20, t=20, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("데이터가 없습니다.")

    st.divider()
    st.markdown("**공정별 불량률**")
    # production/daily 는 통합 집계이므로, 공정별 표는 quality/trend 대신
    # 일별 생산 데이터를 가공해 표로 표시 (불량률 + 생산량/불량량)
    if daily:
        view = [{
            "일자": d.get("work_date"),
            "투입(kg)": round(d.get("input_kg", 0), 1),
            "생산(kg)": round(d.get("output_kg", 0), 1),
            "불량(kg)": round(d.get("defect_kg", 0), 1),
            "불량률(%)": d.get("defect_rate_pct"),
        } for d in daily]
        st.dataframe(pd.DataFrame(view), use_container_width=True, hide_index=True)
    else:
        st.info("데이터가 없습니다.")


# ---------------------------------------------------------------------------
# 탭 2: 품질현황 분석
# ---------------------------------------------------------------------------
def render_quality_tab() -> None:
    st.subheader("품질현황 분석")

    days = st.slider("조회 기간(일)", 7, 30, 7, key="qual_days")
    trend = api_get("/quality/trend", params={"days": days}, default=[]) or []

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("**불량률 추세 (%)**")
        if trend:
            df = pd.DataFrame(trend)
            fig = go.Figure(go.Scatter(
                x=df["work_date"],
                y=df["defect_rate_pct"],
                mode="lines+markers",
                line=dict(color="#ef4444", width=2),
                name="불량률",
            ))
            # 목표선 1.0% (KPI 목표)
            fig.add_hline(
                y=1.0, line_dash="dash", line_color="#10b981",
                annotation_text="목표 1.0%",
            )
            fig.update_layout(
                template="plotly_white",
                height=340,
                xaxis_title="일자",
                yaxis_title="불량률(%)",
                margin=dict(l=40, r=20, t=20, b=40),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("데이터가 없습니다.")

    with col_b:
        st.markdown("**발효 품질 등급 분포**")
        dist = api_get("/fermentation/status", default={}) or {}
        total = dist.get("total", 0)
        if total > 0:
            labels = ["정상", "주의", "이상"]
            values = [dist.get("normal", 0), dist.get("warning", 0), dist.get("abnormal", 0)]
            colors = [FERMENT_COLOR[lab] for lab in labels]
            fig = go.Figure(go.Pie(
                labels=labels,
                values=values,
                marker=dict(colors=colors),
                hole=0.45,
                textinfo="label+value",
            ))
            fig.update_layout(
                template="plotly_white",
                height=340,
                margin=dict(l=20, r=20, t=20, b=20),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("데이터가 없습니다.")


# ---------------------------------------------------------------------------
# 탭 3: 발효상태 모니터링 (@st.fragment 30초 자동 갱신)
# ---------------------------------------------------------------------------
@st.fragment(run_every=30)
def render_fermentation_fragment() -> None:
    """활성 발효 LOT 카드형 표시 — 30초마다 자동 갱신."""
    st.caption(f"🔄 자동 갱신 (30초) · 최종 {datetime.now():%H:%M:%S}")

    active = api_get("/fermentation/active", default=[]) or []
    dist = api_get("/fermentation/status", default={}) or {}

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("발효중 LOT", f"{dist.get('total', 0)} 건")
    m2.metric("🟢 정상", dist.get("normal", 0))
    m3.metric("🟡 주의", dist.get("warning", 0))
    m4.metric("🔴 이상", dist.get("abnormal", 0))

    st.divider()

    if not active:
        st.info("데이터가 없습니다.")
        return

    # 카드형 3열 표시
    for i in range(0, len(active), 3):
        cols = st.columns(3)
        for col, lot in zip(cols, active[i:i + 3]):
            with col:
                label = lot.get("ferment_status_label", "-")
                emoji = FERMENT_EMOJI.get(label, "⚪")
                with st.container(border=True):
                    st.markdown(f"**{emoji} {lot.get('lot_id', '-')}**")
                    st.caption(f"상태: {label}")
                    cc1, cc2, cc3 = st.columns(3)
                    temp = lot.get("temperature")
                    acid = lot.get("acidity")
                    ph = lot.get("ph")
                    cc1.metric("온도", f"{temp:.1f}°C" if temp is not None else "-")
                    cc2.metric("산도", f"{acid:.2f}%" if acid is not None else "-")
                    cc3.metric("pH", f"{ph:.2f}" if ph is not None else "-")
                    ts = (lot.get("recorded_at") or "")[:16].replace("T", " ")
                    st.caption(f"🕒 {ts}")


def render_fermentation_tab() -> None:
    st.subheader("발효상태 모니터링")
    render_fermentation_fragment()


# ---------------------------------------------------------------------------
# 탭 4: 출하현황 분석
# ---------------------------------------------------------------------------
def render_shipping_tab() -> None:
    st.subheader("출하현황 분석")

    shipping = api_get("/shipping/daily", params={"days": 7}, default=[]) or []

    if shipping:
        df = pd.DataFrame(shipping)
        st.markdown("**일별 출하량 / 포장량 (kg)**")
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df["work_date"], y=df["packaging_kg"],
            name="포장량", marker_color="#94a3b8",
        ))
        fig.add_trace(go.Bar(
            x=df["work_date"], y=df["shipping_kg"],
            name="출하량(양품)", marker_color="#1a73e8",
        ))
        fig.update_layout(
            template="plotly_white",
            height=360,
            barmode="group",
            xaxis_title="일자",
            yaxis_title="중량(kg)",
            margin=dict(l=40, r=20, t=20, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.markdown("**최근 출하 실적**")
        view = [{
            "일자": s.get("work_date"),
            "출하건수": s.get("shipment_count"),
            "포장량(kg)": round(s.get("packaging_kg", 0), 1),
            "출하량(kg)": round(s.get("shipping_kg", 0), 1),
        } for s in shipping]
        st.dataframe(pd.DataFrame(view), use_container_width=True, hide_index=True)
    else:
        st.info("데이터가 없습니다.")


# ---------------------------------------------------------------------------
# 메인 레이아웃
# ---------------------------------------------------------------------------
def main() -> None:
    st.title("📊 AI 대시보드")
    st.caption("평창꽃순이 제조AI 스마트공장 — 생산·품질·발효·출하 통합 현황")

    # 사이드바 알림 패널
    render_sidebar_alerts()

    # 상단 KPI 메트릭
    render_kpi_metrics()

    st.divider()

    # 탭 4개
    tabs = st.tabs(
        ["생산현황 분석", "품질현황 분석", "발효상태 모니터링", "출하현황 분석"]
    )
    with tabs[0]:
        render_production_tab()
    with tabs[1]:
        render_quality_tab()
    with tabs[2]:
        render_fermentation_tab()
    with tabs[3]:
        render_shipping_tab()


if __name__ == "__main__":
    main()
else:
    # Streamlit 페이지로 import 될 때도 렌더링
    main()
