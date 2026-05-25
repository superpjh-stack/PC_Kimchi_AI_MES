"""
꽃순이김치 제조AI MES — FastAPI 메인 애플리케이션
Project: SF26179540 | 로뎀솔루션 주식회사

실행:
    uvicorn app.main:app --reload --port 8000

Swagger UI:  http://localhost:8000/docs
ReDoc:       http://localhost:8000/redoc
"""
from __future__ import annotations

import sys
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ─── _workspace 라우터 경로 추가 ──────────────────────────────────────────────
_WORKSPACE = os.path.join(os.path.dirname(__file__), "..", "_workspace")
if _WORKSPACE not in sys.path:
    sys.path.insert(0, os.path.abspath(_WORKSPACE))

# ─── 라우터 임포트 ────────────────────────────────────────────────────────────
from api_dashboard_router import router as dashboard_router
from api_material_router import router as material_router
from api_fermentation_router import router as fermentation_router
from api_shipping_router import router as shipping_router
from api_process_router import router as process_router
from api_data_router import router as data_router
from api_kpi_router import router as kpi_router
from api_master_router import router as master_router
from api_system_router import router as system_router
from api_agent_router import router as agent_router

# ─── 승인 워크플로우 라우터 (app 패키지 내부) ──────────────────────────────────
from app.api.approval_router import router as approval_router

# ─── Shadow Mode 미들웨어 ──────────────────────────────────────────────────────
from app.middleware.shadow_mode import ShadowModeMiddleware

# ─── DB 풀 ───────────────────────────────────────────────────────────────────
from app.database import init_pool, close_pool, ping as db_ping


# ─── Lifespan (startup / shutdown) ───────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 DB 풀 초기화, 종료 시 정리."""
    await init_pool()
    yield
    await close_pool()


# ─── FastAPI 앱 ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="꽃순이김치 제조AI MES API",
    description=(
        "평창꽃순이(주)농업회사법인 제조AI 스마트공장 MES REST API\n\n"
        "프로젝트: SF26179540 | 개발: 로뎀솔루션 주식회사\n\n"
        "**주요 모듈**: AI 대시보드 / 원재료관리 / 숙성발효관리 / "
        "포장출하관리 / 공정관리 / 데이터관리 / KPI관리 / 기준정보 / 시스템관리 / AI Agent"
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Shadow-Mode", "X-Approval-Required", "X-Shadow-Endpoint"],
)

# ─── Shadow Mode 미들웨어 ─────────────────────────────────────────────────────
# AI 추천이 공정에 영향을 주는 경로를 인터셉트해 "승인 후 반영" 게이트를 적용한다.
# 환경변수 SHADOW_MODE=true/false 로 부팅 기본값 제어, /api/v1/approval/shadow-mode 로 런타임 토글.
app.add_middleware(ShadowModeMiddleware)


# ─── 전역 예외 핸들러 ─────────────────────────────────────────────────────────
@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError):
    """DB 미연결 등 RuntimeError → 503 반환."""
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc), "hint": "DB 서버 연결을 확인하세요."},
    )


# ─── 라우터 등록 ──────────────────────────────────────────────────────────────
app.include_router(dashboard_router)
app.include_router(material_router)
app.include_router(fermentation_router)
app.include_router(shipping_router)
app.include_router(process_router)
app.include_router(data_router)
app.include_router(kpi_router)
app.include_router(master_router)
app.include_router(system_router)
app.include_router(agent_router)
app.include_router(approval_router)


# ─── 헬스체크 ─────────────────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health():
    """
    서버 헬스체크 엔드포인트 (DB ping 포함).

    - DB 연결 가능 시 status="ok", db="up"
    - DB 미연결 시 status="degraded", db="down" (앱은 기동 상태)
    """
    db_ok = await db_ping()
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "꽃순이김치 MES API",
        "version": "1.0.0",
        "project": "SF26179540",
        "db": "up" if db_ok else "down",
    }


@app.get("/", tags=["system"])
async def root():
    """루트 — 앱 정보(버전 / 모듈 목록 / 문서 링크)."""
    return {
        "message": "꽃순이김치 제조AI MES API",
        "project": "SF26179540",
        "developer": "로뎀솔루션 주식회사",
        "version": "1.0.0",
        "modules": [
            "AI대시보드 (/api/v1/dashboard)",
            "원재료관리 (/api/v1/material)",
            "숙성발효관리 (/api/v1/fermentation)",
            "포장출하관리 (/api/v1/shipping)",
            "공정관리 (/api/v1/process)",
            "데이터관리 (/api/v1/data)",
            "KPI관리 (/api/v1/kpi)",
            "기준정보관리 (/api/v1/master)",
            "사용자/시스템관리 (/api/v1/system)",
            "AI Agent 통합관리 (/api/v1/agent)",
            "승인워크플로우 / Shadow Mode (/api/v1/approval)",
        ],
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
    }
