---
name: fastapi-mes
description: 꽃순이김치 MES FastAPI 백엔드 REST API 개발 스킬. 원재료관리, 숙성발효관리, 포장출하관리, 공정관리, KPI 관리 등 MES 모듈별 API 엔드포인트 개발 시 반드시 이 스킬을 사용하라. 트리거: FastAPI, API 개발, 엔드포인트, REST API, CRUD, 백엔드 개발, Pydantic, 라우터.
---

# MES FastAPI 백엔드 개발 스킬

## 프로젝트 구조

```
app/
├── main.py               -- FastAPI 앱 진입점
├── database.py           -- DB 연결 (asyncpg)
├── routers/
│   ├── intake.py         -- 원재료관리 API
│   ├── fermentation.py   -- 숙성발효관리 API
│   ├── shipping.py       -- 포장출하관리 API
│   ├── process.py        -- 공정관리 API
│   ├── kpi.py            -- KPI관리 API
│   └── ai_prediction.py  -- AI 예측 API (ML/RAG 프록시)
├── models/
│   ├── intake.py         -- Pydantic 모델 (원재료)
│   ├── fermentation.py   -- Pydantic 모델 (발효)
│   └── ...
└── services/
    ├── lot_service.py    -- LOT 트레이서빌리티 서비스
    └── kpi_service.py    -- KPI 계산 서비스
```

---

## FastAPI 앱 설정

```python
# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import intake, fermentation, shipping, process, kpi, ai_prediction

app = FastAPI(
    title="꽃순이김치 MES API",
    description="평창꽃순이 제조AI 스마트공장 MES REST API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],  # Streamlit
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(intake.router)
app.include_router(fermentation.router)
app.include_router(shipping.router)
app.include_router(process.router)
app.include_router(kpi.router)
app.include_router(ai_prediction.router)
```

---

## DB 연결 (asyncpg)

```python
# app/database.py
import asyncpg
from contextlib import asynccontextmanager

DATABASE_URL = "postgresql://user:password@db-server:5432/mes_db"

async def create_pool():
    return await asyncpg.create_pool(DATABASE_URL, min_size=5, max_size=20)

_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        _pool = await create_pool()
    return _pool

@asynccontextmanager
async def get_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn
```

---

## 원재료관리 API

```python
# app/routers/intake.py
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from datetime import date
from app.database import get_db

router = APIRouter(prefix="/api/v1/intake", tags=["원재료관리"])

class IntakeLotCreate(BaseModel):
    intake_lot_id: str
    supplier_id: int
    intake_date: date
    material_type: str
    weight_kg: float
    moisture_content: float | None = None
    cabbage_size: str | None = None
    appearance_grade: str | None = None
    origin: str | None = None

class IntakeLotResponse(IntakeLotCreate):
    id: int
    quality_status: str

@router.post("/lots", response_model=IntakeLotResponse, status_code=201)
async def create_intake_lot(data: IntakeLotCreate):
    async with get_db() as conn:
        row = await conn.fetchrow("""
            INSERT INTO raw_material_intake
                (intake_lot_id, supplier_id, intake_date, material_type, weight_kg,
                 moisture_content, cabbage_size, appearance_grade, origin)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            RETURNING *
        """, data.intake_lot_id, data.supplier_id, data.intake_date,
            data.material_type, data.weight_kg, data.moisture_content,
            data.cabbage_size, data.appearance_grade, data.origin)
    return dict(row)

@router.get("/lots/{lot_id}", response_model=IntakeLotResponse)
async def get_intake_lot(lot_id: str):
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM raw_material_intake WHERE intake_lot_id = $1", lot_id
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"LOT {lot_id} 없음")
    return dict(row)

@router.get("/lots/{lot_id}/traceability")
async def get_lot_traceability(lot_id: str):
    """LOT 전 공정 추적 조회"""
    async with get_db() as conn:
        row = await conn.fetchrow("""
            SELECT rmi.intake_lot_id, sp.salting_lot_id, fp.fermentation_lot_id,
                   s.shipping_lot_id, fp.ml_quality_prediction, s.quality_status
            FROM raw_material_intake rmi
            LEFT JOIN salting_process sp ON rmi.intake_lot_id = sp.intake_lot_id
            LEFT JOIN fermentation_process fp ON sp.salting_lot_id = fp.salting_lot_id
            LEFT JOIN shipping s ON fp.fermentation_lot_id = s.fermentation_lot_id
            WHERE rmi.intake_lot_id = $1
        """, lot_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"LOT {lot_id} 없음")
    return dict(row)
```

