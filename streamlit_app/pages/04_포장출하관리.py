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

st.set_page_config(page_title="포장출하관리 | 꽃순이김치 MES", page_icon="📦", layout="wide")
apply_styles()
render_sidebar(current="shipping")

np.random.seed(42)

def style_fig(fig, height=320):
    return style_plotly(fig, height=height)


def badge_table(df: pd.DataFrame, status_col, highlight_col=None, highlight_vals=None):
    """상태 컬럼(들)을 배지 HTML로 렌더링한 테이블 출력.
    highlight_col/highlight_vals 지정 시 해당 값을 가진 행 배경 강조."""
    d = df.copy()
    cols = status_col if isinstance(status_col, (list, tuple)) else [status_col]
    raw_hl = d[highlight_col].tolist() if highlight_col else None
    for c in cols:
        d[c] = d[c].apply(status_badge)
    rows_html = ""
    headers = "".join(f"<th>{c}</th>" for c in d.columns)
    for ri in range(len(d)):
        cells = "".join(f"<td>{d.iloc[ri][c]}</td>" for c in d.columns)
        row_style = ""
        if raw_hl is not None and highlight_vals and raw_hl[ri] in highlight_vals:
            row_style = " style='background:rgba(217,122,43,.10);'"
        rows_html += f"<tr{row_style}>{cells}</tr>"
    html = f"<table class='mes-table'><thead><tr>{headers}</tr></thead><tbody>{rows_html}</tbody></table>"
    st.markdown(
        "<div class='mes-card' style='padding:0; overflow-x:auto;'>"
        "<style>.mes-table{width:100%;border-collapse:collapse;font-size:13px;color:#29261b;}"
        ".mes-table th{background:#F9F7F4;color:#C53D2E;padding:10px;text-align:left;border-bottom:1px solid rgba(0,0,0,.09);}"
        ".mes-table td{padding:9px 10px;border-bottom:1px solid rgba(0,0,0,.06);}</style>"
        + html + "</div>",
        unsafe_allow_html=True,
    )


# ===== 헤더 =====
st.markdown(
    "<div style='font-size:24px;font-weight:700;color:#29261b;margin-bottom:4px;'>📦 포장출하관리</div>"
    "<div style='font-size:13px;color:#7B7670;margin-bottom:16px;'>포장실적 · 출하승인 · LOT추적 · 검사 · 클레임 · 출하 AI Agent</div>",
    unsafe_allow_html=True,
)

# ===== 상단 KPI =====
k1, k2, k3, k4 = st.columns(4)
with k1:
    metric_card("오늘 포장 완료", "18,540 kg", color=COLORS["accent"])
with k2:
    metric_card("오늘 출하 건수", "8건", color=COLORS["celadon"])
with k3:
    metric_card("출하 승인 대기", "2건", color=COLORS["orange"])
with k4:
    metric_card("불량률", "0.92%", delta="목표 1.0% 달성", color=COLORS["green"], target="1.0% 이하")

st.markdown("<br>", unsafe_allow_html=True)

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🏷️ 포장실적관리",
    "🚛 출하관리",
    "🔗 LOT 추적",
    "🔍 검사결과관리",
    "📣 클레임분석",
    "🤖 출하 AI Agent",
])
activate_tab()

PRODUCTS = ["포기김치", "깍두기", "열무김치", "백김치"]
PRODUCT_WEIGHTS = [0.50, 0.25, 0.15, 0.10]
SPECS = ["1kg", "2kg", "5kg", "10kg", "20kg"]
WORKERS = ["김철수", "이영희", "박민수", "최지은", "정태호"]
DESTS = ["서울 마트", "경기 물류센터", "인천 냉동창고", "대전 대형마트", "부산 수산시장"]

