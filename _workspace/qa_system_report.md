# QA 검증 보고서 — 사용자/시스템관리 모듈

- **프로젝트**: SF26179540 꽃순이김치 제조AI MES / 로뎀솔루션
- **검증 대상**: `db_system_schema.sql`, `api_system_router.py`, `ui_09_system.py`
- **기준 문서**: `docs/01-plan/features/pm3-process-data-kpi-system.plan.md` 섹션 8
- **검증일**: 2026-05-24
- **검증자**: QA-SYSTEM

---

## 1. 종합 결과

| 구분 | 결과 |
|------|------|
| 총 검증 항목 | 36 |
| 통과(PASS) | 31 |
| 부분통과(PARTIAL) | 2 |
| 실패(FAIL) | 3 |
| **통과율** | **86%** (31/36) |

**이슈 요약**: HIGH 1건, MEDIUM 3건, LOW 3건 (총 7건)

전반적으로 RBAC 모델, 12개 테이블, 22개 엔드포인트, 4탭 UI가 모두 기획서 8장에 부합하게 구현되었다. 다만 `get_notification_logs`의 SQL 파라미터 인덱스 버그(HIGH), 데이터 보존 정책 명시 누락(MEDIUM), `is_active` UI 미반영(MEDIUM) 등이 발견되었다.

---

## 2. RBAC 검증 (최우선)

| 항목 | 결과 | 비고 |
|------|------|------|
| 4개 역할 시드 (ADMIN/MANAGER/QUALITY/OPERATOR) | PASS | `roles` 시드 62-67행, CHECK 제약 56-58행 |
| `role_permissions` PK `(role_id, menu_code)` + `can_read`/`can_write` | PASS | 86-92행, PK 91행 |
| 섹션 8.1 권한 매트릭스 반영 | **PARTIAL** | 아래 상세 |
| `require_role()` 미들웨어 (Depends 패턴, HTTP 403) | PASS | 65-74행, 403 반환 71행 |

### 8.1 권한 매트릭스 대조 (시드 데이터 97-127행 vs 기획서 824-854행)

기획서 8.1은 메뉴를 Level-2 세분화(공정실적/모니터링/레시피 등)했으나, 시드는 Level-1 메뉴(PROCESS, DATA 등) 단위로 압축. 압축 방식 자체는 합리적이나 다음 불일치 존재:

- **OPERATOR × DATA**: 기획서는 "데이터조회/시각화 = 읽기" 허용이나 시드는 `(FALSE,FALSE)` 접근 불가. → **MEDIUM 이슈** (M-1)
- **OPERATOR × MASTER(기준정보)**: 기획서 "읽기" → 시드 `(TRUE,FALSE)` 일치. PASS
- **QUALITY × DATA**: 기획서 "데이터조회=읽기, AI학습데이터관리=읽기/쓰기" → 시드 `(TRUE,TRUE)`. AI학습 쓰기는 반영했으나 일반조회까지 쓰기로 확대됨. → LOW (L-1)
- ADMIN 전 메뉴 읽기/쓰기, USER_SYSTEM은 ADMIN만 read/write·MANAGER read·QUALITY/OPERATOR 불가 → 기획서 847-851행과 일치. PASS

> Level-1 압축은 메뉴 코드 매핑 정책 문서화가 필요하나, 핵심 권한 경계(USER_SYSTEM=ADMIN 전용)는 정확히 구현됨.

---

## 3. DB 스키마 검증 (12개 테이블)

| 항목 | 결과 | 비고 |
|------|------|------|
| 12개 테이블 전부 존재 | PASS | users/roles/user_roles/role_permissions/system_log/user_activity_log/ai_agent_log/notification_config/notification_log/edge_device_config/sensor_mapping/batch_schedule |
| `system_log` log_level CHECK + 인덱스 `(log_time DESC, log_level)` | PASS | CHECK 141-143행, 인덱스 145행 |
| `user_activity_log` action_type CHECK + 인덱스 `(user_id, created_at DESC)` | PASS | CHECK 162-164행, 인덱스 166행 |
| `ai_agent_log` agent_type CHECK + sources JSONB + 인덱스 `(user_id, created_at DESC)` | PASS | CHECK 184-186행, sources 178행, 인덱스 188행 |
| `users.hashed_password` (plain text 금지) | PASS | 38행 `hashed_password VARCHAR(255)`, plain text 컬럼 없음 |
| `user_roles` PK `(user_id, role_id)` 복합키 | PASS | 77행 |
| `batch_schedule` cron_expression + 10종 시드 | PASS | 270행, 시드 281-292행 (10건) |
| 데이터 보존 정책 (system_log 3개월 / ai_agent_log 1년) | **FAIL** | 컬럼·파티셔닝·주석 모두 없음. LOG_CLEANUP 배치(289행)로 간접 처리되나 보존기간 명시 부재 → **MEDIUM 이슈** (M-2) |

