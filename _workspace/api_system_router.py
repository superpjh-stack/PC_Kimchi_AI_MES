"""
꽃순이김치 제조AI 스마트공장 MES — 사용자/시스템관리 API 라우터
프로젝트: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션

prefix: /api/v1/system
기획서 8장(사용자/시스템관리) + db_system_schema.sql 기준.

구성:
  - 사용자 관리      : GET/POST/PUT/DELETE /users, 역할 부여/제거
  - 역할/권한 매트릭스: GET /roles, GET/PUT /roles/{id}/permissions
  - 로그 조회        : /logs/system, /logs/activity, /logs/ai-agent
  - 알림 설정/이력   : /notifications/config, /notifications/logs
  - 시스템 설정      : /edge-devices, /edge-devices/{id}/sensors, /batch-schedules

권한 검증:
  require_role(["ADMIN", ...]) 의존성으로 엔드포인트를 역할 기반 보호한다.
  사용자/시스템관리 메뉴는 기본적으로 ADMIN 전용(기획서 8.1)이며,
  알림 설정 조회 등 일부는 MANAGER 까지 허용한다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from app.database import get_db
from app.auth import (
    CurrentUser,
    TokenResponse,
    get_current_user,
    get_user_roles,
    require_role,
    hash_password,
    create_login_token,
    authenticate_user,
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)

router = APIRouter(prefix="/api/v1/system", tags=["사용자/시스템관리"])


# =====================================================================
# Pydantic 모델
# =====================================================================
class LoginRequest(BaseModel):
    """JSON Body 로그인 요청 (Streamlit / REST 클라이언트용)."""
    username: str
    password: str


class LoginResponse(BaseModel):
    """JSON Body 로그인 응답."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict  # { user_id, username, roles }


class UserCreate(BaseModel):
    username: str
    full_name: str
    email: str | None = None
    department: str | None = None
    password: str
    role_ids: list[int] = Field(default_factory=list)


class UserUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    department: str | None = None
    is_active: bool | None = None
    password: str | None = None


class PermissionItem(BaseModel):
    menu_code: str
    can_read: bool
    can_write: bool


class PermissionMatrixUpdate(BaseModel):
    permissions: list[PermissionItem]


class RoleGrant(BaseModel):
    role_id: int


class NotificationConfigCreate(BaseModel):
    notification_type: str  # ALARM/KPI/SYSTEM
    channel: str            # SMS/EMAIL/PUSH
    recipients: list[str] = Field(default_factory=list)
    is_active: bool = True


class NotificationConfigUpdate(BaseModel):
    channel: str | None = None
    recipients: list[str] | None = None
    is_active: bool | None = None


class EdgeDeviceCreate(BaseModel):
    device_name: str
    protocol: str           # OPC_UA/MODBUS
    host: str
    port: int
    timeout_sec: int = 10
    retry_count: int = 3
    is_active: bool = True


class EdgeDeviceUpdate(BaseModel):
    device_name: str | None = None
    protocol: str | None = None
    host: str | None = None
    port: int | None = None
    timeout_sec: int | None = None
    retry_count: int | None = None
    is_active: bool | None = None


class SensorMappingCreate(BaseModel):
    sensor_id: str
    sensor_name: str | None = None
    data_field: str
    unit: str | None = None
    scale_factor: float = 1.0
    offset_value: float = 0.0
    interval_sec: int = 600


class BatchScheduleUpdate(BaseModel):
    cron_expression: str | None = None
    is_active: bool | None = None
    description: str | None = None


