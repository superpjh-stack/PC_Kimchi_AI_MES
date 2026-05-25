"""
꽃순이김치 제조AI MES — Shadow Mode 미들웨어
Project: SF26179540 | 로뎀솔루션 주식회사

CLAUDE.md 원칙:
    "AI는 조회·분석·추천·경고. 작업자 승인 후 공정 반영 (파일럿 검증 단계)"

Shadow Mode 3단계 게이트:
    AI 추천 생성  →  사람(작업자/관리자) 승인  →  공정 반영

이 미들웨어가 하는 일:
    1) AI 추천이 공정에 영향을 주는 경로(SHADOW_ENDPOINTS)의 요청을 인터셉트한다.
    2) Shadow Mode 가 ON 이면:
         - request.state.shadow_mode = True  를 설정해 라우터가 "즉시 반영" 대신
           "승인 대기(pending)" 로 동작하도록 신호를 준다.
         - 응답에 X-Shadow-Mode / X-Approval-Required 헤더를 부착한다.
         - 모든 AI 결정 경로 접근을 로깅(감사 추적)한다.
    3) Shadow Mode 가 OFF 면 (미래 자동화 단계) 즉시 반영을 허용한다.

환경변수:
    SHADOW_MODE = "true" | "false"   (기본 "true" — 시범운영 중 항상 ON)

런타임 토글:
    set_shadow_mode(True/False)      — /api/v1/approval/shadow-mode (ADMIN) 에서 호출.
    환경변수는 부팅 시 기본값이며, 런타임 토글이 우선한다.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Iterable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# ─── 로거 (감사 추적) ─────────────────────────────────────────────────────────
logger = logging.getLogger("mes.shadow_mode")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(asctime)s] %(name)s %(levelname)s %(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)


def _env_default() -> bool:
    """환경변수 SHADOW_MODE 의 부팅 기본값."""
    return os.getenv("SHADOW_MODE", "true").strip().lower() in ("true", "1", "yes", "on")


# 부팅 기본값 — 런타임에 set_shadow_mode() 로 덮어쓸 수 있다.
_SHADOW_MODE_STATE: bool = _env_default()


def is_shadow_mode_enabled() -> bool:
    """현재 Shadow Mode 활성 여부 (런타임 토글 반영)."""
    return _SHADOW_MODE_STATE


def set_shadow_mode(enabled: bool) -> bool:
    """
    Shadow Mode 를 런타임에 ON/OFF 한다. (ADMIN 전용 API 에서 호출)
    반환값: 변경 후 상태(bool).
    """
    global _SHADOW_MODE_STATE
    prev = _SHADOW_MODE_STATE
    _SHADOW_MODE_STATE = bool(enabled)
    logger.info(
        "Shadow Mode 상태 변경: %s -> %s",
        "ON" if prev else "OFF",
        "ON" if _SHADOW_MODE_STATE else "OFF",
    )
    return _SHADOW_MODE_STATE


# ─── Shadow Mode 적용 대상 경로 ───────────────────────────────────────────────
# "METHOD /path/template" 형식. {param} 자리표시자는 정규식으로 매칭한다.
# AI 추천이 공정 데이터에 영향을 줄 수 있는 경로만 게이트 대상으로 둔다.
SHADOW_ENDPOINTS: set[str] = {
    "POST /api/v1/fermentation/recommendations",          # 절임/발효 조건 추천
    "PATCH /api/v1/fermentation/lots/{lot_id}/status",    # 발효 LOT 상태변경
    "PATCH /api/v1/shipping/orders/{order_id}/approve",   # 출하 승인
    "PATCH /api/v1/agent/query/{query_id}/approve",       # AI 의사결정 승인
    "PATCH /api/v1/agent/recommendations/{rec_id}/action",  # AI 추천 처리
}


def _template_to_regex(template: str) -> re.Pattern[str]:
    """
    'PATCH /api/v1/.../{lot_id}/status' →
        컴파일된 정규식 (METHOD 공백 PATH 전체 매칭).
    경로 파라미터 {name} 는 슬래시를 제외한 1개 이상 문자에 매칭한다.
    """
    method, _, path = template.partition(" ")
    # 경로 부분의 특수문자를 이스케이프한 뒤 {param} 만 패턴으로 치환
    escaped = re.escape(path)
    escaped = re.sub(r"\\\{[^}]+\\\}", r"[^/]+", escaped)
    return re.compile(rf"^{re.escape(method)}\s{escaped}$")


# 부팅 시 1회 컴파일 (요청마다 재컴파일 방지)
_COMPILED_ENDPOINTS: list[tuple[str, re.Pattern[str]]] = [
    (tpl, _template_to_regex(tpl)) for tpl in SHADOW_ENDPOINTS
]


def _match_shadow_endpoint(method: str, path: str) -> str | None:
    """
    (method, path) 가 Shadow 대상 경로와 일치하면 매칭된 템플릿 문자열을, 아니면 None.
    """
    target = f"{method.upper()} {path}"
    for tpl, pattern in _COMPILED_ENDPOINTS:
        if pattern.match(target):
            return tpl
    return None


class ShadowModeMiddleware(BaseHTTPMiddleware):
    """
    Shadow Mode 미들웨어.

    등록 (app/main.py):
        from app.middleware.shadow_mode import ShadowModeMiddleware
        app.add_middleware(ShadowModeMiddleware)

    라우터에서 참조 (예시):
        @router.patch("/lots/{lot_id}/status")
        async def update_status(lot_id: str, request: Request, ...):
            if getattr(request.state, "shadow_mode", False):
                # 즉시 반영 대신 approval_item 으로 등록 → 승인 대기
                ...
    """

    def __init__(
        self,
        app: ASGIApp,
        protected_endpoints: Iterable[str] | None = None,
    ) -> None:
        super().__init__(app)
        # 테스트/확장을 위해 보호 경로를 주입 가능하게 둔다.
        if protected_endpoints is not None:
            self._compiled = [
                (tpl, _template_to_regex(tpl)) for tpl in protected_endpoints
            ]
        else:
            self._compiled = _COMPILED_ENDPOINTS

    def _match(self, method: str, path: str) -> str | None:
        target = f"{method.upper()} {path}"
        for tpl, pattern in self._compiled:
            if pattern.match(target):
                return tpl
        return None

    async def dispatch(self, request: Request, call_next) -> Response:
        method = request.method
        path = request.url.path
        matched = self._match(method, path)
        shadow_on = is_shadow_mode_enabled()

        # 라우터가 참조할 상태 플래그.
        # - shadow_mode: 이 요청을 pending 으로 처리해야 하는가
        # - shadow_protected: 이 경로가 Shadow 게이트 대상인가
        request.state.shadow_mode = bool(shadow_on and matched)
        request.state.shadow_protected = matched is not None
        request.state.shadow_endpoint = matched

        # 감사 추적 — Shadow 대상 경로 접근은 항상 로깅
        if matched:
            client = request.client.host if request.client else "unknown"
            logger.info(
                "Shadow 게이트 경로 접근 | mode=%s | %s %s | endpoint=%s | client=%s",
                "ON" if shadow_on else "OFF",
                method,
                path,
                matched,
                client,
            )

        response = await call_next(request)

        # Shadow Mode ON + 대상 경로 → 승인 필요 헤더 부착
        if shadow_on and matched:
            response.headers["X-Shadow-Mode"] = "active"
            response.headers["X-Approval-Required"] = "true"
            response.headers["X-Shadow-Endpoint"] = matched
        elif matched:
            # OFF 이지만 대상 경로 — 자동 반영됨을 명시
            response.headers["X-Shadow-Mode"] = "inactive"
            response.headers["X-Approval-Required"] = "false"

        return response
