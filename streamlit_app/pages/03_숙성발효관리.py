import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from components.styles import (
    apply_styles, metric_card, status_badge, section_header,
    render_page_header, style_plotly,
)
from components.sidebar import render_sidebar
from components.nav import activate_tab
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

st.set_page_config(page_title="숙성발효관리 | 꽃순이김치 MES", page_icon="🫙", layout="wide")
apply_styles()
render_sidebar(current="fermentation")

np.random.seed(42)


# ----------------------------------------------------------------------------
# 공통 Plotly 레이아웃 헬퍼 (라이트 테마)
# ----------------------------------------------------------------------------
def style_fig(fig, height=360, legend=True):
    return style_plotly(fig, height=height, legend=legend)


# ----------------------------------------------------------------------------
# Mock 데이터 생성
# ----------------------------------------------------------------------------
LOT_IDS = [f"FERM-2026-{n:04d}" for n in range(512, 524)]  # 12개
ABNORMAL_LOT = "FERM-2026-0523"


@st.cache_data
def make_ferment_lots():
    rows = []
    base_start = datetime(2026, 5, 21, 8, 0)
    remain_hours = [2.3, 8.5, 14.2, 22.1, 30.4, 5.7, 11.9, 18.6, 26.3, 33.8, 7.2, 1.1]
    for i, lot in enumerate(LOT_IDS):
        is_ab = lot == ABNORMAL_LOT
        start = base_start + timedelta(hours=i * 3.5)
        rem = remain_hours[i]
        eta = datetime(2026, 5, 23, 15, 0) + timedelta(hours=rem)
        temp = round(np.random.uniform(16.5, 20.5), 1) if not is_ab else 24.1
        ph = round(np.random.uniform(0.38, 0.52), 2) if not is_ab else 0.61
        salt = round(np.random.uniform(1.7, 2.4), 2)
        if is_ab:
            qual, conf = "이상", 91.3
        elif i in (3, 9):
            qual, conf = "주의", round(np.random.uniform(72, 80), 1)
        else:
            qual, conf = "정상", round(np.random.uniform(82, 95), 1)
        rows.append({
            "LOT_ID": lot,
            "시작시간": start.strftime("%m-%d %H:%M"),
            "예상완료시간": eta.strftime("%m-%d %H:%M"),
            "온도(°C)": temp,
            "산도(pH)": ph,
            "염도(%)": salt,
            "ML품질예측": qual,
            "신뢰도(%)": conf,
            "잔여시간(h)": rem,
            "상태": qual,
        })
    return pd.DataFrame(rows)


@st.cache_data
def make_sensor_series(lot_id, abnormal=False):
    hours = np.arange(0, 48)
    t0 = datetime(2026, 5, 21, 8, 0)
    times = [t0 + timedelta(hours=int(h)) for h in hours]
    temp = 18 + 1.5 * np.sin(hours / 8) + np.random.normal(0, 0.4, len(hours))
    temp = np.clip(temp, 15, 22)
    if abnormal:
        temp[34:] = np.clip(temp[34:] + np.linspace(2, 6, len(temp[34:])), 15, 26)
    ph = 0.55 - (hours / 48) * 0.20 + np.random.normal(0, 0.01, len(hours))
    ph = np.clip(ph, 0.35, 0.55)
    if abnormal:
        ph[34:] = ph[34:] + np.linspace(0.02, 0.10, len(ph[34:]))
    salt = 2.0 + np.random.normal(0, 0.12, len(hours))
    salt = np.clip(salt, 1.5, 2.5)
    return pd.DataFrame({"시간": times, "온도": temp, "산도": ph, "염도": salt})


@st.cache_data
def make_prediction_table():
    lots = [f"FERM-2026-{n:04d}" for n in range(509, 524)]  # 15개
    quals = (["정상"] * 10) + (["주의"] * 3) + (["이상"] * 2)
    np.random.shuffle(quals)
    rows = []
    for lot, q in zip(lots, quals):
        if q == "정상":
            p_n = np.random.uniform(70, 92)
            p_w = np.random.uniform(5, 20)
        elif q == "주의":
            p_n = np.random.uniform(30, 50)
            p_w = np.random.uniform(40, 60)
        else:
            p_n = np.random.uniform(5, 20)
            p_w = np.random.uniform(15, 30)
        p_e = max(0, 100 - p_n - p_w)
        tot = p_n + p_w + p_e
        p_n, p_w, p_e = p_n / tot * 100, p_w / tot * 100, p_e / tot * 100
        conf = max(p_n, p_w, p_e)
        rows.append({
            "LOT_ID": lot,
            "예측품질": q,
            "신뢰도(%)": round(conf, 1),
            "확률_정상(%)": round(p_n, 1),
            "확률_주의(%)": round(p_w, 1),
            "확률_이상(%)": round(p_e, 1),
        })
    return pd.DataFrame(rows)


