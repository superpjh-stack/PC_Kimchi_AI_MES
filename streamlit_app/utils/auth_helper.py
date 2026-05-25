"""
꽃순이김치 MES — Streamlit 인증 헬퍼
Project: SF26179540 / 로뎀솔루션

모든 Streamlit 페이지에서 공통으로 사용하는 인증 유틸리티.
- API 요청 시 Authorization: Bearer 헤더 자동 생성
- 로그인 상태 확인 및 미인증 페이지 차단
- 역할(Role) 기반 기능 노출 제어
"""
from __future__ import annotations

import streamlit as st

BASE_API_URL = "http://localhost:8000"


def get_auth_headers() -> dict[str, str]:
    """
    현재 세션의 access_token → Authorization 헤더 반환.
    토큰이 없으면 빈 딕셔너리 반환.

    사용 예:
        headers = get_auth_headers()
        resp = httpx.get(f"{BASE_API_URL}/api/v1/kpi/summary/today", headers=headers)
    """
    token = st.session_state.get("access_token")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def check_login() -> bool:
    """
    로그인 여부 확인.
    미로그인 시 경고 메시지를 표시하고 st.stop()으로 페이지 실행을 중단.

    사용 예 (각 페이지 최상단):
        from utils.auth_helper import check_login
        check_login()
    """
    if not st.session_state.get("logged_in"):
        st.warning("로그인이 필요합니다. 홈 화면에서 로그인해 주세요.")
        st.stop()
    return True


def has_role(*roles: str) -> bool:
    """
    현재 사용자가 지정된 역할 중 하나를 보유하는지 확인.
    역할 코드: ADMIN, MANAGER, QUALITY, OPERATOR

    사용 예:
        if has_role("ADMIN", "MANAGER"):
            st.button("KPI 목표 수정")
    """
    user_roles: list[str] = st.session_state.get("user_roles", [])
    return any(r in roles for r in user_roles)


def require_login_and_role(*roles: str) -> None:
    """
    로그인 + 역할 검증 통합.
    로그인 미완료 또는 역할 미보유 시 에러 메시지와 함께 st.stop().

    사용 예 (쓰기 전용 섹션):
        require_login_and_role("ADMIN", "MANAGER")
    """
    check_login()
    if roles and not has_role(*roles):
        st.error(f"이 기능은 {', '.join(roles)} 역할만 사용할 수 있습니다.")
        st.stop()


def handle_401(response_status: int) -> bool:
    """
    API 401 응답 처리 — 세션 클리어 + 안내 메시지.
    True 반환 시 호출자가 st.stop() 또는 return 처리해야 함.

    사용 예:
        if handle_401(resp.status_code):
            st.stop()
    """
    if response_status == 401:
        st.session_state.clear()
        st.error("세션이 만료되었습니다. 다시 로그인해 주세요.")
        return True
    return False


def get_current_username() -> str:
    """현재 로그인 사용자명 반환. 미로그인 시 '게스트' 반환."""
    return st.session_state.get("user_id", "게스트")


def get_current_roles() -> list[str]:
    """현재 로그인 사용자 역할 목록 반환."""
    return st.session_state.get("user_roles", [])
