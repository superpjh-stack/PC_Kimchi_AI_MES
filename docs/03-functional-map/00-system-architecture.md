# 꽃순이김치 제조AI 스마트공장 MES — 시스템 아키텍처 설계서

| 항목 | 내용 |
|------|------|
| 과제번호 | SF26179540 |
| 고객사 | 평창꽃순이(주)농업회사법인 (강원 평창, 고랭지 배추 100% 국내산 프리미엄 김치) |
| 공급사 | 로뎀솔루션 주식회사 |
| 사업비 | 약 3.97억원 |
| 수행연도 | 2026년 |
| 문서버전 | v1.0 (2026-05-23) |
| 작성 | 수석 아키텍트 |

> **설계 원칙**: AI는 공정을 직접 제어하지 않는다. 조회·분석·추천·경고의 의사결정 지원(Decision Support) 역할이며, 시범운영 기간 모든 AI 추천값은 작업자/공장장 승인 후 반영된다. 모든 공정 데이터는 **LOT 단위**로 연계되어 전 공정 추적성(Traceability)을 보장한다.

---

## 1. 전체 시스템 레이어 다이어그램

```
┌══════════════════════════════════════════════════════════════════════════════┐
║                          PRESENTATION LAYER                                    ║
║  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐             ║
║  │ 관리자 Web │  │ SmartPad   │  │  현황판    │  │  Mobile    │             ║
║  │ (Streamlit)│  │ x3 (POP)   │  │ (Dashboard)│  │ (점검/입력)│             ║
║  │ KPI/모니터 │  │ 입고/절임/ │  │ 생산/발효/ │  │ 품질/재고  │             ║
║  │ 통합관리   │  │ 포장출하   │  │ 출하승인   │  │ 작업상태   │             ║
║  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘             ║
└════════│════════════════│════════════════│════════════════│══════════════════┘
         │                │                │                │      HTTPS / WSS
         └────────────────┴────────┬───────┴────────────────┘
                                    │
┌═══════════════════════════════════▼════════════════════════════════════════════┐
║                       PRESENTATION GATEWAY (AP Server)                          ║
║                    Nginx  (Reverse Proxy, TLS, Rate Limit)                      ║
└═══════════════════════════════════┬════════════════════════════════════════════┘
                                     │
┌═══════════════════════════════════▼════════════════════════════════════════════┐
║                         APPLICATION LAYER (AP Server)                           ║
║  ┌─────────────────────────────────────────────────────────────────────────┐  ║
║  │                       FastAPI (Python) — REST API                          │  ║
║  │  Auth │ 원재료 │ 숙성발효 │ 포장출하 │ 공정 │ 데이터 │ AIAgent │ 기준정보 │  ║
║  │       │  관리  │   관리   │   관리   │ 관리 │  관리  │  통합   │  /KPI   │  ║
║  └───────────────┬─────────────────────────────┬──────────────┬─────────────┘  ║
║                  │                              │              │                ║
║         ┌────────▼──────┐            ┌──────────▼─────┐  ┌─────▼──────┐         ║
║         │ Streamlit App │            │  AI Chat (RAG) │  │  WebSocket │         ║
║         │ (대시보드 UI) │            │   Endpoint     │  │  (실시간)  │         ║
║         └───────────────┘            └────────────────┘  └────────────┘         ║
└═══════════════┬═══════════════════════════════┬═══════════════════┬════════════┘
                │ SQLAlchemy/asyncpg             │ REST/Batch        │ REST
┌═══════════════▼═══════════════════════════════▼═══════════════════▼════════════┐
║                              AI LAYER (AI Server)                               ║
║  ┌─────────────────────────────┐         ┌─────────────────────────────────┐  ║
║  │      ML ENGINE              │         │      RAG AI AGENT               │  ║
║  │  XGBoost (품질분류)         │         │  LangChain / LangGraph          │  ║
║  │  RandomForest (중요도)      │         │  ┌──────────────┐               │  ║
║  │  SVR (산도/숙성도 회귀)     │         │  │ 입고 Agent   │               │  ║
║  │  LSTM (시계열 완료시점)     │         │  │ 출하 Agent   │               │  ║
║  │  Prophet (추세)             │         │  │ 통합 Agent   │               │  ║
║  │  SHAP (설명가능성)          │         │  └──────┬───────┘               │  ║
║  └──────────────┬──────────────┘         └─────────┼───────────────────────┘  ║
└═════════════════│════════════════════════════════════│═══════════════════════════┘
                  │ Train/Predict                       │ Embedding Search
┌═════════════════▼════════════════════════════════════▼═══════════════════════════┐
║                                DATA LAYER                                       ║
║  ┌────────────────────────┐  ┌─────────────────────┐  ┌────────────────────┐  ║
║  │  PostgreSQL (DB Server)│  │ pgvector (VectorDB) │  │  Data Lake (S3 Raw)│  ║
║  │  운영DB (정형)         │  │  SOP/매뉴얼/품질문서│  │  센서 원천 데이터  │  ║
║  │  생산/LOT/공정/품질    │  │  임베딩 (1536-dim)  │  │  Raw Zone          │  ║
║  └────────────┬───────────┘  └─────────────────────┘  └─────────┬──────────┘  ║
║               │  Redis (Cache / Pub-Sub) ────────────────────────┘             ║
└═══════════════│════════════════════════════════════════════════════════════════┘
                │ ETL (가공/정제/LOT 통합)
┌═══════════════▲════════════════════════════════════════════════════════════════┐
║                          MESSAGE / STREAMING LAYER                              ║
║       MQTT Broker  ───────►  Kafka (Topic per Process)  ───────►  Data Lake     ║
║       (경량 센서)            (스트리밍 버퍼링/순서보장)                          ║
└═══════════════▲════════════════════════════════════════════════════════════════┘
                │ OPC-UA / Modbus TCP/IP
┌═══════════════▲════════════════════════════════════════════════════════════════┐
║                          EDGE LAYER (Factory Floor)                             ║
║  ┌──────────────────────────────────────────────────────────────────────────┐ ║
║  │  AI Data Gateway (Edge Collector Mini PC + PLC)                            │ ║
║  │  - 전 공정 데이터 수집 허브,  LOT 추적 키 부여                              │ ║
║  │  - 네트워크 단절 시 로컬 버퍼링(무결성 확보) → 복구 시 재전송               │ ║
║  └──────────────────────────────────────────────────────────────────────────┘ ║
└═══════════════▲════════════════════════════════════════════════════════════════┘
                │ Sensor Signals
┌═══════════════▲════════════════════════════════════════════════════════════════┐
║                       PHYSICAL LAYER (현장 설비/센서)                           ║
║  입고/보관 → 절단/전처리 → 세척/절임 → 세척/선별 → 탈수 → 혼합               ║
║          → 숙성/발효 → 금속검출 → 포장/출하                                    ║
║  센서: 온도 / 염도 / pH / 산도 / 중량 / 함수율 / 외기온습도 / 금속검출         ║
└═════════════════════════════════════════════════════════════════════════════════┘
```

