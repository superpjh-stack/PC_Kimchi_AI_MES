# jwt-auth-integration Plan

> **Project**: 꽃순이김치 제조AI MES (SF26179540 / 로뎀솔루션)
> **Feature**: JWT 인증 통합 — 실제 JWT 발급·검증·RBAC 연동
> **Author**: PM3
> **Created**: 2026-05-25
> **Priority**: High (시범운영 전 필수 — pm3 Gap G-3)
> **Estimated Effort**: 1~2일 (단일 개발자 기준)
> **Plan Ref**: pm3 Gap Analysis G-3 (`docs/03-analysis/pm3-process-data-kpi-system.analysis.md`)

---

## 1. 배경 및 목적

### 현재 상태 (As-Is)

| 위치 | 현황 | 문제 |
|------|------|------|
| `api_system_router.py:41-47` | `get_current_user()` → 하드코딩 `admin` 반환 | 인증 없이 모든 요청 통과 |
| `api_process_router.py` | stub `require_role` (pass-through) | OPERATOR·MANAGER 권한 분리 불가 |
| `api_kpi_router.py` | stub `require_role` (pass-through) | 권한 제한 없이 목표값 수정 가능 |
| `streamlit_app/Home.py` | 로그인 폼 → `st.session_state`만 설정 | 실제 인증 없음, 누구나 접근 가능 |

### 목표 (To-Be)

- `POST /api/v1/auth/login` → bcrypt 검증 → JWT Access Token 발급
- `app/auth.py` 공유 모듈: 실제 JWT 디코드 + DB 역할 조회
- 10개 API 라우터 전체 → `app/auth.py`의 `require_role()` 일원화
- Streamlit `Home.py` → 실제 login API 호출 → 토큰 `st.session_state` 저장
- 만료 토큰 → 401 Unauthorized 자동 처리

---

## 2. 기능 명세

### 2.1 Auth 엔드포인트 (`POST /api/v1/auth/login`)

**입력**
```json
{ "username": "admin", "password": "plain-text-password" }
```

**처리 흐름**
1. `users` 테이블에서 `username`으로 사용자 조회
2. `bcrypt.checkpw(password, hashed_password)` 검증
3. 검증 성공 → JWT 생성 (`sub=user_id`, `username`, `exp=+8h`, `jti`)
4. 실패 → 401 `Incorrect username or password`

**응답**
```json
{
  "access_token": "<JWT>",
  "token_type": "bearer",
  "expires_in": 28800,
  "user": { "user_id": 1, "username": "admin", "roles": ["ADMIN"] }
}
```

### 2.2 `app/auth.py` 공유 모듈

**함수 목록**

| 함수 | 역할 |
|------|------|
| `create_access_token(data, expires_delta)` | JWT 생성 (HS256, SECRET_KEY) |
| `decode_access_token(token)` | JWT 디코드 + 만료 검증 → `TokenPayload` |
| `get_current_user(token)` | Bearer 토큰 추출 → DB 사용자 조회 → `CurrentUser` |
| `require_role(allowed_roles)` | FastAPI `Depends` — 역할 미일치 시 403 |

**`CurrentUser` 스키마**
```python
class CurrentUser(BaseModel):
    user_id: int
    username: str
    roles: list[str]
    is_active: bool
```

### 2.3 토큰 스펙

| 항목 | 값 |
|------|-----|
| 알고리즘 | HS256 |
| 만료 | 8시간 (현장 교대 1사이클) |
| 비밀키 | `JWT_SECRET_KEY` 환경변수 (≥32자) |
| Payload | `sub`(user_id), `username`, `exp`, `iat`, `jti`(UUID) |
| Refresh Token | Phase-2 (현재 범위 외, 로그아웃 = 토큰 만료 대기) |

### 2.4 라우터 일원화

**대상 파일 10개**

