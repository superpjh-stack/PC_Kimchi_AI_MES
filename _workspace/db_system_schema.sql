-- =====================================================================
-- 꽃순이김치 제조AI 스마트공장 MES — 사용자/시스템관리 모듈 스키마
-- 프로젝트: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션
-- DBMS    : PostgreSQL 15+
-- 담당    : 사용자/시스템관리 (RBAC / 로그 / 알림 / 시스템 설정)
--
-- 기획서 8장(사용자/시스템관리 상세 명세) 기준.
--
-- RBAC 권한 모델:
--   users  ──(user_roles)──  roles  ──(role_permissions)── menu_code
--   역할: ADMIN(관리자) / MANAGER(공장장) / QUALITY(품질담당자) / OPERATOR(현장작업자)
--   메뉴별 can_read / can_write 권한을 role_permissions 에 저장하고 API 에서 검증한다.
--
-- 로그 체계 (기획서 8.2):
--   system_log         — 시스템 ERROR/WARNING/INFO/DEBUG
--   user_activity_log  — 사용자 행위(LOGIN/LOGOUT/CREATE/UPDATE/DELETE/VIEW)
--   ai_agent_log       — AI Agent 질의/응답 + RAG 출처
--
-- 알림 체계 (기획서 8.3):
--   notification_config — 알림 유형/채널/수신자 설정
--   notification_log    — 실제 발송 이력
--
-- 시스템 설정 (기획서 8.4):
--   edge_device_config  — Edge Collector 연결 설정 (OPC-UA / Modbus)
--   sensor_mapping      — 센서 ID ↔ DB 컬럼 매핑
--   batch_schedule      — Cron 기반 배치 스케줄
-- =====================================================================

-- =====================================================================
-- 1. users (사용자)
-- =====================================================================
CREATE TABLE IF NOT EXISTS users (
    user_id         BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username        VARCHAR(50)  UNIQUE NOT NULL,             -- 로그인 ID
    full_name       VARCHAR(100) NOT NULL,                    -- 사용자 성명
    email           VARCHAR(150),
    department      VARCHAR(50),                              -- 부서
    hashed_password VARCHAR(255) NOT NULL,                    -- bcrypt 등 해시 저장
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,        -- 활성/비활성(삭제 대체)
    last_login      TIMESTAMP,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);

-- =====================================================================
-- 2. roles (역할)
-- =====================================================================
CREATE TABLE IF NOT EXISTS roles (
    role_id     BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    role_code   VARCHAR(20)  UNIQUE NOT NULL,                 -- ADMIN/MANAGER/QUALITY/OPERATOR
    role_name   VARCHAR(50)  NOT NULL,                        -- 관리자/공장장/품질담당자/현장작업자
    description VARCHAR(200),
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_roles_code CHECK (
        role_code IN ('ADMIN','MANAGER','QUALITY','OPERATOR')
    )
);

-- 기본 역할 4종 시드
INSERT INTO roles (role_code, role_name, description) VALUES
    ('ADMIN',    '관리자',     '시스템 전체 관리 권한'),
    ('MANAGER',  '공장장',     '생산/품질/KPI 운영 관리'),
    ('QUALITY',  '품질담당자', '품질기준/검사/라벨링 관리'),
    ('OPERATOR', '현장작업자', '공정실적 입력 및 조회')
ON CONFLICT (role_code) DO NOTHING;

-- =====================================================================
-- 3. user_roles (사용자-역할 매핑, N:M)
-- =====================================================================
CREATE TABLE IF NOT EXISTS user_roles (
    user_id    BIGINT      NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role_id    BIGINT      NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    granted_by BIGINT      REFERENCES users(user_id),         -- 권한 부여자
    granted_at TIMESTAMP   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
);
CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role_id);

-- =====================================================================
-- 4. role_permissions (역할별 메뉴 권한 매트릭스)
--    menu_code 예: DASHBOARD / PROCESS / DATA / KPI / MASTER /
--                  USER_SYSTEM / INTAKE / FERMENTATION / SHIPPING
-- =====================================================================
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id   BIGINT      NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    menu_code VARCHAR(30) NOT NULL,                           -- 메뉴 코드
    can_read  BOOLEAN     NOT NULL DEFAULT FALSE,
    can_write BOOLEAN     NOT NULL DEFAULT FALSE,
    PRIMARY KEY (role_id, menu_code)
);
CREATE INDEX IF NOT EXISTS idx_role_perm_menu ON role_permissions(menu_code);