# ===================== Tab 1: 포장실적관리 =====================
with tab1:
    section_header("포장 실적 입력", "📝")
    with st.form("pack_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            ferm_lot = st.selectbox("포장 LOT ID (발효 LOT 연계)",
                                    [f"FERM-2026-{510 + i:04d}" for i in range(10)])
            pack_dt = st.date_input("포장일시", value=date(2026, 5, 23))
            product = st.selectbox("제품유형", PRODUCTS)
        with c2:
            qty = st.number_input("포장 수량(kg)", min_value=0.0, value=3050.0, step=10.0)
            spec = st.selectbox("포장 규격", SPECS)
            worker = st.selectbox("작업자", WORKERS)
        with c3:
            defect_qty = st.number_input("불량 수량(kg)", min_value=0.0, value=20.0, step=1.0)
            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='mes-card' style='padding:10px;'>"
                f"<div style='color:#7B7670;font-size:12px;'>예상 불량률</div>"
                f"<div style='color:#4C9B52;font-size:20px;font-weight:700;'>"
                f"{(defect_qty / qty * 100 if qty else 0):.2f}%</div></div>",
                unsafe_allow_html=True,
            )
        submitted = st.form_submit_button("포장 실적 등록")
        if submitted:
            st.success(f"✅ 포장 실적 등록 완료 — {product} {qty:,.0f}kg ({spec}), 발효 LOT: {ferm_lot}")

    st.markdown("<br>", unsafe_allow_html=True)
    section_header("포장 실적 이력", "📋")

    pack_products = np.random.choice(PRODUCTS, size=15, p=PRODUCT_WEIGHTS)
    pack_rows = []
    for i in range(15):
        d = datetime(2026, 5, 23) - timedelta(days=i // 2)
        qv = int(np.random.randint(2800, 3300))
        dq = round(np.random.uniform(10, 28), 1)
        rate = round(dq / qv * 100, 2)
        pack_rows.append({
            "LOT_ID": f"PACK-2026-{180 + i:04d}",
            "포장일": d.strftime("%Y-%m-%d"),
            "제품": pack_products[i],
            "수량(kg)": qv,
            "규격": np.random.choice(SPECS),
            "불량량(kg)": dq,
            "불량률(%)": rate,
            "작업자": np.random.choice(WORKERS),
            "상태": "완료",
        })
    df_pack = pd.DataFrame(pack_rows)
    badge_table(df_pack, "상태")

    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        section_header("제품별 포장 수량", "🥧")
        prod_sum = df_pack.groupby("제품")["수량(kg)"].sum().reindex(PRODUCTS).fillna(0)
        fig = go.Figure(go.Pie(labels=prod_sum.index.tolist(), values=prod_sum.values.tolist(), hole=0.45,
                               marker=dict(colors=COLORWAY)))
        fig.update_traces(textinfo="label+percent")
        st.plotly_chart(style_fig(fig), use_container_width=True)
    with c2:
        section_header("일별 포장량", "📊")
        day_sum = df_pack.groupby("포장일")["수량(kg)"].sum().sort_index()
        fig = go.Figure(go.Bar(x=day_sum.index.tolist(), y=day_sum.values.tolist(),
                               marker_color=COLORS["accent"],
                               text=[f"{v:,.0f}" for v in day_sum.values], textposition="outside"))
        fig.update_layout(yaxis_title="포장량 (kg)")
        st.plotly_chart(style_fig(fig), use_container_width=True)

# ===================== Tab 2: 출하관리 =====================
with tab2:
    section_header("출하 승인 현황", "✅")
    ship_status = (["승인"] * 8) + (["대기"] * 2) + (["반려"] * 1) + (["승인"] * 1)
    ship_products = np.random.choice(PRODUCTS, size=12, p=PRODUCT_WEIGHTS)
    ship_rows = []
    for i in range(12):
        d = datetime(2026, 5, 23) - timedelta(days=i // 3)
        stt = ship_status[i]
        approver = "-" if stt == "대기" else np.random.choice(["품질팀장", "생산팀장", "공장장"])
        ship_time = "-" if stt != "승인" else (d + timedelta(hours=14, minutes=int(i * 7))).strftime("%H:%M")
        insp = "정상" if stt != "반려" else "불합격"
        ship_rows.append({
            "SHIP_LOT_ID": f"SHIP-2026-{310 + i:04d}",
            "출하일": d.strftime("%Y-%m-%d"),
            "제품": ship_products[i],
            "수량(kg)": int(np.random.randint(500, 3200)),
            "납품처": DESTS[i % len(DESTS)],
            "최종검사결과": insp,
            "승인상태": stt,
            "승인자": approver,
            "출하시간": ship_time,
        })
    df_ship = pd.DataFrame(ship_rows)
    badge_table(df_ship, ["승인상태"], highlight_col="승인상태", highlight_vals=["대기", "반려"])

    st.markdown("<br>", unsafe_allow_html=True)
    section_header("출하 승인 처리 (대기 건)", "🖐️")
    pending = df_ship[df_ship["승인상태"] == "대기"]
    for _, r in pending.iterrows():
        cc = st.columns([3, 1, 1])
        with cc[0]:
            st.markdown(
                f"<div class='mes-card' style='padding:10px;'>"
                f"<span style='color:#29261b;font-weight:600;'>{r['SHIP_LOT_ID']}</span> · "
                f"{r['제품']} {r['수량(kg)']:,}kg · {r['납품처']} "
                f"{status_badge('대기')}</div>",
                unsafe_allow_html=True,
            )
        with cc[1]:
            if st.button("승인", key=f"appr_{r['SHIP_LOT_ID']}"):
                st.success(f"출하 승인 완료 — {r['SHIP_LOT_ID']}")
        with cc[2]:
            if st.button("반려", key=f"rej_{r['SHIP_LOT_ID']}"):
                st.warning(f"출하 반려 처리 — {r['SHIP_LOT_ID']}")

    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2 = st.columns([1, 1])
    with c1:
        section_header("출하 승인 현황 비율", "🥧")
        sc = df_ship["승인상태"].value_counts().reindex(["승인", "대기", "반려"]).fillna(0)
        fig = go.Figure(go.Pie(labels=["승인", "대기", "반려"], values=sc.values.tolist(), hole=0.45,
                               marker=dict(colors=[COLORS["green"], COLORS["orange"], COLORS["red"]])))
        fig.update_traces(textinfo="label+value")
        st.plotly_chart(style_fig(fig), use_container_width=True)
    with c2:
        section_header("납품처별 출하량", "🚚")
        dest_sum = df_ship.groupby("납품처")["수량(kg)"].sum()
        fig = go.Figure(go.Bar(x=dest_sum.index.tolist(), y=dest_sum.values.tolist(),
                               marker_color=COLORS["celadon"],
                               text=[f"{v:,.0f}" for v in dest_sum.values], textposition="outside"))
        fig.update_layout(yaxis_title="출하량 (kg)")
        st.plotly_chart(style_fig(fig), use_container_width=True)

# ===================== Tab 3: LOT 추적 =====================
with tab3:
    section_header("전 공정 LOT 추적", "🔗")
    c1, c2 = st.columns([3, 1])
    with c1:
        track_id = st.text_input("LOT ID (INTAKE / SALT / FERM / PACK / SHIP)", value="SHIP-2026-0518")
    with c2:
        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
        do_track = st.button("추적 조회")

    # 기본 조회 (SHIP-2026-0518) 또는 입력 LOT — mock 동일 데이터 반환
    stages = [
        {"icon": "📦", "name": "원재료 입고", "lot": "INTAKE-2026-0515", "time": "2026-05-15 08:00",
         "info": "배추 3,200kg", "status": "정상"},
        {"icon": "✂️", "name": "절임 공정", "lot": "SALT-2026-0515", "time": "2026-05-15 10:30",
         "info": "3,200kg → 3,100kg", "status": "합격"},
        {"icon": "🫙", "name": "발효 공정", "lot": "FERM-2026-0515", "time": "2026-05-15 18:00",
         "info": "3,100kg", "status": "정상 (ML:정상91%)"},
        {"icon": "🏷️", "name": "포장", "lot": "PACK-2026-0518", "time": "2026-05-18 09:00",
         "info": "3,050kg 포기김치", "status": "불량0.65%"},
        {"icon": "🚛", "name": "출하", "lot": "SHIP-2026-0518", "time": "2026-05-18 14:00",
         "info": "3,050kg → 납품완료", "status": "서울마트 납품"},
    ]

    # 타임라인 시각화
    tl_html = "<div style='display:flex;align-items:stretch;gap:0;overflow-x:auto;padding:8px 0;'>"
    for i, s in enumerate(stages):
        tl_html += (
            f"<div style='flex:1;min-width:160px;background:#FFFFFF;border:1px solid rgba(0,0,0,.09);"
            f"border-radius:10px;padding:14px;text-align:center;'>"
            f"<div style='font-size:26px;'>{s['icon']}</div>"
            f"<div style='color:#C53D2E;font-weight:700;font-size:13px;margin:4px 0;'>{s['name']}</div>"
            f"<div style='color:#29261b;font-size:12px;font-weight:600;'>{s['lot']}</div>"
            f"<div style='color:#7B7670;font-size:11px;'>{s['time']}</div>"
            f"<div style='color:#29261b;font-size:12px;margin-top:6px;'>{s['info']}</div>"
            f"<div style='color:#4C9B52;font-size:11px;margin-top:4px;'>{s['status']}</div>"
            f"</div>"
        )
        if i < len(stages) - 1:
            tl_html += "<div style='display:flex;align-items:center;color:#C53D2E;font-size:22px;padding:0 4px;'>→</div>"
    tl_html += "</div>"
    st.markdown(tl_html, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    section_header("각 단계 상세 데이터", "🔎")

    details = {
        "INTAKE-2026-0515": {"공급처": "강원 평창농협", "품목": "배추", "중량": "3,200kg",
                             "외관등급": "A", "함수율": "94.2%", "원산지": "강원 평창"},
        "SALT-2026-0515": {"염도": "2.4%", "절임시간": "8.0h", "절임온도": "12.5°C",
                           "투입중량": "3,200kg", "산출중량": "3,100kg", "탈수율": "3.1%"},
        "FERM-2026-0515": {"발효온도": "18.2°C", "산도(pH)": "4.3", "숙성시간": "72h",
                           "ML예측": "정상 91%", "완료예측오차": "1.5h", "외기온습도": "16°C / 62%"},
        "PACK-2026-0518": {"제품": "포기김치", "규격": "5kg", "포장수량": "3,050kg",
                           "불량량": "19.8kg", "불량률": "0.65%", "작업자": "이영희"},
        "SHIP-2026-0518": {"납품처": "서울 마트", "출하수량": "3,050kg", "최종검사": "정상",
                           "금속검출": "미검출", "승인자": "품질팀장", "출하시간": "14:00"},
    }
    for s in stages:
        with st.expander(f"{s['icon']} {s['name']} — {s['lot']}"):
            dd = details.get(s['lot'], {})
            cols = st.columns(3)
            for idx, (k, v) in enumerate(dd.items()):
                with cols[idx % 3]:
                    st.markdown(
                        f"<div style='color:#7B7670;font-size:12px;'>{k}</div>"
                        f"<div style='color:#29261b;font-size:15px;font-weight:600;margin-bottom:8px;'>{v}</div>",
                        unsafe_allow_html=True,
                    )

# ===================== Tab 4: 검사결과관리 =====================
with tab4:
    section_header("금속검출 결과", "🧲")
    metal_rows = []
    detect_idx = 4  # 1건 검출
    for i in range(10):
        dt = datetime(2026, 5, 23, 9, 0) - timedelta(hours=i * 2)
        detected = (i == detect_idx)
        metal_rows.append({
            "검사일시": dt.strftime("%Y-%m-%d %H:%M"),
            "포장 LOT": f"PACK-2026-{180 + i:04d}",
            "제품": np.random.choice(PRODUCTS, p=PRODUCT_WEIGHTS),
            "검출여부": "검출" if detected else "미검출",
            "검출물질": "이물질(금속편)" if detected else "-",
            "처리결과": "이물질 처리완료" if detected else "정상 출고",
        })
    df_metal = pd.DataFrame(metal_rows)
    # 검출여부 컬러 강조 위해 직접 렌더 (검출=이상 배지, 미검출=정상 배지)
    df_metal_disp = df_metal.copy()
    df_metal_disp["검출여부"] = df_metal_disp["검출여부"].apply(
        lambda x: status_badge("이상") if x == "검출" else status_badge("정상"))
    _hl = df_metal["검출여부"].tolist()
    rows_html = ""
    for ri in range(len(df_metal_disp)):
        cells = "".join(f"<td>{df_metal_disp.iloc[ri][c]}</td>" for c in df_metal_disp.columns)
        rs = " style='background:rgba(197,61,46,.10);'" if _hl[ri] == "검출" else ""
        rows_html += f"<tr{rs}>{cells}</tr>"
    headers = "".join(f"<th>{c}</th>" for c in df_metal_disp.columns)
    st.markdown(
        "<div class='mes-card' style='padding:0; overflow-x:auto;'>"
        "<style>.mes-table{width:100%;border-collapse:collapse;font-size:13px;color:#29261b;}"
        ".mes-table th{background:#F9F7F4;color:#C53D2E;padding:10px;text-align:left;border-bottom:1px solid rgba(0,0,0,.09);}"
        ".mes-table td{padding:9px 10px;border-bottom:1px solid rgba(0,0,0,.06);}</style>"
        f"<table class='mes-table'><thead><tr>{headers}</tr></thead><tbody>{rows_html}</tbody></table></div>",
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)
    section_header("중량검사 결과", "⚖️")
    spec_weight = {"1kg": 1.0, "2kg": 2.0, "5kg": 5.0, "10kg": 10.0, "20kg": 20.0}
    weight_rows = []
    for i in range(10):
        dt = datetime(2026, 5, 23, 9, 0) - timedelta(hours=i * 2)
        sp = np.random.choice(SPECS)
        std_w = spec_weight[sp]
        meas = round(std_w * np.random.uniform(0.985, 1.02), 3)
        err = round((meas - std_w) / std_w * 100, 2)
        passed = abs(err) <= 2.0
        weight_rows.append({
            "검사일시": dt.strftime("%Y-%m-%d %H:%M"),
            "포장 LOT": f"PACK-2026-{180 + i:04d}",
            "제품 규격": sp,
            "기준중량(kg)": std_w,
            "측정중량(kg)": meas,
            "오차율(%)": err,
            "합격여부": "PASS" if passed else "FAIL",
        })
    df_weight = pd.DataFrame(weight_rows)
    badge_table(df_weight, ["합격여부"], highlight_col="합격여부", highlight_vals=["FAIL"])

    st.markdown("<br>", unsafe_allow_html=True)
    section_header("일별 검사 합격률 (최근 14일)", "📈")
    days = [(datetime(2026, 5, 23) - timedelta(days=13 - i)).strftime("%m-%d") for i in range(14)]
    pass_rate = np.round(np.clip(np.random.normal(98.8, 0.8, 14), 97.0, 100.0), 1)
    fig = go.Figure(go.Scatter(x=days, y=pass_rate, mode="lines+markers",
                               line=dict(color=COLORS["green"], width=2), marker=dict(size=6)))
    fig.add_hline(y=99.0, line_dash="dash", line_color=COLORS["celadon"],
                  annotation_text="목표 99%", annotation_font_color=COLORS["celadon"])
    fig.update_layout(yaxis_title="합격률 (%)", yaxis_range=[96, 101])
    st.plotly_chart(style_fig(fig), use_container_width=True)

# ===================== Tab 5: 클레임분석 =====================
with tab5:
    c1, c2, c3 = st.columns(3)
    with c1:
        metric_card("이번 달 클레임", "5건", color=COLORS["orange"])
    with c2:
        metric_card("전월 대비", "-37.5%", delta="감소 추세", color=COLORS["green"])
    with c3:
        metric_card("주요 원인", "포장불량", color=COLORS["celadon"])

    st.markdown("<br>", unsafe_allow_html=True)
    section_header("클레임 목록", "📋")
    causes = (["포장불량"] * 3) + (["중량미달"] * 1) + (["품질이상"] * 1) + \
             list(np.random.choice(["포장불량", "중량미달", "품질이상"], 5))
    contents = {
        "포장불량": "포장 밀봉 불량 / 누액 발생",
        "중량미달": "표기 중량 대비 미달",
        "품질이상": "조기 산패 / 이취 발생",
    }
    statuses = ["처리완료", "처리완료", "처리중", "처리완료", "접수", "처리완료",
                "처리중", "처리완료", "접수", "처리완료"]
    claim_rows = []
    for i in range(10):
        d = datetime(2026, 5, 23) - timedelta(days=i * 2)
        cause = causes[i]
        comp = 0 if statuses[i] == "접수" else int(np.random.choice([0, 30000, 50000, 80000, 120000]))
        claim_rows.append({
            "접수일": d.strftime("%Y-%m-%d"),
            "클레임 ID": f"CLM-2026-{52 - i:04d}",
            "납품처": DESTS[i % len(DESTS)],
            "제품": np.random.choice(PRODUCTS, p=PRODUCT_WEIGHTS),
            "LOT_ID": f"FERM-2026-{510 + (i % 10):04d}",
            "클레임 내용": contents[cause],
            "원인": cause,
            "처리상태": statuses[i],
            "보상금액(원)": f"{comp:,}",
        })
    df_claim = pd.DataFrame(claim_rows)
    st.dataframe(df_claim, use_container_width=True, hide_index=True)

    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        section_header("클레임 원인 분포", "🥧")
        cause_cnt = df_claim["원인"].value_counts()
        fig = go.Figure(go.Pie(labels=cause_cnt.index.tolist(), values=cause_cnt.values.tolist(), hole=0.45,
                               marker=dict(colors=[COLORS["orange"], COLORS["red"], COLORS["celadon"]])))
        fig.update_traces(textinfo="label+value")
        st.plotly_chart(style_fig(fig), use_container_width=True)
    with c2:
        section_header("월별 클레임 건수", "📊")
        months = ["1월", "2월", "3월", "4월", "5월"]
        m_cnt = [12, 10, 9, 8, 5]
        fig = go.Figure(go.Bar(x=months, y=m_cnt, marker_color=COLORS["red"],
                               text=m_cnt, textposition="outside"))
        fig.update_layout(yaxis_title="클레임 건수")
        st.plotly_chart(style_fig(fig), use_container_width=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class="mes-card" style="border-left:4px solid #3F8C9C;">
            <div class="mes-card-title">🤖 AI 클레임 원인 분석 결과</div>
            <div style="color:#29261b;font-size:13px;line-height:1.9;">
                <b>클레임 CLM-2026-0052: 포장 불량</b> → 발효 LOT <b>FERM-2026-0510</b> 추적 결과<br>
                • 해당 LOT 염도 <span style="color:#D97A2B;">2.8% (기준 초과)</span> → 조기 산화 가능성<br>
                • 포장 후 냉장 이송 지연 <span style="color:#D97A2B;">(3.5시간)</span> → 온도 상승<br>
                • <b style="color:#4C9B52;">권고사항:</b> 포장~이송 간격 2시간 이내 유지
            </div>
            <div class="chat-source" style="margin-top:10px;">
                출처: 클레임 대응 매뉴얼 v1.3, 품질기준서 §4.2
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ===================== Tab 6: 출하 AI Agent =====================
with tab6:
    if "shipping_chat" not in st.session_state:
        st.session_state["shipping_chat"] = [
            {"role": "ai", "text": "안녕하세요. 출하 AI Agent입니다. 출하 승인 기준, LOT 추적, 클레임 원인 분석을 도와드립니다.",
             "source": ""},
        ]

    ANSWERS = {
        "q1": {
            "text": "SHIP-2026-0518 LOT은 최종 품질검사 정상(ML 예측: 정상 91%), 불량률 0.65%(기준: ≤1.0%), "
                    "금속검출 미검출로 출하 승인 기준에 적합합니다.",
            "source": "출처: 출하 품질기준서 v2.0, §3.1",
        },
        "q2": {
            "text": "CLM-2026-0052(포장 불량)는 발효 LOT FERM-2026-0510 추적 결과, 염도 2.8%(기준 초과)에 따른 "
                    "조기 산화 및 포장 후 냉장 이송 지연(3.5시간)이 복합 원인입니다. 포장~이송 간격을 2시간 이내로 "
                    "유지할 것을 권고합니다.",
            "source": "출처: 클레임 대응 매뉴얼 v1.3, 품질기준서 §4.2",
        },
        "q3": {
            "text": "이번 주 출하 가능 LOT: PACK-2026-0185(포기김치, 불량 0.58%), PACK-2026-0187(깍두기, 불량 0.72%), "
                    "PACK-2026-0190(백김치, 불량 0.61%) — 3건 모두 최종검사 정상, 금속검출 미검출로 출하 가능합니다. "
                    "PACK-2026-0188(중량검사 FAIL)은 재검사 필요합니다.",
            "source": "출처: 포장 실적 DB, 출하 품질기준서 v2.0",
        },
    }

    col_chat, col_info = st.columns([2, 1])

    with col_chat:
        section_header("출하 AI Agent 채팅", "💬")

        st.markdown("<div style='color:#7B7670;font-size:12px;margin-bottom:6px;'>예시 질문</div>",
                    unsafe_allow_html=True)
        b1, b2, b3 = st.columns(3)
        clicked = None
        with b1:
            if st.button("SHIP-2026-0518의 출하 승인 기준 적합 여부는?", key="qbtn1"):
                clicked = ("SHIP-2026-0518의 출하 승인 기준 적합 여부는?", "q1")
        with b2:
            if st.button("CLM-2026-0052 클레임 원인 분석 결과를 알려줘", key="qbtn2"):
                clicked = ("CLM-2026-0052 클레임 원인 분석 결과를 알려줘", "q2")
        with b3:
            if st.button("이번 주 출하 가능한 LOT 목록을 알려줘", key="qbtn3"):
                clicked = ("이번 주 출하 가능한 LOT 목록을 알려줘", "q3")

        if clicked:
            q_text, q_key = clicked
            st.session_state["shipping_chat"].append({"role": "user", "text": q_text, "source": ""})
            ans = ANSWERS[q_key]
            st.session_state["shipping_chat"].append(
                {"role": "ai", "text": ans["text"], "source": ans["source"]})

        # 직접 입력
        user_q = st.chat_input("질문을 입력하세요...")
        if user_q:
            st.session_state["shipping_chat"].append({"role": "user", "text": user_q, "source": ""})
            st.session_state["shipping_chat"].append({
                "role": "ai",
                "text": "해당 질문은 출하 품질기준서 및 클레임 대응 매뉴얼을 참조하여 분석합니다. "
                        "(파일럿 단계: 정확한 LOT 정보와 함께 운영자 최종 확인이 필요합니다.)",
                "source": "출처: 출하 품질기준서 v2.0",
            })

        st.markdown("<br>", unsafe_allow_html=True)
        for msg in st.session_state["shipping_chat"]:
            if msg["role"] == "user":
                st.markdown(f"<div class='chat-user'>{msg['text']}</div>", unsafe_allow_html=True)
            else:
                src = f"<div class='chat-source'>{msg['source']}</div>" if msg["source"] else ""
                st.markdown(f"<div class='chat-ai'>{msg['text']}{src}</div>", unsafe_allow_html=True)
            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    with col_info:
        section_header("Agent 정보", "ℹ️")
        st.markdown(
            """
            <div class="mes-card">
                <div style="color:#4A4640;font-size:13px;line-height:2.1;">
                    <div>Agent 상태: <span class="badge-ok">● 활성</span></div>
                    <div style="margin-top:8px;">참조 문서:</div>
                    <div style="color:#29261b;">• 품질표준서</div>
                    <div style="color:#29261b;">• 클레임 대응 매뉴얼</div>
                    <div style="color:#29261b;">• 출하 승인 데이터</div>
                </div>
            </div>
            <div class="mes-card" style="border-left:4px solid #D97A2B;">
                <div style="color:#D97A2B;font-size:13px;font-weight:600;">
                    ⚠️ 파일럿 단계
                </div>
                <div style="color:#7B7670;font-size:12px;margin-top:6px;line-height:1.7;">
                    AI Agent의 분석·추천 결과는 운영자 최종 확인 후 적용됩니다.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
