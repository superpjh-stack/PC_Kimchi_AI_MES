# jwt-auth-integration 설계 문서

> **Feature**: JWT 인증 통합 — 실제 JWT 발급·검증·RBAC 연동
> **Author**: PM3 + 개발팀
> **Created**: 2026-05-25
> **Status**: Design (Pre-implementation)
> **Plan Ref**: `docs/01-plan/features/jwt-auth-integration.plan.md`

---

## 1. 현황 분석 (As-Is)

### 1.1 `app/auth.py` — 이미 완전 구현됨 ✅

```
app/auth.py  (실제 구현 완료)
├── hash_password(raw) → str            # bcrypt 해시
├── verify_password(raw, hashed) → bool # bcrypt 검증
├── get_current_user(token)             # JWT Bearer 디코드 + DB users 조회
├── get_user_roles(user_id) → list[str] # user_roles JOIN roles → role_code 목록
├── require_role(*allowed)              # FastAPI Depends — 역할 불일치 → 403
├── authenticate_user(username, pwd)    # users 테이블 조회 + bcrypt 검증
└── create_login_token(form_data)       # OAuth2PasswordRequestForm → TokenResponse
```

**JWT 설정**: HS256, 기본 8시간, `JWT_SECRET_KEY` 환경변수

### 1.2 로그인 엔드포인트 — 이미 존재 ✅

`api_system_router.py:127-143`
```
POST /api/v1/system/auth/token
Content-Type: application/x-www-form-urlencoded
Body: username=<id>&password=<pw>   (OAuth2PasswordRequestForm)
→ TokenResponse { access_token, token_type, expires_in }
```

### 1.3 라우터별 인증 현황

| 라우터 | auth 상태 | 구체적 문제 |
|--------|-----------|------------|
| `api_system_router.py` | ✅ 실제 JWT | `from app.auth import ...` 정상 사용 |
| `api_process_router.py` | ✅ 실제 JWT | `from app.auth import require_role` 정상 사용 |
| `api_agent_router.py` | ✅ 실제 JWT | `from app.auth import ...` 정상 사용 |
| `api_fermentation_router.py` | ✅ 실제 JWT | `from app.auth import require_role` 정상 사용 |
| `api_kpi_router.py` | ❌ 로컬 stub | `def require_role(*allowed): async def _dep(): pass` — pass-through |
| `api_shipping_router.py` | ❌ 로컬 stub | query param `?role=MANAGER` 기반 — Bearer 토큰 미검증 |
| `api_data_router.py` | ❌ auth 없음 | 쓰기 엔드포인트 3개 인증 없음 |
| `api_master_router.py` | ❌ auth 없음 | 쓰기 엔드포인트 11개 인증 없음 |
| `api_material_router.py` | ❌ auth 없음 | 쓰기 엔드포인트 4개 인증 없음 |
| `api_dashboard_router.py` | ⚪ 읽기 전용 | 공개 대시보드 — 인증 선택적 |

### 1.4 Streamlit `Home.py` — 클라이언트 모크 ❌

```python
# 현재 코드 (Home.py:47-54) — DB 미연동
if submitted:
    st.session_state["logged_in"] = True
    st.session_state["user_id"] = user_id.strip()
    st.session_state["user_role"] = role  # selectbox 값 그대로 저장
    st.rerun()
```

---

## 2. 목표 아키텍처 (To-Be)

```
[Streamlit Home.py]
    │  POST /api/v1/system/auth/token (username, password)
    ▼
[FastAPI api_system_router.py /auth/token]
    │  authenticate_user() → bcrypt 검증 → users 테이블
    │  create_login_token() → JWT HS256 (8h)
    ▼
[app/auth.py] ──────────────────────────────────────────
    │  TokenResponse { access_token, token_type, expires_in }
    ▼
[Streamlit session_state]
    access_token, username, roles (DB 조회 결과)
    │
    │  모든 API 요청 헤더: Authorization: Bearer <token>
    ▼
[모든 FastAPI 라우터]
    │  Depends(require_role("ADMIN", "MANAGER", ...))
    │  → get_current_user() → JWT decode → users 조회 → CurrentUser
    │  → get_user_roles() → user_roles JOIN roles → role_code 목록
    │  → 역할 불일치 → 403 / 미인증 → 401
    ▼
[PostgreSQL users / roles / user_roles]
```

---