---

## 2. 레이어별 상세 설명

### 2.1 Physical Layer (현장 설비/센서)
- **대상 공정**: 입고/보관 → 절단/전처리 → 세척/절임 → 세척/선별 → 탈수 → 혼합 → 숙성/발효 → 금속검출 → 포장/출하 (9단계)
- **수집 신호**: 절임조 온도·염도·pH, 발효실 온도·산도·숙성시간, 외기 온습도, 원재료 중량·함수율, 금속검출 결과, 생산량(kg/h)
- **신호 변환**: 설비 PLC가 센서 아날로그/디지털 신호를 산업 프로토콜로 변환

### 2.2 Edge Layer (AI Data Gateway)
- **장비**: AI Data Gateway x1 (2층 사무실 설치), Edge Collector Mini PC + PLC 구성
- **프로토콜**: OPC-UA(설비 표준), Modbus TCP/IP(레거시 설비)
- **핵심 책무**:
  - 전 공정 데이터 수집 단일 허브
  - **LOT ID 부여 및 전 공정 추적 키 매핑** (입고LOT → 절임LOT → 발효LOT → 출하LOT)
  - **네트워크 단절 시 로컬 버퍼링** → 복구 시 순서 보장 재전송으로 데이터 무결성 확보
  - 1차 정규화 후 상위 메시지 레이어로 발행(publish)