| 파일 | 현재 require_role | 변경 후 |
|------|-------------------|---------|
| `api_system_router.py` | DB 조회 방식 (부분 구현) | `app/auth.py` 공통 함수로 교체 |
| `api_process_router.py` | stub pass-through | `app/auth.py` 실제 JWT 검증 |
| `api_kpi_router.py` | stub pass-through | `app/auth.py` 실제 JWT 검증 |
| `api_data_router.py` | 확인 필요 | `app/auth.py` 실제 JWT 검증 |
| `api_master_router.py` | 확인 필요 | `app/auth.py` 실제 JWT 검증 |
| `api_dashboard_router.py` | 확인 필요 | `app/auth.py` 실제 JWT 검증 |
| `api_material_router.py` | 확인 필요 | `app/auth.py` 실제 JWT 검증 |
| `api_fermentation_router.py` | 확인 필요 | `app/auth.py` 실제 JWT 검증 |
| `api_shipping_router.py` | 확인 필요 | `app/auth.py` 실제 JWT 검증 |
| `api_agent_router.py` | 확인 필요 | `app/auth.py` 실제 JWT 검증 |

### 2.5 RBAC 권한 매트릭스 (변경 없음)

| 역할 | 공정 | 데이터 | KPI | 기준정보 | 시스템 |
|------|------|--------|-----|---------|--------|
| ADMIN | R/W | R/W | R/W | R/W | R/W |
| MANAGER | R/W | R | R/W | R | R |
| QUALITY | R | R/W | R | R/W | — |
| OPERATOR | R/W | R | — | R | — |

### 2.6 Streamlit 로그인 연동 (`Home.py`)

**현재**: 폼 제출 → `st.session_state["role"]` 만 설정 (DB 미연동)

**변경**:
1. `httpx.post("http://localhost:8000/api/v1/auth/login", json={"username":…,"password":…})`
2. 성공 (200): `st.session_state["access_token"]` + `st.session_state["user_info"]` 저장
3. 실패 (401): `st.error("아이디 또는 비밀번호가 잘못되었습니다")`
4. 모든 Streamlit 페이지: API 요청 시 `Authorization: Bearer <token>` 헤더 추가
5. 401 응답 수신 시 `st.session_state.clear()` + 로그인 페이지 리다이렉트

### 2.7 초기 사용자 시드

`db_system_schema.sql` 또는 별도 `seed_users.sql` 파일에 bcrypt 해시 포함한 초기 계정:

| username | password | role |
|----------|----------|------|
| admin | Admin1234! | ADMIN |
| manager1 | Manager1234! | MANAGER |
| quality1 | Quality1234! | QUALITY |
| operator1 | Operator1234! | OPERATOR |

---

## 3. 기술 스택 및 의존성

```
python-jose[cryptography]  # JWT 생성/검증 (또는 PyJWT)
bcrypt                      # 비밀번호 해시 검증
passlib[bcrypt]             # bcrypt 래퍼 (선택)
```

**환경 변수 추가**
```env
JWT_SECRET_KEY=your-super-secret-key-at-least-32-characters
JWT_ALGORITHM=HS256
JWT_EXPIRE_HOURS=8
```

---

## 4. 구현 순서 (체크리스트)

### Phase 1: 핵심 인증 모듈 (우선순위 1)
- [ ] `python-jose[cryptography]`, `bcrypt` 패키지 설치
- [ ] `app/auth.py` 생성 (create_access_token, decode_access_token, get_current_user, require_role)
- [ ] `app/main.py` — `auth_router` 추가, `/api/v1/auth` prefix 등록
- [ ] `_workspace/api_auth_router.py` 생성 — `POST /login` 엔드포인트

### Phase 2: 라우터 일원화 (우선순위 2)
- [ ] `api_process_router.py` — `from app.auth import require_role` 교체
- [ ] `api_kpi_router.py` — stub require_role 제거 후 실제 연동
- [ ] `api_data_router.py`, `api_master_router.py` 검토 및 교체
- [ ] `api_dashboard_router.py`, `api_material_router.py`, `api_fermentation_router.py`, `api_shipping_router.py`, `api_agent_router.py` 검토 및 교체
- [ ] `api_system_router.py` — 기존 부분 구현 → 공통 모듈로 대체

### Phase 3: Streamlit 연동 (우선순위 3)
- [ ] `streamlit_app/Home.py` — 실제 login API 호출 구현
- [ ] `streamlit_app/utils/auth_helper.py` 생성 — `get_auth_headers()`, `check_login()` 유틸
- [ ] 모든 `pages/*.py` — API 요청에 `auth_header` 추가
- [ ] 401 수신 시 자동 로그아웃 처리

