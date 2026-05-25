# 꽃순이김치 제조AI MES 풀스택 개발 완료 보고서

> **Status**: Complete
>
> **Project**: 꽃순이김치 제조AI 스마트공장 MES
> **Project Code**: SF26179540
> **Version**: 1.0.0
> **Author**: report-generator (로뎀솔루션 주식회사)
> **Completion Date**: 2026-05-24
> **PDCA Cycle**: #1 (Full-Stack Build)

---

## 1. 프로젝트 개요 및 목표

### 1.1 프로젝트 정보

| 항목 | 내용 |
|------|------|
| 프로젝트명 | 꽃순이김치 제조AI 스마트공장 MES |
| 프로젝트 코드 | SF26179540 |
| 발주처 | 평창꽃순이(주)농업회사법인 |
| 개발사 | 로뎀솔루션 주식회사 |
| 예산 | 약 3.97억원 |
| 개발 기간 | 2026-05-23 ~ 2026-05-24 |
| 작업 디렉토리 | `C:\AI Make\31 PC-Kimchi-AI-MES\_workspace\` |

### 1.2 프로젝트 목표

원재료 입고부터 발효·포장·출하까지 IoT + MES + AI를 연결하여 LOT 기반 완전 추적성을 확보하고, 두 핵심 공정(숙성/발효, 원재료입고/포장출하)에 제조AI를 적용한다.

- **숙성/발효**: ML 기반 품질 예측 (XGBoost / LSTM / SHAP)
- **원재료입고 / 포장·출하**: RAG 기반 AI Agent (LangChain / LangGraph)

### 1.3 KPI 목표

| KPI | 현재 (Baseline) | 목표 | 개선율 |
|-----|----------------|------|--------|
| 시간당 생산량 | 2,750 kg/h | 3,000 kg/h | +9.1% |
| 완제품 불량률 | 1.5% | 1.0% | -26.8% |
| 발효 품질 예측 정확도 | - | ≥ 80% | - |
| 발효 완료 시점 예측 오차 | - | ≤ 2시간 MAE | - |
| 이상발효 조기탐지 정확도 | - | ≥ 85% | - |

---

## 2. 결과 요약

```
┌─────────────────────────────────────────────┐
│  MES 풀스택 구현 완료: 100%                   │
├─────────────────────────────────────────────┤
│  ✅ 모듈 구현:     10 / 10 모듈               │
│  ✅ 산출 파일:     30 / 30 파일               │
│  ✅ QA 이슈 수정:  30 / 30 건                 │
│  ⏳ AI 모델 학습:   다음 단계 (실데이터 필요) │
└─────────────────────────────────────────────┘
```

| 지표 | 값 |
|------|-----|
| 총 산출 파일 | 30개 (Python 20개 + SQL 10개) |
| 총 코드 라인 | 13,971줄 |
| API 라우터 | 10개 (약 130개 엔드포인트) |
| DB 테이블 | 약 45개 + 4개 뷰 |
| QA 이슈 수정 | 30건 (Phase1 25건 + Phase2 5건) |
| Streamlit UI 페이지 | 10개 모듈 페이지 |

---

## 3. 개발 범위 및 모듈별 구현 현황

전체 개발은 2개 Phase로 나누어 진행되었으며, 각 Phase마다 에이전트 팀 5명이 병렬 개발 후 QA 검증·수정을 거쳤다.

### 3.1 Phase 1 — PM3 백오피스 모듈 (공정·데이터·KPI·기준정보·시스템관리)

| 모듈 | DB 스키마 | API 라우터 | UI 페이지 | 상태 |
|------|-----------|------------|-----------|------|
| 공정관리 | `db_process_schema.sql` | `api_process_router.py` | `ui_05_process.py` | ✅ |
| 데이터관리 | `db_data_schema.sql` | `api_data_router.py` | `ui_06_data.py` | ✅ |
| KPI관리 | `db_kpi_schema.sql` | `api_kpi_router.py` | `ui_07_kpi.py` | ✅ |
| 기준정보관리 | `db_master_schema.sql` | `api_master_router.py` | `ui_08_master.py` | ✅ |
| 사용자/시스템관리 | `db_system_schema.sql` | `api_system_router.py` | `ui_09_system.py` | ✅ |

### 3.2 Phase 2 — 핵심 비즈니스 5개 모듈 (대시보드·원재료·발효·출하·AI Agent)

| 모듈 | DB 스키마 | API 라우터 | UI 페이지 | 상태 |
|------|-----------|------------|-----------|------|
| 📊 AI 대시보드 | `db_dashboard_schema.sql` | `api_dashboard_router.py` | `ui_01_dashboard.py` | ✅ |
| 🥬 원재료관리 | `db_material_schema.sql` | `api_material_router.py` | `ui_02_material.py` | ✅ |
| 🫙 숙성발효관리 | `db_fermentation_schema.sql` | `api_fermentation_router.py` | `ui_03_fermentation.py` | ✅ |
| 📦 포장출하관리 | `db_shipping_schema.sql` | `api_shipping_router.py` | `ui_04_shipping.py` | ✅ |
| 🤖 AI Agent 통합관리 | `db_agent_schema.sql` | `api_agent_router.py` | `ui_10_agent.py` | ✅ |

### 3.3 모듈별 핵심 기능 (CLAUDE.md 모듈 정의 매핑)

| 모듈 | 핵심 기능 |
|------|-----------|
| AI 대시보드 | 생산현황 분석, 품질현황 분석, 발효상태 모니터링, 출하현황 분석 |
| 원재료관리 | 입고관리, 원재료 이력조회, 선별 데이터관리, 공급처 품질분석, 입고 AI Agent |
| 숙성발효관리 | 발효상태 모니터링, 품질예측결과, 발효완료예측, 이상발효알림, ML분석, 영향요인/공정조건 분석 |
| 포장출하관리 | 포장실적관리, 출하관리, LOT추적, 검사결과관리, 클레임분석, 출하 AI Agent |
| 공정관리 | 공정실적관리, 공정 데이터 모니터링, 레시피 관리, 공정이력조회, 공정데이터 분석 |
| 데이터관리 | 데이터통합관리, 데이터조회, 시각화, 다운로드, AI학습 데이터관리 |
| AI Agent 통합관리 | 통합 AI질의, 생산/품질 분석, 의사결정 지원, 알림·추천, 사용자 질문이력 |
| 기준정보관리 | 품질기준 관리, 작업표준 관리, 코드관리 |
| 사용자/시스템관리 | 사용자 관리, 로그 관리, 알림 설정, 시스템 설정 |
| KPI관리 | 생산성 KPI 조회, 품질 KPI 조회, KPI 관리 |

---

## 4. 에이전트 팀 구성 및 병렬 개발 전략

### 4.1 에이전트 팀 (mes-orchestrator 조율)

| 에이전트 | 역할 | 스킬 |
|----------|------|------|
| `mes-orchestrator` | 전체 조율 (오케스트레이터) | - |
| `db-architect` | PostgreSQL/pgvector 스키마 설계 | `db-schema-design` |
| `backend-developer` | FastAPI REST API | `fastapi-mes` |
| `ml-engineer` | XGBoost/LSTM/SHAP 발효 예측 모델 | `ml-fermentation` |
| `rag-engineer` | LangChain/LangGraph RAG Agent | `rag-agent-mes` |
| `frontend-developer` | Streamlit 대시보드/UI | `streamlit-dashboard` |
| `data-pipeline-engineer` | IoT/MQTT/Kafka/ETL | `data-pipeline` |
| `qa-validator` | 통합 테스트 및 QA 검증 | - |

### 4.2 병렬 개발 전략

각 Phase에서 모듈 단위로 5명의 개발 에이전트가 동시에 DB → API → UI 수직 슬라이스를 구현하고, 이후 `qa-validator`가 전체 산출물을 교차 검증하였다. 이 전략으로 모듈 간 결합도를 낮추면서 단기간(2일) 풀스택 구현을 달성하였다.

```
[Phase 1]  5개 모듈 병렬 개발  ──▶  QA 검증  ──▶  25건 수정
[Phase 2]  5개 모듈 병렬 개발  ──▶  QA 검증  ──▶   5건 수정
```

병렬 개발 시 발생하는 전형적 충돌(테이블 중복 정의, 라우트 순서, 시그니처 불일치, LOT 형식 불일치)은 QA 단계에서 집중적으로 검출·수정되었다.

---

## 5. QA 이슈 분류 및 수정 현황

총 30건의 QA 이슈를 검출·수정하였다 (Phase1 25건 + Phase2 5건).

### 5.1 Phase 1 QA — 25건

#### HIGH (3건)

| 이슈 | 수정 |
|------|------|
| `GET /ai/labels` 엔드포인트 누락 | 누락 라우트 추가 |
| PGVector 스키마 충돌 | 스키마 정의 정합화 |
| `RETURNING *` 보안 노출 | 필요 컬럼만 명시 반환 |

#### MEDIUM (9건)

| 이슈 | 수정 |
|------|------|
| `st.fragment` 자동갱신 미적용 | fragment 기반 주기적 갱신 적용 |
| KPI 척도 불일치 (10,250% 버그) | 척도 정규화 |
| 400/500 오류 미분리 | 클라이언트/서버 오류 분리 처리 |
| asyncpg 트랜잭션 안전성 | 트랜잭션 경계 보강 |
| SOP 버전 그룹핑 오류 | 버전 그룹핑 로직 수정 |
| RBAC 권한 제한 미흡 | 권한 제한 강화 |
| 시드 데이터 오류 | 시드 정정 |
| 보존 정책 미문서화 | 보존 정책 문서화 |
| 알림 토글 UI 누락 | 토글 UI 추가 |

#### LOW (13건)

FK 설계 주석, 422 Pydantic 오류 파싱, 알림 시드, `require_role` stub, 파라미터 검증, DQ 규칙 SQL, 서버 다운로드 API, 품질기준 시드, 제품코드 시드, 임베딩 중복 제거, 권한 주석, 타입 주석, 인덱스 패턴 통일.

### 5.2 Phase 2 QA — 5건

| 심각도 | 이슈 | 수정 |
|--------|------|------|
| HIGH | `supplier` 테이블 중복 정의 (`db_master` + `db_material`) | 단일 소스로 통합 |
| HIGH | `/suppliers/ranking` 라우트 순서 버그 (`supplier_code`로 캡처) | 정적 라우트를 동적 라우트보다 우선 배치 |
| MEDIUM | `require_role` 시그니처 불일치 (list vs *args) | 시그니처 통일 |
| LOW | `packaging_lot.source_lot_id` LOT 형식 불일치 (FERM- → FE-) | LOT 접두사 정합화 |
| LOW | 알림/알람 텍스트 `FERM-` 잔존 | 텍스트 정정 |

### 5.3 심각도별 집계

| 심각도 | Phase 1 | Phase 2 | 합계 |
|--------|:-------:|:-------:|:----:|
| HIGH | 3 | 2 | 5 |
| MEDIUM | 9 | 1 | 10 |
| LOW | 13 | 2 | 15 |
| **합계** | **25** | **5** | **30** |

---

## 6. 기술적 주요 결정 사항

| 결정 영역 | 결정 내용 | 사유 |
|-----------|-----------|------|
| DB 접근 계층 | PGVector ORM 추상화 대신 직접 `asyncpg` 사용 | 트랜잭션 제어·성능 명시성 확보, pgvector 쿼리 직접 제어 |
| 대시보드 자동갱신 | Streamlit `st.fragment` 기반 부분 갱신 | 전체 페이지 rerun 없이 실시간 모니터링, 자원 절감 |
| LOT 체인 설계 | 입고LOT → 절임LOT → 발효LOT → 출하LOT 단방향 연결, 접두사 표준화 (FE- 등) | 공정 간 완전 추적성(Traceability) 확보, FK 정합성 |
| 권한 제어 | `require_role` RBAC 의존성 통일 시그니처 | 모듈 간 권한 검증 일관성, 시그니처 충돌 방지 |
| 오류 처리 | 400(클라이언트) / 422(검증) / 500(서버) 명시적 분리 | API 디버깅 용이성, 클라이언트 처리 명확화 |
| API 반환 정책 | `RETURNING *` 금지, 필요 컬럼만 명시 | 내부 컬럼·민감정보 노출 방지 |
| AI 통합 정책 | AI는 조회·분석·추천·경고만, 직접 공정 제어 없음 | 시범운영 단계 운영자 승인 게이트 원칙 (CLAUDE.md) |
| 테이블 단일 소스 | 공유 엔티티(supplier 등) 중복 정의 금지 | 스키마 충돌·데이터 정합성 오류 방지 |

---

## 7. 아키텍처 다이어그램

### 7.1 시스템 전체 데이터 흐름

```
[현장 설비/센서 (Physical)]
        │  (OPC-UA / Modbus TCP/IP)
        ▼