### 2.3 Message / Streaming Layer
- **MQTT**: 경량 센서/Smart Pad 입력의 저지연 수집 (QoS 1 이상)
- **Kafka**: 공정별 Topic 분리(`process.intake`, `process.fermentation`, `process.shipping` 등), 스트리밍 버퍼링 및 순서 보장, Consumer Group으로 ETL/실시간 대시보드 분리 소비
- **역할**: Edge ↔ Cloud 비동기 디커플링, 트래픽 급증 흡수, 장애 격리

### 2.4 Data Layer
| 저장소 | 서버 | 용도 |
|--------|------|------|
| Data Lake (S3 Raw Zone) | AWS S3 | 센서 원천 데이터 원본 무가공 보관 (재처리/감사용) |
| PostgreSQL 운영DB | DB Server (4vCPU/16G/300G x2) | 정형 데이터: 생산실적·작업지시·LOT·공정·품질·출하 |
| pgvector Vector DB | Vector DB Server (4vCPU/16G/200G) | 비정형 문서 임베딩(SOP/기준서/매뉴얼) |
| Redis | AP/AI Server | 캐시(KPI 집계, 세션), Pub/Sub(실시간 알림) |

- **ETL 파이프라인**: Raw → 노이즈 제거(Moving Average, Low-pass) → 이상치 제거(IQR, Z-score, Isolation Forest) → 결측치 보정(Forward Fill, KNN) → **LOT 단위 통합** → LSTM용 Sliding Window 변환

### 2.5 AI Layer (AI Server, 8vCPU/16G/200G)
- **ML Engine**: 숙성/발효 공정 — XGBoost(품질분류 정상/주의/이상), RandomForest(특성중요도), SVR(산도·숙성도 회귀), LSTM(완료시점 예측), Prophet(추세), SHAP(설명가능 출력)
- **RAG AI Agent**: 원재료 입고·포장/출하 — LangChain/LangGraph 기반, pgvector 임베딩 검색 + LLM 응답 생성
- **연계**: ML 결과/RAG 응답은 Application Layer를 통해 인간 승인 게이트 후 운영 반영

### 2.6 Application Layer (AP Server, 4vCPU/8G/100G)
- **FastAPI**: 10개 모듈 도메인 REST API, JWT 인증, RBAC 권한 미들웨어
- **Streamlit**: 관리자/모니터링 대시보드 UI 렌더링
- **WebSocket**: 현황판·실시간 발효 모니터링 푸시
- **AI Chat Endpoint**: SmartPad/Web의 RAG 질의 중계

### 2.7 Presentation Layer
- **관리자 Web (Streamlit)**: 생산·품질 모니터링, KPI, 재고·출하 통합관리
- **SmartPad x3 (POP)**: 입고/절임/포장출하 현장 작업자 — 작업지시 확인, 데이터 입력, 실적·품질 입력, AI Agent 질의
- **현황판 x1**: 공정별 생산량·발효 상태·출하 승인 상태 실시간 표출
- **Mobile**: 현장 점검, 품질 입력, 재고·작업 상태 조회

---

## 3. 데이터 흐름 다이어그램 (LOT 기반 전 공정 연계)

