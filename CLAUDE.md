# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**꽃순이김치 제조AI 스마트공장 시스템** — A Manufacturing AI-specialized Smart Factory MES for 평창꽃순이(주)농업회사법인 (Pyeongchang Kkotsooni Kimchi). Project code: SF26179540, budget: ~3.97억원, year: 2026. Developed by 로뎀솔루션 주식회사.

The system connects raw material intake through fermentation, packaging, and shipping via IoT + MES + AI. The two AI-targeted processes are:
- **숙성/발효** (Fermentation): ML-based quality prediction
- **원재료 입고 / 포장·출하** (Raw intake / Packaging-shipping): RAG-based AI Agent

**KPI targets**: 시간당 생산량 2,750→3,000 kg/h (+9.1%), 완제품 불량률 1.5%→1.0% (-26.8%)

---

## Manufacturing Process Flow

```
입고/보관 → 절단/전처리 → 세척/절임 → 세척/선별 → 탈수 → 혼합 → 숙성/발효 → 금속검출 → 포장/출하
```

All process data flows through the **Data Gateway** (centralized physical hub) into the cloud data management system keyed on **LOT** for full traceability.

---

## System Architecture

### Layer Overview

```
[현장 설비/센서 (Physical)] 
    → [Edge Collector Mini PC + PLC]  (OPC-UA / Modbus TCP/IP)
    → [MQTT / Kafka Streaming]
    → [Data Lake (Raw)]
    → [ETL 가공]
    → [PostgreSQL 운영DB + pgvector Vector DB]
    → [AI Engine + RAG Agent + Dashboard]
```

### Cloud Servers (AWS)

| Server | Spec | Stack | Role |
|--------|------|-------|------|
| AP Server | 4vCPU / 8G / 100G SSD | Nginx, Streamlit, FastAPI, Docker | Web/API, Admin, AI Chat |
| DB Server | 4vCPU / 16G / 300G SSD | PostgreSQL | Process & operational data |
| Vector DB | 4vCPU / 16G / 200G SSD | PostgreSQL + pgvector | SOPs, manuals, quality docs (embedding search) |
| AI Server | 8vCPU / 16G / 200G SSD | LangChain, LangGraph, Prophet, Python | ML engine, RAG, prediction/chart |

### Hardware (Factory Floor)

| HW | Qty | Role |
|----|-----|------|
| AI Data Gateway | 1 | Edge data collection hub, LOT traceability |
| Smart Pad | 3 | Field worker AI Agent terminal (intake / fermentation / shipping) |
| 현황판 (Dashboard Board) | 1 | Real-time production/quality/fermentation display |

---

## Data Layer

### PostgreSQL (정형 데이터)
- 생산 실적 데이터
- 작업지시 데이터
- 원재료 입고 및 LOT 데이터
- 절임/발효 공정 데이터 (염도, pH, 온도, 숙성시간)
- 포장 및 출하 데이터
- 품질 검사 및 불량 데이터

### pgvector (비정형 데이터 — Embedding)
- 작업표준서 (SOP)
- 절임/발효 기준서
- 품질 기준서 및 QC 문서
- HACCP CCP 관리 문서
- 설비 운영 매뉴얼
- 불량 대응 / 클레임 대응 매뉴얼

**Data Integration Rule**: All cross-process data joins via LOT ID. Input LOT → 절임LOT → 발효LOT → 출하LOT must be linkable for Traceability.

---

## AI Modules

### ML Engine — 숙성/발효 공정

**Input features**: 절임 온도·염도·pH·시간, 발효 온도·산도·숙성시간, 외기 온습도, 원재료 LOT 정보 (배추 크기·중량·외관등급·함수율·원산지)

**Models and roles**:
- **XGBoost**: Core quality classification (정상/주의/이상)
- **Random Forest**: Feature importance analysis (SHAP과 연계)
- **SVR**: Continuous quality value prediction (산도, 숙성도)
- **LSTM**: Time-series fermentation progress and completion time prediction (Sliding Window input)
- **SHAP**: Explainable AI — quality factor analysis output for operators

