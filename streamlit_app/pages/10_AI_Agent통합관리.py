import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from components.styles import (
    apply_styles, metric_card, status_badge, section_header,
    style_plotly, COLORWAY, COLORS,
)
from components.sidebar import render_sidebar
from components.nav import activate_tab
from utils.auth_helper import check_login
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

st.set_page_config(page_title="AI Agent 통합관리 | 꽃순이김치 MES", page_icon="🤖", layout="wide")
apply_styles()
render_sidebar(current="agent")
check_login()

np.random.seed(42)

# ===== 헤더 =====
st.markdown(
    "<div style='font-size:24px;font-weight:700;color:#29261b;margin-bottom:4px;'>🤖 AI Agent 통합관리</div>"
    "<div style='font-size:13px;color:#7B7670;margin-bottom:16px;'>통합 AI 질의 · 생산/품질 분석 · 의사결정 지원</div>",
    unsafe_allow_html=True,
)

# 세션 상태
if "ai_history" not in st.session_state:
    st.session_state["ai_history"] = []

# Mock AI 응답 사전 (출처 포함)
MOCK_ANSWERS = {
    "오늘 입고된 배추의 품질 기준 적합 여부는?": {
        "answer": (
            "오늘 입고된 배추 LOT 3건(IN-2026-0521~0523)을 검토한 결과, **2건은 입고 기준에 적합**하며 "
            "1건(IN-2026-0522)은 **함수율 94.2%로 기준(92% 이하)을 초과**하여 주의가 필요합니다.\n\n"
            "- IN-2026-0521 (강원 평창산): 중량 2.1kg, 외관 A등급, 함수율 91.3% → 적합 ✅\n"
            "- IN-2026-0522 (충북 음성산): 중량 1.9kg, 외관 B등급, 함수율 94.2% → 주의 ⚠️\n"
            "- IN-2026-0523 (강원 평창산): 중량 2.3kg, 외관 A등급, 함수율 90.8% → 적합 ✅\n\n"
            "함수율 초과 LOT는 탈수 공정 시간을 +15% 조정할 것을 권장합니다."
        ),
        "source": "출처: 원재료 LOT DB, 품질기준서 v2.3, 공급처 평가이력",
    },
    "FERM-2026-0523 LOT의 이상발효 원인은?": {
        "answer": (
            "FERM-2026-0523의 이상발효 주요 원인은 **발효 온도 상승(24.1°C, 정상범위 17~20°C)**으로 분석됩니다.\n\n"
            "SHAP 기여도 분석:\n"
            "- 발효 온도: +0.42 (가장 큰 영향)\n"
            "- 산도 급상승(0.61): +0.31\n"
            "- 절임 염도 편차: +0.12\n\n"
            "온도 상승으로 산패가 가속화되어 산도가 기준치를 초과했습니다. "
            "**즉시 냉각(목표 18°C) 및 발효 조기 종료**를 권장하며, 해당 LOT는 품질담당 검수 후 처리하십시오."
        ),
        "source": "출처: 발효 공정 시계열 DB, ML 엔진(XGBoost+SHAP), 발효 기준서",
    },
    "이번 주 출하 가능한 LOT 목록을 알려줘": {
        "answer": (
            "이번 주(2026-05-19~05-23) 출하 승인 기준을 충족한 LOT는 **6건**입니다.\n\n"
            "- LOT-2026-0510 (배추김치): 품질 정상, 금속검출 PASS → 출하 가능 ✅\n"
            "- LOT-2026-0511 (포기김치): 품질 정상, 금속검출 PASS → 출하 가능 ✅\n"
            "- LOT-2026-0513 (묵은지): 품질 정상 → 출하 가능 ✅\n"
            "- LOT-2026-0515 (백김치): 품질 정상 → 출하 가능 ✅\n"
            "- LOT-2026-0517 (총각김치): 품질 정상 → 출하 가능 ✅\n"
            "- LOT-2026-0519 (배추김치): 품질 정상 → 출하 가능 ✅\n\n"
            "LOT-2026-0512는 중량 검사 대기 중이며, LOT-2026-0518은 발효 미완료로 출하 보류 상태입니다."
        ),
        "source": "출처: 출하 승인 데이터, 품질표준서, LOT 추적 DB",
    },
}
DEFAULT_ANSWER = {
    "answer": (
        "질의를 분석했습니다. 현재 파일럿 검증 단계로, 사전 정의된 질문에 대해 상세 답변을 제공합니다. "
        "예시 질문 버튼을 활용하시거나, 입고/발효/출하 관련 LOT ID를 포함하여 질의해 주세요. "
        "AI Agent의 모든 분석 결과는 담당자 승인 후 생산 계획에 반영됩니다."
    ),
    "source": "출처: RAG Agent (LangChain/LangGraph) · pgvector 표준문서 검색",
}