```
 [원재료 입고]                                                      [최종 출하]
      │                                                                  ▲
      ▼                                                                  │
 ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
 │ 입고LOT │──►│ 전처리  │──►│ 절임LOT │──►│ 탈수/혼합│─►│ 발효LOT │──►│ 출하LOT │
 │ INP-xxx │   │         │   │ SLT-xxx │   │          │  │ FRM-xxx │   │ SHP-xxx │
 └────┬────┘   └────┬────┘   └────┬────┘   └────┬─────┘  └────┬────┘   └────┬────┘
      │             │             │             │            │             │
      ▼             ▼             ▼             ▼            ▼             ▼
 ┌───────────────────────────────────────────────────────────────────────────────┐
 │                    LOT 매핑 테이블 (lot_genealogy)                              │
 │   input_lot_id → salting_lot_id → fermentation_lot_id → shipping_lot_id        │
 │   (1:N, N:1 관계 허용 — 혼합/분할 공정 추적)                                    │
 └───────────────────────────────────────┬───────────────────────────────────────┘
                                          │
            ┌─────────────────────────────┼─────────────────────────────┐
            ▼                             ▼                             ▼
   ┌─────────────────┐          ┌──────────────────┐         ┌──────────────────┐
   │  ML Engine      │          │  RAG AI Agent    │         │  KPI 집계        │
   │ 발효품질 예측   │          │ 입고이력/클레임  │         │ 생산량/불량률    │
   │ 완료시점 예측   │          │ 추적 질의응답    │         │ 추적             │
   │ 이상발효 경보   │          │                  │         │                  │
   └────────┬────────┘          └────────┬─────────┘         └────────┬─────────┘
            └─────────────────────────────┼─────────────────────────────┘
                                          ▼
                          ┌───────────────────────────────┐
                          │   인간 승인 게이트 (Approval)  │
                          │   작업자/공장장 검토 → 반영    │
                          └───────────────────────────────┘
```

**연계 규칙**: 모든 Cross-Process 조인은 `lot_genealogy`를 경유한다. 혼합 공정(N:1)·분할 출하(1:N)를 추적하기 위해 LOT 계보는 다대다 관계를 지원한다.

---

## 4. API 엔드포인트 구조 (모듈별 주요 API)

> 기본 prefix: `/api/v1` — 인증: `Authorization: Bearer <JWT>` — 내부 서비스 호출: `X-Internal-Token`

### 4.1 인증/사용자 (auth, user)
```
POST   /api/v1/auth/login                로그인 (JWT 발급)
POST   /api/v1/auth/refresh              토큰 갱신
POST   /api/v1/auth/logout               로그아웃
GET    /api/v1/users                     사용자 목록 (관리자)
POST   /api/v1/users                     사용자 등록
PATCH  /api/v1/users/{id}/role           권한 변경
```

### 4.2 AI 대시보드 (dashboard)
```
GET    /api/v1/dashboard/production      생산현황 분석 데이터
GET    /api/v1/dashboard/quality         품질현황 분석 데이터
GET    /api/v1/dashboard/fermentation    발효상태 모니터링 (실시간)
GET    /api/v1/dashboard/shipping        출하현황 분석
WS     /ws/dashboard/live                현황판 실시간 스트림
```

### 4.3 원재료관리 (material)
```
POST   /api/v1/materials/intake          입고 등록 (LOT 생성)
GET    /api/v1/materials/{lot_id}/history 원재료 이력조회
GET    /api/v1/materials/sorting          선별 데이터 조회
GET    /api/v1/materials/suppliers/quality 공급처 품질분석
POST   /api/v1/materials/agent/query     입고 AI Agent 질의 (RAG)
```