**Output**: 발효 품질 예측값, 발효 완료 예상 시점, 이상발효 조기 경보, 최적 절임 조건 추천값

**AI Performance Targets**:
- 발효 품질 예측 정확도: ≥ 80%
- 발효 완료 시점 예측 오차: ≤ 2시간 MAE
- 이상발효 조기탐지 정확도: ≥ 85%
- 품질 리스크 재현율(Recall): ≥ 85%
- 회귀 성능(R²): ≥ 0.85

### RAG-based AI Agent — 원재료 입고 / 포장·출하

**Stack**: LLM + pgvector (LangChain / LangGraph)

**원재료 입고 Agent**:
- Query: 공급처 품질 이력, 입고 기준 적합 여부, LOT 기반 traceability 조회
- Data sources: 원재료 LOT DB + 품질기준서/공급처 평가 이력 (Vector DB)

**포장·출하 Agent**:
- Query: 출하 승인 기준 질의, LOT 추적, 클레임 원인 분석, 대응 가이드
- Data sources: 출하 승인 데이터 + 품질표준서/클레임 대응 매뉴얼 (Vector DB)

**Integration with MES**: AI Agent results go through human approval before affecting production plan (pilot verification phase).

---

## Application Modules

The system is organized into these top-level modules:

| Module | Key Functions |
|--------|---------------|
| **AI 대시보드** | 생산현황 분석, 품질현황 분석, 발효상태 모니터링, 출하현황 분석 |
| **원재료관리** | 입고관리, 원재료 이력조회, 선별 데이터관리, 공급처 품질분석, 입고 AI Agent |
| **숙성발효관리** | 발효상태 모니터링, 품질예측결과, 발효완료예측, 이상발효알림, ML분석, 영향요인 분석, 공정조건 분석 |
| **포장출하관리** | 포장실적관리, 출하관리, LOT추적, 검사결과관리, 클레임분석, 출하 AI Agent |
| **공정관리** | 공정실적관리, 공정 데이터 모니터링, 레시피 관리, 공정이력조회, 공정데이터 분석 |
| **데이터관리** | 데이터통합관리, 데이터조회, 데이터시각화, 데이터다운로드, AI학습 데이터관리 |
| **AI Agent 통합관리** | 통합 AI질의, 생산/품질 분석, 의사결정 지원, 알림 및 추천, 사용자 질문이력 |
| **기준정보관리** | 품질기준 관리, 작업표준 관리, 코드관리 |
| **사용자/시스템관리** | 사용자 관리, 로그 관리, 알림 설정, 시스템 설정 |
| **KPI관리** | 생산성 KPI 조회, 품질 KPI 조회, KPI 관리 |

### Presentation Clients
- **관리자 Web**: 생산·품질 모니터링, KPI, 재고·출하 통합관리
- **현장 POP / Smart Pad**: 작업지시 확인, 원재료 입고 데이터 입력, 생산실적·품질 입력
- **Mobile**: 현장 점검, 품질 입력, 재고·작업 상태 조회
- **현황판**: 공정별 생산량, 발효 상태, 출하 승인 상태 (대시보드)

---

## Integration Interfaces

| Integration | Method | Data |
|-------------|--------|------|
| MES ↔ Data Management System | API / DB / Excel | 원재료 정보, LOT, 재고, 출하 이력 |
| Data Management System ↔ ML Engine | REST API / Batch | 발효 공정 시계열 데이터 |
| Data Management System ↔ AI Agent | Vector DB | 표준문서 + 공정데이터 + 품질데이터 |

**Existing MES** manages: 생산실적, 작업지시, 공정 데이터 일부, 입고·재고·출하·거래 데이터. This project extends the MES with IoT integration and AI, not replacing it.

---

## Data Pipeline & Preprocessing