-- 기준 권한 매트릭스 시드 (기획서 8.1)
-- can_read=TRUE: 조회, can_write=TRUE: 등록/수정/삭제
INSERT INTO role_permissions (role_id, menu_code, can_read, can_write)
SELECT r.role_id, p.menu_code, p.can_read, p.can_write
FROM roles r
JOIN (VALUES
    -- ADMIN: 전 메뉴 읽기/쓰기
    ('ADMIN','DASHBOARD',TRUE,TRUE),  ('ADMIN','PROCESS',TRUE,TRUE),
    ('ADMIN','DATA',TRUE,TRUE),       ('ADMIN','KPI',TRUE,TRUE),
    ('ADMIN','MASTER',TRUE,TRUE),     ('ADMIN','USER_SYSTEM',TRUE,TRUE),
    ('ADMIN','INTAKE',TRUE,TRUE),     ('ADMIN','FERMENTATION',TRUE,TRUE),
    ('ADMIN','SHIPPING',TRUE,TRUE),
    -- MANAGER(공장장)
    ('MANAGER','DASHBOARD',TRUE,FALSE),  ('MANAGER','PROCESS',TRUE,TRUE),
    ('MANAGER','DATA',TRUE,FALSE),       ('MANAGER','KPI',TRUE,TRUE),
    ('MANAGER','MASTER',TRUE,FALSE),     ('MANAGER','USER_SYSTEM',TRUE,FALSE),
    ('MANAGER','INTAKE',TRUE,FALSE),     ('MANAGER','FERMENTATION',TRUE,FALSE),
    ('MANAGER','SHIPPING',TRUE,FALSE),
    -- QUALITY(품질담당자)
    ('QUALITY','DASHBOARD',TRUE,FALSE),  ('QUALITY','PROCESS',TRUE,FALSE),
    -- QUALITY×DATA: can_write=TRUE는 AI학습데이터(data_label) 쓰기 허용 의도.
    -- 현재 DATA 메뉴 코드가 단일이라 일반 조회까지 쓰기 권한이 부여됨.
    -- 세분화하려면 DATA_QUERY(읽기)/DATA_AI(쓰기) 서브 메뉴 코드 분리 필요 (향후 개선).
    ('QUALITY','DATA',TRUE,TRUE),        ('QUALITY','KPI',TRUE,FALSE),
    ('QUALITY','MASTER',TRUE,TRUE),      ('QUALITY','USER_SYSTEM',FALSE,FALSE),
    ('QUALITY','INTAKE',TRUE,TRUE),      ('QUALITY','FERMENTATION',TRUE,FALSE),
    ('QUALITY','SHIPPING',TRUE,TRUE),
    -- OPERATOR(현장작업자)
    ('OPERATOR','DASHBOARD',TRUE,FALSE), ('OPERATOR','PROCESS',TRUE,TRUE),
    ('OPERATOR','DATA',TRUE,FALSE),      ('OPERATOR','KPI',FALSE,FALSE),  -- §8.1: OPERATOR 데이터조회/시각화=읽기 허용
    ('OPERATOR','MASTER',TRUE,FALSE),    ('OPERATOR','USER_SYSTEM',FALSE,FALSE),
    ('OPERATOR','INTAKE',TRUE,TRUE),     ('OPERATOR','FERMENTATION',TRUE,TRUE),
    ('OPERATOR','SHIPPING',TRUE,TRUE)
) AS p(role_code, menu_code, can_read, can_write)
  ON r.role_code = p.role_code
ON CONFLICT (role_id, menu_code) DO NOTHING;

-- =====================================================================
-- 5. system_log (시스템 로그) — 기획서 8.2
-- =====================================================================
CREATE TABLE IF NOT EXISTS system_log (
    log_id      BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    log_level   VARCHAR(10)  NOT NULL,                        -- ERROR/WARNING/INFO/DEBUG
    log_time    TIMESTAMP    NOT NULL DEFAULT NOW(),
    module      VARCHAR(50),                                  -- 발생 모듈
    message     TEXT         NOT NULL,
    stack_trace TEXT,                                         -- 오류 시 스택 트레이스
    server_id   VARCHAR(20),                                  -- 발생 서버 ID

    CONSTRAINT chk_syslog_level CHECK (
        log_level IN ('ERROR','WARNING','INFO','DEBUG')
    )
);
CREATE INDEX IF NOT EXISTS idx_system_log_time  ON system_log(log_time DESC, log_level);
CREATE INDEX IF NOT EXISTS idx_system_log_level ON system_log(log_level);

