"""
꽃순이김치 제조AI MES — 원재료관리 화면 (pages/02_material.py)
프로젝트: SF26179540 / 로뎀솔루션

streamlit-dashboard 스킬 원칙:
  - 모든 API 호출은 try/except 로 감싸고 실패 시 st.warning()
  - 차트는 Plotly, use_container_width=True
  - 데이터 없을 때 graceful 처리 (st.info)

탭 구성:
  1. 입고관리        — LOT 등록 Form + 입고 목록 (상태 뱃지)
  2. 원재료 이력조회 — LOT ID 검색 + 전체 이력 타임라인
  3. 선별 데이터관리 — 선별 입력 + 선별율 추세 bar chart
  4. 공급처 품질분석 — 공급처 선택 + 월별 합격률 line chart + 랭킹
  5. 입고 AI Agent   — Chat UI (POST /api/v1/agent/query, INTAKE)

API: http://localhost:8000/api/v1/material  (api_material_router.py)
"""
from datetime import date, datetime

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="원재료관리 | 꽃순이김치 MES", page_icon="🥬", layout="wide")

API_BASE = "http://localhost:8000/api/v1/material"
AGENT_BASE = "http://localhost:8000/api/v1/agent"  # AI Agent 프록시 (/api/v1/ai/* 계열)

# 상태 뱃지 매핑
STATUS_BADGE = {
    "RECEIVED": "⏳ 입고",
    "INSPECTING": "🔬 검사중",
    "PASSED": "✅ 합격",
    "REJECTED": "❌ 불합격",
    "CONSUMED": "📦 투입완료",
}
QC_BADGE = {"PASS": "✅ 합격", "FAIL": "❌ 불합격", "CONDITIONAL": "⚠️ 조건부"}
CABBAGE_SIZES = ["SMALL", "MEDIUM", "LARGE", "XLARGE"]
REJECT_REASONS = ["ROTTEN", "PEST", "SIZE", "FOREIGN", "OTHER"]