@st.cache_data
def make_alert_history():
    types = ["고온 이상", "산도 급상승", "염도 미달", "온도 변동", "pH 정체"]
    sev = ["높음", "중간", "낮음"]
    rows = []
    for i in range(10):
        dt = datetime(2026, 5, 23, 14, 32) - timedelta(days=i * 2, hours=int(np.random.randint(0, 10)))
        status = "처리중" if i == 0 else "처리완료"
        rows.append({
            "발생일시": dt.strftime("%Y-%m-%d %H:%M"),
            "LOT_ID": f"FERM-2026-{523 - i * 2:04d}",
            "이상유형": types[i % len(types)],
            "심각도": sev[i % len(sev)] if i != 0 else "높음",
            "조치내용": "발효실 온도 조정" if i == 0 else np.random.choice(["온도 재조정", "염수 보충", "수동 검수 후 정상", "발효시간 연장"]),
            "처리상태": status,
        })
    return pd.DataFrame(rows)


df_lots = make_ferment_lots()
df_pred = make_prediction_table()
df_alert = make_alert_history()

# ----------------------------------------------------------------------------
# 헤더
# ----------------------------------------------------------------------------
render_page_header("숙성 · 발효 관리",
                   "ML 기반 발효 품질 예측 · 완료 시점 예측 · 이상발효 조기경보")

# ----------------------------------------------------------------------------
# 상단 요약 메트릭
# ----------------------------------------------------------------------------
m1, m2, m3, m4 = st.columns(4)
with m1:
    metric_card("발효 진행 중", "12 LOT", color="#3F8C9C")
with m2:
    metric_card("이상발효 알림", "1 건", color="#C53D2E")
with m3:
    metric_card("오늘 발효완료", "5 LOT", color="#4C9B52")
with m4:
    metric_card("평균 발효 품질", "83.5%", target="80%", color="#7A8C3C")

st.markdown("")

# ----------------------------------------------------------------------------
# 탭 7개
# ----------------------------------------------------------------------------
tabs = st.tabs([
    "발효상태 모니터링",
    "품질예측결과",
    "발효완료예측",
    "이상발효알림",
    "ML분석",
    "영향요인 분석",
    "공정조건 분석",
])
activate_tab()

