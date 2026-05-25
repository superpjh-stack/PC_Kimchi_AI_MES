import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import httpx
import streamlit as st
from datetime import datetime
from components.styles import apply_styles, metric_card, status_badge, section_header
from components.sidebar import render_sidebar

st.set_page_config(page_title="꽃순이김치 MES", page_icon="🥬", layout="wide")
apply_styles()
render_sidebar()  # Home page는 current="" (홈)

# API 기본 URL
_API_BASE = os.getenv("API_BASE_URL", "http://localhost:8001")

# 세션 상태 초기화
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "user_id" not in st.session_state:
    st.session_state["user_id"] = ""
if "user_role" not in st.session_state:
    st.session_state["user_role"] = ""
if "user_roles" not in st.session_state:
    st.session_state["user_roles"] = []
if "access_token" not in st.session_state:
    st.session_state["access_token"] = ""


def _do_login(username: str, password: str) -> None:
    """
    FastAPI /api/v1/system/auth/login 호출 → JWT 토큰 + 사용자 정보 세션 저장.
    성공: 세션 설정 후 rerun.
    실패: st.error 메시지 표시.
    """
    try:
        resp = httpx.post(
            f"{_API_BASE}/api/v1/system/auth/login",
            json={"username": username, "password": password},
            timeout=5.0,
        )
    except httpx.RequestError:
        st.error("서버에 연결할 수 없습니다. FastAPI 서버가 실행 중인지 확인해 주세요.")
        return

    if resp.status_code == 200:
        data = resp.json()
        roles: list[str] = data.get("user", {}).get("roles", [])
        st.session_state["logged_in"] = True
        st.session_state["access_token"] = data["access_token"]
        st.session_state["user_id"] = data["user"]["username"]
        st.session_state["user_roles"] = roles
        # 단일 역할 문자열 하위 호환 (pages/*.py 일부가 user_role 참조)
        st.session_state["user_role"] = roles[0] if roles else "OPERATOR"
        st.rerun()
    elif resp.status_code == 401:
        st.error("아이디 또는 비밀번호가 잘못되었습니다.")
    else:
        st.error(f"로그인 오류 (HTTP {resp.status_code})")


def render_login():
    """로그인 화면"""
    st.markdown(
        """
        <div style="text-align:center; padding:24px 0 8px 0;">
            <div style="width:56px;height:56px;background:#C53D2E;border-radius:12px;
                        display:inline-grid;place-items:center;font-size:30px;font-weight:700;
                        color:#F4EFE6;font-family:'Noto Serif KR',serif;">花</div>
            <div style="font-size:26px; font-weight:700; color:#29261b; margin-top:12px;">
                평창꽃순이김치 제조AI 스마트공장 MES
            </div>
            <div style="font-size:14px; color:#7B7670; margin-top:6px;">
                평창꽃순이(주)농업회사법인 · IoT + MES + AI 통합 제조 시스템
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_l, col_c, col_r = st.columns([1, 1.2, 1])
    with col_c:
        st.markdown('<div class="mes-card">', unsafe_allow_html=True)
        section_header("로그인", "🔐")
        with st.form("login_form", clear_on_submit=False):
            user_id = st.text_input("사용자 ID", placeholder="아이디를 입력하세요")
            password = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")
            submitted = st.form_submit_button("로그인", use_container_width=True)

        if submitted:
            if not user_id.strip():
                st.warning("사용자 ID를 입력해 주세요.")
            elif not password:
                st.warning("비밀번호를 입력해 주세요.")
            else:
                _do_login(user_id.strip(), password)

        # ── 퀵로그인 버튼 (개발용) ──────────────────────────────────
        st.markdown(
            "<div style='margin:12px 0 4px 0; text-align:center; "
            "font-size:11px; color:#A8A39E; letter-spacing:.5px;'>— 개발 퀵로그인 —</div>",
            unsafe_allow_html=True,
        )
        qa, qb, qc, qd = st.columns(4)
        quick_accounts = [
            ("⚡ admin",    "admin",    "Admin1234!"),
            ("🏭 공장장",   "manager1", "Manager1234!"),
            ("🔬 품질",     "quality1", "Quality1234!"),
            ("👷 작업자",   "operator1","Operator1234!"),
        ]
        for col, (label, uname, pwd) in zip([qa, qb, qc, qd], quick_accounts):
            with col:
                if st.button(label, use_container_width=True, key=f"quick_{uname}"):
                    _do_login(uname, pwd)

        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown(
            "<div style='text-align:center; font-size:11px; color:#A8A39E; margin-top:12px;'>"
            "로뎀솔루션 주식회사 · SF26179540 · 2026</div>",
            unsafe_allow_html=True,
        )


def render_home():
    """로그인 후 메인 진입점"""
    st.markdown(
        f"""
        <div class="page-header">
            <div>
                <div class="page-title">평창꽃순이김치 제조AI MES</div>
                <div class="page-desc">IoT + MES + AI 통합 제조 시스템 · AI MES v2.4</div>
            </div>
            <div style="font-size:13px; color:#7B7670;">{datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.success(
        f"환영합니다, **{st.session_state['user_id']}** 님 ({st.session_state['user_role']}). "
        "좌측 사이드바의 **AI 대시보드** 메뉴에서 생산·품질·발효·출하 현황을 확인하세요."
    )

    st.markdown("<br>", unsafe_allow_html=True)
    section_header("시스템 현황 요약", "📊")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card("오늘 생산량", "3,024 kg/h", delta="목표 3,000 대비 +0.8%", color="#4C9B52", target="3,000 kg/h")
    with c2:
        metric_card("발효 진행 중", "12 LOT", color="#3F8C9C")
    with c3:
        metric_card("이상발효 알림", "1 건", color="#C53D2E")
    with c4:
        metric_card("오늘 출하", "8 건", color="#29261b")

    st.markdown("<br>", unsafe_allow_html=True)

    g1, g2 = st.columns(2)
    with g1:
        st.markdown(
            """
            <div class="mes-card">
                <div class="mes-card-title">🏭 제조 공정 흐름</div>
                <div style="color:#4A4640; font-size:13px; line-height:2.0; margin-top:8px;">
                    입고/보관 → 절단/전처리 → 세척/절임 → 세척/선별 → 탈수 →
                    혼합 → <span style="color:#C53D2E; font-weight:600;">숙성/발효 (AI)</span> → 금속검출 →
                    <span style="color:#C53D2E; font-weight:600;">포장/출하 (AI)</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with g2:
        st.markdown(
            """
            <div class="mes-card">
                <div class="mes-card-title">🤖 AI 모듈 현황</div>
                <div style="color:#4A4640; font-size:13px; line-height:2.1; margin-top:8px;">
                    · ML 엔진 (숙성/발효 품질 예측) — <span class="badge badge-green">✓ 정상</span><br>
                    · 입고 RAG Agent — <span class="badge badge-green">✓ 정상</span><br>
                    · 출하 RAG Agent — <span class="badge badge-green">✓ 정상</span><br>
                    · Data Gateway (LOT 추적) — <span class="badge badge-green">✓ 정상</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)
    section_header("바로가기", "🧭")
    q1, q2, q3 = st.columns(3)
    with q1:
        st.page_link("pages/01_AI대시보드.py", label="📊 AI 대시보드", use_container_width=True)
    with q2:
        st.page_link("pages/07_KPI관리.py", label="📈 KPI 관리", use_container_width=True)
    with q3:
        st.page_link("pages/10_AI_Agent통합관리.py", label="🤖 AI Agent 통합관리", use_container_width=True)


# 라우팅
if st.session_state["logged_in"]:
    render_home()
else:
    render_login()
