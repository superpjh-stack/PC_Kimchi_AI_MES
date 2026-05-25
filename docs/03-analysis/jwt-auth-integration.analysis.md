# Gap Analysis Report — jwt-auth-integration

> **Project**: 꽃순이김치 제조AI MES (SF26179540 / 로뎀솔루션)
> **Analyst**: bkit:gap-detector
> **Date**: 2026-05-25
> **PDCA Phase**: Check
> **Plan**: `docs/01-plan/features/jwt-auth-integration.plan.md`
> **Design**: `docs/02-design/features/jwt-auth-integration.design.md`

---

## 1. 분석 개요

- **범위**: JWT 인증 통합 (로그인 엔드포인트 / 공통 auth 모듈 / 10개 라우터 / Streamlit 연동 / seed 데이터)
- **검증 파일**: 17개 파일 (app/auth.py + API 라우터 7개 + utils 2개 + pages 5개 + seed_users.sql + Home.py)
- **분석 방법**: Design §3 체크리스트 51개 항목 ↔ 실제 코드 라인 대조

---

## 2. 전체 Match Rate

| 카테고리 | 점수 | 상태 |
|----------|:----:|:----:|
| Design §3 체크리스트 (51개 항목) | 100% (51/51) | ✅ |
| RBAC 권한 매트릭스 (Design §5) | 100% | ✅ |
| 코드 컨벤션 (fastapi-mes / asyncpg / Pydantic v2) | 98% | ✅ |
| **종합 Match Rate** | **100%** | ✅ **PASS** |

---

## 3. 섹션별 결과

| § | 섹션 | 항목 수 | 통과 | 근거 |
|---|------|:------:|:----:|------|
| 3.1 | JSON 로그인 엔드포인트 | 4 | 4/4 | `api_system_router.py:163-195` — POST /auth/login, LoginRequest:49, LoginResponse:55, 401 메시지:182 |
| 3.2 | `app/auth.py` 핵심 함수 | 6 | 6/6 | `create_access_token:87`, `get_current_user:104`, `get_user_roles:142`, `require_role:160`, `hash_password:45`, `verify_password:50` |
| 3.3 | `api_kpi_router.py` stub 제거 | 4 | 4/4 | 로컬 stub 없음; `from app.auth import require_role:20`; PUT /targets/:334; PUT /alerts/config/:382 |
| 3.4 | `api_shipping_router.py` stub 제거 | 2 | 2/2 | 로컬 stub 없음; `from app.auth import require_role:31`; approve Depends:502-505 |
| 3.5 | `api_data_router.py` 인증 추가 | 3 | 3/3 | `/ai/labels:499-502`, `/ai/labels/{id}/approve:515-519`, `/quality/run:679-682` |
| 3.6 | `api_master_router.py` 인증 추가 | 11 | 11/11 | quality-standards POST/PUT, sop upload/embed/activate/delete, codes POST/PUT/DELETE, suppliers POST/PUT — 전체 require_role |
| 3.7 | `api_material_router.py` 인증 추가 | 4 | 4/4 | `/lots:194-197`, `/lots/{id}/status:310-314`, `/inspections:349-352`, `/selections:449-452` |
| 3.8 | `streamlit_app/utils/auth_helper.py` | 4 | 4/4 | `get_auth_headers:17`, `check_login:32`, `has_role:47`, `handle_401:74` |
| 3.9 | `streamlit_app/Home.py` | 5 | 5/5 | `_do_login:28`, httpx.post→/auth/login:35, token+roles 세션:47-50, 401 st.error:55, selectbox 제거 |
| 3.10 | `pages/05~09.py` 인증 적용 | 5 | 5/5 | 각 페이지 sys.path + check_login + get_auth_headers 주입 |
| — | `seed_users.sql` | 3 | 3/3 | 4개 계정, bcrypt `$2b$12$` 해시, user_roles 부여 |
| | **합계** | **51** | **51** | **100%** |

---

## 4. Gap 목록

### 🔴 누락 항목 (차단 Gap)
없음 — 체크리스트 51개 항목 전체 충족.