# =====================================================================
# 로그인 — POST /api/v1/system/auth/token (OAuth2 Bearer)
# =====================================================================
@router.post(
    "/auth/token",
    response_model=TokenResponse,
    summary="로그인 (JWT 토큰 발급)",
    tags=["사용자/시스템관리"],
)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    OAuth2 Password Flow 로그인.

    - username / password 를 검증한다
    - 성공 시 JWT Bearer 토큰을 반환한다 (유효기간 8시간, 환경변수 JWT_EXPIRE_MINUTES 으로 조정)
    - 실패 시 401 반환
    """
    return await create_login_token(form_data)


@router.post(
    "/auth/login",
    response_model=LoginResponse,
    summary="로그인 (JSON Body — Streamlit/REST 클라이언트용)",
    tags=["사용자/시스템관리"],
)
async def login_json(data: LoginRequest):
    """
    JSON Body 로그인 엔드포인트.

    - username / password JSON 을 받아 bcrypt 검증 후 JWT 반환
    - Streamlit Home.py 및 REST 클라이언트에서 사용
    - OAuth2 폼 방식(/auth/token)과 동일한 인증 로직, 응답에 roles 추가
    """
    from datetime import timedelta
    user = await authenticate_user(data.username, data.password)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="사용자명 또는 비밀번호가 잘못되었습니다",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(
        data={"sub": str(user.user_id)},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    roles = await get_user_roles(user.user_id)
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user={"user_id": user.user_id, "username": user.username, "roles": roles},
    )


# =====================================================================
# 사용자 관리
# =====================================================================
@router.get("/users", dependencies=[Depends(require_role("ADMIN"))])
async def list_users(is_active: bool | None = Query(None)):
    """사용자 목록 (역할 집계 포함, is_active 필터)."""
    where = "WHERE u.is_active = $1" if is_active is not None else ""
    params: list[Any] = [is_active] if is_active is not None else []
    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT u.user_id, u.username, u.full_name, u.email, u.department,
                   u.is_active, u.last_login, u.created_at,
                   COALESCE(
                       ARRAY_AGG(r.role_code) FILTER (WHERE r.role_code IS NOT NULL),
                       '{{}}'
                   ) AS roles
            FROM users u
            LEFT JOIN user_roles ur ON u.user_id = ur.user_id
            LEFT JOIN roles r ON ur.role_id = r.role_id
            {where}
            GROUP BY u.user_id
            ORDER BY u.user_id
            """,
            *params,
        )
    return [dict(r) for r in rows]


@router.post("/users", status_code=201, dependencies=[Depends(require_role("ADMIN"))])
async def create_user(data: UserCreate):
    """사용자 등록 + 역할 부여."""
    async with get_db() as conn:
        async with conn.transaction():
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO users (username, full_name, email, department, hashed_password)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING user_id, username, full_name, email, department, is_active, created_at
                    """,
                    data.username, data.full_name, data.email,
                    data.department, hash_password(data.password),
                )
            except Exception as e:  # UniqueViolation 등
                raise HTTPException(status_code=409, detail=f"사용자 등록 실패: {e}")
            for role_id in data.role_ids:
                await conn.execute(
                    """
                    INSERT INTO user_roles (user_id, role_id)
                    VALUES ($1, $2)
                    ON CONFLICT (user_id, role_id) DO NOTHING
                    """,
                    row["user_id"], role_id,
                )
    return dict(row)


@router.put("/users/{user_id}", dependencies=[Depends(require_role("ADMIN"))])
async def update_user(user_id: int, data: UserUpdate):
    """사용자 정보 수정 (전달된 필드만 갱신)."""
    fields: list[str] = []
    params: list[Any] = []
    idx = 1
    payload = data.model_dump(exclude_unset=True)
    if "password" in payload:
        payload["hashed_password"] = hash_password(payload.pop("password"))
    for col, val in payload.items():
        fields.append(f"{col} = ${idx}")
        params.append(val)
        idx += 1
    if not fields:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다")
    fields.append("updated_at = NOW()")
    params.append(user_id)
    async with get_db() as conn:
        row = await conn.fetchrow(
            f"UPDATE users SET {', '.join(fields)} WHERE user_id = ${idx} "
            f"RETURNING user_id, username, full_name, email, department, is_active, updated_at",
            *params,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"사용자 {user_id} 없음")
    return dict(row)


@router.delete("/users/{user_id}", dependencies=[Depends(require_role("ADMIN"))])
async def deactivate_user(user_id: int):
    """사용자 비활성화 (물리 삭제 대신 is_active=False)."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            "UPDATE users SET is_active = FALSE, updated_at = NOW() "
            "WHERE user_id = $1 RETURNING user_id, is_active",
            user_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"사용자 {user_id} 없음")
    return {"user_id": row["user_id"], "is_active": row["is_active"], "message": "비활성화 완료"}


# =====================================================================
# 역할 / 권한 매트릭스
# =====================================================================
@router.get("/roles", dependencies=[Depends(require_role("ADMIN", "MANAGER"))])
async def list_roles():
    """역할 목록."""
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT role_id, role_code, role_name, description FROM roles ORDER BY role_id"
        )
    return [dict(r) for r in rows]