### Phase 4: 시드 및 검증 (우선순위 4)
- [ ] `seed_users.sql` — bcrypt 해시 포함한 초기 계정 4개
- [ ] 수동 QA: 올바른 자격증명 → 200 + 토큰 발급
- [ ] 수동 QA: 잘못된 자격증명 → 401
- [ ] 수동 QA: 만료/위조 토큰 → 401
- [ ] 수동 QA: 권한 부족 → 403 (OPERATOR로 KPI 목표 수정 시도)
- [ ] 수동 QA: Streamlit 로그인 → 페이지 정상 접근 → 로그아웃

---

## 5. 파일 목록 (예상 생성/수정)

| 구분 | 파일 | 작업 |
|------|------|------|
| 신규 | `app/auth.py` | JWT 핵심 모듈 |
| 신규 | `_workspace/api_auth_router.py` | 로그인 엔드포인트 |
| 신규 | `streamlit_app/utils/auth_helper.py` | 프론트 인증 유틸 |
| 신규 | `seed_users.sql` | 초기 계정 데이터 |
| 수정 | `app/main.py` | auth_router 등록 |
| 수정 | `api_process_router.py` | require_role 일원화 |
| 수정 | `api_kpi_router.py` | require_role 일원화 |
| 수정 | `api_data_router.py` | require_role 검토/수정 |
| 수정 | `api_master_router.py` | require_role 검토/수정 |
| 수정 | `api_dashboard_router.py` | require_role 검토/수정 |
| 수정 | `api_material_router.py` | require_role 검토/수정 |
| 수정 | `api_fermentation_router.py` | require_role 검토/수정 |
| 수정 | `api_shipping_router.py` | require_role 검토/수정 |
| 수정 | `api_agent_router.py` | require_role 검토/수정 |
| 수정 | `api_system_router.py` | 공통 모듈로 대체 |
| 수정 | `streamlit_app/Home.py` | 실제 로그인 API 호출 |
| 수정 | `streamlit_app/pages/*.py` | Authorization 헤더 추가 |

---

## 6. 위험 요소 및 완화

| 위험 | 가능성 | 완화 방안 |
|------|--------|-----------|
| SECRET_KEY 노출 | Low | `.env` 파일, `.gitignore` 적용 |
| 기존 API 테스트 401 오류 | Medium | `/health` 엔드포인트는 인증 제외; 개발 중 `DEBUG_NO_AUTH=true` 옵션 |
| Streamlit 세션 토큰 보안 | Low | `st.session_state`는 서버사이드, HTTPS 필수 (운영) |
| bcrypt 느린 해시 (로그인 지연) | Low | work factor 12 (기본값) — 100ms 이내로 허용 가능 |
| 토큰 탈취 후 8시간 유효 | Medium | 운영 단계에서 Refresh Token + Blacklist 도입 (Phase-2) |

---

## 7. 완료 기준 (Definition of Done)

- [ ] `POST /api/v1/auth/login` — 올바른 자격증명으로 JWT 반환
- [ ] 모든 보호된 엔드포인트 — Bearer 토큰 없이 접근 시 401 반환
- [ ] OPERATOR 계정으로 `PUT /kpi/targets/{kpi_type}` 시도 시 403 반환
- [ ] Streamlit 로그인 폼 — 실제 API 호출 후 토큰 저장, 페이지 접근
- [ ] Gap Analysis ≥ 90% (bkit gap-detector 검증)

---

## 8. 관련 문서

- `docs/02-design/features/pm3-process-data-kpi-system.design.md` §2.5 RBAC
- `docs/03-analysis/pm3-process-data-kpi-system.analysis.md` — G-3 Gap 항목
- `_workspace/db_system_schema.sql` — users, roles, user_roles, role_permissions 테이블
- `api_system_router.py:41-65` — 기존 stub get_current_user / require_role 위치

---

*Plan 작성: bkit PDCA | 다음 단계: `/pdca design jwt-auth-integration`*
