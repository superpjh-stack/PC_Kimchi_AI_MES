"""
꽃순이김치 제조AI MES — 공통 JWT 인증 + bcrypt 비밀번호 모듈
Project: SF26179540 | 로뎀솔루션 주식회사

이 모듈이 담당하는 것:
  - JWT 토큰 발급 / 검증 (python-jose[cryptography] + HS256)
  - bcrypt 비밀번호 해싱 / 검증 (passlib[bcrypt])
  - FastAPI 의존성 get_current_user (OAuth2 Bearer 토큰 → CurrentUser)
  - RBAC 의존성 require_role(*allowed)
  - 로그인 Pydantic 스키마

환경변수:
  JWT_SECRET_KEY      — 서명 키 (운영 시 반드시 변경)
  JWT_EXPIRE_MINUTES  — 토큰 유효 분 (기본 480 = 8시간)
  DATABASE_URL        — asyncpg 연결 (app.database 에서 읽음)

모든 라우터는 이 모듈에서 CurrentUser, get_current_user, require_role 을 임포트한다.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt as _bcrypt

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel

from app.database import get_db

# =====================================================================
# 설정
# =====================================================================
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-change-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))  # 8시간

# =====================================================================
# 비밀번호 해시 (bcrypt 직접 사용 — passlib Python 3.14 호환 문제 우회)
# =====================================================================

def hash_password(raw: str) -> str:
    """평문 비밀번호 → bcrypt 해시 (rounds=12)."""
    return _bcrypt.hashpw(raw.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    """평문 비밀번호와 bcrypt 해시 일치 여부 확인."""
    # 레거시 시드 데이터 호환: hashed:: prefix 는 항상 불일치로 처리
    if not hashed or hashed.startswith("hashed::"):
        return False
    try:
        return _bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# =====================================================================
# OAuth2 스킴
# =====================================================================
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/system/auth/token",
    auto_error=True,
)


# =====================================================================
# Pydantic 모델
# =====================================================================
class CurrentUser(BaseModel):
    user_id: int
    username: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_EXPIRE_MINUTES * 60


# =====================================================================
# JWT 유틸리티
# =====================================================================
def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """JWT 액세스 토큰 생성 (공개 API)."""
    to_encode = data.copy()
    expire = datetime.now(tz=timezone.utc) + (
        expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# 내부 호환 alias
_create_access_token = create_access_token


# =====================================================================
# FastAPI 의존성: get_current_user
# =====================================================================
async def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    """
    Authorization: Bearer <token> 헤더에서 JWT 를 검증한 후 CurrentUser 반환.

    검증 단계:
      1. jose.jwt.decode — 서명 / 만료 검증
      2. sub 클레임 → user_id(int) 추출
      3. users 테이블에서 username 조회 (비활성 사용자 거부)

    실패 시: 401 "인증 실패"
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증 실패",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub: str | None = payload.get("sub")
        if sub is None:
            raise credentials_exception
        user_id = int(sub)
    except (JWTError, ValueError):
        raise credentials_exception

    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, username FROM users WHERE user_id = $1 AND is_active = TRUE",
            user_id,
        )
    if row is None:
        raise credentials_exception
    return CurrentUser(user_id=row["user_id"], username=row["username"])


# =====================================================================
# FastAPI 의존성: get_user_roles
# =====================================================================
async def get_user_roles(user_id: int) -> list[str]:
    """사용자의 role_code 목록 조회 (user_roles JOIN roles)."""
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT r.role_code
            FROM user_roles ur
            JOIN roles r ON ur.role_id = r.role_id
            WHERE ur.user_id = $1
            """,
            user_id,
        )
    return [r["role_code"] for r in rows]


# =====================================================================
# FastAPI 의존성: require_role
# =====================================================================
def require_role(*allowed: str):
    """
    역할 기반 엔드포인트 보호 (FastAPI 의존성).

    사용 예:
        @router.post("/sensitive")
        async def endpoint(current_user = Depends(require_role("ADMIN", "MANAGER"))):
            ...

    허용된 역할이 아닌 경우 403 "권한 없음" 반환.
    """
    async def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        user_roles = await get_user_roles(current_user.user_id)
        if not any(r in allowed for r in user_roles):
            raise HTTPException(status_code=403, detail="권한 없음")
        return current_user

    return dependency


# =====================================================================
# 로그인 함수 (api_system_router.py 에서 사용)
# =====================================================================
async def authenticate_user(username: str, password: str) -> CurrentUser | None:
    """
    username + password 를 검증해 CurrentUser 반환.
    검증 실패 시 None 반환.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, username, hashed_password FROM users "
            "WHERE username = $1 AND is_active = TRUE",
            username,
        )
    if row is None:
        return None
    if not verify_password(password, row["hashed_password"]):
        return None
    return CurrentUser(user_id=row["user_id"], username=row["username"])


async def create_login_token(form_data: OAuth2PasswordRequestForm) -> TokenResponse:
    """
    OAuth2 폼 데이터로 사용자를 인증하고 JWT 토큰을 반환한다.
    실패 시 401 HTTPException 발생.
    """
    user = await authenticate_user(form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자명 또는 비밀번호가 잘못되었습니다",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = _create_access_token(data={"sub": str(user.user_id)})
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
