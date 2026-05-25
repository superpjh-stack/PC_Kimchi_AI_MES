"""
꽃순이김치 제조AI MES — 기준정보관리 화면 (08_master)
Project : SF26179540 | 평창꽃순이(주) | 로뎀솔루션
Module  : 기준정보관리 (품질 기준 / 작업표준(SOP) / 코드 관리 / 공급업체)
Mockup  : docs/02-design/mockups/07-master-system.html
Stack   : Streamlit + httpx (FastAPI /api/v1/master 연동)

실행: streamlit run app/pages/08_master.py
"""
from __future__ import annotations

import time

import httpx
import pandas as pd
import streamlit as st

# =============================================================================
# 설정 / API 클라이언트
# =============================================================================
st.set_page_config(page_title="기준정보관리", layout="wide")

BASE_URL = "http://localhost:8000/api/v1/master"

# 공정 코드 라벨 (UI 표시용)
PROCESS_LABELS = {
    "PROC01": "입고/보관", "PROC02": "절단/전처리", "PROC03": "세척/절임",
    "PROC04": "세척/선별", "PROC05": "탈수", "PROC06": "혼합",
    "PROC07": "숙성/발효", "PROC08": "금속검출", "PROC09": "포장/출하",
}
DOC_TYPE_LABELS = {
    "SOP": "작업표준(SOP)", "QC_STANDARD": "품질기준서", "HACCP": "HACCP",
    "EQUIPMENT_MANUAL": "설비매뉴얼", "CLAIM_RESPONSE": "클레임대응",
}
CODE_GROUPS = ["PROCESS", "PRODUCT", "DEFECT", "MATERIAL", "SUPPLIER", "UNIT"]
GRADES = ["A", "B", "C", "D"]

# 권한: 관리자/품질담당자만 편집 가능 (품질기준·SOP·공급업체)
# 코드관리(tab_code)는 §8.1 기준 관리자 전용
CURRENT_ROLE = st.session_state.get("user_role", "관리자")
CAN_EDIT = CURRENT_ROLE in ("관리자", "품질담당자")
CAN_EDIT_CODE = CURRENT_ROLE in ("관리자",)  # §8.1: 코드관리는 관리자 전용


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=30.0)


def api_get(path: str, params: dict | None = None):
    try:
        r = _client().get(path, params=params or {})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.warning(f"조회 실패: {e}")
        return []


def api_post(path: str, json: dict):
    try:
        r = _client().post(path, json=json)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"등록 실패: {e}")
        return None


def api_put(path: str, json: dict | None = None, params: dict | None = None):
    try:
        r = _client().put(path, json=json, params=params or {})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"수정 실패: {e}")
        return None


def api_delete(path: str):
    try:
        r = _client().delete(path)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"삭제 실패: {e}")
        return None


st.title("기준정보관리")
if not CAN_EDIT:
    st.info(f"현재 역할({CURRENT_ROLE})은 조회 전용입니다. 편집은 관리자/품질담당자만 가능합니다.")

tab_qs, tab_sop, tab_code, tab_sup = st.tabs(
    ["품질 기준", "작업표준(SOP)", "코드 관리", "공급업체"]
)


# =============================================================================
# 탭 1: 품질 기준
# =============================================================================
def _range_style(row: pd.Series):
    """정상 범위는 초록, 경고 범위는 주황으로 셀 배경 색상"""
    styles = [""] * len(row)
    cols = list(row.index)
    for c in ("normal_min", "normal_max"):
        if c in cols:
            styles[cols.index(c)] = "background-color: rgba(0,200,83,.15)"
    for c in ("warning_min", "warning_max"):
        if c in cols:
            styles[cols.index(c)] = "background-color: rgba(255,152,0,.15)"
    return styles


