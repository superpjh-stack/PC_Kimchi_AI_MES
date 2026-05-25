"""
꽃순이김치 MES — 커스텀 사이드바 컴포넌트
로고 / 아코디언 메뉴 / 접속자 정보 + 로그아웃
"""
from __future__ import annotations
import streamlit as st

MENU_ITEMS = [
    {
        "id": "dashboard",
        "label": "AI 대시보드",
        "icon": "📊",
        "page": "pages/01_AI대시보드.py",
        "sub": [
            ("생산현황 분석", "📈", 0),
            ("품질현황 분석", "🔍", 1),
            ("발효상태 모니터링", "🌡️", 2),
            ("출하현황 분석", "🚚", 3),
        ],
    },
    {
        "id": "material",
        "label": "원재료관리",
        "icon": "🌿",
        "page": "pages/02_원재료관리.py",
        "sub": [
            ("입고관리", "📥", 0),
            ("원재료 이력조회", "🔍", 1),
            ("선별 데이터관리", "📋", 2),
            ("공급처 품질분석", "📊", 3),
            ("입고 AI Agent", "🤖", 4),
        ],
    },
    {
        "id": "fermentation",
        "label": "숙성발효관리",
        "icon": "🌡️",
        "page": "pages/03_숙성발효관리.py",
        "sub": [
            ("발효상태 모니터링", "🔭", 0),
            ("품질예측결과", "🔮", 1),
            ("발효완료예측", "⏱️", 2),
            ("이상발효알림", "🚨", 3),
            ("ML분석", "🧠", 4),
            ("영향요인 분석", "📉", 5),
        ],
    },
    {
        "id": "shipping",
        "label": "포장출하관리",
        "icon": "📦",
        "page": "pages/04_포장출하관리.py",
        "sub": [
            ("포장실적관리", "🏭", 0),
            ("출하관리", "🚚", 1),
            ("LOT추적", "🔗", 2),
            ("검사결과관리", "✅", 3),
            ("클레임분석", "⚠️", 4),
            ("출하 AI Agent", "🤖", 5),
        ],
    },
    {
        "id": "process",
        "label": "공정관리",
        "icon": "⚙️",
        "page": "pages/05_공정관리.py",
        "sub": [
            ("공정실적관리", "📊", 0),
            ("공정 데이터 모니터링", "📡", 1),
            ("레시피 관리", "📝", 2),
            ("공정이력조회", "🔍", 3),
            ("공정데이터 분석", "📈", 4),
        ],
    },
    {
        "id": "data",
        "label": "데이터관리",
        "icon": "💾",
        "page": "pages/06_데이터관리.py",
        "sub": [
            ("데이터통합관리", "🗄️", 0),
            ("데이터조회", "🔍", 1),
            ("데이터시각화", "📊", 2),
            ("데이터다운로드", "⬇️", 3),
            ("AI학습 데이터관리", "🧠", 4),
        ],
    },
    {
        "id": "kpi",
        "label": "KPI관리",
        "icon": "📈",
        "page": "pages/07_KPI관리.py",
        "sub": [
            ("KPI 현황", "📊", 0),
            ("생산성 분석", "🏭", 1),
            ("품질 분석", "🔬", 2),
            ("KPI 설정", "⚙️", 3),
            ("리포트", "📄", 4),
        ],
    },
    {
        "id": "master",
        "label": "기준정보관리",
        "icon": "📋",
        "page": "pages/08_기준정보관리.py",
        "sub": [
            ("품질기준 관리", "✅", 0),
            ("작업표준 관리", "📝", 1),
            ("코드관리", "🔢", 2),
        ],
    },
    {
        "id": "system",
        "label": "시스템관리",
        "icon": "🔧",
        "page": "pages/09_시스템관리.py",
        "sub": [
            ("사용자 관리", "👥", 0),
            ("로그 관리", "📜", 1),
            ("알림 설정", "🔔", 2),
            ("시스템 설정", "⚙️", 3),
        ],
    },
    {
        "id": "agent",
        "label": "AI Agent 통합관리",
        "icon": "🤖",
        "page": "pages/10_AI_Agent통합관리.py",
        "sub": [
            ("통합 AI질의", "💬", 0),
            ("생산/품질 분석", "📊", 1),
            ("의사결정 지원", "🎯", 1),
            ("알림 및 추천", "🔔", 2),
            ("사용자 질문이력", "📚", 0),
        ],
    },
]

_ROLE_COLOR = {
    "ADMIN": "#E8A89F",
    "MANAGER": "#D97A2B",
    "QUALITY": "#7FC2D0",
    "OPERATOR": "#8FCB93",
}


def render_sidebar(current: str = "") -> None:
    """
    커스텀 사이드바 렌더링.
    Parameters
    ----------
    current : str
        현재 페이지 메뉴 id (예: "material"). 해당 항목이 자동으로 펼쳐짐.
    """
    if not st.session_state.get("logged_in"):
        return

    with st.sidebar:
        # ── ① 브랜드 마크 (花) ─────────────────────────────────
        st.markdown(
            """
            <div class="sb-brand">
                <div class="sb-brand-mark">花</div>
                <div class="sb-brand-text">
                    <div class="sb-brand-name">평창꽃순이김치</div>
                    <div class="sb-brand-sub">AI MES v2.4</div>
                </div>
            </div>
            <div class="sb-divider"></div>
            """,
            unsafe_allow_html=True,
        )

        # ── ② 메뉴 ────────────────────────────────────────────
        for item in MENU_ITEMS:
            is_active = current == item["id"]

            if not item["sub"]:
                # 서브메뉴 없음 → 단순 페이지 링크
                st.page_link(
                    item["page"],
                    label=f"{item['icon']}  {item['label']}",
                    use_container_width=True,
                )
            else:
                # 서브메뉴 있음 → expander
                with st.expander(
                    f"{item['icon']}  {item['label']}",
                    expanded=is_active,
                ):
                    st.page_link(
                        item["page"],
                        label="📌  전체 보기",
                        use_container_width=True,
                    )
                    for i, (sub_label, sub_icon, tab_idx) in enumerate(item["sub"]):
                        if st.button(
                            f"{sub_icon}  {sub_label}",
                            key=f"sb_sub_{item['id']}_{i}_{tab_idx}",
                            use_container_width=True,
                        ):
                            st.session_state["_nav_tab"] = tab_idx
                            st.switch_page(item["page"])

        # ── ③ 하단 ─────────────────────────────────────────────
        st.markdown('<div class="sb-divider" style="margin-top:16px;"></div>', unsafe_allow_html=True)

        # 접속자 정보
        user_id = st.session_state.get("user_id", "")
        roles: list[str] = st.session_state.get("user_roles", [st.session_state.get("user_role", "")])
        role_str = ", ".join(r for r in roles if r) or "-"
        first_role = roles[0] if roles else ""
        badge_color = _ROLE_COLOR.get(first_role, "#64748b")

        st.markdown(
            f"""
            <div class="sb-user-card">
                <div class="sb-user-avatar">👤</div>
                <div class="sb-user-info">
                    <div class="sb-user-name">{user_id}</div>
                    <div class="sb-user-role" style="color:{badge_color};">{role_str}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 로그아웃
        if st.button("🚪  로그아웃", use_container_width=True, key="sb_logout"):
            st.session_state.clear()
            st.rerun()