# ---------------------------------------------------------------------------
# API 헬퍼 — 모든 호출 try/except, 실패 시 st.warning + 기본값
# ---------------------------------------------------------------------------
def api_get(path: str, params: dict | None = None, default=None, base: str = API_BASE):
    try:
        r = httpx.get(f"{base}{path}", params=params or {}, timeout=10.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        st.warning(f"API 조회 실패 ({path}): {e}")
        return default


def api_post(path: str, json: dict, params: dict | None = None, base: str = API_BASE):
    try:
        r = httpx.post(f"{base}{path}", json=json, params=params or {}, timeout=30.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        # 422 등 HTTP 오류: 응답 본문의 detail 메시지 파싱하여 표시
        try:
            body = e.response.json()
            detail = body.get("detail", str(e))
            if isinstance(detail, list):
                msgs = "; ".join(
                    f"{'.'.join(str(x) for x in d.get('loc', []))}: {d.get('msg', '')}"
                    for d in detail
                )
                detail = f"입력값 검증 오류 — {msgs}"
        except Exception:  # noqa: BLE001
            detail = str(e)
        st.error(f"🚫 API 오류 ({path} · {e.response.status_code}): {detail}")
        return None
    except Exception as e:  # noqa: BLE001
        st.warning(f"API 등록 실패 ({path}): {e}")
        return None


def api_patch(path: str, json: dict, base: str = API_BASE):
    try:
        r = httpx.patch(f"{base}{path}", json=json, timeout=10.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json().get("detail", str(e))
        except Exception:  # noqa: BLE001
            detail = str(e)
        st.error(f"🚫 상태 변경 오류 ({e.response.status_code}): {detail}")
        return None
    except Exception as e:  # noqa: BLE001
        st.warning(f"API 처리 실패 ({path}): {e}")
        return None


def status_badge(status: str | None) -> str:
    return STATUS_BADGE.get(status or "", status or "-")


st.title("🥬 원재료관리")

tabs = st.tabs(
    ["입고관리", "원재료 이력조회", "선별 데이터관리", "공급처 품질분석", "입고 AI Agent"]
)

# ===========================================================================
# 탭 1: 입고관리 — LOT 등록 Form + 입고 목록
# ===========================================================================
with tabs[0]:
    st.subheader("원재료 입고 등록")

    # 오늘 입고 현황 요약
    summary = api_get("/summary/today", default={})
    if summary:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("오늘 입고 LOT", f"{summary.get('total_lots', 0)} 건")
        m2.metric("오늘 입고량", f"{summary.get('total_kg', 0):,.0f} kg")
        m3.metric("검사 완료", f"{summary.get('inspected_count', 0)} 건")
        pass_rate = summary.get("inspection_pass_rate_pct")
        m4.metric("검사 합격률", f"{pass_rate}%" if pass_rate is not None else "-")

    # 공급처 목록 (selectbox 옵션)
    suppliers = api_get("/suppliers", default=[]) or []
    sup_options = {f"{s['supplier_code']} - {s['supplier_name']}": s["supplier_code"]
                   for s in suppliers}

    st.divider()
    with st.form("intake_form", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            lot_id = st.text_input("LOT ID", value=f"RM-{date.today():%Y%m%d}-001")
            intake_dt = st.date_input("입고일", value=date.today())
            if sup_options:
                sup_label = st.selectbox("공급처", list(sup_options.keys()))
                supplier_code = sup_options[sup_label]
            else:
                supplier_code = st.text_input("공급처 코드", value="SUP01")
        with c2:
            material_code = st.text_input("재료 코드", value="MAT-BC")
            origin = st.text_input("원산지", value="강원 평창")
            quantity_kg = st.number_input("입고 수량 (kg)", min_value=0.0, value=3000.0, step=10.0)
        with c3:
            unit_price = st.number_input("단가 (원/kg)", min_value=0.0, value=1150.0, step=10.0)
            vehicle_no = st.text_input("차량번호", value="강원80가1234")
            received_by = st.text_input("입고 담당자", value="한입고")
        driver_name = st.text_input("운전기사", value="최운송")
        notes = st.text_input("비고", value="")

        if st.form_submit_button("💾 입고 등록", use_container_width=True):
            payload = {
                "lot_id": lot_id,
                "intake_date": str(intake_dt),
                "supplier_code": supplier_code,
                "material_code": material_code,
                "origin": origin or None,
                "quantity_kg": quantity_kg,
                "unit_price": unit_price or None,
                "vehicle_no": vehicle_no or None,
                "driver_name": driver_name or None,
                "received_by": received_by or None,
                "notes": notes or None,
            }
            res = api_post("/lots", json=payload)
            if res:
                st.success(f"✅ 입고 등록 완료: {res.get('lot_id')} "
                           f"({res.get('quantity_kg')}kg)")

    st.divider()
    st.markdown("**입고 LOT 목록**")
    fc1, fc2, fc3 = st.columns([2, 2, 1])
    f_from = fc1.date_input("입고일(시작)", value=None, key="lot_from")
    f_status = fc2.selectbox("상태 필터", ["전체"] + list(STATUS_BADGE.keys()), key="lot_status_f")
    f_limit = fc3.number_input("표시 수", 10, 500, 50, step=10, key="lot_limit")

    params: dict = {"limit": int(f_limit)}
    if f_from:
        params["date_from"] = str(f_from)
    if f_status != "전체":
        params["lot_status"] = f_status

    lots = api_get("/lots", params=params, default=[]) or []
    if lots:
        df = pd.DataFrame(lots)
        df["상태"] = df["lot_status"].map(status_badge)
        cols = [c for c in ["lot_id", "intake_date", "supplier_name", "material_code",
                            "origin", "quantity_kg", "상태", "received_by"] if c in df.columns]
        st.dataframe(
            df[cols].rename(columns={
                "lot_id": "LOT ID", "intake_date": "입고일", "supplier_name": "공급처",
                "material_code": "재료", "origin": "원산지", "quantity_kg": "수량(kg)",
                "received_by": "담당자",
            }),
            use_container_width=True, hide_index=True,
        )

        # LOT 상태 변경
        with st.expander("🔄 LOT 상태 변경"):
            sc1, sc2, sc3 = st.columns([2, 2, 2])
            target_lot = sc1.selectbox("LOT 선택", [l["lot_id"] for l in lots])
            new_status = sc2.selectbox("변경 상태", ["PASSED", "REJECTED", "INSPECTING", "CONSUMED"])
            changed_by = sc3.text_input("변경자", value="관리자", key="status_changer")
            if st.button("상태 변경 적용", key="apply_status"):
                res = api_patch(f"/lots/{target_lot}/status",
                                json={"lot_status": new_status, "changed_by": changed_by})
                if res:
                    st.success(f"✅ {target_lot} → {status_badge(res.get('lot_status'))}")
                    st.rerun()
    else:
        st.info("표시할 입고 LOT 이 없습니다.")

# ===========================================================================
# 탭 2: 원재료 이력조회 — LOT 검색 + 타임라인
# ===========================================================================
with tabs[1]:
    st.subheader("원재료 이력조회")

    search_lot = st.text_input("LOT ID 검색", value=f"RM-{date.today():%Y%m%d}-001")
    if st.button("🔍 이력 조회", key="hist_search"):
        st.session_state["material_hist_lot"] = search_lot

    target = st.session_state.get("material_hist_lot", search_lot)
    if target:
        hist = api_get(f"/history/{target}", default=None)
        if hist and hist.get("timeline"):
            lot = hist.get("lot", {})
            i1, i2, i3, i4 = st.columns(4)
            i1.metric("LOT", hist.get("lot_id"))
            i2.metric("공급처", lot.get("supplier_name", "-"))
            i3.metric("입고량", f"{lot.get('quantity_kg', 0):,.0f} kg")
            i4.metric("현재 상태", status_badge(lot.get("lot_status")))

            st.markdown(f"**이력 타임라인** ({hist.get('step_count', 0)} 단계)")
            stage_icon = {"입고": "📥", "입고검사": "🔬", "선별": "🧹", "후속공정": "⚙️"}
            for ev in hist["timeline"]:
                icon = stage_icon.get(ev.get("stage"), "•")
                st_txt = f" [{ev['status']}]" if ev.get("status") else ""
                st.markdown(
                    f"{icon} **{ev.get('stage')}** "
                    f"`{ev.get('date')}`{st_txt} — {ev.get('detail')}"
                )

            # 후속 공정 연계 테이블
            downstream = hist.get("downstream", [])
            if downstream:
                st.markdown("**후속 공정 연계 (LOT 체인)**")
                st.dataframe(pd.DataFrame(downstream), use_container_width=True, hide_index=True)
        else:
            st.info(f"LOT {target} 의 이력이 없습니다.")

# ===========================================================================
# 탭 3: 선별 데이터관리 — 입력 Form + 선별율 추세 bar chart
# ===========================================================================
with tabs[2]:
    st.subheader("선별 데이터 입력")

    with st.form("selection_form", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            s_lot = st.text_input("LOT ID", value=f"RM-{date.today():%Y%m%d}-001")
            s_date = st.date_input("선별일", value=date.today(), key="sel_date")
        with c2:
            input_qty = st.number_input("투입량 (kg)", min_value=0.0, value=3000.0, step=10.0)
            selected_qty = st.number_input("선별 통과량 (kg)", min_value=0.0, value=2850.0, step=10.0)
        with c3:
            reject_qty = st.number_input("제거량 (kg)", min_value=0.0, value=150.0, step=1.0)
            s_reason = st.selectbox("제거 사유", REJECT_REASONS)
        operator = st.text_input("선별 작업자", value="선별조A")

        if st.form_submit_button("💾 선별 실적 저장", use_container_width=True):
            payload = {
                "lot_id": s_lot,
                "selection_date": str(s_date),
                "operator": operator or None,
                "input_qty_kg": input_qty,
                "selected_qty_kg": selected_qty,
                "reject_qty_kg": reject_qty,
                "reject_reason": s_reason,
            }
            res = api_post("/selections", json=payload)
            if res:
                st.success(f"✅ 선별 실적 저장 완료 "
                           f"(선별율 {res.get('selection_rate_pct', '-')}%)")

    st.divider()
    st.markdown("**선별 실적 및 선별율 추세**")
    selections = api_get("/selections", params={"limit": 30}, default=[]) or []
    if selections:
        df = pd.DataFrame(selections)
        df = df.sort_values("selection_date")

        # 선별율 추세 bar chart (Plotly)
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df["lot_id"],
            y=df["selection_rate_pct"],
            text=df["selection_rate_pct"],
            texttemplate="%{text:.1f}%",
            textposition="outside",
            marker_color="#4CAF50",
            name="선별율",
        ))
        fig.update_layout(
            title="LOT별 선별율 (%)",
            xaxis_title="LOT ID", yaxis_title="선별율 (%)",
            yaxis_range=[0, 105], height=380,
        )
        st.plotly_chart(fig, use_container_width=True)

        cols = [c for c in ["lot_id", "selection_date", "operator", "input_qty_kg",
                            "selected_qty_kg", "reject_qty_kg", "selection_rate_pct",
                            "reject_reason"] if c in df.columns]
        st.dataframe(
            df[cols].rename(columns={
                "lot_id": "LOT ID", "selection_date": "선별일", "operator": "작업자",
                "input_qty_kg": "투입(kg)", "selected_qty_kg": "통과(kg)",
                "reject_qty_kg": "제거(kg)", "selection_rate_pct": "선별율(%)",
                "reject_reason": "제거사유",
            }),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("표시할 선별 실적이 없습니다.")

# ===========================================================================
# 탭 4: 공급처 품질분석 — 월별 합격률 line chart + 랭킹
# ===========================================================================
with tabs[3]:
    st.subheader("공급처 품질분석")

    suppliers = api_get("/suppliers", default=[]) or []
    if suppliers:
        sup_map = {f"{s['supplier_code']} - {s['supplier_name']}": s["supplier_code"]
                   for s in suppliers}
        c1, c2 = st.columns([3, 1])
        sel_label = c1.selectbox("공급처 선택", list(sup_map.keys()))
        months = c2.number_input("분석 개월수", 1, 24, 6, key="quality_months")
        sel_code = sup_map[sel_label]

        quality = api_get(f"/suppliers/{sel_code}/quality",
                          params={"months": int(months)}, default=None)
        if quality and quality.get("monthly"):
            summ = quality.get("summary", {})
            q1, q2, q3 = st.columns(3)
            q1.metric("누적 합격률", f"{summ.get('overall_pass_rate_pct', '-')}%")
            q2.metric("평균 신선도", f"{summ.get('avg_freshness', '-')}/10")
            q3.metric("총 입고 LOT", f"{summ.get('total_lots', 0)} 건")

            mdf = pd.DataFrame(quality["monthly"])
            # 월별 합격률 line chart (Plotly)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=mdf["year_month"], y=mdf["pass_rate_pct"],
                mode="lines+markers", name="합격률(%)",
                line=dict(color="#2196F3", width=3), marker=dict(size=8),
            ))
            fig.add_trace(go.Scatter(
                x=mdf["year_month"], y=mdf["avg_freshness"] * 10,
                mode="lines+markers", name="신선도(×10)",
                line=dict(color="#FF9800", width=2, dash="dot"), yaxis="y2",
            ))
            fig.update_layout(
                title=f"{sel_label} — 월별 합격률 추세",
                xaxis_title="연월", yaxis_title="합격률 (%)",
                yaxis=dict(range=[0, 105]),
                yaxis2=dict(title="신선도(×10)", overlaying="y", side="right", range=[0, 105]),
                height=400, legend=dict(orientation="h", y=-0.2),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(f"{sel_label} 의 품질 점수 데이터가 없습니다.")
    else:
        st.info("등록된 공급처가 없습니다.")

    st.divider()
    st.markdown("**공급처 품질 랭킹 (최근 3개월 합격률 기준)**")
    ranking = api_get("/suppliers/ranking", params={"months": 3}, default=None)
    if ranking and ranking.get("ranking"):
        rdf = pd.DataFrame(ranking["ranking"])
        cols = [c for c in ["rank", "supplier_code", "supplier_name", "region",
                            "total_lots", "passed_lots", "pass_rate_pct",
                            "avg_freshness", "total_kg"] if c in rdf.columns]
        st.dataframe(
            rdf[cols].rename(columns={
                "rank": "순위", "supplier_code": "코드", "supplier_name": "공급처",
                "region": "지역", "total_lots": "총LOT", "passed_lots": "합격LOT",
                "pass_rate_pct": "합격률(%)", "avg_freshness": "평균신선도",
                "total_kg": "총입고(kg)",
            }),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("랭킹 데이터가 없습니다.")

# ===========================================================================
# 탭 5: 입고 AI Agent — Chat UI
#   POST /api/v1/agent/query  ({"query": "...", "agent_type": "INTAKE"})
# ===========================================================================
with tabs[4]:
    st.subheader("입고 AI Agent 💬")
    st.caption("원재료 입고 관련 질의 — 공급처 품질 이력, 입고 기준 적합 여부, LOT traceability")

    if "intake_chat" not in st.session_state:
        st.session_state["intake_chat"] = [
            {"role": "assistant",
             "content": "안녕하세요. 원재료 입고 AI Agent 입니다. "
                        "공급처 품질, 입고 기준, LOT 추적 관련 질문을 해주세요."},
        ]

    # 예시 질문 버튼
    st.markdown("**예시 질문**")
    examples = [
        "이번 달 입고 불합격 LOT 원인은?",
        "최고 품질 공급처는?",
        "함수율 기준 초과 LOT 조회",
    ]
    ec = st.columns(len(examples))
    picked_example = None
    for col, q in zip(ec, examples):
        if col.button(q, use_container_width=True, key=f"ex_{q}"):
            picked_example = q

    # 기존 대화 렌더링
    for msg in st.session_state["intake_chat"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 입력 처리 (chat_input 또는 예시 버튼)
    user_query = st.chat_input("입고 관련 질문을 입력하세요...")
    if picked_example:
        user_query = picked_example

    if user_query:
        st.session_state["intake_chat"].append({"role": "user", "content": user_query})
        with st.chat_message("user"):
            st.markdown(user_query)

        with st.chat_message("assistant"):
            with st.spinner("AI Agent 분석 중..."):
                res = api_post(
                    "/query",
                    json={"query": user_query, "agent_type": "INTAKE"},
                    base=AGENT_BASE,
                )
            if res and (res.get("answer") or res.get("response")):
                answer = res.get("answer") or res.get("response")
                st.markdown(answer)
                # 참조 근거(있으면) 표시
                sources = res.get("sources") or res.get("references")
                if sources:
                    with st.expander("📚 참조 근거"):
                        for s in sources:
                            st.markdown(f"- {s}")
                st.session_state["intake_chat"].append(
                    {"role": "assistant", "content": answer}
                )
            else:
                msg = "AI Agent 응답 대기중"
                st.info(msg)
                st.session_state["intake_chat"].append(
                    {"role": "assistant", "content": msg}
                )

    if st.button("🗑️ 대화 초기화", key="clear_intake_chat"):
        st.session_state.pop("intake_chat", None)
        st.rerun()