with tab_qs:
    st.subheader("공정별 품질 기준")
    c1, c2 = st.columns([1, 1])
    with c1:
        proc_opt = ["전체"] + list(PROCESS_LABELS.keys())
        sel_proc = st.selectbox(
            "공정 선택", proc_opt,
            format_func=lambda x: "전체 공정" if x == "전체" else f"{x} {PROCESS_LABELS.get(x, '')}",
        )
    with c2:
        only_active = st.checkbox("활성 기준만 표시", value=True)

    params = {}
    if sel_proc != "전체":
        params["process_code"] = sel_proc
    if only_active:
        params["is_active"] = True
    qs_rows = api_get("/quality-standards", params)

    if qs_rows:
        df = pd.DataFrame(qs_rows)
        show_cols = [
            "id", "process_code", "standard_item", "normal_min", "normal_max",
            "warning_min", "warning_max", "unit", "measurement_method", "is_active",
        ]
        show_cols = [c for c in show_cols if c in df.columns]
        st.dataframe(
            df[show_cols].style.apply(_range_style, axis=1),
            use_container_width=True, hide_index=True,
        )
    else:
        st.caption("표시할 품질 기준이 없습니다.")

    if CAN_EDIT:
        st.divider()
        st.markdown("**품질 기준 등록 / 수정**")
        mode = st.radio("모드", ["신규 등록", "수정"], horizontal=True, key="qs_mode")
        with st.form("qs_form", clear_on_submit=False):
            fc1, fc2 = st.columns(2)
            with fc1:
                f_proc = st.selectbox(
                    "공정", list(PROCESS_LABELS.keys()),
                    format_func=lambda x: f"{x} {PROCESS_LABELS[x]}",
                )
                f_item = st.text_input("기준 항목", placeholder="예: 발효 pH")
                f_unit = st.text_input("단위", placeholder="예: pH, %, °C")
                f_method = st.text_input("측정 방법", placeholder="예: IoT 센서")
            with fc2:
                f_nmin = st.number_input("정상 하한", value=0.0, format="%.3f")
                f_nmax = st.number_input("정상 상한", value=0.0, format="%.3f")
                f_wmin = st.number_input("경고 하한", value=0.0, format="%.3f")
                f_wmax = st.number_input("경고 상한", value=0.0, format="%.3f")
            edit_id = None
            if mode == "수정":
                edit_id = st.number_input("수정 대상 id", min_value=1, step=1)
            submitted = st.form_submit_button("저장", type="primary")
            if submitted:
                payload = {
                    "process_code": f_proc, "standard_item": f_item,
                    "normal_min": f_nmin, "normal_max": f_nmax,
                    "warning_min": f_wmin, "warning_max": f_wmax,
                    "unit": f_unit, "measurement_method": f_method,
                }
                if mode == "신규 등록":
                    if api_post("/quality-standards", payload):
                        st.success("품질 기준이 등록되었습니다."); st.rerun()
                else:
                    if api_put(f"/quality-standards/{int(edit_id)}", payload):
                        st.success("품질 기준이 수정되었습니다."); st.rerun()