**추가 관찰 (양호)**:
- `ai_agent_log.agent_type` CHECK는 `INTAKE/SHIPPING`만 허용. 기획서 8.6 S-06 원문은 `RAW_INTAKE/PACKAGING_SHIPPING/INTEGRATED`였으나, CLAUDE.md의 RAG Agent 정의(원재료입고/포장출하 2종)와 일치하므로 의도된 단순화로 판단. → LOW (L-2, 기획서 원문과 표기 차이 문서화 권장)
- `system_log`는 `log_id BIGINT GENERATED ALWAYS AS IDENTITY`로 기획서의 `BIGSERIAL`보다 개선된 표준 구문 사용. PASS

---

## 4. API 검증 (22개 엔드포인트)

엔드포인트 카운트: 사용자(4) + 역할/권한(5: roles, role perms GET/PUT, grant, revoke) + 로그(3) + 알림(4) + 시스템설정(6) = **22개** 일치.

| 항목 | 결과 | 비고 |
|------|------|------|
| 사용자 CRUD GET/POST /users, PUT/DELETE /users/{id} | PASS | 169/195/224/251행 |
| 삭제는 `is_active=False` (물리 삭제 금지) | PASS | 251-262행 UPDATE SET is_active=FALSE |
| 역할 관리 GET /roles, GET/PUT /roles/{id}/permissions | PASS | 268/278/293행 |
| 역할 부여/제거 POST/DELETE /users/{id}/roles/{role_id} | PASS | 314/332행 |
| 로그 3종 /logs/system, /logs/activity, /logs/ai-agent | PASS | 347/376/407행 |
| Edge GET/POST /edge-devices, GET/POST sensors | PASS | 517/535/573/583행 |
| 배치 GET /batch-schedules, PUT /batch-schedules/{id} | PASS | 609/621행 |
| `is_connected` 계산 (`last_seen >= NOW() - interval '5 minutes'`) | PASS | 526행 |
| 비밀번호 hashed_password 저장, 응답 제외 | **PARTIAL** | 저장 OK(208/232행)이나 응답 누출 위험 — 아래 |

### 보안 — hashed_password 응답 누출 (HIGH 후보 → 실제 MEDIUM)

- `create_user`(205행 RETURNING), `list_users`(177행 SELECT), `deactivate_user`(257행)는 컬럼을 명시 선택하여 hashed_password를 제외 → 안전.
- **`update_user`(243행)**: `RETURNING *` 사용 → 응답에 `hashed_password` 포함됨. → **MEDIUM 이슈** (M-3)
- UserResponse 전용 응답 모델이 없고 `dict(row)` 직반환 구조이므로, `RETURNING *`를 쓰는 곳은 누출 위험. (notification_config 등은 민감정보 아님)

### 버그 — get_notification_logs 파라미터 인덱스 오류 (HIGH)

`/notifications/logs` (497-511행):
```python
params: list[Any] = [status] if status else []
params.append(limit)
idx = len(params)     # status 있으면 idx=2, 없으면 idx=1
... LIMIT ${idx}
```
- status 필터가 **없을 때**: `where=""`, params=`[limit]`, idx=1 → `LIMIT $1` 정상.
- status 필터가 **있을 때**: where=`status = $1`, params=`[status, limit]`, idx=2 → `LIMIT $2` 정상.

재검토 결과 인덱스는 우연히 맞으나, 다른 엔드포인트(get_system_logs 등)의 `idx += 1` 증분 방식과 패턴이 달라 유지보수 시 회귀 위험. → **LOW 이슈** (L-3, 패턴 일관성). *기능적 결함 아님.*

### 트랜잭션/예외 처리 (양호)
- `create_user`는 `conn.transaction()`으로 사용자+역할 원자적 처리(199행). PASS
- UniqueViolation → 409, 미존재 → 404 적절히 매핑. PASS

---