## 3. 구현 상세 설계

### 3.1 추가 로그인 엔드포인트 (JSON Body — Streamlit 친화)

> **결정**: 기존 `/api/v1/system/auth/token` (OAuth2 Form 방식)은 유지.  
> Streamlit용으로 JSON 바디를 받는 엔드포인트를 **추가**한다.

**위치**: `api_system_router.py` 에 추가 (또는 `api_auth_router.py` 신규)  
**선택**: `api_system_router.py` 에 추가 — 신규 파일 최소화

```
POST /api/v1/system/auth/login
Content-Type: application/json
{
  "username": "admin",
  "password": "Admin1234!"
}

→ 200 OK
{
  "access_token": "<JWT>",
  "token_type": "bearer",
  "expires_in": 28800,
  "user": {
    "user_id": 1,
    "username": "admin",
    "roles": ["ADMIN"]
  }
}
→ 401  { "detail": "사용자명 또는 비밀번호가 잘못되었습니다" }
```

**Pydantic 모델 추가**:
```python
class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict  # { user_id, username, roles }
```

### 3.2 `api_kpi_router.py` 수정

**변경 전**:
```python
def require_role(*allowed: str):
    async def _dep() -> None:
        pass  # TODO: JWT
    return _dep
```

**변경 후**:
```python
from app.auth import require_role  # 로컬 stub 제거 → 공통 모듈
```

**영향 엔드포인트**:
- `PUT /targets/{kpi_type}` → `Depends(require_role("ADMIN", "MANAGER"))` 실제 검증
- `PUT /alerts/config/{kpi_type}` → `Depends(require_role("ADMIN", "MANAGER"))` 실제 검증

### 3.3 `api_shipping_router.py` 수정

**변경 전**:
```python
def require_role(*allowed: str):
    async def _checker(x_user_role: str = Query("MANAGER", alias="role")) -> str:
        if x_user_role not in allowed:
            raise HTTPException(status_code=403, ...)
        return x_user_role
    return _checker
```

**변경 후**:
```python
from app.auth import require_role  # 쿼리 파라미터 stub → 실제 Bearer 토큰 검증
```

**영향 엔드포인트**:
- `POST /shipping/approve` → `Depends(require_role("MANAGER", "ADMIN"))` 실제 검증

### 3.4 `api_data_router.py` 인증 추가

**추가할 import**:
```python
from app.auth import require_role, get_current_user, CurrentUser
```

**보호 대상 엔드포인트**:

| 엔드포인트 | 역할 | 이유 |
|-----------|------|------|
| `POST /ai/labels` | QUALITY, ADMIN, MANAGER | 라벨 등록 — 데이터 품질 영향 |
| `PUT /ai/labels/{id}/approve` | QUALITY, ADMIN | 라벨 승인 — 학습 데이터 확정 |
| `POST /quality/run` | ADMIN, MANAGER | DQ 검증 실행 — 시스템 부하 |

**코드 패턴**:
```python
@router.post("/ai/labels", status_code=201)
async def create_label(
    data: LabelCreate,
    _: CurrentUser = Depends(require_role("QUALITY", "ADMIN", "MANAGER")),
):
    ...
```

### 3.5 `api_master_router.py` 인증 추가

**추가할 import**:
```python
from app.auth import require_role, CurrentUser
```

**보호 대상 엔드포인트**:

| 엔드포인트 | 역할 |
|-----------|------|
| `POST /quality-standards` | QUALITY, ADMIN |
| `PUT /quality-standards/{id}` | QUALITY, ADMIN |
| `POST /sop-documents/upload` | ADMIN, MANAGER |
| `POST /sop-documents/{id}/embed` | ADMIN |
| `PUT /sop-documents/{id}/activate` | ADMIN |
| `DELETE /sop-documents/{id}` | ADMIN |
| `POST /codes` | ADMIN |
| `PUT /codes/{group}/{code}` | ADMIN |
| `DELETE /codes/{group}/{code}` | ADMIN |
| `POST /suppliers` | ADMIN, MANAGER |
| `PUT /suppliers/{id}` | ADMIN, MANAGER |

### 3.6 `api_material_router.py` 인증 추가

**보호 대상 엔드포인트**:

