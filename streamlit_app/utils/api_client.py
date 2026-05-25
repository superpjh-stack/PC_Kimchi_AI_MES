"""
꽃순이김치 MES — HTTP API 클라이언트 팩토리
Project: SF26179540 / 로뎀솔루션

모든 Streamlit 페이지에서 사용하는 인증 포함 HTTP 클라이언트.
- get_client()  : Authorization 헤더가 자동으로 주입된 httpx.Client 반환
- api_get(path) : GET 요청 편의 함수
- api_post(path): POST 요청 편의 함수
"""
from __future__ import annotations

import streamlit as st
import httpx

BASE_API_URL = "http://localhost:8000"


def _auth_headers() -> dict[str, str]:
    """현재 세션 토큰 → Authorization 헤더."""
    token = st.session_state.get("access_token", "")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def get_client(timeout: float = 10.0) -> httpx.Client:
    """
    Authorization 헤더가 자동 포함된 httpx.Client 반환.

    사용 예:
        client = get_client()
        resp = client.get("/api/v1/kpi/summary/today")
    """
    return httpx.Client(
        base_url=BASE_API_URL,
        headers=_auth_headers(),
        timeout=timeout,
    )


def api_get(path: str, params: dict | None = None, timeout: float = 10.0):
    """
    GET 요청 편의 함수. 실패 시 None 반환 + Streamlit 경고.
    path 예: "/api/v1/kpi/summary/today"
    """
    try:
        r = get_client(timeout).get(path, params=params or {})
        if r.status_code == 401:
            st.session_state.clear()
            st.error("세션 만료 — 다시 로그인해 주세요.")
            st.stop()
        r.raise_for_status()
        return r.json()
    except httpx.RequestError as e:
        st.warning(f"서버 연결 실패 ({path}): {e}")
        return None
    except httpx.HTTPStatusError as e:
        st.warning(f"API 오류 ({path}): HTTP {e.response.status_code}")
        return None


def api_post(path: str, payload: dict | None = None, timeout: float = 10.0):
    """POST 요청 편의 함수."""
    try:
        r = get_client(timeout).post(path, json=payload or {})
        if r.status_code == 401:
            st.session_state.clear()
            st.error("세션 만료 — 다시 로그인해 주세요.")
            st.stop()
        r.raise_for_status()
        return r.json()
    except httpx.RequestError as e:
        st.error(f"서버 연결 실패 ({path}): {e}")
        return None
    except httpx.HTTPStatusError as e:
        st.error(f"API 오류 ({path}): HTTP {e.response.status_code}")
        return None


def api_put(path: str, payload: dict | None = None, timeout: float = 10.0):
    """PUT 요청 편의 함수."""
    try:
        r = get_client(timeout).put(path, json=payload or {})
        if r.status_code == 401:
            st.session_state.clear()
            st.error("세션 만료 — 다시 로그인해 주세요.")
            st.stop()
        r.raise_for_status()
        return r.json()
    except httpx.RequestError as e:
        st.error(f"서버 연결 실패 ({path}): {e}")
        return None
    except httpx.HTTPStatusError as e:
        st.error(f"API 오류 ({path}): HTTP {e.response.status_code}")
        return None
