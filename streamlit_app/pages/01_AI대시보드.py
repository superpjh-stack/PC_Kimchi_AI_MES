import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from components.styles import (
    apply_styles, metric_card, status_badge, section_header,
    render_page_header, style_plotly, COLORWAY,
)
from components.sidebar import render_sidebar
from components.nav import activate_tab
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

st.set_page_config(page_title="AI 대시보드 | 꽃순이김치 MES", page_icon="📊", layout="wide")
apply_styles()
render_sidebar(current="dashboard")

np.random.seed(42)


def style_fig(fig, height=320):
    return style_plotly(fig, height=height)


def badge_table(df: pd.DataFrame, status_col: str):
    """상태 컬럼을 배지 HTML로 렌더링한 테이블 출력 (라이트 테마)"""
    d = df.copy()
    d[status_col] = d[status_col].apply(status_badge)
    html = d.to_html(escape=False, index=False, classes="mes-table")
    st.markdown(
        "<div class='mes-card' style='padding:0; overflow-x:auto;'>" + html + "</div>",
        unsafe_allow_html=True,
    )


# ===== 헤더 =====
render_page_header("AI 대시보드", "생산 · 품질 · 발효 · 출하 통합 모니터링",
                   right=datetime.now().strftime("%Y-%m-%d %H:%M"))

# ===== 상단 KPI =====
k1, k2, k3, k4 = st.columns(4)
with k1:
    metric_card("시간당 생산량", "3,024 kg/h", delta="목표 대비 +0.8%", color="#4C9B52", target="3,000 kg/h")
with k2:
    metric_card("완제품 불량률", "0.92%", delta="목표 1.0% 달성", color="#4C9B52", target="1.0% 이하")
with k3:
    metric_card("발효 품질 예측 정확도", "83.5%", delta="목표 80% 달성", color="#4C9B52", target="80% 이상")
with k4:
    metric_card("발효 완료 예측 MAE", "1.7시간", delta="목표 2h 달성", color="#4C9B52", target="2h 이하")

st.markdown("<br>", unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["📈 생산현황 분석", "🔍 품질현황 분석", "🌡️ 발효상태 모니터링", "🚚 출하현황 분석"])
activate_tab()

# ===================== Tab 1: 생산현황 =====================
with tab1:
    c1, c2 = st.columns(2)
    with c1:
        section_header("시간대별 생산량", "⏰")
        hours = [f"{h:02d}시" for h in range(6, 22)]
        prod = np.random.randint(2700, 3201, size=len(hours))
        fig = go.Figure(go.Bar(x=hours, y=prod, marker_color="#C53D2E",
                               text=prod, textposition="outside"))
        fig.add_hline(y=3000, line_dash="dash", line_color="#4C9B52",
                      annotation_text="목표 3,000", annotation_font_color="#4C9B52")
        fig.update_layout(yaxis_title="kg/h")
        st.plotly_chart(style_fig(fig), use_container_width=True)
    with c2:
        section_header("공정별 가동률", "⚙️")
        procs = ["절임", "세척/선별", "탈수", "혼합", "발효", "금속검출", "포장", "출하"]
        rates = [89, 91, 86, 88, 92, 94, 87, 95]
        fig = go.Figure(go.Bar(x=procs, y=rates, marker_color="#3F8C9C",
                               text=[f"{r}%" for r in rates], textposition="outside"))
        fig.update_layout(yaxis_title="가동률 (%)", yaxis_range=[0, 105])
        st.plotly_chart(style_fig(fig), use_container_width=True)

    section_header("오늘 작업 LOT 현황", "📋")
    procs_list = ["절임", "세척/선별", "탈수", "혼합", "발효", "금속검출", "포장", "출하"]
    statuses = ["완료", "완료", "진행중", "완료", "진행중", "정상", "주의", "완료", "진행중", "완료"]
    rows = []
    base = datetime(2026, 5, 23, 6, 0)
    for i in range(10):
        inp = base + timedelta(minutes=i * 47)
        done = inp + timedelta(minutes=np.random.randint(30, 90))
        st_v = statuses[i]
        rows.append({
            "LOT_ID": f"LOT-2026-{520 + i:04d}",
            "공정": procs_list[i % len(procs_list)],
            "투입시간": inp.strftime("%H:%M"),
            "완료시간": done.strftime("%H:%M") if st_v in ("완료", "정상") else "-",
            "수량(kg)": int(np.random.randint(2700, 3200)),
            "상태": st_v,
        })
    df_lot = pd.DataFrame(rows)
    badge_table(df_lot, "상태")