# ============================================================================
# Tab 1: 발효상태 모니터링
# ============================================================================
with tabs[0]:
    section_header("발효 LOT 목록", "🫙")

    def fmt_status(v):
        return v

    show = df_lots[["LOT_ID", "시작시간", "예상완료시간", "온도(°C)", "산도(pH)",
                    "염도(%)", "ML품질예측", "잔여시간(h)", "상태"]].copy()

    def highlight_row(row):
        if row["상태"] == "이상":
            return ["background-color: #FCE5E1; color:#7D1C0F"] * len(row)
        if row["상태"] == "주의":
            return ["background-color: #FEF3C7"] * len(row)
        return [""] * len(row)

    st.dataframe(
        show.style.apply(highlight_row, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("")
    section_header("LOT 상세 — 발효 센서 시계열 (48시간)", "📈")

    sel_lot = st.selectbox("LOT 선택", LOT_IDS, index=LOT_IDS.index(ABNORMAL_LOT))
    is_ab = sel_lot == ABNORMAL_LOT

    if is_ab:
        st.error(
            f"🚨 **{sel_lot} — 이상발효 감지!** 온도 24.1°C (기준 ≤22°C), "
            "산도 0.61 (기준 ≤0.55) 초과. 품질 관리자 확인이 필요합니다."
        )

    df_s = make_sensor_series(sel_lot, abnormal=is_ab)

    c_temp, c_ph = st.columns(2)
    with c_temp:
        fig = go.Figure()
        fig.add_hrect(y0=15, y1=22, fillcolor="#4C9B52", opacity=0.10, line_width=0,
                      annotation_text="정상범위", annotation_position="top left",
                      annotation_font_color="#4C9B52")
        fig.add_trace(go.Scatter(x=df_s["시간"], y=df_s["온도"], mode="lines",
                                 name="온도(°C)", line=dict(color="#C53D2E", width=2)))
        fig.update_layout(title="발효 온도 (°C)")
        st.plotly_chart(style_fig(fig, legend=False), use_container_width=True)

    with c_ph:
        fig = go.Figure()
        fig.add_hrect(y0=0.35, y1=0.55, fillcolor="#3F8C9C", opacity=0.10, line_width=0,
                      annotation_text="정상범위", annotation_position="top left",
                      annotation_font_color="#3F8C9C")
        fig.add_trace(go.Scatter(x=df_s["시간"], y=df_s["산도"], mode="lines",
                                 name="산도(pH)", line=dict(color="#D97A2B", width=2)))
        fig.update_layout(title="산도 (pH)")
        st.plotly_chart(style_fig(fig, legend=False), use_container_width=True)

    fig = go.Figure()
    fig.add_hrect(y0=1.5, y1=2.5, fillcolor="#7A8C3C", opacity=0.10, line_width=0,
                  annotation_text="정상범위", annotation_position="top left",
                  annotation_font_color="#7A8C3C")
    fig.add_trace(go.Scatter(x=df_s["시간"], y=df_s["염도"], mode="lines",
                             name="염도(%)", line=dict(color="#3F8C9C", width=2)))
    fig.update_layout(title="염도 (%)")
    st.plotly_chart(style_fig(fig, height=300, legend=False), use_container_width=True)

# ============================================================================
# Tab 2: 품질예측결과 (XGBoost)
# ============================================================================
with tabs[1]:
    section_header("ML 품질 예측 결과 (XGBoost)", "🤖")

    def highlight_pred(row):
        if row["예측품질"] == "이상":
            return ["background-color: #FCE5E1; color:#7D1C0F"] * len(row)
        if row["예측품질"] == "주의":
            return ["background-color: #FEF3C7"] * len(row)
        return [""] * len(row)

    st.dataframe(
        df_pred.style.apply(highlight_pred, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("")
    c1, c2 = st.columns(2)
    with c1:
        section_header("품질 분포", "🥧")
        fig = go.Figure(data=[go.Pie(
            labels=["정상", "주의", "이상"],
            values=[70, 20, 10],
            hole=0.45,
            marker=dict(colors=["#4C9B52", "#D97A2B", "#C53D2E"]),
            textinfo="label+percent",
        )])
        st.plotly_chart(style_fig(fig), use_container_width=True)

    with c2:
        section_header("예측 신뢰도 분포", "📊")
        conf_vals = np.concatenate([
            np.random.normal(88, 4, 60),
            np.random.normal(76, 5, 25),
            np.random.normal(91, 3, 15),
        ])
        conf_vals = np.clip(conf_vals, 60, 99)
        fig = px.histogram(x=conf_vals, nbins=20, color_discrete_sequence=["#C53D2E"])
        fig.update_layout(title="신뢰도(%) 분포", xaxis_title="신뢰도(%)", yaxis_title="LOT 수")
        st.plotly_chart(style_fig(fig, legend=False), use_container_width=True)

# ============================================================================
# Tab 3: 발효완료예측 (LSTM)
# ============================================================================
with tabs[2]:
    section_header("발효 완료 잔여시간 예측 (LSTM)", "⏱️")

    df_rem = df_lots[["LOT_ID", "잔여시간(h)"]].sort_values("잔여시간(h)")
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=df_rem["LOT_ID"],
        x=df_rem["잔여시간(h)"],
        orientation="h",
        marker=dict(color="#3F8C9C"),
        error_x=dict(type="constant", value=1.7, color="#D97A2B", thickness=1.5),
        text=[f"{v:.1f}h" for v in df_rem["잔여시간(h)"]],
        textposition="outside",
    ))
    fig.update_layout(title="LOT별 발효 완료 잔여시간 (±1.7h 오차)",
                      xaxis_title="잔여시간 (h)", yaxis_title="")
    st.plotly_chart(style_fig(fig, height=420, legend=False), use_container_width=True)

    st.markdown("")
    section_header("예측 정확도 이력 (최근 30일 MAE)", "📉")
    days = [datetime(2026, 4, 23) + timedelta(days=i) for i in range(30)]
    mae = np.clip(np.random.uniform(1.5, 2.0, 30) + np.linspace(0.15, -0.1, 30), 1.4, 2.05)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=days, y=mae, mode="lines+markers", name="MAE(h)",
                             line=dict(color="#3F8C9C", width=2),
                             marker=dict(size=5)))
    fig.add_hline(y=2.0, line_dash="dash", line_color="#C53D2E",
                  annotation_text="목표 MAE 2.0h", annotation_position="bottom right",
                  annotation_font_color="#C53D2E")
    fig.update_layout(title="발효완료 예측 오차(MAE) 추이",
                      xaxis_title="날짜", yaxis_title="MAE (시간)")
    st.plotly_chart(style_fig(fig, legend=False), use_container_width=True)