| 엔드포인트 | 역할 |
|-----------|------|
| `POST /lots` | OPERATOR, MANAGER, ADMIN |
| `PATCH /lots/{lot_id}/status` | MANAGER, ADMIN |
| `POST /inspections` | QUALITY, MANAGER, ADMIN |
| `POST /selections` | OPERATOR, QUALITY, ADMIN |

### 3.7 Streamlit `Home.py` 수정

**변경 목표**: 폼 제출 시 실제 `/api/v1/system/auth/login` API 호출

```python
# 신규 로직 (Home.py render_login 교체)
import httpx

if submitted:
    if not user_id.strip():
        st.warning("사용자 ID를 입력해 주세요.")
    else:
        try:
            resp = httpx.post(
                "http://localhost:8000/api/v1/system/auth/login",
                json={"username": user_id.strip(), "password": password},
                timeout=5.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                st.session_state["logged_in"] = True
                st.session_state["access_token"] = data["access_token"]
                st.session_state["user_id"] = data["user"]["username"]
                st.session_state["user_roles"] = data["user"]["roles"]
                # 하위 호환: 단일 역할 문자열도 유지
                st.session_state["user_role"] = data["user"]["roles"][0] if data["user"]["roles"] else "OPERATOR"
                st.rerun()
            else:
                st.error("아이디 또는 비밀번호가 잘못되었습니다.")
        except httpx.RequestError:
            st.error("서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")
```

**로그아웃 처리** (기존 유지):
```python
if st.button("로그아웃", use_container_width=True):
    st.session_state.clear()
    st.rerun()
```

### 3.8 `streamlit_app/utils/auth_helper.py` 신규 생성

```python
"""Streamlit 인증 헬퍼 — API 요청 시 Bearer 토큰 헤더 생성."""
import streamlit as st

BASE_URL = "http://localhost:8000"


def get_auth_headers() -> dict[str, str]:
    """세션의 access_token → Authorization 헤더 반환. 토큰 없으면 빈 dict."""
    token = st.session_state.get("access_token")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def check_login() -> bool:
    """로그인 여부 확인. 미로그인 시 경고 메시지 출력 후 False 반환."""
    if not st.session_state.get("logged_in"):
        st.warning("로그인이 필요합니다.")
        st.stop()
    return True


def has_role(*roles: str) -> bool:
    """현재 사용자가 지정 역할 중 하나를 가지는지 확인."""
    user_roles = st.session_state.get("user_roles", [])
    return any(r in roles for r in user_roles)


def require_login_and_role(*roles: str) -> None:
    """로그인 + 역할 확인. 미충족 시 st.stop()."""
    check_login()
    if roles and not has_role(*roles):
        st.error(f"이 기능은 {', '.join(roles)} 역할만 사용할 수 있습니다.")
        st.stop()
```

### 3.9 각 Streamlit Page의 API 요청 수정 패턴

```python
# pages/*.py 공통 패턴
from utils.auth_helper import get_auth_headers, check_login

check_login()  # 페이지 상단에서 로그인 확인

# API 요청 시
headers = get_auth_headers()
resp = httpx.get("http://localhost:8000/api/v1/process/results",
                 headers=headers, timeout=10.0)
if resp.status_code == 401:
    st.session_state.clear()
    st.error("세션이 만료되었습니다. 다시 로그인해 주세요.")
    st.stop()
```

### 3.10 `seed_users.sql` 초기 계정

```sql
-- seed_users.sql
-- bcrypt 해시: Admin1234!, Manager1234!, Quality1234!, Operator1234!
-- python -c "from passlib.context import CryptContext; c=CryptContext(schemes=['bcrypt']); print(c.hash('Admin1234!'))"

-- 역할 기본 데이터 (없으면 삽입)
INSERT INTO roles (role_code, role_name, description) VALUES
  ('ADMIN',    '관리자',   '전체 시스템 관리'),
  ('MANAGER',  '공장장',   '생산/품질 관리'),
  ('QUALITY',  '품질담당', '품질 검사 및 기준 관리'),
  ('OPERATOR', '작업자',   '공정 실적 입력')
ON CONFLICT (role_code) DO NOTHING;

-- 초기 사용자 (비밀번호는 배포 전 변경 필수)
INSERT INTO users (username, full_name, email, hashed_password, department, is_active) VALUES
  ('admin',    '시스템관리자', 'admin@kkotsooni.com',    '<bcrypt_Admin1234!>',    'IT팀',   TRUE),
  ('manager1', '생산공장장',   'manager@kkotsooni.com',  '<bcrypt_Manager1234!>',  '생산팀', TRUE),
  ('quality1', '품질담당자',   'quality@kkotsooni.com',  '<bcrypt_Quality1234!>',  '품질팀', TRUE),
  ('operator1','현장작업자',   'operator@kkotsooni.com', '<bcrypt_Operator1234!>', '생산팀', TRUE)
ON CONFLICT (username) DO NOTHING;

-- 역할 부여
INSERT INTO user_roles (user_id, role_id)
SELECT u.user_id, r.role_id FROM users u, roles r
WHERE (u.username='admin'    AND r.role_code='ADMIN')
   OR (u.username='manager1' AND r.role_code='MANAGER')
   OR (u.username='quality1' AND r.role_code='QUALITY')
   OR (u.username='operator1'AND r.role_code='OPERATOR')
ON CONFLICT DO NOTHING;
```