---

## 숙성발효관리 API

```python
# app/routers/fermentation.py
from fastapi import APIRouter, HTTPException
from app.database import get_db

router = APIRouter(prefix="/api/v1/fermentation", tags=["숙성발효관리"])

@router.get("/active")
async def get_active_fermentations():
    """현재 발효 중인 LOT 목록"""
    async with get_db() as conn:
        rows = await conn.fetch("""
            SELECT fermentation_lot_id, start_time, predicted_end_time,
                   ml_quality_prediction, ml_quality_score, status
            FROM fermentation_process
            WHERE status = 'IN_PROGRESS'
            ORDER BY start_time
        """)
    return [dict(r) for r in rows]

@router.get("/{lot_id}/status")
async def get_fermentation_status(lot_id: str):
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM fermentation_process WHERE fermentation_lot_id = $1", lot_id
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"LOT {lot_id} 없음")
    return dict(row)

@router.get("/{lot_id}/timeseries")
async def get_fermentation_timeseries(lot_id: str, hours: int = 24):
    """발효 시계열 데이터 조회 (최근 N시간)"""
    async with get_db() as conn:
        rows = await conn.fetch("""
            SELECT * FROM fermentation_timeseries
            WHERE fermentation_lot_id = $1
              AND recorded_at >= NOW() - ($2 || ' hours')::INTERVAL
            ORDER BY recorded_at
        """, lot_id, str(hours))
    return [dict(r) for r in rows]
```

---

## KPI API

```python
# app/routers/kpi.py
from fastapi import APIRouter
from datetime import date
from app.database import get_db

router = APIRouter(prefix="/api/v1/kpi", tags=["KPI관리"])

@router.get("/today")
async def get_today_kpi():
    async with get_db() as conn:
        row = await conn.fetchrow("""
            SELECT kpi_date,
                   AVG(hourly_production_kg) AS hourly_production_kg,
                   AVG(defect_rate) AS defect_rate,
                   AVG(fermentation_accuracy) AS fermentation_accuracy,
                   AVG(fermentation_time_mae) AS fermentation_time_mae
            FROM production_kpi
            WHERE kpi_date = CURRENT_DATE
            GROUP BY kpi_date
        """)
    return dict(row) if row else {
        "hourly_production_kg": 0, "defect_rate": 0,
        "fermentation_accuracy": 0, "fermentation_time_mae": 0
    }

@router.get("/weekly")
async def get_weekly_kpi():
    async with get_db() as conn:
        rows = await conn.fetch("""
            SELECT kpi_date, AVG(hourly_production_kg) AS hourly_production_kg,
                   AVG(defect_rate) AS defect_rate
            FROM production_kpi
            WHERE kpi_date >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY kpi_date
            ORDER BY kpi_date
        """)
    return [dict(r) for r in rows]
```

---

## 개발 원칙
1. 모든 조회 엔드포인트는 LOT ID 기반 필터링을 지원한다
2. ML/RAG 결과는 `/api/v1/ai/*` 엔드포인트로 분리한다
3. 비동기 처리(`async/await` + `asyncpg`)를 기본으로 사용한다
4. Pydantic v2 모델로 요청/응답 스키마를 정의한다
5. `ON CONFLICT DO NOTHING` 또는 `DO UPDATE`로 멱등성을 보장한다