def push_chat(agent: str, question: str):
    ans = MOCK_ANSWERS.get(question, DEFAULT_ANSWER)
    st.session_state["ai_history"].append({"role": "user", "content": question, "agent": agent})
    st.session_state["ai_history"].append({
        "role": "ai", "content": ans["answer"], "source": ans["source"], "agent": agent,
    })


tab1, tab2, tab3 = st.tabs(["💬 통합 AI 질의", "📊 생산/품질 분석", "🔔 알림 및 추천"])
activate_tab()

# ===================== Tab 1: 통합 AI 질의 =====================
with tab1:
    c_top1, c_top2 = st.columns([1, 2])
    with c_top1:
        agent = st.selectbox("에이전트 선택",
                             ["원재료 입고 Agent", "포장·출하 Agent", "통합 분석 Agent"])
    with c_top2:
        st.markdown(
            f"<div style='padding-top:28px;color:#7B7670;font-size:13px;'>"
            f"현재 에이전트: <span style='color:#C53D2E;font-weight:600;'>{agent}</span> · "
            f"데이터 소스: LOT DB + pgvector 표준문서</div>",
            unsafe_allow_html=True,
        )

    section_header("예시 질문", "💡")
    e1, e2, e3 = st.columns(3)
    examples = list(MOCK_ANSWERS.keys())
    with e1:
        if st.button(examples[0], use_container_width=True):
            push_chat(agent, examples[0]); st.rerun()
    with e2:
        if st.button(examples[1], use_container_width=True):
            push_chat(agent, examples[1]); st.rerun()
    with e3:
        if st.button(examples[2], use_container_width=True):
            push_chat(agent, examples[2]); st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    section_header("대화 내역", "💬")

    if not st.session_state["ai_history"]:
        st.markdown(
            "<div class='mes-card' style='text-align:center;color:#A8A39E;'>"
            "질문을 입력하거나 예시 질문 버튼을 눌러 AI Agent와 대화를 시작하세요.</div>",
            unsafe_allow_html=True,
        )
    else:
        for msg in st.session_state["ai_history"]:
            if msg["role"] == "user":
                st.markdown(
                    f"<div class='chat-user'>{msg['content']}</div>",
                    unsafe_allow_html=True,
                )
            else:
                body = msg["content"].replace("\n", "<br>")
                st.markdown(
                    f"<div class='chat-ai'>{body}"
                    f"<div class='chat-source'>{msg.get('source','')}</div></div>",
                    unsafe_allow_html=True,
                )
        st.markdown("<br>", unsafe_allow_html=True)

    # 자유 질의 입력
    with st.form("ai_query_form", clear_on_submit=True):
        q_col, b_col = st.columns([4, 1])
        with q_col:
            user_q = st.text_input("질문 입력", placeholder="질문을 입력하세요...", label_visibility="collapsed")
        with b_col:
            sent = st.form_submit_button("전송", use_container_width=True)
        if sent and user_q.strip():
            push_chat(agent, user_q.strip())
            st.rerun()

    if st.session_state["ai_history"]:
        if st.button("🗑️ 대화 초기화"):
            st.session_state["ai_history"] = []
            st.rerun()

