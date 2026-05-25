---
name: mes-orchestrator
description: 꽃순이김치 제조AI MES 개발을 총괄 조율하는 오케스트레이터 스킬. MES 기능 구현, 모듈 개발, 화면 개발, API 개발, 스키마 설계, ML 모델, RAG Agent, 대시보드, KPI, 데이터 파이프라인, 시스템 연계 등 모든 MES 개발 요청 시 반드시 이 스킬을 사용하라. 다시 개발, 재실행, 업데이트, 수정, 보완 요청에도 트리거된다.
---

# 꽃순이김치 MES 개발 오케스트레이터

## 역할
평창꽃순이 제조AI 스마트공장 MES 시스템 개발을 전체 조율한다. 기능 요청을 분석하고 전문가 에이전트 팀을 구성하여 구현한다.

## 실행 모드
**에이전트 팀 (기본)**: `TeamCreate` + `TaskCreate` + `SendMessage`로 자체 조율.

---

## Phase 0: 컨텍스트 확인

`_workspace/` 존재 여부를 확인하여 실행 모드를 결정한다.

| 상황 | 실행 모드 |
|------|----------|
| `_workspace/` 없음 | **초기 실행** — Phase 1부터 전체 진행 |
| `_workspace/` 있음 + 부분 수정 요청 | **부분 재실행** — 해당 에이전트만 재호출 |
| `_workspace/` 있음 + 새 입력 제공 | **새 실행** — 기존 `_workspace/`를 `_workspace_prev/`로 이동 후 초기 실행 |

---

## Phase 1: 요구사항 분석

1. 사용자 요청에서 구현 대상 모듈/기능을 파악한다
2. 관련 문서를 확인한다:
   - `docs/01-plan/features/*.plan.md` — 기능 계획서
   - `docs/02-design/mockups/*.html` — UI 목업
   - `CLAUDE.md` — 시스템 아키텍처, AI 모듈, 공정 흐름
3. 구현 범위와 필요 에이전트 팀을 결정하고 사용자에게 확인한다

---

## Phase 2: 에이전트 팀 구성

기능 유형에 따라 필요한 에이전트를 선택하여 `TeamCreate`로 팀을 구성한다:

| 기능 유형 | 필요 에이전트 |
|----------|-------------|
| DB 스키마 설계 | db-architect |
| FastAPI API 개발 | backend-developer (db-architect 완료 후) |
| 발효 ML 모델 | ml-engineer (data-pipeline-engineer 완료 후) |
| RAG Agent 개발 | rag-engineer (db-architect pgvector 완료 후) |
| Streamlit UI | frontend-developer (backend-developer 완료 후) |
| IoT/ETL 파이프라인 | data-pipeline-engineer |
| 검증 | qa-validator (각 모듈 완료 후 즉시) |
| 전체 기능 구현 | 모든 에이전트 |

팀 구성 후 `TaskCreate`로 Phase별 작업을 할당하고 의존성을 명시한다.

---

## Phase 3: 개발 실행

### 3-1. 의존성 순서
```
data-pipeline-engineer
        ↓
db-architect
        ↓
backend-developer ──────┬──────────────────────
        ↓               ↓                      ↓
ml-engineer      rag-engineer       frontend-developer
        ↓               ↓                      ↓
                  qa-validator (모듈별 점진적 검증)
```

### 3-2. 병렬 실행 가능 항목
- `ml-engineer`와 `rag-engineer`는 DB 스키마 완료 후 병렬 실행 가능
- `frontend-developer`는 API 완료 후 독립 진행

### 3-3. 산출물 경로 규칙
모든 중간 산출물은 `_workspace/`에 저장한다:

```
_workspace/
├── db_{module}_schema.sql      -- DB 스키마 (db-architect)
├── api_{module}_router.py      -- FastAPI 라우터 (backend-developer)
├── ml_{model_name}.py          -- ML 모델 코드 (ml-engineer)
├── rag_{agent_name}.py         -- RAG Agent 코드 (rag-engineer)
├── ui_{page_name}.py           -- Streamlit 페이지 (frontend-developer)
├── pipeline_{component}.py     -- 파이프라인 코드 (data-pipeline-engineer)
└── qa_validation_report.md     -- QA 검증 보고서 (qa-validator)
```

---

## Phase 4: QA 검증

각 모듈 완성 직후 qa-validator를 호출하여 검증한다 (전체 완성 후 일괄 검증 X):

- API 엔드포인트 응답 (상태코드, 스키마 shape)
- LOT ID 연결성 (입고 → 절임 → 발효 → 출하)
- ML 성능 목표 달성 여부 (정확도, MAE, Recall, R²)
- RAG Agent 응답 품질 및 출처 명시

QA 실패 항목은 해당 에이전트에게 재작업 요청한다.

---

## Phase 5: 완료 보고

구현 완료 후 사용자에게 보고한다:
- 구현된 기능 목록
- 생성된 파일 경로
- QA 결과 요약
- 미완료/이슈 항목

---

## 에러 핸들링

| 상황 | 처리 방법 |
|------|----------|
| 에이전트 1회 실패 | 재시도 |
| 에이전트 2회 연속 실패 | 해당 항목 제외하고 진행, 보고서에 명시 |
| ML 성능 목표 미달 | ml-engineer에게 하이퍼파라미터 튜닝 재요청 (최대 3회) |
| LOT ID 불일치 | db-architect에게 스키마 확인 우선 요청 |
| pgvector 검색 품질 저하 | rag-engineer에게 임베딩 모델 재검토 요청 |

---

## MES 핵심 정보

### KPI 목표
- 시간당 생산량: 2,750 → 3,000 kg/h (+9.1%)
- 완제품 불량률: 1.5% → 1.0% (-26.8%)

### 공정 흐름
```
입고/보관 → 절단/전처리 → 세척/절임 → 세척/선별 → 탈수 → 혼합 → 숙성/발효 → 금속검출 → 포장/출하
```

### 주요 모듈
| 모듈 | 핵심 기능 |
|------|----------|
| AI 대시보드 | 생산/품질/발효/출하 현황 실시간 모니터링 |
| 원재료관리 | 입고, LOT, 공급처 품질, 입고 AI Agent |
| 숙성발효관리 | ML 품질예측, 발효완료예측, 이상발효 알림 |
| 포장출하관리 | 출하관리, LOT 추적, 클레임, 출하 AI Agent |
| 공정관리 | 공정실적, 레시피, 이력 |
| KPI관리 | 생산성/품질 KPI 시각화 |

---

## 테스트 시나리오

### 정상 흐름
"원재료 입고 관리 기능 개발해줘" →
1. Phase 0: `_workspace/` 없음 → 초기 실행
2. Phase 1: `pm2-intake-shipping.plan.md`, `10-material-shipping.html` 참조
3. Phase 2: db-architect + backend-developer + frontend-developer 팀 구성
4. Phase 3: db → api → ui 순차 개발
5. Phase 4: qa-validator가 API-UI 정합성 검증
6. Phase 5: 완료 보고

### 에러 흐름
db-architect 실패 → 1회 재시도 → 재실패 → 사용자에게 DB 스키마 설계 지연 보고 → 다른 에이전트 준비 작업 (Pydantic 모델 초안 등) 진행