> **주의**: `<bcrypt_XXX>` 플레이스홀더는 구현 시 실제 해시값으로 교체.  
> `hash_password()` 함수 또는 `python -m passlib.apps --hash bcrypt` 사용.

---

## 4. 파일별 변경 요약

| 파일 | 변경 유형 | 변경 내용 |
|------|-----------|-----------|
| `app/auth.py` | **변경 없음** ✅ | 이미 완전 구현됨 |
| `_workspace/api_system_router.py` | **추가** | `POST /auth/login` JSON 엔드포인트 + `LoginRequest`/`LoginResponse` 모델 |
| `_workspace/api_kpi_router.py` | **수정** | 로컬 stub 제거 → `from app.auth import require_role` |
| `_workspace/api_shipping_router.py` | **수정** | 로컬 stub 제거 → `from app.auth import require_role` |
| `_workspace/api_data_router.py` | **수정** | 쓰기 엔드포인트 3개 → `Depends(require_role(...))` 추가 |
| `_workspace/api_master_router.py` | **수정** | 쓰기 엔드포인트 11개 → `Depends(require_role(...))` 추가 |
| `_workspace/api_material_router.py` | **수정** | 쓰기 엔드포인트 4개 → `Depends(require_role(...))` 추가 |
| `streamlit_app/Home.py` | **수정** | 실제 API 호출 + token/roles 세션 저장 |
| `streamlit_app/utils/auth_helper.py` | **신규** | `get_auth_headers()`, `check_login()`, `has_role()` |
| `streamlit_app/pages/*.py` (5개) | **수정** | `check_login()` + `get_auth_headers()` 적용 |
| `seed_users.sql` | **신규** | bcrypt 해시 포함 초기 계정 4개 |

---

## 5. RBAC 권한 테이블 (최종)

### 5.1 API 엔드포인트별 허용 역할

| 모듈 | 엔드포인트 | ADMIN | MANAGER | QUALITY | OPERATOR |
|------|-----------|:-----:|:-------:|:-------:|:--------:|
| **공정** | POST /results | ✅ | ✅ | — | ✅ |
| **공정** | POST/PUT /recipes | ✅ | ✅ | — | — |
| **KPI** | PUT /targets/{type} | ✅ | ✅ | — | — |
| **KPI** | PUT /alerts/config/{type} | ✅ | ✅ | — | — |
| **데이터** | POST /ai/labels | ✅ | ✅ | ✅ | — |
| **데이터** | PUT /ai/labels/{id}/approve | ✅ | — | ✅ | — |
| **데이터** | POST /quality/run | ✅ | ✅ | — | — |
| **기준정보** | POST/PUT /quality-standards | ✅ | — | ✅ | — |
| **기준정보** | SOP 업로드/임베딩/활성화 | ✅ | ✅ | — | — |
| **기준정보** | SOP 삭제, 코드 관리 | ✅ | — | — | — |
| **기준정보** | POST/PUT /suppliers | ✅ | ✅ | — | — |
| **원재료** | POST /lots | ✅ | ✅ | — | ✅ |
| **원재료** | PATCH /lots/{id}/status | ✅ | ✅ | — | — |
| **원재료** | POST /inspections | ✅ | ✅ | ✅ | — |
| **원재료** | POST /selections | ✅ | — | ✅ | ✅ |
| **출하** | POST /approve | ✅ | ✅ | — | — |
| **시스템** | 사용자/역할 CRUD | ✅ | — | — | — |
| **시스템** | 로그 조회 | ✅ | — | — | — |
| **시스템** | 알림 설정 조회 | ✅ | ✅ | — | — |

