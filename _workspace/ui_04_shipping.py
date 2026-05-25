"""
꽃순이김치 제조AI MES — 포장출하관리 화면 (pages/04_shipping.py)
프로젝트: SF26179540 / 로뎀솔루션

streamlit-dashboard 스킬 원칙:
  - 모든 API 호출은 try/except 로 감싸고 실패 시 st.warning()
  - 차트는 Plotly, use_container_width=True
  - 탭 구성: 포장실적관리 / 출하관리 / LOT 추적 / 검사결과관리 / 클레임분석 / 출하 AI Agent

API : http://localhost:8000/api/v1/shipping  (api_shipping_router.py)
AI  : http://localhost:8000/api/v1/agent/query (api_agent_router.py, agent_type=SHIPPING)
"""
from datetime import date, datetime, timedelta

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="포장출하관리 | 꽃순이김치 MES", page_icon="📦", layout="wide")

API_BASE = "http://localhost:8000/api/v1/shipping"
AGENT_BASE = "http://localhost:8000/api/v1/agent"

# 제품 코드별 메타데이터 (단위 중량 g / 표준 단가 KRW) — API PRODUCT_META 와 동기화
PRODUCT_META = {
    "KIM-BC-300":  {"name": "배추김치 300g",  "unit_weight_g": 300,  "unit_price": 4500},
    "KIM-BC-500":  {"name": "배추김치 500g",  "unit_weight_g": 500,  "unit_price": 6900},
    "KIM-BC-1000": {"name": "배추김치 1kg",   "unit_weight_g": 1000, "unit_price": 12900},
    "KIM-BC-2000": {"name": "배추김치 2kg",   "unit_weight_g": 2000, "unit_price": 23900},
    "KIM-BC-5000": {"name": "배추김치 5kg",   "unit_weight_g": 5000, "unit_price": 54000},
}
PRODUCT_CODES = list(PRODUCT_META.keys())

# LOT 추적 단계 표시 메타 (단계 순서 / 아이콘 / 색상)
TRACE_STEPS = {
    "INTAKE":       {"label": "원재료 입고", "icon": "🥬", "color": "#16a34a", "order": 1},
    "SALTING":      {"label": "세척/절임",   "icon": "🧂", "color": "#0ea5e9", "order": 2},
    "FERMENTATION": {"label": "숙성/발효",   "icon": "🫙", "color": "#a855f7", "order": 3},
    "PACKAGING":    {"label": "포장/출하",   "icon": "📦", "color": "#f59e0b", "order": 4},
}

# 상태 뱃지 매핑
LOT_STATUS_BADGE = {
    "PACKED": "🔵 포장완료", "INSPECTED": "🟢 검사합격",
    "SHIPPED": "🚚 출하완료", "HOLD": "🟡 보류",
}
ORDER_STATUS_BADGE = {
    "PENDING": "⏳ 대기", "PICKING": "📋 피킹/승인", "SHIPPED": "🚚 출하완료",
    "DELIVERED": "✅ 배송완료", "CANCELLED": "❌ 취소",
}
QC_BADGE = {"PASS": "🟢 합격", "FAIL": "🔴 불합격", "HOLD": "🟡 보류"}
CLAIM_TYPE_KR = {
    "QUALITY": "품질", "DELIVERY": "배송", "FOREIGN": "이물", "LABELING": "표기", "OTHER": "기타",
}
SEVERITY_KR = {"MINOR": "경미", "NORMAL": "보통", "MAJOR": "중대", "CRITICAL": "심각"}


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


def _parse_http_error(e: httpx.HTTPStatusError) -> str:
    try:
        body = e.response.json()
        detail = body.get("detail", str(e))
        if isinstance(detail, list):
            detail = "; ".join(
                f"{'.'.join(str(x) for x in d.get('loc', []))}: {d.get('msg', '')}"
                for d in detail
            )
        return f"{detail}"
    except Exception:  # noqa: BLE001
        return str(e)