# ============================================================================
# Tab 4: 이상발효알림
# ============================================================================
with tabs[3]:
    section_header("실시간 이상발효 알림", "🚨")

    st.error(
        "🚨 **FERM-2026-0523 — 이상발효 감지!**\n\n"
        "- **발생 시각**: 2026-05-23 14:32\n"
        "- **이상 지표**: 온도 24.1°C (기준: ≤22°C), 산도 0.61 (기준: ≤0.55)\n"
        "- **ML 예측**: 이상 (신뢰도 91.3%)\n"
        "- **권장 조치**: 즉시 발효실 온도 조정, 품질 관리자 확인 필요"
    )
    if st.button("✅ 조치 완료 처리", key="ack_alert"):
        st.success("FERM-2026-0523 이상발효 알림이 '처리완료'로 기록되었습니다.")

    st.markdown("")
    section_header("알림 이력 (최근 30일)", "📋")

    def highlight_alert(row):
        if row["처리상태"] == "처리중":
            return ["background-color: #FEF3C7"] * len(row)
        return [""] * len(row)

    st.dataframe(
        df_alert.style.apply(highlight_alert, axis=1),
        use_container_width=True,
        hide_index=True,
    )

# ============================================================================
# Tab 5: ML분석 (모델 성능)
# ============================================================================
with tabs[4]:
    section_header("모델 학습 성능 지표", "🧠")

    cL, cR = st.columns(2)
    with cL:
        st.markdown(
            """
            <div class="mes-card">
                <div class="mes-card-title">🌳 XGBoost (품질 분류)</div>
                <div style="color:#4A4640;font-size:14px;line-height:2.0;margin-top:8px;">
                    정확도: <b style="color:#4C9B52;">83.5%</b> (목표 80% ✅)<br>
                    Recall(이상): <b style="color:#4C9B52;">87.2%</b> (목표 85% ✅)<br>
                    학습 데이터: <b style="color:#29261b;">15,423건</b> (2025-11-01 ~ 2026-05-01)<br>
                    마지막 재학습: <b style="color:#29261b;">2026-05-01</b>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with cR:
        st.markdown(
            """
            <div class="mes-card">
                <div class="mes-card-title">🔁 LSTM (완료시점 예측)</div>
                <div style="color:#4A4640;font-size:14px;line-height:2.0;margin-top:8px;">
                    MAE: <b style="color:#4C9B52;">1.7시간</b> (목표 2h ✅)<br>
                    슬라이딩 윈도우: <b style="color:#29261b;">24시간</b><br>
                    학습 LOT 수: <b style="color:#29261b;">1,243 LOT</b><br>
                    R²: <b style="color:#4C9B52;">0.89</b> (목표 0.85 ✅)
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("")
    c1, c2 = st.columns(2)
    with c1:
        section_header("학습 손실 곡선", "📉")
        epochs = np.arange(1, 51)
        train_loss = 1.2 * np.exp(-epochs / 12) + 0.08 + np.random.normal(0, 0.01, 50)
        val_loss = 1.2 * np.exp(-epochs / 12) + 0.13 + np.random.normal(0, 0.015, 50)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=epochs, y=train_loss, mode="lines",
                                 name="Training Loss", line=dict(color="#3F8C9C", width=2)))
        fig.add_trace(go.Scatter(x=epochs, y=val_loss, mode="lines",
                                 name="Validation Loss", line=dict(color="#D97A2B", width=2)))
        fig.update_layout(title="에폭별 손실값", xaxis_title="Epoch", yaxis_title="Loss")
        st.plotly_chart(style_fig(fig), use_container_width=True)

    with c2:
        section_header("Confusion Matrix", "🔢")
        labels = ["정상", "주의", "이상"]
        cm = np.array([
            [142, 8, 2],
            [9, 38, 4],
            [1, 3, 26],
        ])
        fig = go.Figure(data=go.Heatmap(
            z=cm,
            x=[f"예측:{l}" for l in labels],
            y=[f"실제:{l}" for l in labels],
            colorscale="Reds",
            text=cm,
            texttemplate="%{text}",
            textfont=dict(size=16, color="#29261b"),
            showscale=True,
        ))
        fig.update_layout(title="혼동 행렬 (검증셋)")
        st.plotly_chart(style_fig(fig, legend=False), use_container_width=True)