@router.get("/roles/{role_id}/permissions", dependencies=[Depends(require_role("ADMIN", "MANAGER"))])
async def get_role_permissions(role_id: int):
    """역할별 권한 매트릭스 조회."""
    async with get_db() as conn:
        role = await conn.fetchrow("SELECT role_code FROM roles WHERE role_id = $1", role_id)
        if not role:
            raise HTTPException(status_code=404, detail=f"역할 {role_id} 없음")
        rows = await conn.fetch(
            "SELECT menu_code, can_read, can_write FROM role_permissions "
            "WHERE role_id = $1 ORDER BY menu_code",
            role_id,
        )
    return {"role_id": role_id, "role_code": role["role_code"], "permissions": [dict(r) for r in rows]}


@router.put("/roles/{role_id}/permissions", dependencies=[Depends(require_role("ADMIN"))])
async def update_role_permissions(role_id: int, data: PermissionMatrixUpdate):
    """권한 매트릭스 수정 (UPSERT)."""
    async with get_db() as conn:
        exists = await conn.fetchval("SELECT 1 FROM roles WHERE role_id = $1", role_id)
        if not exists:
            raise HTTPException(status_code=404, detail=f"역할 {role_id} 없음")
        async with conn.transaction():
            for p in data.permissions:
                await conn.execute(
                    """
                    INSERT INTO role_permissions (role_id, menu_code, can_read, can_write)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (role_id, menu_code)
                    DO UPDATE SET can_read = EXCLUDED.can_read, can_write = EXCLUDED.can_write
                    """,
                    role_id, p.menu_code, p.can_read, p.can_write,
                )
    return {"role_id": role_id, "updated": len(data.permissions)}


@router.post("/users/{user_id}/roles", status_code=201, dependencies=[Depends(require_role("ADMIN"))])
async def grant_role(user_id: int, data: RoleGrant, current_user: CurrentUser = Depends(get_current_user)):
    """사용자에게 역할 부여."""
    async with get_db() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO user_roles (user_id, role_id, granted_by)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, role_id) DO NOTHING
                """,
                user_id, data.role_id, current_user.user_id,
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"역할 부여 실패: {e}")
    return {"user_id": user_id, "role_id": data.role_id, "message": "역할 부여 완료"}


@router.delete("/users/{user_id}/roles/{role_id}", dependencies=[Depends(require_role("ADMIN"))])
async def revoke_role(user_id: int, role_id: int):
    """사용자 역할 제거."""
    async with get_db() as conn:
        result = await conn.execute(
            "DELETE FROM user_roles WHERE user_id = $1 AND role_id = $2", user_id, role_id
        )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="해당 역할 매핑이 없습니다")
    return {"user_id": user_id, "role_id": role_id, "message": "역할 제거 완료"}


# =====================================================================
# 로그 조회
# =====================================================================
@router.get("/logs/system", dependencies=[Depends(require_role("ADMIN"))])
async def get_system_logs(
    level: str | None = Query(None, description="ERROR/WARNING/INFO/DEBUG"),
    module: str | None = Query(None),
    start_dt: datetime | None = Query(None),
    end_dt: datetime | None = Query(None),
    limit: int = Query(100, le=1000),
):
    """시스템 로그 조회 (레벨/모듈/기간 필터)."""
    conds: list[str] = []
    params: list[Any] = []
    idx = 1
    if level:
        conds.append(f"log_level = ${idx}"); params.append(level); idx += 1
    if module:
        conds.append(f"module = ${idx}"); params.append(module); idx += 1
    if start_dt:
        conds.append(f"log_time >= ${idx}"); params.append(start_dt); idx += 1
    if end_dt:
        conds.append(f"log_time <= ${idx}"); params.append(end_dt); idx += 1
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    params.append(limit)
    async with get_db() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM system_log {where} ORDER BY log_time DESC LIMIT ${idx}", *params
        )
    return [dict(r) for r in rows]


@router.get("/logs/activity", dependencies=[Depends(require_role("ADMIN"))])
async def get_activity_logs(
    user_id: int | None = Query(None),
    action_type: str | None = Query(None),
    limit: int = Query(100, le=1000),
):
    """사용자 활동 로그 조회 (사용자/액션 필터)."""
    conds: list[str] = []
    params: list[Any] = []
    idx = 1
    if user_id is not None:
        conds.append(f"a.user_id = ${idx}"); params.append(user_id); idx += 1
    if action_type:
        conds.append(f"a.action_type = ${idx}"); params.append(action_type); idx += 1
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    params.append(limit)
    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT a.*, u.username, u.full_name
            FROM user_activity_log a
            LEFT JOIN users u ON a.user_id = u.user_id
            {where}
            ORDER BY a.created_at DESC
            LIMIT ${idx}
            """,
            *params,
        )
    return [dict(r) for r in rows]