# =============================================================================
# 탭 2: 작업표준(SOP)
# =============================================================================
with tab_sop:
    st.subheader("작업표준서 (SOP) / Vector DB 임베딩")
    sc1, sc2 = st.columns([1, 1])
    with sc1:
        dt_opt = ["전체"] + list(DOC_TYPE_LABELS.keys())
        sel_dt = st.selectbox(
            "문서 유형", dt_opt,
            format_func=lambda x: "전체 분류" if x == "전체" else DOC_TYPE_LABELS.get(x, x),
        )
    with sc2:
        sop_only_active = st.checkbox("활성 문서만 표시", value=False, key="sop_active")

    sop_params = {}
    if sel_dt != "전체":
        sop_params["doc_type"] = sel_dt
    if sop_only_active:
        sop_params["is_active"] = True
    sop_rows = api_get("/sop-documents", sop_params)

    left, right = st.columns([3, 2])

    # --- 문서 목록 + 뷰어 ---
    with left:
        st.markdown("**문서 목록**")
        if sop_rows:
            for d in sop_rows:
                badge = {
                    "PENDING": "🕓 대기", "PROCESSING": "⏳ 처리중",
                    "COMPLETED": "✅ 완료", "FAILED": "❌ 실패",
                }.get(d.get("embed_status"), d.get("embed_status"))
                active = "🟢 활성" if d.get("is_active") else "⚪ 비활성"
                with st.expander(f"{d['title']} ({d.get('version')}) — {active}"):
                    st.write(f"문서ID: `{d['doc_id']}`")
                    st.write(f"유형: {DOC_TYPE_LABELS.get(d['doc_type'], d['doc_type'])}")
                    st.write(f"공정: {', '.join(d.get('process_codes') or []) or '-'}")
                    st.write(f"임베딩 상태: {badge} (chunk {d.get('chunk_count', 0)}개)")
                    st.write(f"파일: {d.get('file_path') or '-'}")
                    # 문서 뷰어 (PDF 경로가 URL이면 iframe, 아니면 안내)
                    fp = d.get("file_path") or ""
                    if fp.startswith("http"):
                        st.components.v1.iframe(fp, height=300)
                    else:
                        st.caption("문서 뷰어: 서버 파일 경로는 다운로드 API 연동 필요")
                    if CAN_EDIT:
                        bc1, bc2, bc3 = st.columns(3)
                        with bc1:
                            if st.button("임베딩 재처리", key=f"emb_{d['doc_id']}"):
                                if api_post(f"/sop-documents/{d['doc_id']}/embed", {}) is not None:
                                    st.success("임베딩 시작"); st.rerun()
                        with bc2:
                            if d.get("embed_status") == "COMPLETED" and not d.get("is_active"):
                                if st.button("활성화", key=f"act_{d['doc_id']}"):
                                    if api_put(
                                        f"/sop-documents/{d['doc_id']}/activate",
                                        params={"approved_by": CURRENT_ROLE},
                                    ):
                                        st.success("활성화됨 (이전 버전 비활성화)"); st.rerun()
                        with bc3:
                            if st.button("폐기", key=f"del_{d['doc_id']}"):
                                if api_delete(f"/sop-documents/{d['doc_id']}"):
                                    st.success("폐기됨"); st.rerun()
        else:
            st.caption("표시할 문서가 없습니다.")

        # --- 버전 이력 (동일 title 그룹핑) ---
        if sop_rows:
            st.markdown("**버전 이력**")
            hist = pd.DataFrame(sop_rows)[
                ["title", "version", "is_active", "embed_status", "approved_at"]
            ].sort_values(["title", "version"])
            st.dataframe(hist, use_container_width=True, hide_index=True)

    # --- 업로드 + 임베딩 진행 ---
    with right:
        st.markdown("**문서 등록 / 임베딩**")
        if not CAN_EDIT:
            st.caption("관리자/품질담당자만 업로드할 수 있습니다.")
        else:
            with st.form("sop_upload", clear_on_submit=True):
                up_file = st.file_uploader("파일 첨부 (PDF/DOCX)", type=["pdf", "docx"])
                up_title = st.text_input("문서명", placeholder="예: 발효관리기준서")
                up_type = st.selectbox(
                    "분류", list(DOC_TYPE_LABELS.keys()),
                    format_func=lambda x: DOC_TYPE_LABELS[x],
                )
                up_version = st.text_input("버전", value="v1.0")
                up_procs = st.multiselect(
                    "해당 공정", list(PROCESS_LABELS.keys()),
                    format_func=lambda x: f"{x} {PROCESS_LABELS[x]}",
                )
                up_auto = st.checkbox("업로드 즉시 임베딩(pgvector)", value=True)
                up_submit = st.form_submit_button("등록 및 임베딩 시작", type="primary")

            if up_submit:
                if not up_file or not up_title:
                    st.error("파일과 문서명을 입력하세요.")
                else:
                    files = {"file": (up_file.name, up_file.getvalue())}
                    data = {
                        "doc_type": up_type, "title": up_title, "version": up_version,
                        "process_codes": ",".join(up_procs),
                        "created_by": CURRENT_ROLE, "auto_embed": str(up_auto).lower(),
                    }
                    try:
                        r = _client().post("/sop-documents/upload", data=data, files=files)
                        r.raise_for_status()
                        res = r.json()
                        st.success(f"업로드 완료: {res['document']['doc_id']}")
                        # 임베딩 처리 상태 progress bar (상태 폴링)
                        if res.get("embedding_started"):
                            doc_id = res["document"]["doc_id"]
                            prog = st.progress(0, text="임베딩 처리 중...")
                            for i in range(20):
                                time.sleep(1)
                                docs = api_get("/sop-documents", {"doc_type": up_type})
                                cur = next((x for x in docs if x["doc_id"] == doc_id), None)
                                stt = cur.get("embed_status") if cur else "PENDING"
                                if stt == "COMPLETED":
                                    prog.progress(100, text=f"완료 (chunk {cur['chunk_count']}개)")
                                    break
                                if stt == "FAILED":
                                    prog.progress(100, text="임베딩 실패")
                                    break
                                prog.progress(min((i + 1) * 5, 95), text=f"임베딩 처리 중... ({stt})")
                        st.rerun()
                    except Exception as e:
                        st.error(f"업로드 실패: {e}")