### 4.4 숙성발효관리 (fermentation)
```
GET    /api/v1/fermentation/status        발효상태 모니터링
GET    /api/v1/fermentation/{lot}/predict 품질예측 결과 (ML)
GET    /api/v1/fermentation/{lot}/eta     발효완료 예측 시점 (LSTM)
GET    /api/v1/fermentation/alerts        이상발효 알림 목록
GET    /api/v1/fermentation/{lot}/shap    영향요인 분석 (SHAP)
GET    /api/v1/fermentation/conditions    최적 공정조건 추천
POST   /api/v1/fermentation/ml/retrain    ML 재학습 트리거 (공장장)
```

### 4.5 포장출하관리 (shipping)
```
POST   /api/v1/packaging/results          포장실적 등록
POST   /api/v1/shipping/orders            출하 등록
GET    /api/v1/shipping/{lot}/trace       LOT 추적 (계보 조회)
POST   /api/v1/shipping/inspection        검사결과 등록
GET    /api/v1/shipping/claims            클레임 분석
POST   /api/v1/shipping/agent/query       출하 AI Agent 질의 (RAG)
POST   /api/v1/shipping/{lot}/approve     출하 승인 (공장장)
```

### 4.6 공정관리 (process)
```
GET    /api/v1/process/results            공정실적 조회
GET    /api/v1/process/monitor            공정 데이터 모니터링
GET    /api/v1/process/recipes            레시피 목록
PUT    /api/v1/process/recipes/{id}       레시피 수정 (공장장)
GET    /api/v1/process/{lot}/history      공정이력 조회
GET    /api/v1/process/analysis           공정데이터 분석
```

### 4.7 데이터관리 (data)
```
GET    /api/v1/data/integrated            데이터 통합조회
GET    /api/v1/data/query                 조건 검색
GET    /api/v1/data/visualize             시각화 데이터
GET    /api/v1/data/download              CSV/Excel 다운로드
GET    /api/v1/data/training              AI 학습 데이터셋 관리
```

### 4.8 AI Agent 통합관리 (agent)
```
POST   /api/v1/agent/query                통합 AI 질의 (LangGraph 라우팅)
GET    /api/v1/agent/analysis             생산/품질 분석 인사이트
GET    /api/v1/agent/recommendations      의사결정 지원 추천
GET    /api/v1/agent/notifications        알림 및 추천 목록
GET    /api/v1/agent/history              사용자 질문이력
```

### 4.9 기준정보/시스템/KPI (master, system, kpi)
```
GET    /api/v1/master/quality-standards   품질기준 관리
GET    /api/v1/master/work-standards       작업표준(SOP) 관리
GET    /api/v1/master/codes                코드 관리
GET    /api/v1/system/logs                 로그 조회
PUT    /api/v1/system/alerts/config        알림 설정
GET    /api/v1/kpi/productivity            생산성 KPI (kg/h)
GET    /api/v1/kpi/quality                 품질 KPI (불량률)
```

---

## 5. 정형 데이터 테이블 목록 (PostgreSQL 운영DB)

### 5.1 LOT / 추적
| 테이블 | 설명 | 주요 컬럼 |
|--------|------|-----------|
| `lot_genealogy` | LOT 계보 매핑 (전 공정 추적 핵심) | input_lot_id, salting_lot_id, fermentation_lot_id, shipping_lot_id |
| `lot_master` | LOT 기본 정보 | lot_id, lot_type, created_at, status |

### 5.2 원재료 / 입고
| 테이블 | 설명 | 주요 컬럼 |
|--------|------|-----------|
| `material_intake` | 원재료 입고 | input_lot_id, supplier_id, item_code, weight, intake_date |
| `material_attributes` | 배추 속성 | input_lot_id, size, weight, appearance_grade, moisture_rate, origin |
| `material_sorting` | 선별 데이터 | input_lot_id, pass_qty, reject_qty, reject_reason |
| `suppliers` | 공급처 | supplier_id, name, eval_grade |
| `supplier_quality_history` | 공급처 품질 이력 | supplier_id, lot_id, defect_rate, eval_date |