def api_post(path: str, json: dict, params: dict | None = None, base: str = API_BASE):
    try:
        r = httpx.post(f"{base}{path}", json=json, params=params or {}, timeout=15.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        st.error(f"🚫 API 오류 ({path} · {e.response.status_code}): {_parse_http_error(e)}")
        return None
    except Exception as e:  # noqa: BLE001
        st.warning(f"API 등록 실패 ({path}): {e}")
        return None


def api_patch(path: str, json: dict | None = None, params: dict | None = None):
    try:
        r = httpx.patch(f"{API_BASE}{path}", json=json or {}, params=params or {}, timeout=10.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        st.error(f"🚫 처리 오류 ({path} · {e.response.status_code}): {_parse_http_error(e)}")
        return None
    except Exception as e:  # noqa: BLE001
        st.warning(f"API 처리 실패 ({path}): {e}")
        return None


def api_delete(path: str):
    try:
        r = httpx.delete(f"{API_BASE}{path}", timeout=10.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        st.warning(f"삭제 실패 ({path}): {e}")
        return None


# ---------------------------------------------------------------------------
# 사용자 권한 (출하 승인 권한 체크용) — 사이드바에서 모의 선택
# ---------------------------------------------------------------------------
st.sidebar.markdown("### 👤 사용자 역할")
USER_ROLE = st.sidebar.selectbox(
    "역할 (출하 승인 권한)", ["OPERATOR", "MANAGER", "ADMIN"], index=1,
    help="MANAGER/ADMIN 만 출하 승인 가능",
)
CAN_APPROVE = USER_ROLE in ("MANAGER", "ADMIN")
st.sidebar.caption(f"출하 승인 권한: {'✅ 있음' if CAN_APPROVE else '❌ 없음'}")

st.title("📦 포장출하관리")

# 오늘 현황 요약 메트릭
today = api_get("/summary/today", default={})
if today:
    pkg = today.get("packaging", {})
    shp = today.get("shipping", {})
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("오늘 포장 LOT", pkg.get("lot_count", 0))
    m2.metric("포장 단위 수", f"{pkg.get('total_units', 0):,}")
    m3.metric("불량률", f"{pkg.get('defect_rate_pct', 0)}%")
    m4.metric("출하 완료 단위", f"{shp.get('shipped_units', 0):,}")
    m5.metric("미처리 클레임", today.get("open_claims", 0))

tabs = st.tabs(
    ["포장실적관리", "출하관리", "LOT 추적", "검사결과관리", "클레임분석", "출하 AI Agent"]
)

# ===========================================================================
# 탭 1: 포장실적관리
# ===========================================================================
with tabs[0]:
    st.subheader("포장 LOT 등록")
    with st.form("packaging_form", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            lot_id = st.text_input("포장 LOT ID", value=f"PK-{date.today():%Y%m%d}-001")
            source_lot = st.text_input("발효 LOT ID (source)", value=f"FERM-{date.today():%Y%m%d}-001")
            pkg_date = st.date_input("포장일", value=date.today())
        with c2:
            product = st.selectbox(
                "제품 코드", PRODUCT_CODES, index=1,
                format_func=lambda c: f"{c} ({PRODUCT_META[c]['name']})",
            )
            line_no = st.text_input("포장 라인", value="LINE-01")
            operator = st.text_input("작업자", value="김포장")
        with c3:
            input_kg = st.number_input("투입 수량 (kg)", min_value=0.0, value=2100.0, step=10.0)
            output_units = st.number_input("포장 완료 단위 수", min_value=0, value=4150, step=10)
            defect_units = st.number_input("불량 단위 수", min_value=0, value=8, step=1)
        c4, c5 = st.columns(2)
        metal = c4.checkbox("금속검출 통과", value=True)
        barcode = c5.text_input("바코드/QR", value=f"BC-{date.today():%Y%m%d}-001")

        if st.form_submit_button("💾 포장 LOT 등록", use_container_width=True):
            payload = {
                "lot_id": lot_id, "source_lot_id": source_lot or None,
                "packaging_date": str(pkg_date), "product_code": product,
                "line_no": line_no, "operator": operator,
                "input_qty_kg": input_kg, "output_units": int(output_units),
                "defect_units": int(defect_units), "metal_detection": metal,
                "barcode": barcode or None,
            }
            res = api_post("/packaging/lots", json=payload)
            if res:
                st.success(f"✅ 포장 LOT 등록 완료: {res['lot_id']} ({res.get('product_name')})")

    st.divider()
    st.markdown("**포장 실적 목록**")
    f1, f2, f3 = st.columns(3)
    flt_product = f1.selectbox("제품 필터", ["전체"] + PRODUCT_CODES, key="pk_flt_prod")
    flt_status = f2.selectbox("상태 필터", ["전체"] + list(LOT_STATUS_BADGE.keys()), key="pk_flt_status")
    flt_from = f3.date_input("포장일 시작", value=date.today() - timedelta(days=7), key="pk_flt_from")

    params = {"date_from": str(flt_from), "limit": 50}
    if flt_product != "전체":
        params["product_code"] = flt_product
    if flt_status != "전체":
        params["lot_status"] = flt_status
    lots = api_get("/packaging/lots", params=params, default=[])

    if lots:
        view = [{
            "LOT ID": l["lot_id"], "제품": l.get("product_name", l["product_code"]),
            "포장일": l["packaging_date"], "라인": l.get("line_no"),
            "단위수": l["output_units"], "불량": l.get("defect_units"),
            "금속검출": "✅ 통과" if l.get("metal_detection") else "⚠️ 미통과",
            "상태": LOT_STATUS_BADGE.get(l["lot_status"], l["lot_status"]),
            "작업자": l.get("operator"),
        } for l in lots]
        st.dataframe(pd.DataFrame(view), use_container_width=True, hide_index=True)

        # 제품별 단위 수 집계 차트
        df = pd.DataFrame(lots)
        agg = df.groupby("product_code")["output_units"].sum().reset_index()
        agg["product_name"] = agg["product_code"].map(lambda c: PRODUCT_META.get(c, {}).get("name", c))
        fig = px.bar(agg, x="product_name", y="output_units", text="output_units",
                     title="제품별 포장 단위 수", color="product_name")
        fig.update_layout(template="plotly_dark", height=320, showlegend=False,
                          margin=dict(l=40, r=20, t=50, b=40))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("표시할 포장 실적이 없습니다.")

# ===========================================================================
# 탭 2: 출하관리
# ===========================================================================
with tabs[1]:
    st.subheader("출하 주문 관리")

    with st.expander("➕ 신규 출하 주문 등록"):
        with st.form("order_form"):
            o1, o2, o3 = st.columns(3)
            order_no = o1.text_input("주문번호", value=f"SO-{date.today():%Y%m%d}-001")
            cust_name = o2.text_input("고객명", value="롯데마트 평창점")
            cust_code = o3.text_input("고객 코드", value="CUST01")
            o4, o5, o6 = st.columns(3)
            ord_product = o4.selectbox("제품", PRODUCT_CODES, index=2, key="ord_prod",
                                       format_func=lambda c: PRODUCT_META[c]["name"])
            ord_units = o5.number_input("주문 단위 수", min_value=1, value=2000, step=50)
            ship_date = o6.date_input("출하 예정일", value=date.today() + timedelta(days=1))
            addr = st.text_input("배송지", value="강원 평창군 ○○로 12")
            created_by = st.text_input("등록자", value="sales01")
            if st.form_submit_button("📝 주문 등록", use_container_width=True):
                payload = {
                    "order_no": order_no, "customer_name": cust_name,
                    "customer_code": cust_code or None, "ship_date": str(ship_date),
                    "delivery_address": addr, "product_code": ord_product,
                    "ordered_units": int(ord_units), "created_by": created_by,
                }
                res = api_post("/orders", json=payload)
                if res:
                    st.success(f"✅ 주문 등록 완료: {res['order_no']}")

    st.divider()
    sf1, sf2 = st.columns(2)
    flt_ord_status = sf1.selectbox("주문 상태", ["전체"] + list(ORDER_STATUS_BADGE.keys()), key="ord_flt")
    flt_cust = sf2.text_input("고객 코드 필터", value="", key="ord_cust_flt")

    oparams = {"limit": 50}
    if flt_ord_status != "전체":
        oparams["order_status"] = flt_ord_status
    if flt_cust:
        oparams["customer_code"] = flt_cust
    orders = api_get("/orders", params=oparams, default=[])

    if orders:
        ov = [{
            "주문번호": o["order_no"], "고객": o["customer_name"],
            "제품": o.get("product_name", o["product_code"]),
            "주문수": o["ordered_units"], "출하수": o.get("shipped_units", 0),
            "출하일": o["ship_date"],
            "상태": ORDER_STATUS_BADGE.get(o["order_status"], o["order_status"]),
            "승인자": o.get("approved_by") or "-",
        } for o in orders]
        st.dataframe(pd.DataFrame(ov), use_container_width=True, hide_index=True)

        st.markdown("#### 주문 상세 / LOT 할당 / 출하 승인")
        order_map = {f"{o['order_no']} — {o['customer_name']} [{o['order_status']}]": o for o in orders}
        sel_key = st.selectbox("주문 선택", list(order_map.keys()), key="ord_detail_sel")
        sel_order = order_map[sel_key]
        oid = sel_order["order_id"]

        detail = api_get(f"/orders/{oid}", default={})
        if detail:
            d1, d2, d3 = st.columns(3)
            d1.metric("주문 단위", f"{detail.get('ordered_units', 0):,}")
            d2.metric("할당 단위", f"{detail.get('allocated_total_units', 0):,}")
            d3.metric("상태", ORDER_STATUS_BADGE.get(detail.get("order_status"), "-"))

            allocated = detail.get("allocated_lots", [])
            if allocated:
                st.markdown("**할당된 포장 LOT**")
                av = [{
                    "LOT ID": a["lot_id"], "제품": a.get("product_code"),
                    "할당수": a["allocated_units"],
                    "LOT 상태": LOT_STATUS_BADGE.get(a.get("lot_status"), a.get("lot_status")),
                    "발효 LOT": a.get("source_lot_id"),
                } for a in allocated]
                st.dataframe(pd.DataFrame(av), use_container_width=True, hide_index=True)

            # LOT 할당 UI
            ac1, ac2, ac3 = st.columns([2, 1, 1])
            alloc_lot = ac1.text_input("할당할 포장 LOT ID", value="", key=f"alloc_lot_{oid}")
            alloc_units = ac2.number_input("할당 단위", min_value=1, value=1000, step=50, key=f"alloc_u_{oid}")
            if ac3.button("➕ LOT 할당", key=f"alloc_btn_{oid}", use_container_width=True):
                if alloc_lot:
                    res = api_post(f"/orders/{oid}/lots",
                                   json={"lot_id": alloc_lot, "allocated_units": int(alloc_units)})
                    if res:
                        st.success("✅ LOT 할당 완료")
                        st.rerun()

            # 할당 취소
            if allocated:
                dealloc = st.selectbox("할당 취소할 LOT", ["선택 안함"] + [a["lot_id"] for a in allocated],
                                       key=f"dealloc_{oid}")
                if dealloc != "선택 안함" and st.button("🗑️ 할당 취소", key=f"dealloc_btn_{oid}"):
                    if api_delete(f"/orders/{oid}/lots/{dealloc}"):
                        st.success("✅ 할당 취소 완료")
                        st.rerun()

            st.divider()
            # 출하 승인 / 출하 처리 — 권한 체크
            b1, b2 = st.columns(2)
            with b1:
                approve_disabled = not CAN_APPROVE or detail.get("approved_at") is not None
                if st.button("✅ 출하 승인", disabled=approve_disabled,
                             use_container_width=True, key=f"approve_{oid}",
                             help="MANAGER/ADMIN 권한 필요" if not CAN_APPROVE else None):
                    res = api_patch(f"/orders/{oid}/approve", params={"role": USER_ROLE})
                    if res:
                        st.success(f"✅ {res.get('message')} (승인자: {res.get('approved_by')})")
                        st.rerun()
                if not CAN_APPROVE:
                    st.caption("🔒 승인 권한 없음 (현재: " + USER_ROLE + ")")
                elif detail.get("approved_at"):
                    st.caption(f"이미 승인됨: {detail.get('approved_by')}")
            with b2:
                ship_units = st.number_input("출하 단위 수", min_value=0,
                                             value=detail.get("ordered_units", 0),
                                             key=f"ship_u_{oid}")
                ship_disabled = detail.get("approved_at") is None
                if st.button("🚚 출하 처리", disabled=ship_disabled,
                             use_container_width=True, key=f"ship_{oid}",
                             help="먼저 출하 승인 필요" if ship_disabled else None):
                    res = api_patch(f"/orders/{oid}/ship", json={"shipped_units": int(ship_units)})
                    if res:
                        st.success(f"✅ {res.get('message')}")
                        st.rerun()
    else:
        st.info("표시할 출하 주문이 없습니다.")

# ===========================================================================
# 탭 3: LOT 추적 — 전체 체인 타임라인 (입고→절임→발효→포장→출하)
# ===========================================================================
with tabs[2]:
    st.subheader("LOT 완전 역추적")
    st.caption("포장 LOT 또는 출하 주문번호 기준으로 전 공정 LOT 체인을 추적합니다.")

    mode = st.radio("추적 기준", ["포장 LOT ID", "출하 주문"], horizontal=True)

    chains: list[dict] = []
    if mode == "포장 LOT ID":
        trace_lot = st.text_input("포장 LOT ID", value="PK-20260524-001")
        if st.button("🔍 추적 실행", key="trace_lot_btn"):
            res = api_get(f"/trace/{trace_lot}", default=None)
            if res:
                chains = [res]
    else:
        orders = api_get("/orders", params={"limit": 50}, default=[])
        if orders:
            omap = {f"{o['order_no']} — {o['customer_name']}": o["order_id"] for o in orders}
            sel = st.selectbox("출하 주문 선택", list(omap.keys()), key="trace_ord_sel")
            if st.button("🔍 추적 실행", key="trace_ord_btn"):
                res = api_get(f"/trace/by-order/{omap[sel]}", default=None)
                if res:
                    st.info(f"주문 {res['order_no']} — {res['customer_name']} | "
                            f"제품 {res['product_code']} | LOT {res['lot_count']}건")
                    chains = res.get("traces", [])

    # 추적 결과 타임라인 (Plotly Gantt 형태 + 단계별 카드)
    for ci, chain in enumerate(chains):
        steps = chain.get("chain", [])
        if not steps:
            st.warning("추적 가능한 체인이 없습니다.")
            continue
        # 정방향(입고→출하) 정렬
        steps_sorted = sorted(steps, key=lambda s: TRACE_STEPS.get(s["step"], {}).get("order", 99))

        st.markdown(f"### 🔗 {chain.get('packaging_lot_id', '')} 추적 체인")

        # 단계별 진행 카드 (가로 흐름)
        cols = st.columns(len(steps_sorted))
        for col, s in zip(cols, steps_sorted):
            meta = TRACE_STEPS.get(s["step"], {"icon": "•", "label": s["step"], "color": "#888"})
            with col:
                with st.container(border=True):
                    st.markdown(f"<div style='text-align:center;font-size:1.6rem'>{meta['icon']}</div>",
                                unsafe_allow_html=True)
                    st.markdown(f"**{meta['label']}**")
                    st.caption(f"LOT: {s.get('lot_id', '-')}")
                    st.caption(f"일시: {s.get('date', '-') or '-'}")
                    st.caption(f"상태: {s.get('status', '-')}")

        # Plotly 타임라인(Gantt) — 단계별 시점이 있으면 시각화
        gantt_rows = []
        for s in steps_sorted:
            meta = TRACE_STEPS.get(s["step"], {})
            dt = s.get("date")
            if dt:
                try:
                    start = pd.to_datetime(dt)
                    gantt_rows.append({
                        "단계": meta.get("label", s["step"]),
                        "시작": start, "종료": start + pd.Timedelta(hours=6),
                        "LOT": s.get("lot_id", "-"),
                    })
                except Exception:  # noqa: BLE001
                    pass
        if gantt_rows:
            gdf = pd.DataFrame(gantt_rows)
            fig = px.timeline(gdf, x_start="시작", x_end="종료", y="단계", color="단계",
                              text="LOT", title="LOT 추적 타임라인")
            fig.update_yaxes(autorange="reversed")
            fig.update_layout(template="plotly_dark", height=300, showlegend=False,
                              margin=dict(l=40, r=20, t=50, b=30))
            st.plotly_chart(fig, use_container_width=True, key=f"gantt_{ci}")

        # 단계별 상세 detail
        with st.expander("📋 단계별 상세 데이터"):
            for s in steps_sorted:
                meta = TRACE_STEPS.get(s["step"], {})
                st.markdown(f"**{meta.get('icon', '')} {meta.get('label', s['step'])}** — `{s.get('lot_id')}`")
                if s.get("detail"):
                    st.json(s["detail"], expanded=False)
        st.divider()

# ===========================================================================
# 탭 4: 검사결과관리
# ===========================================================================
with tabs[3]:
    st.subheader("포장 검사 등록")
    with st.form("inspection_form"):
        i1, i2, i3 = st.columns(3)
        insp_lot = i1.text_input("포장 LOT ID", value="PK-20260524-003")
        inspector = i2.text_input("검사자", value="정검사")
        insp_date = i3.date_input("검사일", value=date.today())
        i4, i5, i6 = st.columns(3)
        salinity = i4.number_input("염도 (%)", min_value=0.0, value=2.10, step=0.05)
        ph = i5.number_input("pH", min_value=0.0, value=4.30, step=0.05)
        appearance = i6.slider("외관 점수", 1, 5, 5)
        i7, i8, i9 = st.columns(3)
        ferment_level = i7.selectbox("발효 정도", ["FRESH", "MILD", "RIPE", "OVERRIPE"], index=1)
        net_weight = i8.number_input("내용물 중량 (g)", min_value=0.0, value=502.0, step=1.0)
        integrity = i9.checkbox("포장 밀봉 정상", value=True)
        qc_result = st.radio("판정", ["PASS", "FAIL", "HOLD"], horizontal=True)
        fail_reason = st.text_area("불합격 사유 (FAIL/HOLD 시 필수)", value="")
        corrective = st.text_area("조치 사항", value="")

        if st.form_submit_button("💾 검사 결과 등록", use_container_width=True):
            payload = {
                "lot_id": insp_lot, "inspector": inspector,
                "inspection_date": str(insp_date), "salinity_pct": salinity,
                "acidity_ph": ph, "appearance_score": int(appearance),
                "fermentation_level": ferment_level, "net_weight_g": net_weight,
                "packaging_integrity": integrity, "qc_result": qc_result,
                "fail_reason": fail_reason or None, "corrective_action": corrective or None,
            }
            res = api_post("/inspections", json=payload)
            if res:
                st.success(f"✅ 검사 등록 완료 (LOT 상태 → {res.get('lot_status_updated')})")

    st.divider()
    st.markdown("**검사 결과 목록**")
    cf1, cf2 = st.columns(2)
    insp_flt_lot = cf1.text_input("LOT 필터", value="", key="insp_flt_lot")
    insp_flt_result = cf2.selectbox("판정 필터", ["전체", "PASS", "FAIL", "HOLD"], key="insp_flt_result")
    iparams = {"limit": 50}
    if insp_flt_lot:
        iparams["lot_id"] = insp_flt_lot
    if insp_flt_result != "전체":
        iparams["qc_result"] = insp_flt_result
    inspections = api_get("/inspections", params=iparams, default=[])

    if inspections:
        iv = [{
            "LOT ID": i["lot_id"], "검사자": i["inspector"], "검사일": i["inspection_date"],
            "염도(%)": i.get("salinity_pct"), "pH": i.get("acidity_ph"),
            "외관": i.get("appearance_score"), "발효도": i.get("fermentation_level"),
            "중량(g)": i.get("net_weight_g"),
            "밀봉": "✅" if i.get("packaging_integrity") else "⚠️",
            "판정": QC_BADGE.get(i["qc_result"], i["qc_result"]),
        } for i in inspections]
        st.dataframe(pd.DataFrame(iv), use_container_width=True, hide_index=True)

        # 합격/불합격 비율
        rdf = pd.DataFrame(inspections)["qc_result"].value_counts().reset_index()
        rdf.columns = ["판정", "건수"]
        fig = px.pie(rdf, names="판정", values="건수", title="검사 판정 비율", hole=0.4,
                     color="판정", color_discrete_map={"PASS": "#10b981", "FAIL": "#ef4444", "HOLD": "#f59e0b"})
        fig.update_layout(template="plotly_dark", height=300, margin=dict(l=20, r=20, t=50, b=20))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("표시할 검사 결과가 없습니다.")

# ===========================================================================
# 탭 5: 클레임분석
# ===========================================================================
with tabs[4]:
    st.subheader("클레임 관리 / 분석")

    with st.expander("➕ 신규 클레임 등록"):
        with st.form("claim_form"):
            cl1, cl2, cl3 = st.columns(3)
            cl_type = cl1.selectbox("클레임 유형", list(CLAIM_TYPE_KR.keys()),
                                    format_func=lambda t: f"{t} ({CLAIM_TYPE_KR[t]})")
            cl_severity = cl2.selectbox("심각도", list(SEVERITY_KR.keys()), index=1,
                                        format_func=lambda s: f"{s} ({SEVERITY_KR[s]})")
            cl_lot = cl3.text_input("관련 포장 LOT", value="")
            cl_customer = st.text_input("고객명", value="")
            cl_content = st.text_area("클레임 내용", value="")
            if st.form_submit_button("📝 클레임 등록", use_container_width=True):
                if not cl_content:
                    st.warning("클레임 내용을 입력하세요.")
                else:
                    payload = {
                        "claim_type": cl_type, "severity": cl_severity,
                        "lot_id": cl_lot or None, "customer_name": cl_customer or None,
                        "claim_content": cl_content,
                    }
                    res = api_post("/claims", json=payload)
                    if res:
                        st.success(f"✅ 클레임 등록 완료: {res.get('claim_no')}")

    st.divider()
    # 클레임 목록
    clf1, clf2 = st.columns(2)
    flt_cltype = clf1.selectbox("유형 필터", ["전체"] + list(CLAIM_TYPE_KR.keys()), key="cl_flt_type")
    flt_clstatus = clf2.selectbox("상태 필터", ["전체", "OPEN", "INVESTIGATING", "RESOLVED", "CLOSED"], key="cl_flt_status")
    clparams = {"limit": 50}
    if flt_cltype != "전체":
        clparams["claim_type"] = flt_cltype
    if flt_clstatus != "전체":
        clparams["status"] = flt_clstatus
    claims = api_get("/claims", params=clparams, default=[])

    if claims:
        clv = [{
            "클레임번호": c.get("claim_no"), "유형": CLAIM_TYPE_KR.get(c["claim_type"], c["claim_type"]),
            "심각도": SEVERITY_KR.get(c.get("severity"), c.get("severity")),
            "고객": c.get("customer_name"), "LOT": c.get("lot_id"),
            "접수일": c["claim_date"], "상태": c["status"],
        } for c in claims]
        st.dataframe(pd.DataFrame(clv), use_container_width=True, hide_index=True)

        # 클레임 상세/업데이트
        with st.expander("🔧 클레임 원인분석 / 조치 입력"):
            cmap = {f"{c.get('claim_no')} — {CLAIM_TYPE_KR.get(c['claim_type'])}": c for c in claims}
            sel = st.selectbox("클레임 선택", list(cmap.keys()), key="claim_upd_sel")
            target = cmap[sel]
            root = st.text_area("원인 분석", value=target.get("root_cause") or "", key="cl_root")
            action = st.text_area("조치 사항", value=target.get("corrective_action") or "", key="cl_action")
            prevent = st.text_area("재발 방지", value=target.get("recurrence_prevention") or "", key="cl_prevent")
            new_status = st.selectbox("상태 변경", ["OPEN", "INVESTIGATING", "RESOLVED", "CLOSED"],
                                      index=["OPEN", "INVESTIGATING", "RESOLVED", "CLOSED"].index(target["status"]),
                                      key="cl_status")
            resolver = st.text_input("처리자", value="qc01", key="cl_resolver")
            if st.button("💾 클레임 업데이트", key="cl_upd_btn"):
                payload = {
                    "root_cause": root or None, "corrective_action": action or None,
                    "recurrence_prevention": prevent or None, "status": new_status,
                    "resolved_by": resolver or None,
                }
                res = api_patch(f"/claims/{target['claim_id']}", json=payload)
                if res:
                    st.success("✅ 클레임 업데이트 완료")
                    st.rerun()
    else:
        st.info("표시할 클레임이 없습니다.")

    st.divider()
    st.markdown("#### 클레임 유형별 분석 (최근 90일)")
    analysis = api_get("/claims/analysis/summary", params={"days": 90}, default={})
    if analysis and analysis.get("by_type"):
        by_type = analysis["by_type"]
        monthly = analysis.get("monthly_trend", [])
        ca, cb = st.columns(2)
        with ca:
            tdf = pd.DataFrame(by_type)
            tdf["유형"] = tdf["claim_type"].map(lambda t: CLAIM_TYPE_KR.get(t, t))
            fig = px.pie(tdf, names="유형", values="claim_count", title="클레임 유형별 비율", hole=0.4)
            fig.update_layout(template="plotly_dark", height=320, margin=dict(l=20, r=20, t=50, b=20))
            st.plotly_chart(fig, use_container_width=True)
        with cb:
            if monthly:
                mdf = pd.DataFrame(monthly)
                fig2 = go.Figure(go.Bar(x=mdf["month"], y=mdf["claim_count"], marker_color="#ef4444"))
                fig2.update_layout(template="plotly_dark", height=320, title="월별 클레임 추세",
                                   margin=dict(l=40, r=20, t=50, b=40))
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("월별 추세 데이터 없음")
        st.caption(f"최근 90일 총 클레임: {analysis.get('total_claims', 0)}건")
    else:
        st.info("클레임 분석 데이터가 없습니다.")

# ===========================================================================
# 탭 6: 출하 AI Agent — Chat UI (agent_type=SHIPPING)
# ===========================================================================
with tabs[5]:
    st.subheader("🤖 출하 AI Agent")
    st.caption("출하 승인 기준, LOT 추적, 클레임 원인 분석을 자연어로 질의하세요.")

    EXAMPLES = ["이번 달 출하 LOT 추적", "클레임 발생 원인 분석", "출하 승인 기준 확인"]
    ec = st.columns(len(EXAMPLES))
    for col, ex in zip(ec, EXAMPLES):
        if col.button(ex, key=f"ex_{ex}", use_container_width=True):
            st.session_state["ship_agent_pending"] = ex

    if "ship_chat" not in st.session_state:
        st.session_state["ship_chat"] = []

    for msg in st.session_state["ship_chat"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            for doc in msg.get("docs", []):
                st.caption(f"📄 참조: {doc.get('title')} ({doc.get('doc_type')}, score={doc.get('score')})")

    user_input = st.chat_input("출하 관련 질문을 입력하세요...")
    pending = st.session_state.pop("ship_agent_pending", None)
    query = user_input or pending

    if query:
        st.session_state["ship_chat"].append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)

        with st.chat_message("assistant"):
            with st.spinner("AI Agent 분석 중..."):
                payload = {"query": query, "agent_type": "SHIPPING"}
                res = api_post("/query", json=payload, base=AGENT_BASE)
            if res:
                answer = res.get("response_text", "응답을 받지 못했습니다.")
                docs = res.get("referenced_docs", [])
                st.markdown(answer)
                for doc in docs:
                    st.caption(f"📄 참조: {doc.get('title')} ({doc.get('doc_type')}, score={doc.get('score')})")
                st.session_state["ship_chat"].append(
                    {"role": "assistant", "content": answer, "docs": docs}
                )
            else:
                fallback = (
                    "⚠️ AI Agent 서버에 연결할 수 없습니다. "
                    "AI Server(LangChain/LangGraph)가 기동 중인지 확인하세요.\n\n"
                    f"(질의: {query})"
                )
                st.markdown(fallback)
                st.session_state["ship_chat"].append({"role": "assistant", "content": fallback})
