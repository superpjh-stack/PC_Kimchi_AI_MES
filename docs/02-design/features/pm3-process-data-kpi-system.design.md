# pm3-process-data-kpi-system 설계 문서

> **Feature**: 공정관리 / 데이터관리 / KPI관리 / 기준정보관리 / 사용자·시스템관리
> **Author**: PM3 + 개발팀
> **Created**: 2026-05-25
> **Status**: Implemented (Post-hoc Design)
> **Plan Ref**: `docs/01-plan/features/pm3-process-data-kpi-system.plan.md`

---

## 1. 아키텍처 개요

```
[Streamlit 페이지] ──httpx──► [FastAPI /api/v1/*] ──asyncpg──► [PostgreSQL]
                                                              ──PGVector──► [Vector DB]
```

| 레이어 | 기술 | 포트/경로 |
|--------|------|----------|
| Frontend | Streamlit (pages/05~09) | localhost:8501 |
| Backend | FastAPI + uvicorn | localhost:8000 |
| Primary DB | PostgreSQL + asyncpg | localhost:5432/kimchi_mes |
| Vector DB | PostgreSQL + pgvector | VECTOR_DB_URL |

---

## 2. 모듈별 설계

### 2.1 공정관리 (Process Management)

**파일 구조**
```
_workspace/
├── db_process_schema.sql      ← process_result, process_recipe, process_alarm, process_analysis_view
├── api_process_router.py      ← /api/v1/process  (10 endpoints)
└── ui_05_process.py           → streamlit_app/pages/05_공정관리.py
```

**DB 테이블**

| 테이블 | 역할 |
|--------|------|
| `process_result` | 9개 공정 공통 실적 (LOT 체인 + JSONB 공정별 상세) |
| `process_recipe` | 제품별 레시피 버전관리 + 원료비율 + 승인 워크플로우 |
| `process_alarm` | 공정 이상 감지 알림 (WARNING/CRITICAL, OPEN/RESOLVED) |
| `process_analysis_view` | 공정별 KPI 집계 뷰 |

**API 엔드포인트 (10개)**

| Method | Path | 설명 |
|--------|------|------|
| POST | /results | 공정 실적 등록 (수율 자동계산) |
| GET | /results | 공정 실적 조회 (필터: code/date/lot) |
| GET | /results/{lot_id}/history | LOT 공정이력 (RECURSIVE CTE) |
| GET | /monitor/realtime | 실시간 공정 현황 |
| GET | /alarms | 이상 알림 목록 |
| PATCH | /alarms/{id}/resolve | 알림 해결 처리 |
| GET | /recipes | 레시피 목록 |
| POST | /recipes | 레시피 등록 |
| PUT | /recipes/{id} | 레시피 수정 (버전 관리) |
| GET | /analysis | 공정데이터 분석 |

**UI 탭 구조**
```
공정관리
├── 탭1: 공정실적 입력  (9개 공정 폼, httpx POST)
├── 탭2: 실시간 모니터링  (Plotly 게이지 + 알림 패널)
├── 탭3: 레시피 관리  (레시피 목록 + 등록/수정)
├── 탭4: 공정이력 조회  (LOT 검색 + 타임라인)
└── 탭5: 공정데이터 분석  (기간별 차트)
```

---

### 2.2 데이터관리 (Data Management)

**파일 구조**
```
_workspace/
├── db_data_schema.sql         ← pipeline_status, etl_log, edge_device_status, ai_dataset, data_label, data_quality_check
├── api_data_router.py         ← /api/v1/data  (12 endpoints)
└── ui_06_data.py              → streamlit_app/pages/06_데이터관리.py
```

**DB 테이블 (6개)**

| 테이블 | 역할 |
|--------|------|
| `pipeline_status` | Edge→MQTT→ETL→DB 단계별 상태 |
| `etl_log` | ETL 작업 실행 이력 |
| `edge_device_status` | Edge Collector 장치 연결 상태 |
| `ai_dataset` | AI 학습 데이터셋 목록 |
| `data_label` | 발효/입고/품질 데이터 라벨 + 승인 워크플로우 |
| `data_quality_check` | DQ-001~007 검증 규칙 실행 결과 |

**API 엔드포인트 (12개)**