[Edge Collector Mini PC + PLC]   ── 네트워크 단절 시 로컬 버퍼링 (무결성)
        │  (MQTT / Kafka Streaming)
        ▼
[Data Lake (Raw Zone)]
        │  ETL: 노이즈 제거 / 이상치 제거 / 결측 보간 / LOT 통합
        ▼
┌──────────────────────────┬──────────────────────────┐
│  PostgreSQL 운영DB        │  pgvector Vector DB       │
│  (생산·LOT·공정·품질)     │  (SOP·기준서·매뉴얼 임베딩)│
└────────────┬─────────────┴──────────────┬────────────┘
             ▼                             ▼
   [AI Engine (ML)]              [RAG Agent (LangChain)]
   XGBoost/LSTM/SHAP             입고 Agent / 출하 Agent
             │                             │
             └──────────────┬──────────────┘
                            ▼
            [FastAPI REST API — 10 Routers / ~130 EP]
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
  [관리자 Web]       [Smart Pad/POP]        [현황판]
  Streamlit Dashboard  현장 데이터 입력     실시간 표시
```

### 7.2 애플리케이션 계층 (구현 산출물 기준)

```
┌─────────────────────── Presentation (Streamlit) ───────────────────────┐
│ ui_01_dashboard  ui_02_material  ui_03_fermentation  ui_04_shipping     │
│ ui_05_process    ui_06_data      ui_07_kpi   ui_08_master  ui_09_system │
│ ui_10_agent                                                             │
└────────────────────────────────┬───────────────────────────────────────┘
                                  ▼ (httpx)