@router.get("/logs/ai-agent", dependencies=[Depends(require_role("ADMIN"))])
async def get_ai_agent_logs(
    agent_type: str | None = Query(None, description="INTAKE/SHIPPING"),
    user_id: int | None = Query(None),
    limit: int = Query(100, le=1000),
):
    """AI Agent 질의 로그 조회 (에이전트/사용자 필터)."""
    conds: list[str] = []
    params: list[Any] = []
    idx = 1
    if agent_type:
        conds.append(f"l.agent_type = ${idx}"); params.append(agent_type); idx += 1
    if user_id is not None:
        conds.append(f"l.user_id = ${idx}"); params.append(user_id); idx += 1
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    params.append(limit)
    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT l.*, u.username, u.full_name
            FROM ai_agent_log l
            LEFT JOIN users u ON l.user_id = u.user_id
            {where}
            ORDER BY l.created_at DESC
            LIMIT ${idx}
            """,
            *params,
        )
    return [dict(r) for r in rows]


# =====================================================================
# 알림 설정 / 이력
# =====================================================================
@router.get("/notifications/config", dependencies=[Depends(require_role("ADMIN", "MANAGER"))])
async def list_notification_configs(notification_type: str | None = Query(None)):
    """알림 설정 목록."""
    where = "WHERE notification_type = $1" if notification_type else ""
    params: list[Any] = [notification_type] if notification_type else []
    async with get_db() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM notification_config {where} ORDER BY config_id", *params
        )
    return [dict(r) for r in rows]


@router.post("/notifications/config", status_code=201, dependencies=[Depends(require_role("ADMIN"))])
async def create_notification_config(data: NotificationConfigCreate):
    """알림 설정 등록."""
    import json
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO notification_config (notification_type, channel, recipients, is_active)
            VALUES ($1, $2, $3::jsonb, $4)
            RETURNING *
            """,
            data.notification_type, data.channel, json.dumps(data.recipients), data.is_active,
        )
    return dict(row)


@router.put("/notifications/config/{config_id}", dependencies=[Depends(require_role("ADMIN"))])
async def update_notification_config(config_id: int, data: NotificationConfigUpdate):
    """알림 설정 수정."""
    import json
    fields: list[str] = []
    params: list[Any] = []
    idx = 1
    payload = data.model_dump(exclude_unset=True)
    for col, val in payload.items():
        if col == "recipients":
            fields.append(f"recipients = ${idx}::jsonb"); params.append(json.dumps(val))
        else:
            fields.append(f"{col} = ${idx}"); params.append(val)
        idx += 1
    if not fields:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다")
    fields.append("updated_at = NOW()")
    params.append(config_id)
    async with get_db() as conn:
        row = await conn.fetchrow(
            f"UPDATE notification_config SET {', '.join(fields)} WHERE config_id = ${idx} RETURNING *",
            *params,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"알림 설정 {config_id} 없음")
    return dict(row)


@router.get("/notifications/logs", dependencies=[Depends(require_role("ADMIN", "MANAGER"))])
async def get_notification_logs(
    status: str | None = Query(None, description="SENT/FAILED/PENDING"),
    limit: int = Query(100, le=1000),
):
    """알림 발송 이력."""
    # idx += 1 증분 패턴으로 통일 (다른 엔드포인트와 일관성 확보 — S-L3 수정)
    params: list[Any] = []
    idx = 1
    where = ""
    if status:
        params.append(status)
        where = f"WHERE status = ${idx}"
        idx += 1
    params.append(limit)
    async with get_db() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM notification_log {where} ORDER BY sent_at DESC LIMIT ${idx}", *params
        )
    return [dict(r) for r in rows]


