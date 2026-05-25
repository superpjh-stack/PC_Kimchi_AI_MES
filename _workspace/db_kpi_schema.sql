-- =============================================================================
-- 꽃순이김치 제조AI MES — KPI관리 모듈 스키마 (PostgreSQL)
-- Project: SF26179540  |  Module: KPI관리 (K-01 ~ K-08)
-- 참조: docs/01-plan/features/pm3-process-data-kpi-system.plan.md (섹션 6)
--
-- 핵심 KPI 계산 공식
--   시간당 생산량 = 월 포장완료kg / (월 생산일수 × 일 근무시간)   목표 3,000 kg/h
--   완제품 불량률(%) = (불량kg / 총생산kg) × 100                목표 1.0%
--   색상코딩: >=100% 초록, 90~99% 노랑, 70~89% 주황, <70% 빨강
--   (불량률 KPI는 역산 — 낮을수록 달성)
--
-- 생성 순서: kpi_target → kpi_alert_config → kpi_report → kpi_daily_summary
--   (기존 production_kpi 테이블은 db-schema-design 스킬에서 정의됨, 본 스키마와 병행 사용)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. kpi_target — KPI 목표값 (유효기간 기반 버전 관리)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kpi_target (
    id            BIGSERIAL    PRIMARY KEY,
    kpi_type      VARCHAR(40)  NOT NULL,   -- PRODUCTION/DEFECT/FERMENTATION_ACCURACY/FERMENTATION_MAE/EDGE_UPTIME
    target_value  DECIMAL(12,4) NOT NULL,  -- 목표값 (예: 3000.0 kg/h, 1.0 %, 0.80, 2.0 h, 99.0 %)
    unit          VARCHAR(20),             -- kg/h, %, 점수, 시간 등
    higher_is_better BOOLEAN   NOT NULL DEFAULT TRUE,  -- DEFECT/FERMENTATION_MAE 는 FALSE
    baseline_value DECIMAL(12,4),          -- 기준값 (예: PRODUCTION 2750, DEFECT 1.5)
    valid_from    DATE         NOT NULL DEFAULT CURRENT_DATE,
    valid_to      DATE,                    -- NULL = 현행
    created_by    VARCHAR(50),
    created_at    TIMESTAMPTZ  DEFAULT NOW(),
    CONSTRAINT chk_kpi_target_type CHECK (
        kpi_type IN ('PRODUCTION','DEFECT','FERMENTATION_ACCURACY','FERMENTATION_MAE','EDGE_UPTIME')
    )
);

-- 인덱스: (kpi_type, valid_from) — 특정 KPI의 유효 목표값 조회
CREATE INDEX IF NOT EXISTS idx_kpi_target_type_from
    ON kpi_target(kpi_type, valid_from DESC);

-- -----------------------------------------------------------------------------
-- 2. kpi_alert_config — KPI 알림 임계값 설정 (K-07)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kpi_alert_config (
    id                BIGSERIAL    PRIMARY KEY,
    kpi_type          VARCHAR(40)  NOT NULL UNIQUE,
    warning_threshold DECIMAL(12,4) NOT NULL,  -- 경고 임계값
    critical_threshold DECIMAL(12,4) NOT NULL, -- 위험 임계값
    alert_channels    VARCHAR(20)[] NOT NULL DEFAULT ARRAY['DISPLAY']::VARCHAR[],  -- {SMS,EMAIL,DISPLAY}
    is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
    updated_by        VARCHAR(50),
    updated_at        TIMESTAMPTZ  DEFAULT NOW(),
    CONSTRAINT chk_kpi_alert_type CHECK (
        kpi_type IN ('PRODUCTION','DEFECT','FERMENTATION_ACCURACY','FERMENTATION_MAE','EDGE_UPTIME')
    )
);

CREATE INDEX IF NOT EXISTS idx_kpi_alert_active
    ON kpi_alert_config(is_active);

-- -----------------------------------------------------------------------------
-- 3. kpi_report — KPI 리포트 생성 이력 (K-08)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kpi_report (
    id            BIGSERIAL    PRIMARY KEY,
    report_type   VARCHAR(20)  NOT NULL,   -- DAILY/WEEKLY/MONTHLY/CUSTOM
    period_start  DATE         NOT NULL,
    period_end    DATE         NOT NULL,
    file_path     VARCHAR(500),            -- 생성된 리포트 파일 경로 (PDF/Excel)
    file_format   VARCHAR(10)  DEFAULT 'PDF', -- PDF/XLSX
    status        VARCHAR(20)  DEFAULT 'COMPLETED', -- GENERATING/COMPLETED/FAILED
    generated_at  TIMESTAMPTZ  DEFAULT NOW(),
    generated_by  VARCHAR(50),
    CONSTRAINT chk_kpi_report_type CHECK (
        report_type IN ('DAILY','WEEKLY','MONTHLY','CUSTOM')
    ),
    CONSTRAINT chk_kpi_report_period CHECK (period_end >= period_start)
);