| Method | Path | 설명 |
|--------|------|------|
| GET | /pipeline/status | 파이프라인 단계 상태 |
| GET | /pipeline/devices | Edge 장치 목록 |
| GET | /pipeline/etl-logs | ETL 실행 로그 |
| GET | /query/structured | 정형 DB 조회 (ALLOWED_TABLES 화이트리스트) |
| GET | /query/timeseries | 센서 시계열 조회 |
| GET | /query/lot-integrated/{lot_id} | LOT 통합 조회 (4공정 역추적) |
| GET | /download | StreamingResponse 다운로드 (Excel/CSV/JSON) |
| GET | /ai/datasets | 학습 데이터셋 목록 |
| GET | /ai/labels | 라벨 목록 (data_type/is_approved/lot_id 필터) |
| POST | /ai/labels | 라벨 등록 |
| PUT | /ai/labels/{id}/approve | 라벨 승인 |
| GET | /quality/checks | DQ 검증 결과 목록 |
| POST | /quality/run | DQ 검증 실행 (BackgroundTasks) |

**보안**
- SQL Injection 3중 방어: ALLOWED_TABLES 화이트리스트 + 컬럼 isalnum 검증 + $N 파라미터 바인딩

---

### 2.3 KPI관리 (KPI Management)

**파일 구조**
```
_workspace/
├── db_kpi_schema.sql          ← kpi_target, kpi_alert_config, kpi_report, kpi_daily_summary
├── api_kpi_router.py          ← /api/v1/kpi  (12 endpoints)
└── ui_07_kpi.py               → streamlit_app/pages/07_KPI관리.py
```

**KPI 계산 공식**

| KPI | 공식 | 목표 |
|-----|------|------|
| 시간당 생산량 | 월포장완료kg / (생산일수 × 근무시간) | 3,000 kg/h |
| 완제품 불량률 | (불량kg / 총생산kg) × 100 | 1.0% |
| 발효 품질 예측 정확도 | AI 분류 정확도 | ≥80% |
| 발효 완료 예측 오차 | MAE (시간) | ≤2h |

**색상 코딩 (달성률)**

| 달성률 | 색상 | 의미 |
|--------|------|------|
| ≥100% | 초록 | 목표 달성 |
| 90~99% | 노랑 | 목표 근접 |
| 70~89% | 주황 | 주의 필요 |
| <70% | 빨강 | 조치 필요 |

**API 엔드포인트 (12개)**

| Method | Path | 설명 |
|--------|------|------|
| GET | /summary/today | 오늘 KPI 6종 + 달성률 |
| GET | /summary/daily | 일별 KPI 요약 이력 |
| GET | /production/trend | 생산량 트렌드 |
| GET | /defect/trend | 불량률 트렌드 |
| GET | /defect/by-process | 공정별 불량 현황 |
| GET | /targets | KPI 목표값 목록 |
| PUT | /targets/{kpi_type} | KPI 목표값 수정 (버전관리) |
| GET | /alerts/config | 알림 임계값 설정 조회 |
| PUT | /alerts/config/{kpi_type} | 알림 임계값 수정 |
| POST | /reports/generate | KPI 리포트 생성 (DAILY/WEEKLY/MONTHLY/CUSTOM) |
| GET | /reports | 리포트 목록 |
| GET | /reports/{id}/download | 리포트 다운로드 |

---

### 2.4 기준정보관리 (Master Data Management)

**파일 구조**
```
_workspace/
├── db_master_schema.sql       ← quality_standard, sop_document, code_master, supplier
├── api_master_router.py       ← /api/v1/master  (15 endpoints)
└── ui_08_master.py            → streamlit_app/pages/08_기준정보관리.py
```

**SOP 임베딩 파이프라인**

```
파일 업로드 (PDF/DOCX) → 텍스트 추출 → Chunking (1000/200)
    → OpenAI Embeddings → PGVector.from_documents(collection_name="document_embeddings")
    → 관리자 검토/활성화 → RAG Agent 연동
```

**UI 탭 구조**
```
기준정보관리
├── 탭1: 품질 기준  (절임/발효/출하 기준값 + 색상 경고범위)
├── 탭2: 작업표준(SOP)  (업로드 + 임베딩 진행 표시 + 활성화)
├── 탭3: 코드 관리  (PROCESS/PRODUCT/DEFECT/MATERIAL 코드 CRUD)
└── 탭4: 공급업체  (공급업체 등록/수정)
```

---

### 2.5 사용자/시스템관리 (User & System Management)