### 5.3 공정 (절임/탈수/혼합/발효)
| 테이블 | 설명 | 주요 컬럼 |
|--------|------|-----------|
| `work_orders` | 작업지시 | order_id, recipe_id, target_qty, status |
| `salting_process` | 절임 공정 | salting_lot_id, temp, salinity, ph, salting_time |
| `dehydration_process` | 탈수 공정 | lot_id, dehydration_rate, duration |
| `mixing_process` | 혼합 공정 | lot_id, recipe_id, ingredients_json |
| `fermentation_process` | 발효 공정 시계열 | fermentation_lot_id, timestamp, temp, acidity, maturity_time |
| `ambient_conditions` | 외기 온습도 | timestamp, temp, humidity |
| `recipes` | 레시피 | recipe_id, name, params_json, version |

### 5.4 품질 / 검사 / 출하
| 테이블 | 설명 | 주요 컬럼 |
|--------|------|-----------|
| `quality_inspection` | 품질검사 결과 | lot_id, inspection_type, result, defect_type |
| `metal_detection` | 금속검출 결과 | lot_id, detected, timestamp |
| `packaging_results` | 포장실적 | shipping_lot_id, package_type, qty, packaged_at |
| `shipping_orders` | 출하 | shipping_lot_id, customer, qty, approval_status, shipped_at |
| `claims` | 클레임 | claim_id, shipping_lot_id, cause, resolution |

### 5.5 생산 실적 / KPI
| 테이블 | 설명 | 주요 컬럼 |
|--------|------|-----------|
| `production_results` | 생산실적 | order_id, lot_id, output_qty, hourly_rate_kgh |
| `kpi_metrics` | KPI 집계 | metric_date, productivity_kgh, defect_rate |

### 5.6 AI 결과 / 시스템
| 테이블 | 설명 | 주요 컬럼 |
|--------|------|-----------|
| `ml_predictions` | ML 예측 결과 | fermentation_lot_id, pred_quality, eta, anomaly_flag, model_version |
| `ml_feature_importance` | SHAP 영향요인 | fermentation_lot_id, feature, shap_value |
| `agent_query_history` | AI 질의이력 | user_id, query, response, agent_type, created_at |
| `approval_log` | 승인 게이트 로그 | target_type, target_id, approver_id, decision, approved_at |
| `users` | 사용자 | user_id, name, role, dept |
| `system_logs` | 시스템/감사 로그 | log_id, level, actor, action, timestamp |
| `alert_config` | 알림 설정 | alert_type, threshold, channel, enabled |

---

## 6. 비정형 데이터 임베딩 문서 목록 (pgvector)

| 컬렉션 | 문서 종류 | 활용 Agent |
|--------|-----------|-----------|
| `sop_documents` | 작업표준서(SOP) | 입고/출하/통합 Agent |
| `fermentation_standards` | 절임/발효 기준서 (염도·pH·온도·시간 기준) | 통합 Agent (발효 해석 보조) |
| `quality_standards` | 품질 기준서 및 QC 문서 | 출하 Agent (승인 기준 질의) |
| `haccp_ccp_docs` | HACCP CCP 관리 문서 | 출하/통합 Agent |
| `equipment_manuals` | 설비 운영 매뉴얼 | 통합 Agent |
| `defect_response_manuals` | 불량 대응 매뉴얼 | 출하 Agent (클레임 분석) |
| `claim_response_manuals` | 클레임 대응 매뉴얼 | 출하 Agent |
| `supplier_eval_docs` | 공급처 평가 이력 문서 | 입고 Agent |

**임베딩 스키마**: `(doc_id, chunk_id, content, embedding VECTOR(1536), metadata JSONB, source_type)` — 코사인 유사도 검색, HNSW 인덱스 적용.

---

## 7. AI 모델 파이프라인 다이어그램

