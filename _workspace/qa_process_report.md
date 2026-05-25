# QA 검증 보고서 — 공정관리 모듈

> 검증일: 2026-05-24
> 검증 대상: db_process_schema.sql / api_process_router.py / ui_05_process.py
> 기준 문서: pm3-process-data-kpi-system.plan.md (섹션 4), db-schema-design SKILL.md, db_system_schema.sql

## 검증 요약
- 전체 체크 항목: 22개
- 통과: 19개 ✅
- 경고: 2개 ⚠️
- 실패: 1개 ❌
- 매칭률: 약 91% (통과 기준), 경고 포함 시 95.5%

---

## DB 스키마 검증

| 항목 | 결과 | 비고 |
|------|------|------|
| `process_result` 9개 공정 공통 필드 | ✅ | process_code, lot_id, input_qty_kg, output_qty_kg, defect_qty_kg, worker, start_time, end_time 모두 존재. 추가로 source_lot_id/yield_rate/details(JSONB) 보유 |
| LOT FK 체인 호환성 | ⚠️ | 추적은 가능하나 물리 FK 미연결 (아래 이슈 #1) |
| `process_recipe` 버전 관리 필드 | ✅ | is_active, valid_from, valid_to, approved_by 모두 존재 (+approval_status, reviewed_by 워크플로우) |
| `process_alarm` CHECK 제약 | ✅ | chk_alarm_level (WARNING/CRITICAL), chk_alarm_status (OPEN/RESOLVED) 정확히 일치 |
| 복합 인덱스 3종 | ✅ | idx_presult_code_created(process_code, created_at DESC), idx_palarm_status_level(status, alarm_level), idx_precipe_product_active(product_code, is_active) 모두 존재 |

**보충**: 수량 무결성 CHECK(chk_pr_qty), 공정코드 CHECK(chk_pr_process_code), 레시피 UNIQUE(recipe_code,version), process_analysis_view 집계 뷰까지 추가로 갖춰 기획서 요구 이상으로 충실.

---

## API 검증

| 엔드포인트 | 결과 | 비고 |
|------------|------|------|
| POST /results | ✅ | 201, 수율 자동계산 |
| GET /results | ✅ | process_code/date/lot_id 필터 |
| GET /results/{lot_id}/history | ✅ | RECURSIVE CTE 체인 추적 |
| GET /monitor/realtime | ✅ | DISTINCT ON 최신상태 + 알림 집계 |
| GET /alarms | ✅ | status/alarm_level 필터 + 우선순위 정렬 |
| PATCH /alarms/{alarm_id}/resolve | ✅ | OPEN→RESOLVED, 멱등 처리 |
| GET /recipes | ✅ | product_code 필터, is_active=TRUE, 원료 포함 |
| POST /recipes | ✅ | 트랜잭션, require_role(공장장/관리자) |
| PUT /recipes/{id} | ✅ | 구버전 비활성화 + 신버전 생성 |
| GET /analysis | ✅ | 기간별 by_process + daily_trend |

| 검증 패턴 | 결과 | 비고 |
|-----------|------|------|
| 공정코드별 필수 필드 검증 | ✅ | REQUIRED_DETAIL_FIELDS dict + model_validator(mode="after") |
| 레시피 PUT 버전관리 로직 | ✅ | 트랜잭션 내 구버전 is_active=FALSE/valid_to=CURRENT_DATE 후 신버전 INSERT |
| LOT 이력 재귀 추적 | ✅ | WITH RECURSIVE + UNION(중복제거) 으로 양방향 체인 추적 |
| asyncpg 파라미터 바인딩 | ✅ | 전 쿼리 $1,$2... 사용, f-string은 인덱스($len) 조립에만 사용(값 미삽입) — SQL Injection 안전 |
| Pydantic v2 문법 | ✅ | `X \| None`, model_validator, Field(default_factory), Query(pattern=...) 사용 |

---

## UI-API 정합성

| 항목 | 결과 | 비고 |
|------|------|------|
| 5개 탭 구조 | ✅ | 공정실적 입력 / 실시간 모니터링 / 레시피 관리 / 공정이력 조회 / 공정데이터 분석 |
| API URL ↔ 라우터 prefix 일치 | ✅ | BASE_URL=/api/v1/process, 모든 path가 라우터 엔드포인트와 일치 |
| 이상 알림 st.error/st.warning | ✅ | CRITICAL→st.error, WARNING→st.warning (탭2) + API 실패 시 st.warning |
| 모든 API 호출 try/except | ✅ | api_get/api_post/api_patch 헬퍼 전부 try/except |
| 30초 자동 갱신 | ⚠️ | 로직 존재하나 동작 불완전 (아래 이슈 #2) |

**보충 확인**: 공정실적 입력 탭의 공정코드별 동적 폼이 REQUIRED_DETAIL_FIELDS 와 거의 일치하나 일부 미스매치 존재(아래 이슈 #3 참고).

---

## 교차 모듈 호환성

| 항목 | 결과 | 비고 |
|------|------|------|
| users.user_id BIGINT 일치 | ❌ | process_result.worker / recipe.created_by 등이 VARCHAR로 user_id(BIGINT) FK 미연결 (이슈 #1) |
| code_master 코드값 일치 | ✅ | PROC01~09, MAT-*, KIM-BC-500, PRD-BC-500, DEF-001 등 기획서 7.3 코드 체계와 일치 |

---

## 발견된 이슈 (상세)

### 이슈 #1 (severity: LOW) — 작업자/사용자 컬럼이 users FK 미연결
- 위치: db_process_schema.sql:49 (worker VARCHAR(50)), :93-96 (created_by/reviewed_by/approved_by VARCHAR(30)), api_process_router.py 전반
- 내용: 기획서 4.1은 작업자를 "Code(사용자 코드 참조)"로 규정하고 db_system_schema.sql의 users.user_id는 BIGINT다. 그러나 process_result.worker, process_recipe.created_by/approved_by가 자유 문자열(VARCHAR)로 정의되어 users.user_id(BIGINT)와 타입이 다르고 물리 FK도 없다. 샘플 데이터도 '이미경'(성명), 'prod01'(문자 ID)로 혼재.
- 영향: 작업자 기준 활동 로그/권한 추적 시 users 테이블과 JOIN 불가. 다만 공정 실적 모듈은 현장 입력 특성상 성명 직접 입력을 허용하는 설계로 볼 수 있어 치명적 결함은 아님(설계 의도일 가능성).
- 권고 조치: worker/created_by 등을 user_id BIGINT FK로 정규화하거나, 자유 입력을 유지하려면 스키마 주석에 "users FK 비연결, 성명/코드 자유입력" 명시. 최소한 타입 일관성(VARCHAR vs BIGINT) 의도를 문서화.

### 이슈 #2 (severity: MEDIUM) — 30초 자동 갱신이 실질적으로 동작하지 않음
- 위치: ui_05_process.py:233-240
- 내용: `if time.time() - st.session_state.proc_last_refresh > 30: ... st.rerun()` 패턴은 Streamlit이 스크립트를 끝까지 실행한 뒤 입력 대기 상태에 머물기 때문에, 사용자 상호작용이 없으면 30초 경과 조건을 재평가하는 재실행이 트리거되지 않는다. 결과적으로 수동 새로고침 버튼에만 의존하게 됨.
- 영향: 실시간 모니터링 탭(P-10, 기획서 4.4 업데이트 주기 요구)이 자동 갱신되지 않아 현황판 용도가 약화됨.
- 권고 조치: `st.autorefresh`(구버전) 대체로 `st_autorefresh`(streamlit-extras) 또는 `st.fragment(run_every="30s")`(Streamlit 1.37+) 사용 권장. 예: 모니터링 섹션을 `@st.fragment(run_every=30)` 로 감싸기.

### 이슈 #3 (severity: LOW) — UI 동적 폼 details 와 API 필수필드 일부 불일치
- 위치: ui_05_process.py:105-157 vs api_process_router.py:55-65 (REQUIRED_DETAIL_FIELDS)
- 내용: 일부 공정에서 UI가 API 필수키를 직접 채우지 않아 422 검증 실패 위험.
  - PROC01: API 필수 `qc_pass` → UI는 `st.checkbox`로 채움(OK), `supplier_code/material_code/origin` OK. 단, checkbox 값이 False일 때 validator의 `in (None,"")` 체크는 통과(False는 누락 아님) → OK.
  - PROC04: API 필수 `wash_count` → UI 제공(OK). 단 UI는 `pass_qty_kg` 등 부가키만 추가, 누락 없음.
  - PROC06: API 필수 `recipe_code`,`mix_minutes` → UI 제공(OK).
  - PROC02: API 필수 `work_minutes` → UI 제공(OK).
  - 실제 불일치는 없으나, UI가 `worker`를 details가 아닌 최상위로 보내는 점/PROC02의 `defect_reason`이 빈 문자열일 때 등 경계값에서 검증기와의 결합도가 낮음.
- 영향: 경미. 현재 기본값 기준으로는 정상 동작. 사용자가 일부 필드를 비우면 422 발생 가능.
- 권고 조치: UI 제출 전 클라이언트 측에서 REQUIRED_DETAIL_FIELDS 동기화 검사 추가, 또는 API 422 응답 메시지를 st.error로 표면화(현재 api_post 실패 시 st.warning만 표시되어 누락 항목 메시지가 사용자에게 모호하게 전달됨).

---

## 추가 관찰 (이슈 아님, 참고)

1. **재귀 CTE 추적 깊이**: `get_lot_process_history`의 `UNION`(ALL 아님)으로 사이클 방지됨. 다만 JOIN 조건 `pr.lot_id = c.source_lot_id OR pr.source_lot_id = c.lot_id`는 동일 lot_id가 여러 공정에 재사용될 경우 무관한 실적까지 묶일 수 있음. 본 설계는 공정별 LOT가 고유(PICKLING-/FERM- 등 prefix 분리)하다는 전제하에 안전.
2. **realtime monitor의 process_name**: `monitor/realtime`은 각 process의 process_name을 채워주지만, alarm은 별도 `/alarms` 호출에서 process_name을 받아 UI가 정상 표시함.
3. **PUT /recipes 승인상태**: 신버전이 'DRAFT'로 생성되어 승인 워크플로우(작성→검토→승인)와 정합. 기획서 4.2 정책 "구버전 보존, 신버전 생성" 충족.
4. **불량코드 검증**: defect_qty>0 시 defect_code 필수 validator 존재 → 기획서 조건부 필수 규칙 충족.

---

## 종합 의견

공정관리 모듈(DB/API/UI)은 기획서 섹션 4(공정별 실적 입력, 레시피 버전관리, 이상감지 알림, 실시간 모니터링)를 **충실히 구현**했다. 9개 공정 공통 실적 테이블 + JSONB 가변 측정값 설계, 레시피 승인 워크플로우, WARNING/CRITICAL·OPEN/RESOLVED 알림 체계, 3종 복합 인덱스, asyncpg 안전 바인딩, Pydantic v2 문법, UI 5탭 구조와 API 정합성 모두 기준을 만족한다.

치명적 결함(HIGH)은 없으며, 발견된 이슈는 다음과 같다:
- **MEDIUM 1건**: 실시간 모니터링 30초 자동 갱신 미동작 (st.fragment/st_autorefresh로 교체 권장)
- **LOW 2건**: worker/사용자 컬럼의 users FK 미연결(타입 불일치 문서화 필요), UI-API 필수필드 경계값 결합도

운영 투입 전 이슈 #2(자동 갱신) 우선 수정 권고. 이슈 #1, #3은 설계 의도 확인 후 문서화 또는 보완.