# =============================================================================
# 탭 3: 코드 관리
# =============================================================================
with tab_code:
    st.subheader("코드 관리")
    sel_group = st.selectbox("코드 그룹", CODE_GROUPS, key="code_group_sel")
    codes = api_get("/codes", {"code_group": sel_group})

    if codes:
        df = pd.DataFrame(codes)[
            ["code", "code_name", "code_name_en", "sort_order", "is_active", "description"]
        ]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("해당 그룹에 코드가 없습니다.")

    # §8.1: 코드관리 편집은 관리자 전용 (품질담당자는 조회만)
    if not CAN_EDIT_CODE:
        st.info("코드 관리 편집은 관리자 전용입니다.")
    if CAN_EDIT_CODE:
        st.divider()
        ec1, ec2 = st.columns(2)

        # 신규 등록
        with ec1:
            st.markdown("**신규 코드 등록**")
            with st.form("code_create", clear_on_submit=True):
                n_code = st.text_input("코드값", placeholder="예: PROC10")
                n_name = st.text_input("코드명")
                n_name_en = st.text_input("코드명(영문)")
                n_sort = st.number_input("순서", min_value=0, step=1, value=0)
                n_desc = st.text_input("설명")
                if st.form_submit_button("등록", type="primary"):
                    payload = {
                        "code_group": sel_group, "code": n_code, "code_name": n_name,
                        "code_name_en": n_name_en or None, "sort_order": int(n_sort),
                        "description": n_desc or None,
                    }
                    if api_post("/codes", payload):
                        st.success("코드가 등록되었습니다."); st.rerun()

        # 수정 / 삭제
        with ec2:
            st.markdown("**코드 수정 / 삭제**")
            code_vals = [c["code"] for c in codes] if codes else []
            if code_vals:
                with st.form("code_edit", clear_on_submit=False):
                    sel_code = st.selectbox("대상 코드", code_vals)
                    cur = next((c for c in codes if c["code"] == sel_code), {})
                    u_name = st.text_input("코드명", value=cur.get("code_name", ""))
                    u_sort = st.number_input("순서", value=int(cur.get("sort_order", 0)), step=1)
                    u_active = st.checkbox("활성", value=bool(cur.get("is_active", True)))
                    bc1, bc2 = st.columns(2)
                    do_update = bc1.form_submit_button("수정", type="primary")
                    do_delete = bc2.form_submit_button("삭제(비활성)")
                    if do_update:
                        payload = {"code_name": u_name, "sort_order": int(u_sort), "is_active": u_active}
                        if api_put(f"/codes/{sel_group}/{sel_code}", payload):
                            st.success("수정 완료"); st.rerun()
                    if do_delete:
                        if api_delete(f"/codes/{sel_group}/{sel_code}"):
                            st.success("삭제(비활성) 완료"); st.rerun()
            else:
                st.caption("수정할 코드가 없습니다.")