┌─────────────────────── API Layer (FastAPI Routers) ─────────────────────┐
│ dashboard  material  fermentation  shipping  process                    │
│ data       kpi       master        system    agent     (~130 endpoints) │
└────────────────────────────────┬───────────────────────────────────────┘
                                  ▼ (asyncpg)
┌─────────────────────── Data Layer (PostgreSQL + pgvector) ──────────────┐
│ db_dashboard  db_material  db_fermentation  db_shipping  db_process     │
│ db_data       db_kpi       db_master        db_system    db_agent       │
│ (~45 tables + 4 views, LOT 체인 키 연결)                                │
└──────────────────────────────────────────────────────────────────────────┘
```

### 7.3 LOT 추적 체인

```
입고 LOT  ──▶  절임 LOT  ──▶  발효 LOT (FE-)  ──▶  포장 LOT  ──▶  출하 LOT
   │             │              │                    │             │
   └─────────────┴── 모든 공정 데이터 LOT ID 키 조인 (Full Traceability) ──┘
```

---

## 8. 다음 단계 권고사항

### 8.1 즉시 (인프라·통합)

- [ ] AWS 클라우드 인프라 프로비저닝 (AP / DB / Vector DB / AI Server)
- [ ] PostgreSQL + pgvector 스키마 10개 실 DB 배포 및 마이그레이션
- [ ] FastAPI ↔ Streamlit ↔ DB 엔드투엔드 통합 테스트
- [ ] 기존 MES API 연계 인터페이스(원재료·LOT·재고·출하) 검증

### 8.2 단기 (AI 실연동)

| 항목 | 내용 | 우선순위 |
|------|------|:--------:|
| ML 모델 학습 | XGBoost/RF/SVR/LSTM 실데이터 학습 (현재 stub) | High |
| SHAP 설명성 연동 | 운영자용 품질 요인 분석 출력 실연동 | High |
| RAG Agent 실연동 | 입고/출하 Agent LangChain·pgvector 실제 검색 연결 (현재 stub) | High |
| SOP/기준서 임베딩 | 작업표준서·품질기준서·HACCP 문서 Vector DB 적재 | High |
| 데이터 파이프라인 | MQTT/Kafka → Data Lake → ETL 실 스트리밍 구성 | Medium |

### 8.3 중기 (현장 검증)

| 항목 | 내용 | 우선순위 |
|------|------|:--------:|
| Shadow Mode 시범운영 | AI 추천을 운영자가 검토 후 적용 (직접 제어 금지) | High |
| 3개월+ LOT 데이터 축적 | AI 성능 검증 위한 실 LOT 데이터 수집 | High |
| AI 성능 KPI 검증 | 예측 정확도 ≥80%, 완료시점 MAE ≤2h, 이상탐지 ≥85% 측정 | High |
| 생산 KPI 검증 | 생산량 +9.1%, 불량률 -26.8% 달성 측정 | High |
| 모델 재학습 파이프라인 | 지속 재학습·프롬프트/문서 고도화 | Medium |

---

## 9. 총 작업 요약 통계

| 지표 | 값 |
|------|-----|
| 개발 기간 | 2026-05-23 ~ 2026-05-24 (2일) |
| 구현 모듈 | 10개 (100%) |
| 총 산출 파일 | 30개 (Python 20 + SQL 10) |
| 총 코드 라인 | 13,971줄 |
| API 라우터 | 10개 |
| API 엔드포인트 | 약 130개 |
| DB 테이블 | 약 45개 |
| DB 뷰 | 4개 |
| QA 이슈 검출·수정 | 30건 (HIGH 5 / MEDIUM 10 / LOW 15) |
| 참여 에이전트 | 8명 (오케스트레이터 1 + 개발 6 + QA 1) |
| Phase 구성 | 2 Phase (각 5개 모듈 병렬) |

### 9.1 회고 (KPT)

**Keep (잘된 점)**
- 모듈 단위 수직 슬라이스(DB→API→UI) 병렬 개발로 단기간 풀스택 완성
- QA 단계에서 병렬 개발 충돌(테이블 중복, 라우트 순서)을 체계적으로 검출
- LOT 체인 설계로 공정 전반 추적성 기반 확보

**Problem (개선 필요)**
- 공유 엔티티(supplier) 중복 정의 등 병렬 개발 시 스키마 사전 합의 부족
- LOT 접두사 표준(FE-) 미합의로 형식 불일치 다수 발생
- ML/RAG는 stub 수준 — 실데이터·실모델 연동 미완

**Try (다음 시도)**
- 병렬 개발 전 공유 스키마·코드·LOT 표준 사전 확정 (Phase 0 표준화)
- ML/RAG 통합 테스트를 위한 합성 데이터셋 선제 준비
- CI 단계 자동 스키마 충돌·라우트 순서 검증 도입

---

## 10. Changelog

### v1.0.0 (2026-05-24)

**Added:**
- 10개 MES 모듈 풀스택 구현 (DB 스키마 + FastAPI 라우터 + Streamlit UI)
- LOT 기반 추적성 체인 데이터 모델 (약 45개 테이블 + 4개 뷰)
- 약 130개 REST API 엔드포인트
- ML(XGBoost/LSTM/SHAP) 및 RAG Agent(LangChain/LangGraph) 통합 stub
- AI Agent 통합관리 모듈 (통합 질의·추천·의사결정 지원)

**Fixed:**
- Phase 1 QA 25건 (HIGH 3 / MEDIUM 9 / LOW 13)
- Phase 2 QA 5건 (HIGH 2 / MEDIUM 1 / LOW 2)
- KPI 척도 불일치(10,250% 버그), supplier 테이블 중복, 라우트 순서, LOT 형식 불일치 등

**Changed:**
- DB 접근을 ORM 추상화 대신 직접 asyncpg로 통일
- 대시보드를 st.fragment 기반 부분 자동갱신으로 전환
- API 반환 정책 RETURNING * 제거, 오류 코드 400/422/500 분리

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-05-24 | 풀스택 개발 완료 보고서 작성 | report-generator |