CREATE INDEX IF NOT EXISTS idx_kpi_report_generated
    ON kpi_report(generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_kpi_report_type
    ON kpi_report(report_type, period_start DESC);

-- -----------------------------------------------------------------------------
-- 4. kpi_daily_summary — 일별 KPI 집계 캐시 (조회 성능 최적화)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kpi_daily_summary (
    id                     BIGSERIAL     PRIMARY KEY,
    kpi_date               DATE          NOT NULL UNIQUE,
    hourly_production_kg   DECIMAL(10,2),  -- 시간당 생산량 (kg/h)        목표 3,000
    defect_rate            DECIMAL(6,4),   -- 완제품 불량률 (%)           목표 1.0
    fermentation_accuracy  DECIMAL(5,4),   -- 발효 품질 예측 정확도        목표 ≥0.80
    fermentation_mae       DECIMAL(6,2),   -- 발효 완료 예측 MAE (시간)    목표 ≤2.0
    edge_uptime            DECIMAL(5,2),   -- Edge Collector 가동률 (%)    목표 ≥99.0
    lot_traceability_rate  DECIMAL(5,2),   -- LOT 추적가능성 (%)           목표 100.0
    total_production_kg    DECIMAL(12,2),  -- 일 총 포장완료 수량 (집계 원천)
    defect_kg              DECIMAL(12,2),  -- 일 불량 수량 (집계 원천)
    working_hours          DECIMAL(5,2)  DEFAULT 8.0,  -- 일 근무시간
    created_at             TIMESTAMPTZ   DEFAULT NOW(),
    updated_at             TIMESTAMPTZ   DEFAULT NOW()
);

-- 인덱스: kpi_date DESC — 최근 일자 트렌드 조회
CREATE INDEX IF NOT EXISTS idx_kpi_daily_date
    ON kpi_daily_summary(kpi_date DESC);

-- =============================================================================
-- 초기 시드 데이터 (KPI 목표값 / 알림 임계값)
--   참조: 기획서 섹션 6.5 KPI 알림 임계값 설정
-- =============================================================================
INSERT INTO kpi_target (kpi_type, target_value, unit, higher_is_better, baseline_value, valid_from, created_by) VALUES
    ('PRODUCTION',            3000.0, 'kg/h',  TRUE,  2750.0, '2026-01-01', 'system'),
    ('DEFECT',                   1.0, '%',     FALSE,    1.5, '2026-01-01', 'system'),
    ('FERMENTATION_ACCURACY',   80.0, '%',    TRUE,    NULL, '2026-01-01', 'system'),
    -- ↑ kpi_daily_summary.fermentation_accuracy는 0~1 스케일 저장(DECIMAL(5,4)),
    --   API /summary/today 에서 *100 변환 후 이 목표(80.0%)와 비교함. 스케일 통일 필수.
    ('FERMENTATION_MAE',         2.0, '시간',  FALSE,   NULL, '2026-01-01', 'system'),
    ('EDGE_UPTIME',             99.0, '%',     TRUE,    NULL, '2026-01-01', 'system')
ON CONFLICT DO NOTHING;

INSERT INTO kpi_alert_config (kpi_type, warning_threshold, critical_threshold, alert_channels, is_active, updated_by) VALUES
    ('PRODUCTION',            2750.0, 2500.0, ARRAY['SMS','DISPLAY']::VARCHAR[], TRUE, 'system'),
    ('DEFECT',                   1.5,    2.0, ARRAY['SMS','DISPLAY']::VARCHAR[], TRUE, 'system'),
    ('FERMENTATION_ACCURACY',   75.0,   70.0, ARRAY['EMAIL']::VARCHAR[],         TRUE, 'system'),
    -- ↑ 단위 통일: kpi_target과 동일 % 스케일 (75.0% 경고 / 70.0% 위험)
    ('EDGE_UPTIME',             99.0,   95.0, ARRAY['SMS','EMAIL']::VARCHAR[],   TRUE, 'system'),
    -- FERMENTATION_MAE: 낮을수록 우수. 경고 > 2시간 / 위험 > 3시간 (기획서 §6.1 목표 ≤2h 기준)
    ('FERMENTATION_MAE',         2.0,    3.0, ARRAY['EMAIL']::VARCHAR[],         TRUE, 'system')
ON CONFLICT (kpi_type) DO NOTHING;