# ===================== Tab 2: 생산/품질 분석 =====================
with tab2:
    section_header("이번 주 AI 분석 리포트", "📊")
    st.caption("분석 기간: 2026-05-19 ~ 2026-05-23 · RAG + ML 엔진 통합 분석")

    insights = [
        {
            "icon": "🌡️", "title": "발효 품질 개선 요인 분석",
            "color": "#4C9B52",
            "body": (
                "발효 온도를 17~19°C 범위로 유지한 LOT의 품질 정상률이 <b>94.2%</b>로, "
                "20°C 초과 LOT(81.5%) 대비 12.7%p 높았습니다. SHAP 분석 결과 발효 온도가 "
                "품질 결정에 가장 큰 기여(0.38)를 했습니다.<br><br>"
                "<b>추천:</b> 발효실 목표 온도를 18°C ± 1°C로 표준화하면 정상률 추가 향상이 예상됩니다."
            ),
        },
        {
            "icon": "⚠️", "title": "이상발효 패턴 분석",
            "color": "#D97A2B",
            "body": (
                "최근 7일간 이상발효 3건 중 <b>2건이 외기온 25°C 초과</b> 시간대(오후 1~3시)에 발생했습니다. "
                "외기 온습도와 발효실 온도 상승 간 상관계수 0.71로 높은 연관성을 확인했습니다.<br><br>"
                "<b>추천:</b> 고온 시간대 냉각 시스템 선제 가동 및 외기 연동 알림 강화가 필요합니다."
            ),
        },
        {
            "icon": "📈", "title": "생산량 최적화 추천",
            "color": "#C53D2E",
            "body": (
                "현재 시간당 생산량 3,024kg으로 목표(3,000kg)를 달성 중이나, "
                "<b>탈수 공정 가동률(86%)이 병목</b>으로 분석됩니다. 탈수 시간 표준 최적화 시 "
                "시간당 약 80kg 추가 생산이 가능할 것으로 예측됩니다.<br><br>"
                "<b>추천:</b> 함수율 기반 탈수 시간 동적 조정 도입을 검토하십시오."
            ),
        },
    ]
    for ins in insights:
        st.markdown(
            f"""
            <div class="mes-card" style="border-left:4px solid {ins['color']};">
                <div class="mes-card-title" style="color:{ins['color']};">{ins['icon']} {ins['title']}</div>
                <div style="color:#4A4640;font-size:13px;line-height:1.7;">{ins['body']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

# ===================== Tab 3: 알림 및 추천 =====================
with tab3:
    section_header("알림 목록", "🔔")
    alerts = [
        {"발생시간": "2026-05-23 10:42", "유형": "이상발효", "내용": "FERM-2026-0523 온도 24.1°C 초과 / 산도 0.61 이상", "심각도": "이상", "처리상태": "대기"},
        {"발생시간": "2026-05-23 09:15", "유형": "고온경보", "내용": "FERM-2026-0521 발효 온도 21.3°C 주의 구간 진입", "심각도": "주의", "처리상태": "진행중"},
        {"발생시간": "2026-05-23 08:30", "유형": "입고품질", "내용": "IN-2026-0522 배추 함수율 94.2% 기준 초과", "심각도": "주의", "처리상태": "완료"},
        {"발생시간": "2026-05-23 07:50", "유형": "출하반려", "내용": "SHIP-2026-0306 중량 검사 미달로 반려", "심각도": "이상", "처리상태": "완료"},
        {"발생시간": "2026-05-22 16:20", "유형": "가동률", "내용": "탈수 공정 가동률 86%로 병목 발생", "심각도": "주의", "처리상태": "완료"},
        {"발생시간": "2026-05-22 14:05", "유형": "정상", "내용": "LOT-2026-0517 발효 완료 (품질 정상)", "심각도": "정상", "처리상태": "완료"},
    ]
    df_alert = pd.DataFrame(alerts)
    df_alert["심각도"] = df_alert["심각도"].apply(status_badge)
    df_alert["처리상태"] = df_alert["처리상태"].apply(status_badge)
    st.markdown(
        "<div class='mes-card' style='padding:0;overflow-x:auto;'>"
        "<style>.alert-tbl{width:100%;border-collapse:collapse;font-size:13px;color:#29261b;}"
        ".alert-tbl th{background:#F9F7F4;color:#C53D2E;padding:10px;text-align:left;border-bottom:1px solid rgba(0,0,0,.09);}"
        ".alert-tbl td{padding:9px 10px;border-bottom:1px solid rgba(0,0,0,.06);}</style>"
        + df_alert.to_html(escape=False, index=False, classes="alert-tbl") + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)
    section_header("시스템 추천 사항", "💡")
    recs = [
        {"icon": "🌡️", "color": "#C53D2E", "title": "절임 온도 조정",
         "body": "최근 절임 공정 온도가 평균 12.3°C로 권장(10~11°C)보다 높습니다. 절임 온도를 1.5°C 낮추면 염도 균일도 향상 및 발효 안정성 개선이 예상됩니다."},
        {"icon": "⏱️", "color": "#4C9B52", "title": "발효 시간 단축",
         "body": "LSTM 완료 예측 결과, FERM-2026-0520은 잔여 14.2h이나 현 진행률 기준 12.5h에 목표 산도 도달이 예측됩니다. 약 1.7h 조기 종료로 생산 회전율을 높일 수 있습니다."},
        {"icon": "❄️", "color": "#D97A2B", "title": "고온 시간대 냉각 선제 가동",
         "body": "외기온 상승이 예보된 오후 1~3시에 발효실 냉각을 선제 가동하면 이상발효 발생률을 약 40% 저감할 수 있을 것으로 분석됩니다."},
    ]
    rc = st.columns(3)
    for i, r in enumerate(recs):
        with rc[i]:
            st.markdown(
                f"""
                <div class="mes-card" style="border-top:3px solid {r['color']};height:100%;">
                    <div class="mes-card-title" style="color:{r['color']};">{r['icon']} {r['title']}</div>
                    <div style="color:#4A4640;font-size:13px;line-height:1.7;">{r['body']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.info("ℹ️ 모든 AI 추천 사항은 **담당자 승인 후** 생산 계획에 반영됩니다. (파일럿 검증 단계)")
