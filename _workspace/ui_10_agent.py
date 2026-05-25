"""
꽃순이김치 제조AI 스마트공장 MES — AI Agent 통합관리 화면 (Streamlit)
프로젝트: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션

화면(기획서 7장 / 목업 AI Agent 통합관리 기준):
  탭1 통합 AI 질의   : Agent 유형 선택 + Chat UI(st.chat_message/st.chat_input)
                       + 예시 질문 + 참조 문서 expander + 만족도 평가
  탭2 생산/품질 분석 : 미처리 추천 목록(우선순위 뱃지) + 처리 버튼 + 유형 분포 Pie
  탭3 의사결정 지원  : 승인 대기(is_approved=NULL) 목록 + 승인/거절(MANAGER↑) + 승인 이력
  탭4 알림 및 추천   : @st.fragment(run_every=60) 자동갱신
                       — 고우선순위 추천 카드 + AI 컴포넌트 상태 + 문서 인덱스 현황
  탭5 사용자 질문이력: 질의 이력 table(필터) + 만족도 평균 metric
                       + 자주 묻는 질문 TOP5 + 질의 상세 expander

API 연동: FastAPI /api/v1/agent.
모든 API 호출은 try/except 로 감싸 실패 시 안내 메시지를 표시한다.

⚠️ RAG stub 운영 중 — 화면 상단에 "AI Agent 연동 테스트 모드" 안내를 노출한다.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import httpx
import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------
# 설정 / 상수
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="AI Agent 통합관리 | 꽃순이김치 MES",
    page_icon="🤖",
    layout="wide",
)

API_BASE_AGENT = "http://localhost:8000/api/v1/agent"

# Agent 타입별 아이콘/색상/라벨 일관성
AGENT_META: dict[str, dict[str, str]] = {
    "INTAKE":     {"icon": "🥬", "label": "원재료 입고", "color": "#2e7d32"},
    "SHIPPING":   {"icon": "📦", "label": "포장·출하",   "color": "#1565c0"},
    "INTEGRATED": {"icon": "🤖", "label": "통합 질의",   "color": "#6a1b9a"},
}

PRIORITY_BADGE = {
    "CRITICAL": "🔴 CRITICAL",
    "HIGH":     "🟠 HIGH",
    "NORMAL":   "🟡 NORMAL",
    "LOW":      "⚪ LOW",
}

STATUS_BADGE = {
    "ONLINE":   "🟢 ONLINE",
    "OFFLINE":  "🔴 OFFLINE",
    "ERROR":    "🟠 ERROR",
    "DEGRADED": "🟡 DEGRADED",
}

COMPONENT_LABEL = {
    "INTAKE_AGENT":   "🥬 입고 Agent",
    "SHIPPING_AGENT": "📦 출하 Agent",
    "ML_ENGINE":      "🧠 ML 엔진",
    "VECTOR_DB":      "📚 Vector DB",
}

REC_TYPE_LABEL = {
    "QUALITY_ALERT":      "품질 경고",
    "OPTIMAL_CONDITION":  "최적 조건 추천",
    "SUPPLIER_EVAL":      "공급처 평가",
    "SHIPPING_APPROVAL":  "출하 승인",
    "CLAIM_ANALYSIS":     "클레임 분석",
}

EXAMPLE_QUERIES = {
    "INTAKE": [
        "강원농산 최근 입고 배추의 품질 이력을 알려줘",
        "배추 입고 시 외관등급 판정 기준이 뭐야?",
        "이번 주 입고 기준 미달 LOT이 있어?",
    ],
    "SHIPPING": [
        "출하LOT SH-20260523-011 출하 승인 가능한지 검토해줘",
        "최근 클레임 중 식감 불량 원인 분석해줘",
        "출하 승인 기준에서 pH 허용 범위가 어떻게 돼?",
    ],
    "INTEGRATED": [
        "오늘 발효 진행 중인 LOT 중 이상발효 위험이 있는 건이 있어?",
        "이번 주 생산성 KPI 달성률은?",
        "불량률이 높은 공정 구간을 분석해줘",
    ],
}

# 현재 사용자 역할(운영 시 로그인 세션에서 주입). 데모: MANAGER.
CURRENT_ROLE = st.session_state.setdefault("current_role", "MANAGER")
CURRENT_USER = st.session_state.setdefault("current_user", "manager01")


# ---------------------------------------------------------------------
# API 클라이언트
# ---------------------------------------------------------------------
def _client() -> httpx.Client:
    return httpx.Client(base_url=API_BASE_AGENT, timeout=60.0)


def api_get(path: str, params: dict | None = None) -> Any:
    try:
        r = _client().get(path, params=params or {})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.warning(f"조회 실패 ({path}): {e}")
        return None


def api_send(method: str, path: str, json: dict | None = None) -> Any:
    try:
        r = _client().request(method, path, json=json)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"요청 실패 ({method} {path}): {e}")
        return None


def can_approve() -> bool:
    """의사결정 승인 권한 (MANAGER / ADMIN)."""
    return CURRENT_ROLE in ("MANAGER", "ADMIN")


def fmt_ts(value: Any) -> str:
    """ISO 타임스탬프를 'YYYY-MM-DD HH:MM' 로 축약."""
    if not value:
        return "-"
    s = str(value).replace("T", " ")
    return s[:16]


# ---------------------------------------------------------------------
# 헤더 + 테스트 모드 안내
# ---------------------------------------------------------------------
st.title("🤖 AI Agent 통합관리")
st.caption("통합 AI 질의 · 생산/품질 분석 · 의사결정 지원 · 알림/추천 · 질문이력")
st.info(
    "🧪 **AI Agent 연동 테스트 모드** — 현재 응답은 RAG stub(규칙형)입니다. "
    "실제 LangChain/LangGraph Agent 연동 후 자연어 응답으로 대체됩니다.",
    icon="🧪",
)

tab_chat, tab_analysis, tab_decision, tab_alert, tab_history = st.tabs(
    ["💬 통합 AI 질의", "📊 생산/품질 분석", "✅ 의사결정 지원", "🔔 알림 및 추천", "📜 사용자 질문이력"]
)


# =====================================================================
# 탭 1. 통합 AI 질의 (Chat UI)
# =====================================================================
with tab_chat:
    col_sel, col_info = st.columns([2, 3])
    with col_sel:
        agent_type = st.radio(
            "Agent 유형 선택",
            options=list(AGENT_META.keys()),
            format_func=lambda k: f"{AGENT_META[k]['icon']} {AGENT_META[k]['label']}",
            horizontal=True,
            key="chat_agent_type",
        )
    with col_info:
        meta = AGENT_META[agent_type]
        st.markdown(
            f"<div style='padding:8px 12px;border-left:4px solid {meta['color']};"
            f"background:#f5f5f5;border-radius:4px;margin-top:8px;'>"
            f"<b>{meta['icon']} {meta['label']} Agent</b> 가 질의를 처리합니다.</div>",
            unsafe_allow_html=True,
        )

    # 대화 이력 세션 상태
    if "messages" not in st.session_state:
        st.session_state["messages"] = []  # [{role, content, agent_type, query_id, refs}]
    if "chat_session_id" not in st.session_state:
        st.session_state["chat_session_id"] = None

    # 예시 질문 버튼
    st.markdown("**예시 질문**")
    ex_cols = st.columns(3)
    pending_prompt: str | None = None
    for i, example in enumerate(EXAMPLE_QUERIES[agent_type]):
        with ex_cols[i % 3]:
            if st.button(example, key=f"ex_{agent_type}_{i}", use_container_width=True):
                pending_prompt = example

    st.divider()

    # 기존 대화 렌더링
    for msg in st.session_state["messages"]:
        avatar = "🧑‍🏭" if msg["role"] == "user" else AGENT_META.get(
            msg.get("agent_type", "INTEGRATED"), AGENT_META["INTEGRATED"]
        )["icon"]
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])
            # 참조 문서
            if msg.get("refs"):
                with st.expander(f"📚 참조 문서 {len(msg['refs'])}건"):
                    for d in msg["refs"]:
                        st.markdown(
                            f"- **{d.get('title','-')}** "
                            f"(`{d.get('doc_type','-')}`, 유사도 {d.get('score',0):.2f})"
                        )
            # 만족도 평가 (assistant 메시지 + query_id 존재 시)
            if msg["role"] == "assistant" and msg.get("query_id"):
                qid = msg["query_id"]
                if msg.get("rated"):
                    st.caption(f"평가 완료: {'⭐' * int(msg['rated'])}")
                else:
                    star_cols = st.columns(5)
                    for s in range(1, 6):
                        with star_cols[s - 1]:
                            if st.button("⭐" * s, key=f"fb_{qid}_{s}", use_container_width=True):
                                res = api_send(
                                    "PATCH", f"/query/{qid}/feedback",
                                    json={"feedback_score": s},
                                )
                                if res:
                                    msg["rated"] = s
                                    st.rerun()

    # 입력
    user_prompt = st.chat_input("질문을 입력하세요...")
    prompt = pending_prompt or user_prompt
    if prompt:
        st.session_state["messages"].append(
            {"role": "user", "content": prompt, "agent_type": agent_type}
        )
        payload = {"query": prompt, "agent_type": agent_type}
        if st.session_state["chat_session_id"]:
            payload["session_id"] = st.session_state["chat_session_id"]
        with st.spinner("AI Agent 분석 중..."):
            res = api_send("POST", "/query", json=payload)
        if res:
            st.session_state["chat_session_id"] = res.get("session_id")
            st.session_state["messages"].append({
                "role": "assistant",
                "content": res.get("response_text", "(응답 없음)")
                + f"\n\n*⏱ 응답시간 {res.get('response_time_ms', 0)}ms*",
                "agent_type": agent_type,
                "query_id": res.get("query_id"),
                "refs": res.get("referenced_docs", []),
            })
        st.rerun()

    if st.session_state["messages"]:
        if st.button("🗑 대화 초기화", key="clear_chat"):
            st.session_state["messages"] = []
            st.session_state["chat_session_id"] = None
            st.rerun()


# =====================================================================
# 탭 2. 생산/품질 분석 (추천 대시보드)
# =====================================================================
with tab_analysis:
    st.subheader("AI 추천 분석")

    f1, f2, f3 = st.columns(3)
    with f1:
        flt_agent = st.selectbox(
            "Agent 유형", ["전체"] + list(AGENT_META.keys()),
            format_func=lambda k: k if k == "전체" else f"{AGENT_META[k]['icon']} {AGENT_META[k]['label']}",
            key="an_agent",
        )
    with f2:
        flt_rec = st.selectbox(
            "추천 유형", ["전체"] + list(REC_TYPE_LABEL.keys()),
            format_func=lambda k: k if k == "전체" else REC_TYPE_LABEL[k],
            key="an_rec",
        )
    with f3:
        flt_actioned = st.selectbox(
            "처리 여부", ["미처리", "처리완료", "전체"], key="an_actioned"
        )

    params: dict[str, Any] = {"limit": 50}
    if flt_agent != "전체":
        params["agent_type"] = flt_agent
    if flt_rec != "전체":
        params["rec_type"] = flt_rec
    if flt_actioned == "미처리":
        params["is_actioned"] = "false"
    elif flt_actioned == "처리완료":
        params["is_actioned"] = "true"

    recs = api_get("/recommendations", params) or []

    if not recs:
        st.success("표시할 추천이 없습니다.")
    else:
        # 추천 유형별 분포 Pie
        df = pd.DataFrame(recs)
        chart_col, list_col = st.columns([2, 3])
        with chart_col:
            st.markdown("**추천 유형 분포**")
            if "rec_type" in df.columns:
                dist = df["rec_type"].map(lambda x: REC_TYPE_LABEL.get(x, x)).value_counts()
                # 추천 유형별 분포 (plotly 미가용 환경 대비 기본 차트 사용)
                st.bar_chart(dist)
        with list_col:
            st.markdown(f"**추천 목록 ({len(recs)}건)**")
            for rec in recs:
                badge = PRIORITY_BADGE.get(rec.get("priority", "NORMAL"), rec.get("priority"))
                ameta = AGENT_META.get(rec.get("agent_type"), AGENT_META["INTEGRATED"])
                with st.container(border=True):
                    st.markdown(
                        f"{badge} · {ameta['icon']} · "
                        f"`{REC_TYPE_LABEL.get(rec.get('rec_type'), rec.get('rec_type'))}`"
                    )
                    st.markdown(f"**{rec.get('title')}**")
                    st.caption(rec.get("content", ""))
                    meta_line = []
                    if rec.get("lot_id"):
                        meta_line.append(f"LOT `{rec['lot_id']}`")
                    if rec.get("confidence_score") is not None:
                        meta_line.append(f"신뢰도 {float(rec['confidence_score']):.0%}")
                    meta_line.append(fmt_ts(rec.get("created_at")))
                    st.caption(" · ".join(meta_line))
                    if rec.get("is_actioned"):
                        st.success(f"처리 완료 ({rec.get('actioned_by','-')})")
                    else:
                        if st.button("처리 완료", key=f"action_{rec['rec_id']}"):
                            res = api_send(
                                "PATCH", f"/recommendations/{rec['rec_id']}/action",
                                json={"actioned_by": CURRENT_USER},
                            )
                            if res:
                                st.toast("추천을 처리했습니다.")
                                st.rerun()


# =====================================================================
# 탭 3. 의사결정 지원 (승인 대기)
# =====================================================================
with tab_decision:
    st.subheader("의사결정 승인 대기")
    if not can_approve():
        st.warning("의사결정 승인은 MANAGER 이상 권한이 필요합니다. (현재 권한: " + CURRENT_ROLE + ")")

    # 전체 이력에서 미결(is_approved=NULL) 추출
    history = api_get("/query/history", {"limit": 200}) or []
    pending = [h for h in history if h.get("is_approved") is None]
    decided = [h for h in history if h.get("is_approved") is not None]

    st.markdown(f"**승인 대기 항목 ({len(pending)}건)**")
    if not pending:
        st.success("승인 대기 중인 항목이 없습니다.")
    for h in pending:
        ameta = AGENT_META.get(h.get("agent_type"), AGENT_META["INTEGRATED"])
        with st.container(border=True):
            st.markdown(f"{ameta['icon']} **{ameta['label']}** · {fmt_ts(h.get('created_at'))}")
            st.markdown(f"**질의:** {h.get('query_text')}")
            st.caption(f"응답: {h.get('response_text','-')}")
            if h.get("context_lots"):
                st.caption("연관 LOT: " + ", ".join(f"`{x}`" for x in h["context_lots"]))
            if can_approve():
                a1, a2, _ = st.columns([1, 1, 4])
                with a1:
                    if st.button("✅ 승인", key=f"appr_{h['query_id']}"):
                        res = api_send(
                            "PATCH", f"/query/{h['query_id']}/approve",
                            json={"is_approved": True, "approved_by": CURRENT_USER},
                        )
                        if res:
                            st.toast("승인 처리되었습니다.")
                            st.rerun()
                with a2:
                    if st.button("❌ 거절", key=f"rej_{h['query_id']}"):
                        res = api_send(
                            "PATCH", f"/query/{h['query_id']}/approve",
                            json={"is_approved": False, "approved_by": CURRENT_USER},
                        )
                        if res:
                            st.toast("거절 처리되었습니다.")
                            st.rerun()

    st.divider()
    st.markdown(f"**승인/거절 이력 ({len(decided)}건)**")
    if decided:
        rows = [{
            "질의ID": h["query_id"],
            "Agent": AGENT_META.get(h.get("agent_type"), {}).get("label", h.get("agent_type")),
            "질의": (h.get("query_text") or "")[:40],
            "결과": "✅ 승인" if h.get("is_approved") else "❌ 거절",
            "처리자": h.get("approved_by", "-"),
            "처리시각": fmt_ts(h.get("approved_at")),
        } for h in decided]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# =====================================================================
# 탭 4. 알림 및 추천 (1분 자동 갱신)
# =====================================================================
with tab_alert:
    @st.fragment(run_every=60)
    def render_alerts() -> None:
        st.caption(f"마지막 갱신: {dt.datetime.now().strftime('%H:%M:%S')} (60초 자동 갱신)")

        # --- 고우선순위 추천 카드 ---
        st.markdown("#### 🚨 고우선순위 추천")
        active = api_get("/recommendations/active", {"limit": 20}) or []
        if not active:
            st.success("미처리 고우선순위 추천이 없습니다.")
        else:
            cols = st.columns(2)
            for i, rec in enumerate(active):
                with cols[i % 2]:
                    with st.container(border=True):
                        badge = PRIORITY_BADGE.get(rec.get("priority"), rec.get("priority"))
                        st.markdown(f"{badge} · {REC_TYPE_LABEL.get(rec.get('rec_type'), rec.get('rec_type'))}")
                        st.markdown(f"**{rec.get('title')}**")
                        st.caption(rec.get("content", "")[:120])
                        if rec.get("lot_id"):
                            st.caption(f"LOT `{rec['lot_id']}`")

        st.divider()

        # --- AI 컴포넌트 상태 ---
        st.markdown("#### 🩺 AI 컴포넌트 상태")
        status = api_get("/status") or []
        if status:
            scols = st.columns(len(status))
            for i, s in enumerate(status):
                with scols[i]:
                    label = COMPONENT_LABEL.get(s.get("component"), s.get("component"))
                    badge = STATUS_BADGE.get(s.get("status"), s.get("status"))
                    st.metric(
                        label,
                        badge,
                        delta=f"{s.get('avg_response_ms','-')}ms" if s.get("avg_response_ms") else None,
                        delta_color="off",
                    )
                    if s.get("error_count_1h"):
                        st.caption(f"⚠️ 1h 오류 {s['error_count_1h']}건")

        st.divider()

        # --- Vector DB 문서 인덱스 현황 ---
        st.markdown("#### 📚 Vector DB 문서 인덱스")
        docs = api_get("/documents") or []
        if docs:
            rows = [{
                "유형": d.get("doc_type"),
                "제목": d.get("title"),
                "버전": d.get("version"),
                "청크수": d.get("chunk_count"),
                "임베딩상태": d.get("embed_status"),
                "수정시각": fmt_ts(d.get("updated_at")),
            } for d in docs]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    render_alerts()


# =====================================================================
# 탭 5. 사용자 질문이력
# =====================================================================
with tab_history:
    st.subheader("질의 이력")

    h1, h2, h3 = st.columns(3)
    with h1:
        hist_agent = st.selectbox(
            "Agent 유형", ["전체"] + list(AGENT_META.keys()),
            format_func=lambda k: k if k == "전체" else f"{AGENT_META[k]['icon']} {AGENT_META[k]['label']}",
            key="hist_agent",
        )
    with h2:
        date_from = st.date_input(
            "조회 시작일", value=dt.date.today() - dt.timedelta(days=30), key="hist_from"
        )
    with h3:
        lot_filter = st.text_input("연관 LOT ID", key="hist_lot", placeholder="예: SH-20260523-011")

    params = {"limit": 200, "date_from": dt.datetime.combine(date_from, dt.time.min).isoformat()}
    if hist_agent != "전체":
        params["agent_type"] = hist_agent
    if lot_filter.strip():
        params["lot_id"] = lot_filter.strip()

    history = api_get("/query/history", params) or []

    # 만족도 평균 metric + 통계
    m1, m2, m3 = st.columns(3)
    scores = [h["feedback_score"] for h in history if h.get("feedback_score")]
    avg_score = sum(scores) / len(scores) if scores else 0.0
    resp_times = [h["response_time_ms"] for h in history if h.get("response_time_ms")]
    avg_resp = sum(resp_times) / len(resp_times) if resp_times else 0.0
    m1.metric("질의 건수", f"{len(history)} 건")
    m2.metric("평균 만족도", f"⭐ {avg_score:.2f}" if scores else "-")
    m3.metric("평균 응답시간", f"{avg_resp:.0f} ms" if resp_times else "-")

    st.divider()

    # 자주 묻는 질문 TOP5
    st.markdown("**자주 묻는 질문 TOP 5**")
    top = api_get("/analytics/top-queries", {"days": 30, "limit": 5})
    if top and top.get("top_queries"):
        tq = pd.DataFrame(top["top_queries"]).set_index("keyword")
        st.bar_chart(tq["count"])
    else:
        st.caption("분석할 질의가 부족합니다.")

    st.divider()

    # 질의 이력 table + 상세 expander
    st.markdown(f"**질의 목록 ({len(history)}건)**")
    if history:
        table = [{
            "ID": h["query_id"],
            "Agent": AGENT_META.get(h.get("agent_type"), {}).get("label", h.get("agent_type")),
            "질의": (h.get("query_text") or "")[:50],
            "만족도": "⭐" * int(h["feedback_score"]) if h.get("feedback_score") else "-",
            "응답(ms)": h.get("response_time_ms", "-"),
            "승인": "✅" if h.get("is_approved") else ("❌" if h.get("is_approved") is False else "대기"),
            "시각": fmt_ts(h.get("created_at")),
        } for h in history]
        st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)

        for h in history[:30]:
            with st.expander(f"#{h['query_id']} · {(h.get('query_text') or '')[:40]}"):
                ameta = AGENT_META.get(h.get("agent_type"), AGENT_META["INTEGRATED"])
                st.markdown(f"{ameta['icon']} **{ameta['label']}** · {fmt_ts(h.get('created_at'))}")
                st.markdown(f"**질의:** {h.get('query_text')}")
                st.markdown(f"**응답:** {h.get('response_text','-')}")
                if h.get("context_lots"):
                    st.caption("연관 LOT: " + ", ".join(f"`{x}`" for x in h["context_lots"]))
                refs = h.get("referenced_docs") or []
                if isinstance(refs, str):
                    import json as _json
                    try:
                        refs = _json.loads(refs)
                    except Exception:
                        refs = []
                if refs:
                    st.markdown("**참조 문서:**")
                    for d in refs:
                        st.markdown(
                            f"- {d.get('title','-')} (`{d.get('doc_type','-')}`, "
                            f"{float(d.get('score',0)):.2f})"
                        )
    else:
        st.info("조회 조건에 해당하는 질의 이력이 없습니다.")
