-- ============================================================================
-- 꽃순이김치 제조AI MES — 데이터관리 모듈 스키마 (Data Management)
-- Project: SF26179540 / 로뎀솔루션 주식회사 / 2026
-- 담당 모듈: 데이터관리 (데이터통합관리 / 데이터조회 / 데이터시각화 /
--           데이터다운로드 / AI학습 데이터관리)
-- 참조: pm3-process-data-kpi-system.plan.md §5 (데이터관리 상세 명세)
--
-- DDL 생성 순서 (의존성 없음 — 데이터관리 전용 메타/운영 테이블):
--   1. pipeline_status      파이프라인 단계 상태
--   2. etl_log              ETL 작업 이력
--   3. edge_device_status   Edge Collector 장치 상태
--   4. ai_dataset           AI 학습 데이터셋
--   5. data_label           라벨링 데이터
--   6. data_quality_check   DQ 검증 결과
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. pipeline_status — 데이터 파이프라인 단계별 상태 (화면 D-01)
--    Edge → MQTT → Kafka → DataLake → ETL → PostgreSQL 6단계 상태 표시
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS pipeline_status CASCADE;
CREATE TABLE pipeline_status (
    id                BIGSERIAL    PRIMARY KEY,
    stage             VARCHAR(20)  NOT NULL
        CHECK (stage IN ('EDGE','MQTT','KAFKA','DATALAKE','ETL','POSTGRESQL')),
    status            VARCHAR(10)  NOT NULL DEFAULT 'OK'
        CHECK (status IN ('OK','WARNING','ERROR')),
    last_updated      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    message           TEXT,                       -- 상태 부가 설명 (예: "처리 지연 8s")
    records_per_sec   DECIMAL(12,2) DEFAULT 0,    -- 단계별 처리율 (msg/s 또는 rec/s)
    created_at        TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE  pipeline_status              IS '데이터 파이프라인 6단계 실시간 상태';
COMMENT ON COLUMN pipeline_status.stage        IS 'EDGE/MQTT/KAFKA/DATALAKE/ETL/POSTGRESQL';
COMMENT ON COLUMN pipeline_status.status       IS 'OK/WARNING/ERROR';
COMMENT ON COLUMN pipeline_status.records_per_sec IS '초당 처리 메시지/레코드 수';

CREATE INDEX idx_pipeline_status_stage ON pipeline_status(stage);

-- 6개 단계 초기 시드 (각 단계 1행, last_updated 갱신 방식)
INSERT INTO pipeline_status (stage, status, message, records_per_sec) VALUES
    ('EDGE',       'OK', '3/3 장치 연결됨',  3),
    ('MQTT',       'OK', '스트리밍 정상',    42),
    ('KAFKA',      'OK', '스트리밍 정상',    42),
    ('DATALAKE',   'OK', 'Raw Zone 저장중 (지연 8s)', 40),
    ('ETL',        'OK', '배치 실행중',      0),
    ('POSTGRESQL', 'OK', 'DB 응답 45ms',     0)
ON CONFLICT DO NOTHING;


-- ----------------------------------------------------------------------------
-- 2. etl_log — ETL 작업 실행 이력 (화면 D-03)
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS etl_log CASCADE;
CREATE TABLE etl_log (
    id                 BIGSERIAL    PRIMARY KEY,
    job_name           VARCHAR(100) NOT NULL,     -- 발효센서 ETL, LOT 데이터 ETL 등
    start_time         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    end_time           TIMESTAMPTZ,
    status             VARCHAR(20)  NOT NULL DEFAULT 'RUNNING'
        CHECK (status IN ('RUNNING','SUCCESS','FAILED','WARNING')),
    records_processed  INTEGER      DEFAULT 0,
    error_message      TEXT,                      -- 실패 시 오류 메시지
    created_at         TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE  etl_log                   IS 'ETL 배치 작업 실행 이력 및 오류 로그';
COMMENT ON COLUMN etl_log.records_processed IS '처리 레코드 건수';

CREATE INDEX idx_etl_log_start_time ON etl_log(start_time DESC);
CREATE INDEX idx_etl_log_status     ON etl_log(status);


-- ----------------------------------------------------------------------------
-- 3. edge_device_status — Edge Collector 장치 연결 상태 (화면 D-02)
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS edge_device_status CASCADE;
CREATE TABLE edge_device_status (
    id              BIGSERIAL    PRIMARY KEY,
    device_id       VARCHAR(30)  UNIQUE NOT NULL, -- GW-001, PAD-001 등
    device_name     VARCHAR(100) NOT NULL,        -- AI Data Gateway, SmartPad #1 (입고)
    protocol        VARCHAR(20)  NOT NULL
        CHECK (protocol IN ('OPC_UA','MODBUS','MQTT')),
    ip_address      VARCHAR(45),                  -- IPv4/IPv6
    last_heartbeat  TIMESTAMPTZ,                  -- 마지막 수신 시각
    is_connected    BOOLEAN      NOT NULL DEFAULT FALSE,
    records_today   INTEGER      DEFAULT 0,       -- 금일 수집 건수
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE  edge_device_status          IS 'Edge Collector / SmartPad 장치 연결 상태';
COMMENT ON COLUMN edge_device_status.protocol IS 'OPC_UA/MODBUS/MQTT';

CREATE INDEX idx_edge_device_connected ON edge_device_status(is_connected);

-- 장치 시드 (목업 D-02 기준)
INSERT INTO edge_device_status
    (device_id, device_name, protocol, ip_address, last_heartbeat, is_connected, records_today)
VALUES
    ('GW-001',  'AI Data Gateway',      'OPC_UA', '192.168.10.10', NOW(), TRUE, 28470),
    ('PAD-001', 'SmartPad #1 (입고)',   'MQTT',   '192.168.10.21', NOW(), TRUE, 156),
    ('PAD-002', 'SmartPad #2 (발효)',   'MQTT',   '192.168.10.22', NOW(), TRUE, 312),
    ('PAD-003', 'SmartPad #3 (출하)',   'MQTT',   '192.168.10.23', NOW(), TRUE, 89)
ON CONFLICT (device_id) DO NOTHING;


-- ----------------------------------------------------------------------------
-- 4. ai_dataset — AI 학습 데이터셋 (화면 D-09)
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS ai_dataset CASCADE;
CREATE TABLE ai_dataset (
    id              BIGSERIAL    PRIMARY KEY,
    dataset_name    VARCHAR(100) UNIQUE NOT NULL, -- 발효품질학습셋_v3 등
    data_type       VARCHAR(20)  NOT NULL
        CHECK (data_type IN ('FERMENTATION','INTAKE','QUALITY')),
    start_date      DATE,                         -- 데이터 수집 시작일
    end_date        DATE,                         -- 데이터 수집 종료일
    total_records   INTEGER      DEFAULT 0,       -- 전체 샘플 수
    labeled_count   INTEGER      DEFAULT 0,       -- 라벨링 완료 건수
    is_finalized    BOOLEAN      NOT NULL DEFAULT FALSE, -- 학습셋 확정 여부
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE  ai_dataset               IS 'AI 학습 데이터셋 (확정 시 AI Engine에 REST 제공)';
COMMENT ON COLUMN ai_dataset.data_type     IS 'FERMENTATION/INTAKE/QUALITY';
COMMENT ON COLUMN ai_dataset.is_finalized  IS '관리자 승인 후 학습셋 확정 여부';

CREATE INDEX idx_ai_dataset_type_final ON ai_dataset(data_type, is_finalized);

-- 데이터셋 시드 (목업 D-09 기준)
INSERT INTO ai_dataset
    (dataset_name, data_type, start_date, end_date, total_records, labeled_count, is_finalized)
VALUES
    ('발효품질학습셋_v3',  'FERMENTATION', '2026-01-01', '2026-05-20', 2847, 2847, TRUE),
    ('발효완료예측셋_v2',  'FERMENTATION', '2026-01-01', '2026-05-15', 1523, 1523, TRUE),
    ('이상발효탐지셋_v1',  'FERMENTATION', '2026-02-01', '2026-05-23', 876,  631,  FALSE),
    ('입고품질분류셋_v2',  'INTAKE',       '2026-01-01', '2026-04-30', 1204, 1204, TRUE),
    ('원재료불량탐지셋_v1','INTAKE',       '2026-01-01', '2026-04-15', 642,  642,  TRUE),
    ('포장중량예측셋_v1',  'QUALITY',      '2026-01-01', '2026-05-01', 2105, 2105, TRUE),
    ('절임조건최적화셋_v2','FERMENTATION', '2026-02-01', '2026-05-23', 934,  542,  FALSE),
    ('SHAP분석기준셋_v1',  'QUALITY',      '2026-01-01', '2026-05-10', 1847, 1847, TRUE)
ON CONFLICT (dataset_name) DO NOTHING;


-- ----------------------------------------------------------------------------
-- 5. data_label — 라벨링 데이터 (화면 D-10)
--    워크플로우: 미라벨링 → 라벨링(품질담당자) → 검토/승인(관리자)
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS data_label CASCADE;
CREATE TABLE data_label (
    id            BIGSERIAL    PRIMARY KEY,
    lot_id        VARCHAR(50)  NOT NULL,         -- 라벨 대상 LOT
    data_type     VARCHAR(20)  NOT NULL
        CHECK (data_type IN ('FERMENTATION','INTAKE','QUALITY')),
    label_value   VARCHAR(50)  NOT NULL,         -- 정상/주의/이상, 합격/불합격, 발효/절임/포장/기타
    labeled_by    VARCHAR(50),                   -- 라벨 작업자 (품질담당자)
    reviewed_by   VARCHAR(50),                   -- 검토/승인자 (관리자)
    is_approved   BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    approved_at   TIMESTAMPTZ
);
COMMENT ON TABLE  data_label             IS 'AI 학습용 라벨링 데이터 (검토/승인 워크플로우)';
COMMENT ON COLUMN data_label.label_value IS '품질등급/합격여부/불량원인 등 라벨 값';
COMMENT ON COLUMN data_label.is_approved IS '관리자 승인 시 TRUE';

CREATE INDEX idx_data_label_lot       ON data_label(lot_id);
CREATE INDEX idx_data_label_type      ON data_label(data_type);
CREATE INDEX idx_data_label_approved  ON data_label(is_approved);

-- 미승인 라벨 시드 (승인 대기 목록 표출용)
INSERT INTO data_label (lot_id, data_type, label_value, labeled_by, is_approved) VALUES
    ('LOT-20260521-003', 'FERMENTATION', '주의', '박품질', FALSE),
    ('LOT-20260522-005', 'FERMENTATION', '정상', '박품질', FALSE),
    ('LOT-20260523-001', 'INTAKE',       '합격', '박품질', FALSE)
ON CONFLICT DO NOTHING;


-- ----------------------------------------------------------------------------
-- 6. data_quality_check — 데이터 품질 검증 결과 (화면 D-11)
--    검증 규칙 DQ-001 ~ DQ-007 (plan §5.3)
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS data_quality_check CASCADE;
CREATE TABLE data_quality_check (
    id            BIGSERIAL    PRIMARY KEY,
    check_date    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    rule_id       VARCHAR(20)  NOT NULL,         -- DQ-001 ~ DQ-007
    target_table  VARCHAR(100) NOT NULL,         -- 검증 대상 테이블
    check_result  VARCHAR(10)  NOT NULL
        CHECK (check_result IN ('PASS','FAIL','WARNING')),
    issue_count   INTEGER      DEFAULT 0,        -- 발견된 이상 건수
    details       JSONB        DEFAULT '{}',     -- 규칙명/임계값/샘플 등 상세
    created_at    TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE  data_quality_check              IS '데이터 품질(DQ) 검증 규칙 실행 결과';
COMMENT ON COLUMN data_quality_check.rule_id      IS 'DQ-001~DQ-007 (센서범위/결측/LOT연결/시간역전/중복/공정순서/무신호)';
COMMENT ON COLUMN data_quality_check.check_result IS 'PASS/FAIL/WARNING';
COMMENT ON COLUMN data_quality_check.details      IS '규칙 상세 결과 (JSONB)';

CREATE INDEX idx_dq_check_date ON data_quality_check(check_date DESC);
CREATE INDEX idx_dq_rule       ON data_quality_check(rule_id);

-- 최근 DQ 검증 결과 시드 (7개 규칙)
INSERT INTO data_quality_check (rule_id, target_table, check_result, issue_count, details) VALUES
    ('DQ-001', 'fermentation_timeseries', 'WARNING', 3,
        '{"rule":"센서 값 범위 초과","method":"IQR","action":"플래그 처리"}'),
    ('DQ-002', 'fermentation_timeseries', 'PASS',    0,
        '{"rule":"결측값 비율 > 5%","missing_ratio":0.012}'),
    ('DQ-003', 'salting_process',         'PASS',    0,
        '{"rule":"LOT 연결 끊김","method":"FK 검증"}'),
    ('DQ-004', 'fermentation_timeseries', 'PASS',    0,
        '{"rule":"시계열 시간 역전","method":"Timestamp 정렬"}'),
    ('DQ-005', 'fermentation_timeseries', 'WARNING', 5,
        '{"rule":"중복 레코드","method":"LOT+Timestamp","action":"중복 제거"}'),
    ('DQ-006', 'shipping',                'PASS',    0,
        '{"rule":"공정 순서 이상","method":"LOT 기반 순서 검증"}'),
    ('DQ-007', 'edge_device_status',      'PASS',    0,
        '{"rule":"센서 무신호 30분","method":"마지막 수신 시간"}')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 끝 — 6개 테이블 (pipeline_status, etl_log, edge_device_status,
--      ai_dataset, data_label, data_quality_check)
-- ============================================================================