### 🟡 추가 항목 (계획 대비 구현 초과 — 긍정적)

| # | 항목 | 구현 위치 | 설명 |
|---|------|-----------|------|
| A-1 | `streamlit_app/utils/api_client.py` | api_client.py | 설계 §3.8에 없던 HTTP 클라이언트 팩토리 — `get_client()`, `api_get/post/put()`, 401 자동 처리 포함 |
| A-2 | `require_login_and_role()` | auth_helper.py:60 | 로그인 + 역할 통합 헬퍼 — 설계 코드 예시엔 있으나 체크리스트 외 항목 |
| A-3 | `user_role` 하위호환 키 유지 | Home.py:52 | `user_roles[0]`을 단일 `user_role`로 보존 — 기존 pages 호환 |

### 🔵 변경 항목 (비차단)

| # | 설계 | 구현 | 영향도 |
|---|------|------|--------|
| C-1 | 출하 승인 경로 `POST /shipping/approve` (§5 표) | 실제 `PATCH /api/v1/shipping/orders/{order_id}/approve` | Low — 체크리스트(§3.4)는 경로가 아닌 stub 제거·require_role만 요구하므로 충족. 설계 문서 경로 표기 갱신 권장 |
| C-2 | `.env` 파일 (§7) | `app/auth.py:37` fallback 값 사용 | Low — 기능 동작에 문제없으나 운영 배포 전 실제 `.env` 생성 필수 |

---

## 5. DoD 코드 레벨 매핑 (Design §8)

| # | 완료 기준 | 코드 근거 | 상태 |
|---|----------|-----------|------|
| 1 | POST /auth/login → 200 + JWT | `api_system_router.py:185-195` login_json | ✅ |
| 2 | 잘못된 자격증명 → 401 | `api_system_router.py:179-184` | ✅ |
| 3 | 토큰 없이 PUT /kpi/targets → 401 | `require_role` → `get_current_user` → `oauth2_scheme(auto_error=True)` | ✅ |
| 4 | OPERATOR로 PUT /kpi/targets → 403 | `api_kpi_router.py:334` `require_role("ADMIN","MANAGER")` | ✅ |
| 5 | MANAGER로 PUT /kpi/targets → 200 | 동일 require_role — MANAGER 허용 | ✅ |
| 6 | 위조/만료 토큰 → 401 | `app/auth.py:126` JWTError 처리 | ✅ |
| 7 | Streamlit 로그인 → 토큰 세션 저장 | `Home.py:47-50` access_token + user_roles | ✅ |
| 8 | 페이지 전환 시 Bearer 헤더 포함 | `pages/05~09.py` get_auth_headers() 주입 | ✅ |
| 9 | 로그아웃 → session clear | `Home.py:117-119` st.session_state.clear() | ✅ |
| 10 | Gap Analysis ≥ 90% | 본 분석 = 100% | ✅ |

---

## 6. 운영 전 권장 액션

| 우선순위 | 항목 | 내용 |
|----------|------|------|
| 배포 전 필수 | `.env` 파일 생성 | `JWT_SECRET_KEY`(≥32자) 실값 설정 + `.gitignore` 확인 |
| 배포 전 권장 | seed 비밀번호 변경 | Admin1234! 등 → 운영 비밀번호로 교체 |
| 문서화 | 설계 §5 출하 경로 갱신 | `POST /shipping/approve` → 실제 `PATCH /orders/{id}/approve` |
| 문서화 | 설계 §3.8에 api_client.py 추가 | 추가 구현(A-1) 설계 문서 반영 |

---

## 7. 최종 판정

```
[Plan] ✅ → [Design] ✅ → [Do] ✅ → [Check] ✅ 100% → [Report] 권장
```

**100% ≥ 90%: PASS — 완료 판정**

[Act] 반복 불필요. `[Report]` 단계로 진행 권장.

---

*분석 도구: bkit:gap-detector | 검증 기준: jwt-auth-integration Design §3 체크리스트 51개*
