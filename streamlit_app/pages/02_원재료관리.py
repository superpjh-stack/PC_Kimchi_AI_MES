import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from components.styles import (
    apply_styles, metric_card, status_badge, section_header,
    style_plotly, COLORWAY, COLORS,
)
from components.sidebar import render_sidebar
from components.nav import activate_tab
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date

st.set_page_config(page_title="원재료관리 | 꽃순이김치 MES", page_icon="🥬", layout="wide")
apply_styles()
render_sidebar(current="material")

np.random.seed(42)

# ===== 공통 상수 =====
SUPPLIERS = ["충남 서산 농협", "전북 완주 농협", "강원 평창 농협", "경기 이천 농협"]
ITEMS = ["배추", "고추", "마늘", "파", "생강"]
GRADES = ["1등급", "2등급", "3등급"]
ORIGINS = {
    "충남 서산 농협": "충남 서산",
    "전북 완주 농협": "전북 완주",
    "강원 평창 농협": "강원 평창",
    "경기 이천 농협": "경기 이천",
}

# ===== Mock 데이터 생성 =====
@st.cache_data
def make_intake_data(n=15):
    rows = []
    for i in range(n):
        seq = 1 + i
        intake_date = date(2026, 5, 1) + timedelta(days=i + (i // 3))
        if intake_date > date(2026, 5, 23):
            intake_date = date(2026, 5, 23)
        supplier = SUPPLIERS[i % len(SUPPLIERS)]
        item = ITEMS[i % len(ITEMS)]
        weight = int(np.random.randint(2000, 5001))
        moisture = round(float(np.random.uniform(87, 93)), 1)
        grade = GRADES[np.random.randint(0, 3)]
        result = np.random.choice(["PASS", "PASS", "PASS", "FAIL", "대기"], p=[0.6, 0.1, 0.05, 0.1, 0.15])
        rows.append({
            "LOT_ID": f"INTAKE-2026-{500 + seq:04d}",
            "공급처": supplier,
            "입고일": intake_date.strftime("%Y-%m-%d"),
            "품목": item,
            "중량(kg)": weight,
            "함수율(%)": moisture,
            "외관등급": grade,
            "원산지": ORIGINS[supplier],
            "검사결과": result,
        })
    df = pd.DataFrame(rows)
    # LOT ID 0501~0523 형태로 정규화
    df["LOT_ID"] = [f"INTAKE-2026-{501 + i:04d}" for i in range(len(df))]
    return df


@st.cache_data
def make_sorting_data(n=10):
    rows = []
    for i in range(n):
        d = date(2026, 5, 23) - timedelta(days=i)
        invol = int(np.random.randint(2000, 5001))
        defect_rate = float(np.random.uniform(0.03, 0.15))
        defect = int(invol * defect_rate)
        good = invol - defect
        rows.append({
            "선별일": d.strftime("%Y-%m-%d"),
            "LOT ID": f"INTAKE-2026-{523 - i:04d}",
            "투입량(kg)": invol,
            "양품량(kg)": good,
            "불량량(kg)": defect,
            "선별률(%)": round(good / invol * 100, 1),
            "불량유형": np.random.choice(["부패", "이물질", "규격미달", "기타"]),
            "담당자": np.random.choice(["김선별", "이검사", "박품질"]),
        })
    return pd.DataFrame(rows)


@st.cache_data
def make_supplier_quality():
    rows = []
    for s in SUPPLIERS:
        total = int(np.random.randint(20, 60))
        pass_rate = float(np.random.uniform(0.82, 0.95))
        passed = int(total * pass_rate)
        rows.append({
            "공급처": s,
            "총 입고건수": total,
            "합격건수": passed,
            "합격률(%)": round(passed / total * 100, 1),
            "평균 외관등급": round(float(np.random.uniform(1.2, 2.5)), 1),
            "최근 입고일": (date(2026, 5, 23) - timedelta(days=int(np.random.randint(0, 6)))).strftime("%Y-%m-%d"),
            "클레임건수": int(np.random.randint(0, 5)),
        })
    return pd.DataFrame(rows)


df_intake = make_intake_data()
df_sorting = make_sorting_data()
df_supplier = make_supplier_quality()


# ===== 헤더 =====
st.markdown(
    f"""
    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
        <div><span style="font-size:24px; font-weight:700; color:#29261b;">🥬 원재료관리</span></div>
        <div style="font-size:13px; color:#7B7670;">{datetime.now().strftime('%Y-%m-%d %H:%M')} · LOT 기반 입고/이력/선별/공급처 통합관리</div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📦 입고관리", "🔎 원재료 이력조회", "🧹 선별 데이터관리", "🏢 공급처 품질분석", "🤖 입고 AI Agent"]
)
activate_tab()


# =====================================================================
# Tab 1: 입고관리
# =====================================================================
with tab1:
    section_header("오늘 입고 요약", "📦")
    m1, m2, m3 = st.columns(3)
    with m1:
        metric_card("오늘 입고 건수", "8 건", color=COLORS["accent"])
    with m2:
        metric_card("오늘 입고량", "45,200 kg", color=COLORS["celadon"])
    with m3:
        metric_card("입고 합격률", "87.5 %", color=COLORS["green"], target="≥ 85%")

    st.markdown("<br>", unsafe_allow_html=True)

    left, right = st.columns([2, 1])

    # --- 왼쪽: 최근 30일 입고 현황 ---
    with left:
        section_header("최근 30일 입고 현황", "📋")

        f1, f2, f3 = st.columns([1.4, 1, 1])
        with f1:
            date_range = st.date_input(
                "입고일 범위",
                value=(date(2026, 5, 1), date(2026, 5, 23)),
                key="intake_date_range",
            )
        with f2:
            sel_supplier = st.selectbox("공급처", ["전체"] + SUPPLIERS, key="intake_f_supplier")
        with f3:
            sel_item = st.selectbox("품목", ["전체"] + ITEMS, key="intake_f_item")

        df_view = df_intake.copy()
        # 날짜 필터
        if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
            d_from, d_to = date_range
            df_view = df_view[
                (pd.to_datetime(df_view["입고일"]).dt.date >= d_from)
                & (pd.to_datetime(df_view["입고일"]).dt.date <= d_to)
            ]
        if sel_supplier != "전체":
            df_view = df_view[df_view["공급처"] == sel_supplier]
        if sel_item != "전체":
            df_view = df_view[df_view["품목"] == sel_item]

        # 검사결과 배지 컬럼 (HTML 테이블로 표시)
        def _row_html(r):
            badge = status_badge(r["검사결과"])
            return (
                f"<tr>"
                f"<td>{r['LOT_ID']}</td><td>{r['공급처']}</td><td>{r['입고일']}</td>"
                f"<td>{r['품목']}</td><td style='text-align:right'>{r['중량(kg)']:,}</td>"
                f"<td style='text-align:right'>{r['함수율(%)']}</td><td>{r['외관등급']}</td>"
                f"<td>{r['원산지']}</td><td>{badge}</td>"
                f"</tr>"
            )

        if len(df_view) == 0:
            st.info("선택한 조건에 해당하는 입고 데이터가 없습니다.")
        else:
            header = (
                "<tr style='color:#C53D2E;'>"
                "<th>LOT_ID</th><th>공급처</th><th>입고일</th><th>품목</th>"
                "<th>중량(kg)</th><th>함수율(%)</th><th>외관등급</th><th>원산지</th><th>검사결과</th>"
                "</tr>"
            )
            body = "".join(_row_html(r) for _, r in df_view.iterrows())
            table_html = (
                "<div class='mes-card' style='overflow-x:auto;'>"
                "<table style='width:100%; border-collapse:collapse; font-size:12.5px; color:#29261b;'>"
                f"<thead>{header}</thead><tbody>{body}</tbody></table></div>"
            )
            st.markdown(
                "<style>.mes-card table th, .mes-card table td{padding:7px 8px; border-bottom:1px solid rgba(0,0,0,.06); text-align:left;}</style>"
                + table_html,
                unsafe_allow_html=True,
            )
            st.caption(f"총 {len(df_view)} 건 표시 중")

    # --- 오른쪽: 새 입고 등록 폼 ---
    with right:
        section_header("새 입고 등록", "➕")
        st.markdown('<div class="mes-card">', unsafe_allow_html=True)
        with st.form("intake_register", clear_on_submit=False):
            auto_lot = st.checkbox("LOT ID 자동생성", value=True)
            if auto_lot:
                new_lot = f"INTAKE-2026-{524:04d}"
                st.text_input("LOT ID", value=new_lot, disabled=True)
            else:
                new_lot = st.text_input("LOT ID", placeholder="INTAKE-2026-XXXX")
            in_supplier = st.selectbox("공급처", SUPPLIERS, key="reg_supplier")
            in_date = st.date_input("입고일", value=date(2026, 5, 23), key="reg_date")
            in_item = st.selectbox("품목", ITEMS, key="reg_item")
            in_weight = st.number_input("중량 (kg)", min_value=0, max_value=20000, value=3000, step=100)
            in_moisture = st.number_input("함수율 (%)", min_value=0.0, max_value=100.0, value=89.0, step=0.1)
            in_grade = st.selectbox("외관등급", GRADES, key="reg_grade")
            in_origin = st.text_input("원산지", value=ORIGINS[SUPPLIERS[0]])
            submitted = st.form_submit_button("입고 등록", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

        if submitted:
            st.success(f"입고 등록 완료 — {new_lot} ({in_supplier} / {in_item} / {in_weight:,}kg)")


# =====================================================================
# Tab 2: 원재료 이력조회
# =====================================================================
with tab2:
    section_header("LOT 이력 조회", "🔎")
    s1, s2 = st.columns([3, 1])
    with s1:
        lot_query = st.text_input("LOT ID 검색", value="INTAKE-2026-0515", key="hist_lot")
    with s2:
        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
        do_search = st.button("조회", use_container_width=True, key="hist_search")

    # 조회 LOT 결정 (기본 INTAKE-2026-0515)
    target_lot = lot_query.strip() if lot_query.strip() else "INTAKE-2026-0515"

    # 기본 정보 (mock — 0515 기준 고정값 / 그 외는 데이터에서 탐색)
    base_row = df_intake[df_intake["LOT_ID"] == target_lot]
    if len(base_row) > 0:
        r = base_row.iloc[0]
        info = {
            "입고일": r["입고일"], "공급처": r["공급처"], "품목": r["품목"],
            "중량": f"{r['중량(kg)']:,} kg", "등급": r["외관등급"], "원산지": r["원산지"],
        }
    else:
        info = {
            "입고일": "2026-05-15", "공급처": "강원 평창 농협", "품목": "배추",
            "중량": "3,800 kg", "등급": "2등급", "원산지": "강원 평창",
        }

    st.markdown("<br>", unsafe_allow_html=True)
    section_header(f"LOT 기본 정보 — {target_lot}", "📌")
    c1, c2, c3 = st.columns(3)
    with c1:
        metric_card("입고일", info["입고일"], color=COLORS["celadon"])
    with c2:
        metric_card("공급처", info["공급처"], color=COLORS["accent"])
    with c3:
        metric_card("품목 / 중량", f"{info['품목']} · {info['중량']}", color=COLORS["green"])
    st.markdown(
        f"<div class='mes-card' style='color:#7B7670; font-size:13px;'>"
        f"외관등급: <b style='color:#29261b'>{info['등급']}</b> &nbsp;·&nbsp; "
        f"원산지: <b style='color:#29261b'>{info['원산지']}</b></div>",
        unsafe_allow_html=True,
    )

    # --- 공정 추적 타임라인 ---
    st.markdown("<br>", unsafe_allow_html=True)
    section_header("공정 추적 타임라인 (Traceability)", "🧭")

    suffix = target_lot.replace("INTAKE-2026-", "") if target_lot.startswith("INTAKE-2026-") else "0515"
    timeline = [
        ("📦 입고", f"INTAKE-2026-{suffix}", "2026-05-15 08:20", "완료"),
        ("✂️ 절임", f"SALT-2026-{suffix}", "2026-05-15 14:10", "완료"),
        ("🫙 발효", f"FERM-2026-{suffix}", "2026-05-16 09:00", "진행중"),
        ("📦 출하", f"SHIP-2026-{suffix}", "2026-05-18 10:30", "대기"),
    ]
    cols = st.columns(len(timeline) * 2 - 1)
    for idx, (label, lot, ts, status) in enumerate(timeline):
        with cols[idx * 2]:
            st.markdown(
                f"<div class='mes-card' style='text-align:center;'>"
                f"<div style='font-size:15px; color:#29261b; font-weight:600;'>{label}</div>"
                f"<div style='font-size:11px; color:#7B7670; margin:6px 0;'>{lot}</div>"
                f"<div style='margin:6px 0;'>{status_badge(status)}</div>"
                f"<div style='font-size:10.5px; color:#A8A39E;'>{ts}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        if idx < len(timeline) - 1:
            with cols[idx * 2 + 1]:
                st.markdown(
                    "<div style='text-align:center; color:#C53D2E; font-size:24px; padding-top:28px;'>→</div>",
                    unsafe_allow_html=True,
                )

    # --- 공정별 상세 데이터 ---
    st.markdown("<br>", unsafe_allow_html=True)
    section_header("공정별 상세 데이터", "📂")

    with st.expander("📦 입고 상세", expanded=False):
        st.dataframe(pd.DataFrame([{
            "항목": v, "값": k
        } for k, v in {
            info["입고일"]: "입고일", info["공급처"]: "공급처", info["품목"]: "품목",
            info["중량"]: "중량", info["등급"]: "외관등급", info["원산지"]: "원산지",
        }.items()]), use_container_width=True, hide_index=True)

    with st.expander("✂️ 절임 상세", expanded=False):
        st.dataframe(pd.DataFrame({
            "측정시각": ["14:10", "16:10", "18:10", "20:10"],
            "염도(%)": [2.1, 2.4, 2.6, 2.7],
            "온도(℃)": [12.5, 12.8, 13.1, 12.9],
            "pH": [5.9, 5.7, 5.6, 5.5],
        }), use_container_width=True, hide_index=True)

    with st.expander("🫙 발효 상세", expanded=False):
        st.dataframe(pd.DataFrame({
            "측정시각": ["D+0 09:00", "D+1 09:00", "D+2 09:00", "D+3 09:00"],
            "온도(℃)": [8.2, 7.9, 7.5, 7.3],
            "산도(%)": [0.35, 0.52, 0.71, 0.85],
            "숙성도(%)": [10, 35, 62, 80],
        }), use_container_width=True, hide_index=True)

    with st.expander("📦 출하 상세", expanded=False):
        st.dataframe(pd.DataFrame([{
            "출하LOT": f"SHIP-2026-{suffix}",
            "출하예정일": "2026-05-18",
            "검사결과": "대기",
            "출하처": "수도권 물류센터",
            "수량(kg)": 3600,
        }]), use_container_width=True, hide_index=True)


# =====================================================================
# Tab 3: 선별 데이터관리
# =====================================================================
with tab3:
    section_header("선별 결과 입력", "🧹")
    st.markdown('<div class="mes-card">', unsafe_allow_html=True)
    with st.form("sorting_form", clear_on_submit=False):
        sf1, sf2, sf3 = st.columns(3)
        with sf1:
            so_lot = st.selectbox("LOT 선택", df_intake["LOT_ID"].tolist(), key="sort_lot")
            so_date = st.date_input("선별일", value=date(2026, 5, 23), key="sort_date")
        with sf2:
            so_good = st.number_input("양품 수량 (kg)", min_value=0, max_value=20000, value=2800, step=50)
            so_defect = st.number_input("불량 수량 (kg)", min_value=0, max_value=20000, value=200, step=50)
        with sf3:
            so_type = st.selectbox("불량 유형", ["부패", "이물질", "규격미달", "기타"], key="sort_type")
            so_worker = st.text_input("선별 담당자", value="김선별")
        saved = st.form_submit_button("저장", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)
    if saved:
        total = so_good + so_defect
        rate = (so_good / total * 100) if total > 0 else 0
        st.success(f"선별 결과 저장 완료 — {so_lot} / 양품 {so_good:,}kg, 불량 {so_defect:,}kg (선별률 {rate:.1f}%)")

    st.markdown("<br>", unsafe_allow_html=True)
    section_header("선별 이력", "📋")

    df_sort_view = df_sorting.copy()
    df_sort_view["투입량(kg)"] = df_sort_view["투입량(kg)"].map("{:,}".format)
    df_sort_view["양품량(kg)"] = df_sort_view["양품량(kg)"].map("{:,}".format)
    df_sort_view["불량량(kg)"] = df_sort_view["불량량(kg)"].map("{:,}".format)
    st.dataframe(df_sort_view, use_container_width=True, hide_index=True)

    st.markdown("<br>", unsafe_allow_html=True)
    section_header("일별 선별률 추이 (최근 14일)", "📈")
    days = [(date(2026, 5, 23) - timedelta(days=13 - i)) for i in range(14)]
    rates = np.round(np.random.uniform(85, 97, 14), 1)
    fig_sort = go.Figure()
    fig_sort.add_trace(go.Bar(
        x=[d.strftime("%m-%d") for d in days],
        y=rates,
        marker_color=COLORS["celadon"],
        text=rates,
        textposition="outside",
        texttemplate="%{text}%",
    ))
    fig_sort.update_layout(
        yaxis=dict(title="선별률 (%)", range=[80, 100]),
        xaxis=dict(title="날짜"),
    )
    st.plotly_chart(style_plotly(fig_sort, height=360), use_container_width=True)


# =====================================================================
# Tab 4: 공급처 품질분석
# =====================================================================
with tab4:
    section_header("공급처별 품질 비교 (레이더)", "🎯")

    metrics = ["납품 합격률", "외관등급", "함수율 적합도", "납기 준수율", "클레임(역산)"]
    radar_colors = COLORWAY

    fig_radar = go.Figure()
    radar_seed = np.random.RandomState(7)
    for i, s in enumerate(SUPPLIERS):
        vals = list(np.round(radar_seed.uniform(70, 98, len(metrics)), 1))
        fig_radar.add_trace(go.Scatterpolar(
            r=vals + [vals[0]],
            theta=metrics + [metrics[0]],
            fill="toself",
            name=s,
            line=dict(color=radar_colors[i]),
            opacity=0.65,
        ))
    style_plotly(fig_radar, height=460)
    fig_radar.update_layout(
        polar=dict(
            bgcolor="#FFFFFF",
            radialaxis=dict(visible=True, range=[0, 100], gridcolor="rgba(0,0,0,.08)", color="#7B7670"),
            angularaxis=dict(gridcolor="rgba(0,0,0,.08)", color="#29261b"),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=-0.15),
    )
    st.plotly_chart(fig_radar, use_container_width=True)

    col_a, col_b = st.columns([1.3, 1])
    with col_a:
        section_header("공급처별 품질 이력", "📋")
        df_sup_view = df_supplier.copy()
        st.dataframe(df_sup_view, use_container_width=True, hide_index=True)
    with col_b:
        section_header("공급처별 입고 합격률", "📊")
        fig_pass = go.Figure()
        df_sorted = df_supplier.sort_values("합격률(%)")
        fig_pass.add_trace(go.Bar(
            x=df_sorted["합격률(%)"],
            y=df_sorted["공급처"],
            orientation="h",
            marker_color=[COLORS["red"] if v < 85 else COLORS["orange"] if v < 90 else COLORS["green"]
                          for v in df_sorted["합격률(%)"]],
            text=df_sorted["합격률(%)"],
            texttemplate="%{text}%",
            textposition="outside",
        ))
        fig_pass.update_layout(
            xaxis=dict(title="합격률 (%)", range=[0, 105]),
        )
        st.plotly_chart(style_plotly(fig_pass, height=340), use_container_width=True)


# =====================================================================
# Tab 5: 입고 AI Agent
# =====================================================================
with tab5:
    if "intake_chat" not in st.session_state:
        st.session_state["intake_chat"] = [
            {"role": "ai", "text": "안녕하세요. 원재료 입고 AI Agent입니다. LOT 품질 적합성, 공급처 이력, 입고 기준 등을 질의해 주세요.", "source": ""},
        ]

    MOCK_ANSWERS = {
        "INTAKE-2026-0515 LOT 품질 기준 적합 여부는?":
            ("INTAKE-2026-0515 LOT은 외관등급 2등급, 함수율 89.3%로 입고 기준(함수율 ≤92%, 외관등급 ≤3등급)에 "
             "적합합니다. 별도 재검사 없이 절임 공정 투입이 가능합니다.",
             "출처: 원재료 입고 품질기준서 v2.1, 3페이지"),
        "충남 서산 농협의 최근 3개월 품질 이력은?":
            ("충남 서산 농협은 최근 3개월간 총 38건 입고, 합격 34건(합격률 89.5%)을 기록했습니다. "
             "평균 외관등급 1.8등급, 클레임 1건(이물질)으로 우수 등급 공급처입니다.",
             "출처: 공급처 평가 이력 DB · 품질검사 이력(2026-02~05)"),
        "배추 함수율이 95% 이상일 때 처리 기준을 알려줘":
            ("배추 함수율이 95% 이상인 경우 입고 기준(≤92%)을 초과하므로 '조건부 보류'로 분류됩니다. "
             "탈수 공정 추가 또는 절임 시간 단축(기준 대비 -15%) 후 재검사하며, 재검사 불합격 시 반품 처리합니다.",
             "출처: 원재료 입고 품질기준서 v2.1, 7페이지 · 절임 기준서 v1.3"),
    }

    chat_col, info_col = st.columns([2, 1])

    with chat_col:
        section_header("입고 AI Agent 질의", "🤖")

        # 예시 질문 버튼
        st.caption("예시 질문")
        b1, b2, b3 = st.columns(3)
        clicked_q = None
        with b1:
            if st.button("LOT 품질 적합 여부", use_container_width=True, key="q1"):
                clicked_q = "INTAKE-2026-0515 LOT 품질 기준 적합 여부는?"
        with b2:
            if st.button("공급처 품질 이력", use_container_width=True, key="q2"):
                clicked_q = "충남 서산 농협의 최근 3개월 품질 이력은?"
        with b3:
            if st.button("함수율 처리 기준", use_container_width=True, key="q3"):
                clicked_q = "배추 함수율이 95% 이상일 때 처리 기준을 알려줘"

        # 직접 입력
        typed = st.chat_input("질문을 입력하세요...")
        user_q = clicked_q or typed

        if user_q:
            st.session_state["intake_chat"].append({"role": "user", "text": user_q, "source": ""})
            ans, src = MOCK_ANSWERS.get(
                user_q,
                ("해당 질의에 대한 표준문서를 검색했습니다. 관련 LOT/공급처 데이터와 품질기준서를 기반으로 "
                 "답변을 생성합니다. (데모: 등록된 예시 질문에 대해 상세 답변이 제공됩니다.)",
                 "출처: 원재료 입고 품질기준서 · 공급처 평가 이력 DB"),
            )
            st.session_state["intake_chat"].append({"role": "ai", "text": ans, "source": src})

        # 채팅 렌더링
        st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)
        for msg in st.session_state["intake_chat"]:
            if msg["role"] == "user":
                st.markdown(
                    f"<div class='chat-user'>{msg['text']}</div><div style='clear:both; margin-bottom:10px;'></div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<div class='chat-ai'>{msg['text']}</div>",
                    unsafe_allow_html=True,
                )
                if msg.get("source"):
                    st.caption(f"📄 {msg['source']}")
                st.markdown("<div style='margin-bottom:10px;'></div>", unsafe_allow_html=True)

        if st.button("대화 초기화", key="clear_chat"):
            st.session_state["intake_chat"] = [
                {"role": "ai", "text": "대화가 초기화되었습니다. 새로운 질문을 입력해 주세요.", "source": ""},
            ]
            st.rerun()

    with info_col:
        section_header("AI Agent 정보", "ℹ️")
        st.markdown(
            f"""
            <div class="mes-card">
                <div class="mes-card-title">🤖 Agent 상태</div>
                <div style="margin-bottom:10px;">{status_badge("정상")} <span style="color:#7B7670; font-size:12px;">활성</span></div>
                <div style="color:#4A4640; font-size:12.5px; line-height:1.9;">
                    <b style="color:#C53D2E;">참조 문서</b><br>
                    · 원재료 입고 품질기준서<br>
                    · 작업표준서 (SOP)<br>
                    · 공급처 평가 이력<br><br>
                    <b style="color:#C53D2E;">조회 가능 데이터</b><br>
                    · 원재료 LOT DB<br>
                    · 공급처 DB<br>
                    · 품질검사 이력
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.warning("⚠️ 파일럿 단계: AI 응답은 참고용입니다. 최종 판단은 담당자 승인이 필요합니다.")