-- =====================================================================
-- 6. user_activity_log (사용자 활동 로그) — 기획서 8.2
-- =====================================================================
CREATE TABLE IF NOT EXISTS user_activity_log (
    log_id        BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id       BIGINT       REFERENCES users(user_id) ON DELETE SET NULL,
    action_type   VARCHAR(20)  NOT NULL,                      -- LOGIN/LOGOUT/CREATE/UPDATE/DELETE/VIEW
    resource_type VARCHAR(100),                               -- 접근 메뉴/리소스 유형
    resource_id   VARCHAR(50),                                -- 대상 리소스 ID (LOT ID 등)
    ip_address    VARCHAR(45),                                -- IPv4/IPv6
    user_agent    VARCHAR(200),
    result        VARCHAR(10)  DEFAULT 'SUCCESS',             -- SUCCESS/FAIL
    created_at    TIMESTAMP    NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_act_action CHECK (
        action_type IN ('LOGIN','LOGOUT','CREATE','UPDATE','DELETE','VIEW')
    )
);
CREATE INDEX IF NOT EXISTS idx_activity_user_time ON user_activity_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_action    ON user_activity_log(action_type);

-- =====================================================================
-- 7. ai_agent_log (AI Agent 질의 로그) — 기획서 8.2 / S-06
-- =====================================================================
CREATE TABLE IF NOT EXISTS ai_agent_log (
    log_id         BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id        BIGINT      REFERENCES users(user_id) ON DELETE SET NULL,
    agent_type     VARCHAR(20) NOT NULL,                      -- INTAKE/SHIPPING
                                                             -- (기획서 §8.6 원문: RAW_INTAKE/PACKAGING_SHIPPING/INTEGRATED
                                                             --  → CLAUDE.md RAG Agent 정의에 맞춰 INTAKE/SHIPPING으로 단순화.
                                                             --  INTEGRATED 사용 시 CHECK 제약 완화 및 컬럼 주석 업데이트 필요)
    query_text     TEXT        NOT NULL,                      -- 사용자 질의
    response_text  TEXT,                                      -- AI 응답
    sources        JSONB       DEFAULT '[]'::jsonb,           -- 참조 RAG 문서 목록
    needs_approval BOOLEAN     NOT NULL DEFAULT FALSE,        -- 운영자 승인 필요 여부
    latency_ms     INTEGER,                                   -- 응답 지연(ms)
    feedback       VARCHAR(10),                               -- GOOD/BAD/NULL
    created_at     TIMESTAMP   NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_agent_type CHECK (
        agent_type IN ('INTAKE','SHIPPING')
    )
);
CREATE INDEX IF NOT EXISTS idx_agent_user_time ON ai_agent_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_type      ON ai_agent_log(agent_type);

-- =====================================================================
-- 8. notification_config (알림 설정) — 기획서 8.3
-- =====================================================================
CREATE TABLE IF NOT EXISTS notification_config (
    config_id         BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    notification_type VARCHAR(20) NOT NULL,                   -- ALARM/KPI/SYSTEM
    channel           VARCHAR(10) NOT NULL,                   -- SMS/EMAIL/PUSH
    recipients        JSONB       NOT NULL DEFAULT '[]'::jsonb,-- 수신자 목록(번호/메일/토큰)
    is_active         BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMP   NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP   NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_noti_type    CHECK (notification_type IN ('ALARM','KPI','SYSTEM')),
    CONSTRAINT chk_noti_channel CHECK (channel IN ('SMS','EMAIL','PUSH'))
);
CREATE INDEX IF NOT EXISTS idx_noti_config_type ON notification_config(notification_type, is_active);