### 7.1 ML Engine (숙성/발효)
```
 [입력 Feature]
 절임 온도·염도·pH·시간 ┐
 발효 온도·산도·숙성시간├──► [전처리/정제] ──► [Feature Engineering]
 외기 온습도            │     노이즈 제거       파생변수: 온도변화율, pH변화율,
 원재료 LOT 속성        ┘     이상치/결측 보정   염도×절임시간, 함수율 대비 탈수율
 (크기/중량/등급/함수율)                          Z-score / Min-Max 스케일링
                                                          │
        ┌──────────────────────────────┬─────────────────┼──────────────────┐
        ▼                              ▼                  ▼                  ▼
 ┌─────────────┐            ┌──────────────┐    ┌──────────────┐   ┌──────────────┐
 │  XGBoost    │            │ RandomForest │    │     SVR      │   │ LSTM         │
 │ 품질 분류   │            │ 특성 중요도  │    │ 산도/숙성도  │   │ (Sliding Win)│
 │ 정상/주의/  │            │ (→SHAP 연계) │    │ 연속값 회귀  │   │ 완료시점 예측│
 │ 이상        │            │              │    │              │   │ 시계열 진행  │
 └──────┬──────┘            └──────┬───────┘    └──────┬───────┘   └──────┬───────┘
        └───────────────────────────┴───────┬───────────┴──────────────────┘
                                             ▼
                                   ┌──────────────────┐
                                   │   SHAP 설명       │
                                   │ 품질요인 분석 출력│
                                   └────────┬─────────┘
                                            ▼
        [출력] 발효 품질 예측값 · 발효 완료 예상 시점 · 이상발효 조기 경보 · 최적 절임 조건 추천
                                            │
                                            ▼
                          ┌──────────────────────────────────┐
                          │  성능 목표 검증 게이트            │
                          │  품질예측≥80% · 완료오차≤2h MAE  │
                          │  이상탐지≥85% · Recall≥85% · R²≥0.85 │
                          └──────────────────────────────────┘
```

### 7.2 RAG AI Agent (입고/출하/통합)
```
 [사용자 질의 (SmartPad/Web)]
            │
            ▼
 ┌──────────────────────┐
 │ LangGraph Router      │  ── 질의 의도 분류 → 입고/출하/통합 Agent 라우팅
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐     ┌────────────────────────┐
 │ Embedding (Query)     │────►│ pgvector 유사도 검색    │
 └──────────────────────┘     │ (SOP/기준서/매뉴얼)     │
                              └───────────┬────────────┘
            ┌──────────────────────────────┘
            ▼
 ┌──────────────────────┐     ┌────────────────────────┐
 │ Context 결합          │◄────│ PostgreSQL 정형 조회    │
 │ (문서 + LOT 데이터)   │     │ (입고이력/LOT추적/클레임)│
 └──────────┬───────────┘     └────────────────────────┘
            ▼
 ┌──────────────────────┐
 │ LLM 응답 생성         │  ── 출처(문서/LOT) 인용 포함
 └──────────┬───────────┘
            ▼
 [응답 + 근거] → agent_query_history 기록 → (필요 시) 인간 승인 게이트
```

---

## 8. 보안 아키텍처 (VPN, 인증, 권한)

### 8.1 네트워크
```
 [현장 SmartPad/Gateway] ──(Site-to-Site VPN / IPSec)──► [AWS VPC]
                                                            │
   ┌────────────────────────────────────────────────────────┐
   │ VPC                                                      │
   │  ┌─────────────────┐         ┌──────────────────────┐   │
   │  │ Public Subnet   │         │ Private Subnet        │   │
   │  │ - Nginx (ALB)   │────────►│ - FastAPI / Streamlit │   │
   │  │ - Bastion       │         │ - AI Server           │   │
   │  └─────────────────┘         │ - PostgreSQL / pgvector(DB는 절대 Public 금지)│
   │                              └──────────────────────┘   │
   │  Security Group: 포트 최소 개방 (443, 내부 8000/5432만) │
   └──────────────────────────────────────────────────────────┘
```

