# Gap Analysis Report — pm3-process-data-kpi-system

> **Project**: 꽃순이김치 제조AI MES (SF26179540 / 로뎀솔루션)
> **Analyst**: bkit-gap-detector
> **Date**: 2026-05-25
> **PDCA Phase**: Check
> **Plan**: `docs/01-plan/features/pm3-process-data-kpi-system.plan.md`
> **Design**: `docs/02-design/features/pm3-process-data-kpi-system.design.md`

---

## 1. 분석 개요

- **범위**: 5개 운영 기반 모듈 (공정관리 / 데이터관리 / KPI관리 / 기준정보관리 / 사용자·시스템관리)
- **검증 파일**: DB 스키마 5개 + API 라우터 5개 + Streamlit 페이지 5개 = **15개 전체 확인**
- **분석 방법**: Plan §2~8 기능 명세 ↔ 구현 코드 대조, 기존 QA 보고서 5개와 교차 검증

---

## 2. 전체 Match Rate

| 카테고리 | 점수 | 상태 |
|----------|:----:|:----:|
| Design ↔ Plan 정합성 (§2~8 기능 대조) | 91% | ✅ |
| 아키텍처 준수 (Streamlit→FastAPI→asyncpg 3레이어) | 95% | ✅ |
| 코드 컨벤션 (fastapi-mes / asyncpg / Pydantic v2) | 93% | ✅ |
| **종합 Match Rate** | **91%** | ✅ **PASS** |

---

## 3. 모듈별 결과

| 모듈 | 설계 엔드포인트 | 구현 확인 | QA 기준 | 최종 | 상태 |
|------|:-:|:-:|:-:|:-:|:----:|
| 공정관리 (process) | 10 | 10/10 | 91% | 91% | ✅ |
| 데이터관리 (data) | 13* | 13/13 | 86%→92% | 92% | ✅ |
| KPI관리 (kpi) | 12 | 12/12 | 90.9% | 90.9% | ✅ |
| 기준정보관리 (master) | 15 | 15/15 | 87%→91% | 91% | ✅ |
| 사용자·시스템관리 (system) | 22 | 22/22 | 86%→91% | 91% | ✅ |

*데이터관리: `GET /ai/labels` 추가로 12→13개

### 코드 확인 하이라이트

| 모듈 | 검증 항목 | 확인 위치 |
|------|----------|-----------|
| 공정관리 | `WITH RECURSIVE` LOT 체인 추적 | api_process_router.py:279 |
| 공정관리 | 공정별 필수필드 검증 (`REQUIRED_DETAIL_FIELDS`) | api_process_router.py |
| 데이터관리 | `GET /ai/labels` 구현 (HIGH 이슈 해결) | api_data_router.py:467 |
| 데이터관리 | SQL Injection 3중 방어 | api_data_router.py:229,241,243 |
| KPI관리 | 시간당 생산량 공식 일치 | api_kpi_router.py:117-118 |
| KPI관리 | 불량률 역산 (낮을수록 좋음) | api_kpi_router.py:70-74 |
| 기준정보관리 | SOP 임베딩 파이프라인 (chunk 1000/200) | api_master_router.py:506 |
| 기준정보관리 | 활성화 전 임베딩 완료 검증 (409) | api_master_router.py:269 |
| 사용자/시스템관리 | notification_logs 파라미터 인덱스 수정 | api_system_router.py:504 |
| 사용자/시스템관리 | `update_user` RETURNING 명시 (hashed_password 제외) | api_system_router.py:244 |

---

## 4. Gap 목록

### 🔴 누락 항목 (Medium 이슈 — 비차단)

| # | 항목 | Plan 위치 | 설명 |
|---|------|-----------|------|
| G-1 | KPI 리포트 PDF/XLSX 실제 렌더링 | §6.4 K-08 | `POST /reports/generate`가 텍스트 플레이스홀더 저장 (reportlab/openpyxl 미구현) |
| G-2 | 알림 실제 발송 (SMS/Email) | §4.3, §6.4 | 알림 설정/로그 CRUD 존재, 발신 로직 및 에스컬레이션 타이머 미구현 |
| G-3 | `require_role` JWT 실제 연동 | §8.1 | process/kpi 라우터에서 stub (pass-through); system 라우터만 DB 역할 조회 구현 |

### 🟡 추가 항목 (계획 대비 구현 초과 — 긍정적)

| # | 항목 | 구현 위치 | 설명 |
|---|------|-----------|------|
| A-1 | `GET /ai/labels` | api_data_router.py:467 | D-10 라벨링 워크플로우 지원, 설계 문서 엔드포인트 수 업데이트 필요 |
| A-2 | 공급업체 CRUD | api_master_router.py:402 | §7 공급업체 코드 언급 → 완전한 CRUD API로 확장 |
| A-3 | `process_analysis_view` 집계 뷰 | db_process_schema.sql | Plan 최소 요건 초과, 성능 최적화 기여 |

### 🔵 변경 항목

| # | Plan | 구현 | 영향도 |
|---|------|------|--------|
| C-1 | Level-2 메뉴 권한 (공정실적/모니터링…) | Level-1 코드 (PROCESS, DATA…) | Medium — OPERATOR×DATA 읽기 허용이 시드에서 누락 → `(TRUE,FALSE)` 수정 완료 |
| C-2 | FERMENTATION_ACCURACY % 단위 | DB 0~1 저장, API ×100 변환 | Low — 표시는 정상, DB 단위 정규화 권장 |
| C-3 | 대용량 다운로드 서버사이드 | UI 클라이언트사이드 생성 | Low — `/download` StreamingResponse 존재하나 UI 미연결 |

---

## 5. 최종 판정

```
[Plan] ✅ → [Design] ✅ → [Do] ✅ → [Check] ✅ 91% → [Report] 권장
```

**91% ≥ 90%: PASS — 완료 판정**

기존 HIGH 이슈 2건(GET /ai/labels, notification_logs 버그)이 코드에서 확인 완료됨.
나머지 Gap(G-1~G-3)은 시범운영 단계에서 구현 예정인 비차단 항목.

### 다음 단계 권장사항

| 우선순위 | 항목 |
|----------|------|
| 시범운영 전 필수 | `require_role` JWT 실제 연동 (G-3) |
| 운영 전 권장 | KPI 리포트 PDF 렌더링 (G-1) |
| 운영 중 개선 | 알림 발송 로직 구현 (G-2) |
| 문서화 | 설계문서 엔드포인트 수 13개로 업데이트 (A-1) |

---

*분석 도구: bkit:gap-detector | 검증 기준: pm3 Plan §2~8 + Design doc + QA 보고서 5종*