-- =====================================================================
-- 9. notification_log (알림 발송 이력) — 기획서 8.3 / S-09
-- =====================================================================
CREATE TABLE IF NOT EXISTS notification_log (
    log_id    BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    config_id BIGINT      REFERENCES notification_config(config_id) ON DELETE SET NULL,
    sent_at   TIMESTAMP   NOT NULL DEFAULT NOW(),
    recipient VARCHAR(150) NOT NULL,                          -- 실제 수신처
    channel   VARCHAR(10) NOT NULL,                           -- SMS/EMAIL/PUSH
    message   TEXT,
    status    VARCHAR(10) NOT NULL DEFAULT 'PENDING',         -- SENT/FAILED/PENDING

    CONSTRAINT chk_notilog_status  CHECK (status IN ('SENT','FAILED','PENDING')),
    CONSTRAINT chk_notilog_channel CHECK (channel IN ('SMS','EMAIL','PUSH'))
);
CREATE INDEX IF NOT EXISTS idx_notilog_sent   ON notification_log(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_notilog_config ON notification_log(config_id);

-- =====================================================================
-- 10. edge_device_config (Edge Collector 설정) — 기획서 8.4 / S-10
-- =====================================================================
CREATE TABLE IF NOT EXISTS edge_device_config (
    device_id   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_name VARCHAR(100) NOT NULL,
    protocol    VARCHAR(10)  NOT NULL,                        -- OPC_UA/MODBUS
    host        VARCHAR(100) NOT NULL,                        -- IP 또는 호스트명
    port        INTEGER      NOT NULL,                        -- OPC-UA 4840 / Modbus 502
    timeout_sec INTEGER      DEFAULT 10,                      -- 연결 타임아웃
    retry_count INTEGER      DEFAULT 3,                       -- 재연결 시도 횟수
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    last_seen   TIMESTAMP,                                    -- 마지막 수신 시각(연결 상태 판정)
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_edge_protocol CHECK (protocol IN ('OPC_UA','MODBUS'))
);
CREATE INDEX IF NOT EXISTS idx_edge_active ON edge_device_config(is_active);

-- =====================================================================
-- 11. sensor_mapping (센서 매핑) — 기획서 8.4 / S-11
-- =====================================================================
CREATE TABLE IF NOT EXISTS sensor_mapping (
    mapping_id   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id    BIGINT       NOT NULL REFERENCES edge_device_config(device_id) ON DELETE CASCADE,
    sensor_id    VARCHAR(50)  NOT NULL,                       -- SENSOR-PROC03-TEMP-01
    sensor_name  VARCHAR(100),
    data_field   VARCHAR(50)  NOT NULL,                       -- DB 저장 컬럼명(pickling_temp 등)
    unit         VARCHAR(20),                                 -- 측정 단위(°C, %, pH)
    scale_factor NUMERIC(10,4) DEFAULT 1.0,                   -- 보정 계수(곱)
    offset_value NUMERIC(10,4) DEFAULT 0.0,                   -- 보정 오프셋(합)
    interval_sec INTEGER       DEFAULT 600,                   -- 수집 주기(초)
    created_at   TIMESTAMP     NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_sensor_device UNIQUE (device_id, sensor_id)
);
CREATE INDEX IF NOT EXISTS idx_sensor_device ON sensor_mapping(device_id);

-- =====================================================================
-- 12. batch_schedule (배치 스케줄) — 기획서 8.4 / S-12
-- =====================================================================
CREATE TABLE IF NOT EXISTS batch_schedule (
    schedule_id     BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_name        VARCHAR(50) UNIQUE NOT NULL,              -- ETL_SENSOR_DATA 등
    cron_expression VARCHAR(50) NOT NULL,                     -- */10 * * * *
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    last_run        TIMESTAMP,
    next_run        TIMESTAMP,
    last_status     VARCHAR(10),                              -- SUCCESS/FAIL/RUNNING
    description     VARCHAR(200),
    created_at      TIMESTAMP   NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_batch_active ON batch_schedule(is_active);

-- 기본 배치 스케줄 시드 (기획서 8.4 S-12)
INSERT INTO batch_schedule (job_name, cron_expression, description) VALUES
    ('ETL_SENSOR_DATA',     '*/10 * * * *', '10분마다 센서 데이터 ETL'),
    ('ETL_LOT_INTEGRATION', '0 * * * *',    '1시간마다 LOT 통합 데이터 갱신'),
    ('KPI_HOURLY_CALC',     '5 * * * *',    '1시간마다 시간당 생산량 계산'),
    ('KPI_DAILY_REPORT',    '0 18 * * *',   '매일 18:00 일일 KPI 리포트 생성/발송'),
    ('KPI_WEEKLY_REPORT',   '0 8 * * 1',    '매주 월요일 08:00 주간 리포트 생성'),
    ('KPI_MONTHLY_REPORT',  '0 7 1 * *',    '매월 1일 07:00 월간 리포트 생성'),
    ('DATA_QUALITY_CHECK',  '0 2 * * *',    '매일 02:00 데이터 품질 검증'),
    -- 보존 정책(기획서 §8.2): system_log=3개월, ai_agent_log=1년, user_activity_log=6개월
    ('LOG_CLEANUP',         '0 3 * * *',    '매일 03:00 보존기간 초과 로그 삭제 — system_log 3개월 / ai_agent_log 1년 / user_activity_log 6개월'),
    ('DB_BACKUP',           '0 1 * * *',    '매일 01:00 PostgreSQL 백업'),
    ('S3_ARCHIVE',          '0 0 1 * *',    '매월 1일 00:00 Raw 데이터 S3 이관')
ON CONFLICT (job_name) DO NOTHING;

-- =====================================================================
-- 끝 — 12개 테이블 (RBAC 4 / 로그 3 / 알림 2 / 시스템설정 3)
-- =====================================================================