### 8.2 인증/인가
- **인증**: JWT (Access 단기 + Refresh), 로그인 시 발급. SmartPad는 디바이스 등록 기반.
- **인가(RBAC)**: 3개 역할 — `관리자(admin)`, `현장작업자(worker)`, `공장장(manager)`
  - 작업자: 본인 공정 입력/조회만
  - 공장장: 승인 게이트(출하 승인, 레시피 수정, ML 재학습), KPI, 전 공정 조회
  - 관리자: 사용자/시스템/권한 설정
- **내부 서비스 통신**: `X-Internal-Token` + VPC 내부 통신, 향후 mTLS 확장 가능
- **시크릿 관리**: AWS Secrets Manager (하드코딩 금지), IAM 역할 기반 접근

### 8.3 데이터 보안 / 감사
- 전송구간 TLS(HTTPS/WSS), 저장 데이터 RDS 암호화(KMS)
- `system_logs` / `approval_log` 감사 추적 보존
- AI 추천은 직접 제어 불가 — 인간 승인 게이트 필수 (운영 원칙)

---

## 9. 확장성 고려사항

| 영역 | 현재 (시범운영) | 확장 전략 |
|------|-----------------|-----------|
| 데이터 수집 | Gateway x1, Kafka 단일 | Topic 파티션 증설, Consumer Group 수평 확장 |
| API | FastAPI 단일 AP서버 | Docker 컨테이너 다중화 → ALB 로드밸런싱, 추후 EKS 전환 |
| DB | PostgreSQL 운영DB (300G x2) | Read Replica 추가, 시계열 파티셔닝(월/LOT 단위) |
| Vector DB | pgvector 단일 | HNSW 인덱스 튜닝, 컬렉션 분리, 샤딩 |
| ML | 배치 학습 + 온디맨드 추론 | 모델 버전관리(model_version), 주기적 재학습 파이프라인, GPU 인스턴스 옵션 |
| 캐시 | Redis 단일 | KPI 집계/세션 캐시, 추후 클러스터 모드 |
| 다공장 | 단일 공장 | LOT/테넌트 키 설계로 멀티 사이트 확장 대비 |

### 9.1 가용성 / 무결성
- Edge 로컬 버퍼링으로 네트워크 단절 시 데이터 손실 방지
- Kafka 재처리(Replay)로 ETL 장애 복구
- S3 Raw Zone 원본 보존으로 재가공/감사 가능
- DB 자동 백업(스냅샷) + CloudWatch 모니터링/알람

### 9.2 향후 고도화 (Phase 6 운영 안정화)
- ≥3개월 LOT 데이터 축적 후 AI 성능 재검증
- 모델 지속 재학습, 프롬프트/문서 정제
- 단계적 자동화 비중 확대(승인 게이트 → 조건부 자동 반영)

---

## 부록. 서버 배치 요약

| 서버 | 스펙 | 배치 컴포넌트 |
|------|------|---------------|
| AP Server | 4vCPU/8G/100G | Nginx, FastAPI, Streamlit, Docker, Redis(캐시) |
| DB Server | 4vCPU/16G/300G x2 | PostgreSQL 운영DB |
| Vector DB | 4vCPU/16G/200G | PostgreSQL + pgvector |
| AI Server | 8vCPU/16G/200G | LangChain, LangGraph, Prophet, ML(XGBoost/RF/SVR/LSTM/SHAP), Python |
| AI Data Gateway | Edge Mini PC + PLC | OPC-UA/Modbus 수집, LOT 부여, 로컬 버퍼 |
| SmartPad x3 | Tablet | POP 입력 (입고/절임/포장출하) |
| 현황판 x1 | Display | 실시간 대시보드 표출 |