**파일 구조**
```
_workspace/
├── db_system_schema.sql       ← users, roles, user_roles, role_permissions, system_log, user_activity_log,
│                                ai_agent_log, notification_config, notification_log,
│                                edge_device_config, sensor_mapping, batch_schedule
├── api_system_router.py       ← /api/v1/system  (22 endpoints)
└── ui_09_system.py            → streamlit_app/pages/09_시스템관리.py
```

**RBAC 권한 매트릭스**

| 역할 | 공정 | 데이터 | KPI | 기준정보 | 시스템 |
|------|------|--------|-----|---------|--------|
| ADMIN | R/W | R/W | R/W | R/W | R/W |
| MANAGER | R/W | R | R/W | R | R |
| QUALITY | R | R/W | R | R/W | — |
| OPERATOR | R/W | R | — | R | — |

**UI 탭 구조**
```
사용자/시스템관리
├── 탭1: 사용자 관리  (목록/등록/수정/비활성화 + 역할 부여/제거)
├── 탭2: 로그 관리  (시스템/활동/AI Agent 로그 3종 서브탭)
├── 탭3: 알림 설정  (알림 채널 + 수신자 + 이력)
└── 탭4: 시스템 설정  (Edge 장치 + 센서매핑 + 배치 스케줄)
```

---

## 3. LOT 추적 설계

```
입고 LOT
    └─► 절단 LOT
            └─► 절임 LOT
                    └─► 선별 LOT
                            └─► 탈수 LOT
                                    └─► 혼합 LOT
                                            └─► 발효 LOT
                                                    └─► 금속검출 LOT
                                                            └─► 포장 LOT
```

- `process_result.source_lot_id` → 상위 LOT 연결
- RECURSIVE CTE `WITH RECURSIVE lot_chain` → 양방향 체인 추적
- `GET /api/v1/process/results/{lot_id}/history` → 전체 이력 반환

---

## 4. 공통 설계 원칙

| 원칙 | 적용 |
|------|------|
| 비동기 DB | asyncpg + `async with get_db() as conn` |
| Pydantic v2 | 모든 요청/응답 모델 타입 검증 |
| 오류 처리 | DB 미연결 → RuntimeError → 503, 미존재 → 404, 중복 → 409 |
| SQL 보안 | $N 파라미터 바인딩, 동적 식별자 화이트리스트 검증 |
| 권한 | `require_role(["ADMIN", "MANAGER"])` Depends 패턴 |
| 소프트 삭제 | `is_active = FALSE` (물리 삭제 금지) |

---

## 5. QA 검증 결과 요약

| 모듈 | 통과율 | 상태 |
|------|--------|------|
| 공정관리 | 91% | ✅ 기준 충족 |
| KPI관리 | 90.9% | ✅ 기준 충족 |
| 데이터관리 | 86%→92% | ✅ GET /ai/labels 추가 후 기준 충족 |
| 기준정보관리 | 87%→91% | ✅ pgvector 일원화 주석 추가 |
| 사용자/시스템관리 | 86%→91% | ✅ OPERATOR×DATA 권한 수정 |

---

## 6. 파일 목록 (최종)

| 역할 | 파일 | 상태 |
|------|------|------|
| DB 스키마 | `_workspace/db_process_schema.sql` | ✅ |
| DB 스키마 | `_workspace/db_data_schema.sql` | ✅ |
| DB 스키마 | `_workspace/db_kpi_schema.sql` | ✅ |
| DB 스키마 | `_workspace/db_master_schema.sql` | ✅ |
| DB 스키마 | `_workspace/db_system_schema.sql` | ✅ |
| API | `_workspace/api_process_router.py` → `app/main.py` | ✅ |
| API | `_workspace/api_data_router.py` → `app/main.py` | ✅ |
| API | `_workspace/api_kpi_router.py` → `app/main.py` | ✅ |
| API | `_workspace/api_master_router.py` → `app/main.py` | ✅ |
| API | `_workspace/api_system_router.py` → `app/main.py` | ✅ |
| UI | `streamlit_app/pages/05_공정관리.py` | ✅ (교체 완료) |
| UI | `streamlit_app/pages/06_데이터관리.py` | ✅ (교체 완료) |
| UI | `streamlit_app/pages/07_KPI관리.py` | ✅ (교체 완료) |
| UI | `streamlit_app/pages/08_기준정보관리.py` | ✅ (교체 완료) |
| UI | `streamlit_app/pages/09_시스템관리.py` | ✅ (교체 완료) |