**Sensor → DB pipeline**:
1. Edge Collector buffers locally during network outage (무결성 확보)
2. MQTT/Kafka streaming → Data Lake (Raw Zone)
3. ETL: noise removal (Moving Average, Low-pass Filter), outlier removal (IQR, Z-score, Isolation Forest), missing value imputation (Forward Fill, KNN Imputation)
4. LOT-unit data consolidation for cross-process joins
5. Sliding Window transformation for LSTM input

**Feature Engineering for ML**:
- 파생변수: 온도 변화율, pH 변화율, 염도×절임시간, 함수율 대비 탈수율
- Z-score / Min-Max scaling for model stability
- LOT+Timestamp deduplication

---

## Development Phases

1. **현황진단 및 목표 정의** — KPI baseline measurement, bottleneck analysis
2. **데이터 표준화** — Item codes, LOT schema, SOP digitization for Vector DB
3. **시스템 연계 및 기반환경 구축** — MES API integration, cloud infra setup, Data Gateway deployment
4. **제조AI 기능 구축** — ML model training, RAG Agent, dashboard
5. **현장 검증 및 시범운영** — Shadow mode: AI recommendations reviewed by operators before production use; ≥3 months of LOT data required for AI performance validation
6. **운영 안정화 및 고도화** — Continuous model retraining, prompt/document refinement

**Principle**: AI is decision-support (조회·분석·추천·경고), not direct process control. Operator approval gates all AI-generated recommendations during initial rollout.

---

## Tech Stack Summary

| Category | Technology |
|----------|------------|
| Backend API | FastAPI (Python) |
| Web Frontend | Streamlit (admin/monitoring) |
| Web Server | Nginx |
| Containerization | Docker |
| Primary DB | PostgreSQL |
| Vector Search | pgvector |
| Message Broker | MQTT / Kafka |
| Edge Protocol | OPC-UA, Modbus TCP/IP |
| ML Models | scikit-learn (Random Forest, SVR), XGBoost, TensorFlow/PyTorch (LSTM) |
| Explainability | SHAP |
| Time Series | Prophet |
| AI Agent | LangChain, LangGraph |
| Cloud | AWS (EC2, S3, RDS, CloudWatch) |

---

## 하네스: 꽃순이김치 MES 개발

**목표:** MES 기능 개발 전 과정(DB→API→ML→RAG→UI)을 에이전트 팀이 자동으로 조율하여 구현한다.

**트리거:** MES 기능 구현, 모듈 개발, API 개발, 스키마 설계, ML 모델, RAG Agent, 대시보드, KPI, 데이터 파이프라인 등 모든 MES 개발 요청 시 `mes-orchestrator` 스킬을 사용하라. 단순 질문은 직접 응답 가능.

**에이전트 팀 구성 (8명):**
- `mes-orchestrator` — 전체 조율 (오케스트레이터)
- `db-architect` — PostgreSQL/pgvector 스키마 설계 (`db-schema-design` 스킬)
- `backend-developer` — FastAPI REST API (`fastapi-mes` 스킬)
- `ml-engineer` — XGBoost/LSTM/SHAP 발효 예측 모델 (`ml-fermentation` 스킬)
- `rag-engineer` — LangChain/LangGraph RAG Agent (`rag-agent-mes` 스킬)
- `frontend-developer` — Streamlit 대시보드/UI (`streamlit-dashboard` 스킬)
- `data-pipeline-engineer` — IoT/MQTT/Kafka/ETL (`data-pipeline` 스킬)
- `qa-validator` — 통합 테스트 및 QA 검증

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
|------|----------|------|------|
| 2026-05-23 | 초기 구성 | 전체 | 신규 하네스 구축 |
| 2026-05-24 | 하네스 감사 및 개선 | frontend-developer, qa-validator, CLAUDE.md | frontend-design 스킬 연결, qa-validator subagent_type 보강, 변경 이력 갱신 |