### 5.2 읽기(GET) 엔드포인트 정책

| 분류 | 정책 |
|------|------|
| 대시보드 GET | 로그인 필요 (역할 무관) — `Depends(get_current_user)` |
| 공정/KPI/데이터 GET | 로그인 필요 (역할 무관) |
| 시스템 로그 GET | ADMIN 전용 |
| `/health` | 공개 (인증 제외) |

---

## 6. 시퀀스 다이어그램

```
Streamlit                FastAPI                    PostgreSQL
   │                        │                           │
   │─ POST /auth/login ────►│                           │
   │  {username, password}  │─ SELECT users ───────────►│
   │                        │◄────────── row ───────────│
   │                        │─ bcrypt.verify() ─────────│
   │                        │─ create JWT ──────────────│
   │◄── {access_token} ─────│                           │
   │                        │                           │
   │─ GET /api/v1/kpi/... ─►│                           │
   │  Authorization: Bearer │─ jwt.decode() ────────────│
   │                        │─ SELECT users(user_id) ──►│
   │                        │◄────────── row ───────────│
   │                        │─ SELECT user_roles+roles ►│
   │                        │◄────────── roles ─────────│
   │                        │─ roles in allowed? ────────│
   │                        │  NO → 403 Forbidden        │
   │                        │  YES → handle request ─────│
   │◄── response ───────────│                           │
```

---

## 7. 환경 변수

```env
# .env (프로젝트 루트)
JWT_SECRET_KEY=kkotsooni-mes-prod-secret-change-before-deploy-2026
JWT_EXPIRE_MINUTES=480
JWT_ALGORITHM=HS256
```

**`.gitignore`에 `.env` 포함 확인 필수**

---

## 8. 완료 기준 (Definition of Done)

| # | 검증 항목 | 방법 |
|---|----------|------|
| 1 | `POST /api/v1/system/auth/login` → 올바른 자격증명 → 200 + JWT 반환 | httpx/curl |
| 2 | 잘못된 자격증명 → 401 | httpx/curl |
| 3 | Bearer 토큰 없이 `PUT /kpi/targets/PRODUCTION` 접근 → 401 | httpx |
| 4 | OPERATOR 토큰으로 `PUT /kpi/targets/PRODUCTION` → 403 | httpx |
| 5 | MANAGER 토큰으로 `PUT /kpi/targets/PRODUCTION` → 200 | httpx |
| 6 | 만료/위조 토큰 → 401 | jwt.encode with wrong key |
| 7 | Streamlit 로그인 폼 → API 호출 → access_token 세션 저장 | 브라우저 |
| 8 | Streamlit 페이지 전환 시 API 요청에 Bearer 헤더 포함 | 브라우저 DevTools |
| 9 | 로그아웃 → `st.session_state.clear()` → 재로그인 요구 | 브라우저 |
| 10 | Gap Analysis ≥ 90% | `/pdca analyze jwt-auth-integration` |

---

## 9. 구현 순서 (Do Phase 체크리스트)

```
[ ] Step 1: python-jose[cryptography], passlib[bcrypt] 설치 확인
[ ] Step 2: api_system_router.py — POST /auth/login JSON 엔드포인트 추가
[ ] Step 3: api_kpi_router.py — 로컬 stub 제거, from app.auth import require_role
[ ] Step 4: api_shipping_router.py — 로컬 stub 제거, from app.auth import require_role
[ ] Step 5: api_data_router.py — 쓰기 엔드포인트 require_role 추가
[ ] Step 6: api_master_router.py — 쓰기 엔드포인트 require_role 추가
[ ] Step 7: api_material_router.py — 쓰기 엔드포인트 require_role 추가
[ ] Step 8: streamlit_app/utils/auth_helper.py 생성
[ ] Step 9: streamlit_app/Home.py — 실제 API 호출로 교체
[ ] Step 10: streamlit_app/pages/*.py — check_login() + get_auth_headers() 적용
[ ] Step 11: seed_users.sql — bcrypt 해시 실제 값으로 생성
[ ] Step 12: 서버 재시작 후 수동 QA (완료 기준 §8 검증)
```

---

*설계 작성: bkit PDCA | 다음 단계: `/pdca do jwt-auth-integration`*