# ===================== Tab 2: 품질현황 =====================
with tab2:
    c1, c2 = st.columns(2)
    with c1:
        section_header("최근 30일 불량률 추이", "📉")
        days = [datetime(2026, 5, 23) - timedelta(days=29 - i) for i in range(30)]
        defect = np.round(np.clip(np.random.normal(1.05, 0.18, 30), 0.8, 1.5), 2)
        fig = go.Figure(go.Scatter(x=days, y=defect, mode="lines+markers",
                                   line=dict(color="#D97A2B", width=2),
                                   marker=dict(size=5)))
        fig.add_hline(y=1.0, line_dash="dash", line_color="#4C9B52",
                      annotation_text="목표 1.0%", annotation_font_color="#4C9B52")
        fig.update_layout(yaxis_title="불량률 (%)")
        st.plotly_chart(style_fig(fig), use_container_width=True)
    with c2:
        section_header("불량 유형별 분포", "🥧")
        labels = ["발효불량", "포장불량", "이물질", "중량불량"]
        values = [40, 25, 15, 20]
        fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.45,
                               marker=dict(colors=["#C53D2E", "#D97A2B", "#3F8C9C", "#7A8C3C"])))
        fig.update_traces(textinfo="label+percent")
        st.plotly_chart(style_fig(fig), use_container_width=True)

    section_header("품질 등급별 현황", "📋")
    rows = []
    for i in range(10):
        d = datetime(2026, 5, 23) - timedelta(days=9 - i)
        lots = int(np.random.randint(10, 20))
        bul = round(np.random.uniform(0.8, 1.4), 2)
        normal = int(lots * (1 - bul / 100) * np.random.uniform(0.82, 0.9))
        warn = int((lots - normal) * 0.6)
        abn = lots - normal - warn
        rows.append({
            "날짜": d.strftime("%Y-%m-%d"),
            "LOT수": lots,
            "정상": normal,
            "주의": warn,
            "이상": max(abn, 0),
            "불량률(%)": bul,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ===================== Tab 3: 발효상태 =====================
with tab3:
    section_header("현재 발효 진행 중 LOT", "🌡️")
    ferm = [
        {"id": "FERM-2026-0520", "status": "정상", "temp": 18.5, "acid": 0.42, "remain": 14.2, "color": "#4C9B52"},
        {"id": "FERM-2026-0521", "status": "주의", "temp": 21.3, "acid": 0.38, "remain": 8.5, "color": "#D97A2B"},
        {"id": "FERM-2026-0522", "status": "정상", "temp": 17.8, "acid": 0.45, "remain": 22.1, "color": "#4C9B52"},
        {"id": "FERM-2026-0523", "status": "이상", "temp": 24.1, "acid": 0.61, "remain": 6.3, "color": "#C53D2E"},
    ]
    cols = st.columns(3)
    for i, f in enumerate(ferm):
        with cols[i % 3]:
            temp_note = " (고온 주의)" if f["status"] == "주의" else (" (이상)" if f["status"] == "이상" else "")
            acid_note = " (이상)" if f["status"] == "이상" else ""
            icon = "🔴" if f["status"] == "이상" else ("🟡" if f["status"] == "주의" else "🟢")
            st.markdown(
                f"""
                <div class="mes-card" style="border-left:4px solid {f['color']};">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <span style="font-weight:700;color:#29261b;font-size:15px;">{icon} {f['id']}</span>
                        {status_badge(f['status'])}
                    </div>
                    <div style="color:#4A4640;font-size:13px;line-height:2.0;margin-top:8px;">
                        🌡️ 온도: <span style="color:{f['color']};font-weight:600;">{f['temp']}°C{temp_note}</span><br>
                        🧪 산도: <span style="color:{f['color']};font-weight:600;">{f['acid']}{acid_note}</span><br>
                        ⏳ 잔여: <span style="color:#29261b;font-weight:600;">{f['remain']}h</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.error("🔴 **이상발효 경보** — FERM-2026-0523: 온도 24.1°C / 산도 0.61 이상 감지. 즉시 점검이 필요합니다.")

    st.markdown("<br>", unsafe_allow_html=True)
    section_header("발효 온도 시계열 (최근 48시간)", "📈")
    t = [datetime(2026, 5, 23, 12, 0) - timedelta(hours=47 - i) for i in range(48)]
    bases = {"FERM-2026-0520": 18.5, "FERM-2026-0521": 20.5, "FERM-2026-0522": 17.8, "FERM-2026-0523": 22.0}
    fig = go.Figure()
    for j, (lot, b) in enumerate(bases.items()):
        trend = b + np.cumsum(np.random.normal(0, 0.12, 48))
        if lot == "FERM-2026-0523":
            trend = trend + np.linspace(0, 2.5, 48)  # 이상 상승
        fig.add_trace(go.Scatter(x=t, y=np.round(trend, 2), mode="lines", name=lot,
                                 line=dict(width=2, color=COLORWAY[j])))
    fig.add_hline(y=22, line_dash="dot", line_color="#D97A2B",
                  annotation_text="고온 경계 22°C", annotation_font_color="#D97A2B")
    fig.update_layout(yaxis_title="온도 (°C)", legend=dict(orientation="h", y=-0.25))
    st.plotly_chart(style_fig(fig, height=360), use_container_width=True)

# ===================== Tab 4: 출하현황 =====================
with tab4:
    c1, c2 = st.columns(2)
    with c1:
        section_header("최근 7일 일별 출하량", "📦")
        days = [(datetime(2026, 5, 23) - timedelta(days=6 - i)).strftime("%m-%d") for i in range(7)]
        ship = np.random.randint(6, 14, size=7)
        fig = go.Figure(go.Bar(x=days, y=ship, marker_color="#4C9B52",
                               text=ship, textposition="outside"))
        fig.update_layout(yaxis_title="출하 건수")
        st.plotly_chart(style_fig(fig), use_container_width=True)
    with c2:
        section_header("출하 승인 현황", "✅")
        fig = go.Figure(go.Pie(labels=["승인", "대기", "반려"], values=[8, 2, 1], hole=0.45,
                               marker=dict(colors=["#4C9B52", "#D97A2B", "#C53D2E"])))
        fig.update_traces(textinfo="label+value")
        st.plotly_chart(style_fig(fig), use_container_width=True)

    section_header("오늘 출하 목록", "🚚")
    dests = ["서울 물류센터", "부산 대리점", "대전 직영점", "광주 마트", "인천 물류", "수원 대리점", "강릉 직판", "원주 마트"]
    items = ["배추김치 10kg", "포기김치 5kg", "총각김치 3kg", "묵은지 10kg", "백김치 5kg"]
    ship_status = ["승인", "승인", "대기", "승인", "승인", "반려", "승인", "대기"]
    rows = []
    for i in range(8):
        rows.append({
            "출하번호": f"SHIP-2026-{301 + i:04d}",
            "LOT_ID": f"LOT-2026-{510 + i:04d}",
            "거래처": dests[i],
            "품목": items[i % len(items)],
            "수량(kg)": int(np.random.randint(50, 500)),
            "상태": ship_status[i],
        })
    badge_table(pd.DataFrame(rows), "상태")