# ============================================================================
# Tab 6: 영향요인 분석 (SHAP)
# ============================================================================
with tabs[5]:
    section_header("SHAP Feature Importance", "🎯")

    shap_data = [
        ("발효온도", 0.342), ("절임염도", 0.289), ("절임시간", 0.221),
        ("pH변화율", 0.198), ("외기온도", 0.156), ("배추등급", 0.134),
        ("함수율", 0.112), ("원산지", 0.089), ("절임온도", 0.067),
        ("외기습도", 0.045),
    ]
    feats = [f for f, _ in shap_data]
    vals = [v for _, v in shap_data]
    fig = go.Figure(go.Bar(
        x=vals[::-1], y=feats[::-1], orientation="h",
        marker=dict(color=vals[::-1], colorscale="Teal"),
        text=[f"{v:.3f}" for v in vals[::-1]], textposition="outside",
    ))
    fig.update_layout(title="피처별 평균 |SHAP 값|", xaxis_title="평균 |SHAP|", yaxis_title="")
    st.plotly_chart(style_fig(fig, height=420, legend=False), use_container_width=True)

    st.info(
        "💡 **발효온도**가 품질 예측에 가장 큰 영향을 미칩니다. "
        "발효온도 **15~20°C** 범위 유지 시 정상 발효 확률이 **92.3%**까지 높아집니다."
    )

    st.markdown("")
    section_header("SHAP 산점도 — 발효온도 vs SHAP 값", "📌")
    n = 200
    temp_x = np.random.uniform(14, 26, n)
    shap_y = -0.06 * (temp_x - 18) + np.random.normal(0, 0.04, n)
    grade = np.where(temp_x > 22, "이상", np.where(temp_x > 20.5, "주의", "정상"))
    df_shap = pd.DataFrame({"발효온도": temp_x, "SHAP값": shap_y, "품질등급": grade})
    fig = px.scatter(
        df_shap, x="발효온도", y="SHAP값", color="품질등급",
        color_discrete_map={"정상": "#4C9B52", "주의": "#D97A2B", "이상": "#C53D2E"},
    )
    fig.update_layout(title="발효온도에 따른 SHAP 기여도", xaxis_title="발효온도(°C)", yaxis_title="SHAP 값")
    st.plotly_chart(style_fig(fig), use_container_width=True)

# ============================================================================
# Tab 7: 공정조건 분석
# ============================================================================
with tabs[6]:
    section_header("공정 조건 상관 분석", "🔬")

    n = 250
    salt = np.random.uniform(1.5, 2.6, n)
    ferm_days = 6 - 1.2 * (salt - 2.0) + np.random.normal(0, 0.6, n)
    brine_temp = np.random.uniform(14, 24, n)
    qual_score = 90 - 1.8 * np.abs(brine_temp - 19) + np.random.normal(0, 4, n)
    brine_time = np.random.uniform(4, 12, n)
    final_acid = 0.4 + 0.018 * brine_time + np.random.normal(0, 0.03, n)
    origin = np.random.choice(["강원", "충북", "전남"], n)
    grade = np.random.choice(["정상", "주의", "이상"], n, p=[0.7, 0.2, 0.1])

    df_proc = pd.DataFrame({
        "절임염도": salt, "발효기간": ferm_days,
        "절임온도": brine_temp, "발효품질점수": qual_score,
        "절임시간": brine_time, "최종산도": final_acid,
        "원산지": origin, "품질등급": grade,
    })

    grade_map = {"정상": "#4C9B52", "주의": "#D97A2B", "이상": "#C53D2E"}
    origin_map = {"강원": "#C53D2E", "충북": "#3F8C9C", "전남": "#7A8C3C"}

    c1, c2 = st.columns(2)
    with c1:
        fig = px.scatter(df_proc, x="절임염도", y="발효기간", color="품질등급",
                         color_discrete_map=grade_map)
        fig.update_layout(title="절임염도 vs 발효기간")
        st.plotly_chart(style_fig(fig), use_container_width=True)
    with c2:
        fig = px.scatter(df_proc, x="절임온도", y="발효품질점수", color="원산지",
                         color_discrete_map=origin_map)
        fig.update_layout(title="절임온도 vs 발효품질점수")
        st.plotly_chart(style_fig(fig), use_container_width=True)

    fig = px.scatter(df_proc, x="절임시간", y="최종산도", color="품질등급",
                     color_discrete_map=grade_map)
    fig.update_layout(title="절임시간 vs 최종산도")
    st.plotly_chart(style_fig(fig, height=320), use_container_width=True)

    st.markdown("")
    st.success(
        "🎯 **AI 추천 최적 절임 조건**\n\n"
        "- **절임온도**: 18~20°C\n"
        "- **절임염도**: 2.0~2.3%\n"
        "- **절임시간**: 6~8시간\n"
        "- **예상 발효 품질 정상 확률**: 91.2%"
    )