# =====================================================================
# 시스템 설정 — Edge 장치 / 센서 매핑 / 배치 스케줄
# =====================================================================
@router.get("/edge-devices", dependencies=[Depends(require_role("ADMIN"))])
async def list_edge_devices(is_active: bool | None = Query(None)):
    """Edge 장치 설정 목록 (연결 상태 계산 포함)."""
    where = "WHERE is_active = $1" if is_active is not None else ""
    params: list[Any] = [is_active] if is_active is not None else []
    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT *,
                   (last_seen IS NOT NULL AND last_seen >= NOW() - INTERVAL '5 minutes') AS is_connected
            FROM edge_device_config {where}
            ORDER BY device_id
            """,
            *params,
        )
    return [dict(r) for r in rows]


@router.post("/edge-devices", status_code=201, dependencies=[Depends(require_role("ADMIN"))])
async def create_edge_device(data: EdgeDeviceCreate):
    """Edge 장치 등록."""
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO edge_device_config
                (device_name, protocol, host, port, timeout_sec, retry_count, is_active)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
            """,
            data.device_name, data.protocol, data.host, data.port,
            data.timeout_sec, data.retry_count, data.is_active,
        )
    return dict(row)


@router.put("/edge-devices/{device_id}", dependencies=[Depends(require_role("ADMIN"))])
async def update_edge_device(device_id: int, data: EdgeDeviceUpdate):
    """Edge 장치 수정."""
    fields: list[str] = []
    params: list[Any] = []
    idx = 1
    for col, val in data.model_dump(exclude_unset=True).items():
        fields.append(f"{col} = ${idx}"); params.append(val); idx += 1
    if not fields:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다")
    params.append(device_id)
    async with get_db() as conn:
        row = await conn.fetchrow(
            f"UPDATE edge_device_config SET {', '.join(fields)} WHERE device_id = ${idx} RETURNING *",
            *params,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"Edge 장치 {device_id} 없음")
    return dict(row)


@router.get("/edge-devices/{device_id}/sensors", dependencies=[Depends(require_role("ADMIN"))])
async def list_sensor_mappings(device_id: int):
    """센서 매핑 목록."""
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT * FROM sensor_mapping WHERE device_id = $1 ORDER BY mapping_id", device_id
        )
    return [dict(r) for r in rows]


@router.post("/edge-devices/{device_id}/sensors", status_code=201, dependencies=[Depends(require_role("ADMIN"))])
async def create_sensor_mapping(device_id: int, data: SensorMappingCreate):
    """센서 매핑 등록."""
    async with get_db() as conn:
        device = await conn.fetchval(
            "SELECT 1 FROM edge_device_config WHERE device_id = $1", device_id
        )
        if not device:
            raise HTTPException(status_code=404, detail=f"Edge 장치 {device_id} 없음")
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO sensor_mapping
                    (device_id, sensor_id, sensor_name, data_field, unit,
                     scale_factor, offset_value, interval_sec)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING *
                """,
                device_id, data.sensor_id, data.sensor_name, data.data_field,
                data.unit, data.scale_factor, data.offset_value, data.interval_sec,
            )
        except Exception as e:  # uq_sensor_device 위반 등
            raise HTTPException(status_code=409, detail=f"센서 매핑 등록 실패: {e}")
    return dict(row)


@router.get("/batch-schedules", dependencies=[Depends(require_role("ADMIN"))])
async def list_batch_schedules(is_active: bool | None = Query(None)):
    """배치 스케줄 목록."""
    where = "WHERE is_active = $1" if is_active is not None else ""
    params: list[Any] = [is_active] if is_active is not None else []
    async with get_db() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM batch_schedule {where} ORDER BY schedule_id", *params
        )
    return [dict(r) for r in rows]


@router.put("/batch-schedules/{schedule_id}", dependencies=[Depends(require_role("ADMIN"))])
async def update_batch_schedule(schedule_id: int, data: BatchScheduleUpdate):
    """배치 스케줄 수정 (cron, 활성화, 설명)."""
    fields: list[str] = []
    params: list[Any] = []
    idx = 1
    for col, val in data.model_dump(exclude_unset=True).items():
        fields.append(f"{col} = ${idx}"); params.append(val); idx += 1
    if not fields:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다")
    params.append(schedule_id)
    async with get_db() as conn:
        row = await conn.fetchrow(
            f"UPDATE batch_schedule SET {', '.join(fields)} WHERE schedule_id = ${idx} RETURNING *",
            *params,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"배치 스케줄 {schedule_id} 없음")
    return dict(row)