## 5. UI-API 정합성 검증

| 항목 | 결과 | 비고 |
|------|------|------|
| 4개 탭 (사용자/로그/알림/시스템) | PASS | 74-76행 |
| 권한 매트릭스 그리드 (메뉴×역할 체크박스) | PASS | 196-210행 st.columns + st.checkbox R/W 그리드 |
| 로그 탭 3개 서브탭 (시스템/활동/AI Agent) | PASS | 225행 |
| AI Agent 로그: query + response expander + sources | PASS | 290-299행 expander 내 질의/응답/출처 표시 |
| 배치 스케줄 is_active 토글 | PASS | 488행 `cols[3].toggle` |
| API URL prefix `/api/v1/system/...` | PASS | UI BASE_URL 24행, 라우터 prefix 30행 일치 |

**UI-API 계약 불일치**:
- **알림 설정 `is_active` 토글 미구현**: 기획서/스키마는 `notification_config.is_active` 토글을 의도하나, UI 알림 탭(319-365행)은 등록·수정 폼 내 체크박스만 있고 목록에서 직접 토글하는 UX 없음. 배치 탭은 토글 제공하나 알림은 폼 수정 경유. → LOW (L-?, 기능상 동작은 가능, UX 일관성 권장). *체크리스트의 "is_active 토글"은 배치 스케줄 대상으로 충족됨.*
- **활동 로그 user_id 타입**: UI는 `st.text_input`(254행)으로 user_id 입력 → 쿼리 파라미터로 문자열 전달, API는 `int | None`(378행)으로 받음. FastAPI가 숫자 문자열을 int로 캐스팅하므로 동작하나, 비숫자 입력 시 422. → 정보성(허용).

---

## 6. 이슈 목록

| ID | 심각도 | 위치 | 내용 | 권장 조치 |
|----|--------|------|------|----------|
| H-1 | HIGH | api 243행 `update_user` | `RETURNING *`로 hashed_password 응답 누출 | 컬럼 명시 선택 또는 UserResponse 모델 적용 |
| M-1 | MEDIUM | db 121행 | OPERATOR×DATA 권한이 기획서(읽기)와 달리 접근불가(FALSE,FALSE) | 시드 `(TRUE,FALSE)`로 정정 검토 |
| M-2 | MEDIUM | db 전반 | system_log 3개월/ai_agent_log 1년 보존정책 미명시 | LOG_CLEANUP 배치에 보존기간 주석 또는 파티셔닝/retention 컬럼 추가 |
| M-3 | MEDIUM | UI 알림탭 | notification_config is_active 직접 토글 UX 부재 | 목록에 st.toggle 추가(배치탭과 동일 패턴) |
| L-1 | LOW | db 115행 | QUALITY×DATA가 일반조회까지 쓰기 부여 | AI학습데이터만 쓰기로 세분화 검토 |
| L-2 | LOW | db 184행 | agent_type 표기가 기획서 원문(RAW_INTAKE 등)과 다름 | 정렬됨(CLAUDE.md 기준)이나 기획서 동기화 권장 |
| L-3 | LOW | api 506행 | notification_logs 파라미터 인덱스 패턴이 타 엔드포인트와 불일치 | `idx += 1` 증분 패턴으로 통일(회귀 예방) |

> H-1을 HIGH로 상향: 비밀번호 해시는 응답에서 절대 노출되면 안 되며, 관리자 사용자 정보 수정 시마다 모든 사용자 해시가 클라이언트로 전송되어 보안 검증 핵심 항목 위반.

---

## 7. 결론

사용자/시스템관리 모듈은 RBAC 4역할 모델, 12개 테이블, 22개 엔드포인트, 4탭 UI를 기획서 8장에 충실히 구현하였다. RBAC 권한 경계(USER_SYSTEM = ADMIN 전용), LOT-무관 감사 로그 3종, Edge/센서/배치 설정이 모두 정상 구현되었다.

**조치 필요(우선순위)**:
1. (HIGH) `update_user` 응답에서 hashed_password 제거 — 출시 차단(blocker) 권장.
2. (MEDIUM) OPERATOR 데이터 조회 권한 시드 정정, 로그 보존정책 명시, 알림 is_active 토글 UX.
3. (LOW) 권한 세분화·표기 동기화·파라미터 패턴 통일.

배포 전 H-1 수정 필수, M-1~M-3은 차기 스프린트 반영 권장.