# =============================================================================
# 탭 4: 공급업체
# =============================================================================
with tab_sup:
    st.subheader("공급업체 관리")
    pc1, pc2 = st.columns([1, 1])
    with pc1:
        grade_opt = ["전체"] + GRADES
        sel_grade = st.selectbox("품질 등급 필터", grade_opt)
    with pc2:
        sup_only_active = st.checkbox("활성 업체만 표시", value=True, key="sup_active")

    sup_params = {}
    if sel_grade != "전체":
        sup_params["quality_grade"] = sel_grade
    if sup_only_active:
        sup_params["is_active"] = True
    suppliers = api_get("/suppliers", sup_params)

    if suppliers:
        df = pd.DataFrame(suppliers)[
            ["supplier_id", "supplier_code", "supplier_name", "contact",
             "material_types", "quality_grade", "is_active"]
        ]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("표시할 공급업체가 없습니다.")

    if CAN_EDIT:
        st.divider()
        gc1, gc2 = st.columns(2)

        # 등록
        with gc1:
            st.markdown("**공급업체 등록**")
            with st.form("sup_create", clear_on_submit=True):
                s_code = st.text_input("공급업체 코드", placeholder="예: SUP-004")
                s_name = st.text_input("공급업체명")
                s_contact = st.text_input("연락처")
                s_addr = st.text_input("주소")
                s_mats = st.text_input("공급 원재료(콤마 구분)", placeholder="MAT-BC,MAT-MU")
                s_grade = st.selectbox("품질 등급", GRADES)
                if st.form_submit_button("등록", type="primary"):
                    payload = {
                        "supplier_code": s_code, "supplier_name": s_name,
                        "contact": s_contact or None, "address": s_addr or None,
                        "material_types": [m.strip() for m in s_mats.split(",") if m.strip()],
                        "quality_grade": s_grade,
                    }
                    if api_post("/suppliers", payload):
                        st.success("공급업체가 등록되었습니다."); st.rerun()

        # 수정
        with gc2:
            st.markdown("**공급업체 수정**")
            if suppliers:
                with st.form("sup_edit", clear_on_submit=False):
                    names = {s["supplier_id"]: s["supplier_name"] for s in suppliers}
                    sid = st.selectbox(
                        "대상 업체", list(names.keys()),
                        format_func=lambda x: f"{names[x]} (id={x})",
                    )
                    cur = next((s for s in suppliers if s["supplier_id"] == sid), {})
                    u_name = st.text_input("공급업체명", value=cur.get("supplier_name", ""))
                    u_contact = st.text_input("연락처", value=cur.get("contact") or "")
                    u_grade = st.selectbox(
                        "품질 등급", GRADES,
                        index=GRADES.index(cur.get("quality_grade", "B"))
                        if cur.get("quality_grade") in GRADES else 1,
                    )
                    u_active = st.checkbox("활성", value=bool(cur.get("is_active", True)))
                    if st.form_submit_button("수정", type="primary"):
                        payload = {
                            "supplier_name": u_name, "contact": u_contact or None,
                            "quality_grade": u_grade, "is_active": u_active,
                        }
                        if api_put(f"/suppliers/{sid}", payload):
                            st.success("수정 완료"); st.rerun()
            else:
                st.caption("수정할 공급업체가 없습니다.")
