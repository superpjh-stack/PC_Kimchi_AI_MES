-- =====================================================================
-- 꽃순이김치 제조AI 스마트공장 MES — 숙성발효관리 모듈 스키마
-- 프로젝트: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션
-- DBMS    : PostgreSQL 15+
-- 담당    : 숙성발효관리 (발효 LOT / ML 예측 / 이상발효 알림 / 최적조건 추천)
--
-- 기존 db/init.sql 의 LOT FK 체인과 호환되도록 설계한다.
--   raw_material_lot(intake)
--        -> salting_lot
--        -> fermentation_lot   ← 본 모듈이 신규 마스터 정의
--        -> packaging_lot
--        -> shipping_lot
--
-- 참조(재정의 금지) 테이블:
--   process_result            : 공정별 실적 (process_code='PROC07' 가 발효 공정)
--   fermentation_timeseries   : 센서 시계열 (lot_id, recorded_at, temperature,
--                               acidity, salinity, ph, dissolved_oxygen)
--
-- 발효 LOT ID 형식: FE-YYYYMMDD-NNN
--
-- AI 성능 목표 (CLAUDE.md §AI 모듈):
--   발효 품질 예측 정확도 >= 80% / 완료 시점 MAE <= 2h / 이상탐지 >= 85%
--   품질 리스크 재현율 >= 85% / R^2 >= 0.85
-- =====================================================================

-- ---------------------------------------------------------------------
-- 센서 임계값 참조 (애플리케이션 상수와 동기화 — api_fermentation_router.py)
--   TEMP_WARNING  = 20.0 ℃   TEMP_CRITICAL  = 25.0 ℃
--   ACIDITY 정상 범위 0.40 ~ 0.90 %
--   SALINITY 정상 범위 1.8 ~ 3.2 %
-- 임계값 비교/알림 생성은 API/ETL 계층에서 수행하고, 본 스키마는 결과만 보존한다.
-- ---------------------------------------------------------------------

-- =====================================================================
-- 1. fermentation_lot (발효 LOT 마스터)
--    절임 LOT(source_lot_id)을 입력으로 받아 발효 산출 LOT 단위로 관리한다.
-- =====================================================================
CREATE TABLE IF NOT EXISTS fermentation_lot (
    lot_id                   VARCHAR(30)  PRIMARY KEY,             -- FE-YYYYMMDD-NNN
    source_lot_id            VARCHAR(30),                          -- salting_lot 연결(추적 체인)
    start_time               TIMESTAMPTZ  NOT NULL,                -- 발효 시작
    planned_end_time         TIMESTAMPTZ,                          -- 계획 완료 시각
    actual_end_time          TIMESTAMPTZ,                          -- 실제 완료 시각
    fermentation_temp_target NUMERIC(5,2),                         -- 목표 온도 ℃
    room_id                  VARCHAR(20),                          -- 발효실 ID
    lot_status               VARCHAR(20)  DEFAULT 'FERMENTING',    -- FERMENTING/COMPLETED/ABNORMAL/CANCELLED
    input_qty_kg             NUMERIC(10,2),                        -- 투입 수량(kg)
    output_qty_kg            NUMERIC(10,2),                        -- 산출 수량(kg)
    created_at               TIMESTAMPTZ  DEFAULT NOW(),

    CONSTRAINT chk_fl_status CHECK (
        lot_status IN ('FERMENTING','COMPLETED','ABNORMAL','CANCELLED')
    ),
    CONSTRAINT chk_fl_qty CHECK (
        (input_qty_kg  IS NULL OR input_qty_kg  >= 0) AND
        (output_qty_kg IS NULL OR output_qty_kg >= 0)
    ),
    CONSTRAINT chk_fl_time CHECK (
        actual_end_time IS NULL OR actual_end_time >= start_time
    )
);
-- LOT 추적 / 상태별 현황 / 시작시각 정렬 조회
CREATE INDEX IF NOT EXISTS idx_fl_source_lot ON fermentation_lot(source_lot_id);
CREATE INDEX IF NOT EXISTS idx_fl_status     ON fermentation_lot(lot_status);
CREATE INDEX IF NOT EXISTS idx_fl_start      ON fermentation_lot(start_time DESC);
COMMENT ON TABLE  fermentation_lot           IS '발효 LOT 마스터 (절임 LOT → 발효 LOT 추적 체인)';
COMMENT ON COLUMN fermentation_lot.lot_id    IS '발효 LOT ID 형식 FE-YYYYMMDD-NNN';
COMMENT ON COLUMN fermentation_lot.lot_status IS 'FERMENTING/COMPLETED/ABNORMAL/CANCELLED';

-- =====================================================================
-- 2. fermentation_quality_prediction (ML 예측 결과)
--    AI Server(XGBoost/RF/SVR/LSTM) → MES 로 예측 결과를 적재한다.
--    모델별로 채워지는 컬럼이 다르다(분류/회귀/시계열). NULL 허용.
-- =====================================================================
CREATE TABLE IF NOT EXISTS fermentation_quality_prediction (
    prediction_id             BIGSERIAL    PRIMARY KEY,
    lot_id                    VARCHAR(30)  NOT NULL
                               REFERENCES fermentation_lot(lot_id) ON DELETE CASCADE,
    model_type                VARCHAR(20)  NOT NULL,               -- XGBOOST/RANDOM_FOREST/SVR/LSTM
    predicted_at              TIMESTAMPTZ  DEFAULT NOW(),
    -- XGBoost / RandomForest 분류 결과
    quality_class             VARCHAR(10),                         -- NORMAL/CAUTION/ABNORMAL
    quality_score             NUMERIC(5,4),                        -- 0~1 확신도
    -- SVR 회귀 결과
    predicted_acidity         NUMERIC(5,3),                        -- 예측 산도
    predicted_ripeness        NUMERIC(5,3),                        -- 예측 숙성도
    -- LSTM 시계열 결과
    predicted_completion_time TIMESTAMPTZ,                         -- 발효 완료 예측 시각
    completion_mae_hours      NUMERIC(5,2),                        -- MAE(시간)
    -- 회귀 성능
    r2_score                  NUMERIC(5,4),                        -- R^2 점수
    -- SHAP 영향 요인 (JSON)
    shap_features             JSONB,                               -- {"temperature":0.32,"acidity":0.28,...}
    model_version             VARCHAR(20)  DEFAULT '1.0.0',

    CONSTRAINT chk_fqp_model CHECK (
        model_type IN ('XGBOOST','RANDOM_FOREST','SVR','LSTM')
    ),
    CONSTRAINT chk_fqp_class CHECK (
        quality_class IS NULL OR quality_class IN ('NORMAL','CAUTION','ABNORMAL')
    ),
    CONSTRAINT chk_fqp_score CHECK (
        quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)
    )
);
-- LOT별 최신 예측(모델별) / 모델별 성능 트렌드 조회
CREATE INDEX IF NOT EXISTS idx_fqp_lot_pred   ON fermentation_quality_prediction(lot_id, predicted_at DESC);
CREATE INDEX IF NOT EXISTS idx_fqp_model       ON fermentation_quality_prediction(model_type, predicted_at DESC);
CREATE INDEX IF NOT EXISTS idx_fqp_shap        ON fermentation_quality_prediction USING GIN (shap_features);
COMMENT ON TABLE  fermentation_quality_prediction IS '발효 품질 ML 예측 결과 (XGBoost/RF/SVR/LSTM + SHAP)';
COMMENT ON COLUMN fermentation_quality_prediction.shap_features IS 'SHAP 요인 기여도 JSON. 예) {"temperature":0.32,"acidity":0.28,"salinity":0.18}';

-- =====================================================================
-- 3. fermentation_anomaly_alert (이상발효 알림)
--    센서 임계값 초과/이탈, 센서 결측, 예측 이상등급 발생 시 적재한다.
-- =====================================================================
CREATE TABLE IF NOT EXISTS fermentation_anomaly_alert (
    alert_id        BIGSERIAL    PRIMARY KEY,
    lot_id          VARCHAR(30)  NOT NULL
                     REFERENCES fermentation_lot(lot_id) ON DELETE CASCADE,
    alert_type      VARCHAR(30)  NOT NULL,                  -- TEMP_HIGH/TEMP_LOW/ACIDITY_DRIFT/SALINITY_OOB/SENSOR_MISSING
    severity        VARCHAR(10)  NOT NULL,                  -- WARNING/CRITICAL
    detected_at     TIMESTAMPTZ  DEFAULT NOW(),
    sensor_value    NUMERIC(8,3),                           -- 탐지 시점 센서값
    threshold_value NUMERIC(8,3),                           -- 기준값
    message         TEXT         NOT NULL,
    is_resolved     BOOLEAN      DEFAULT FALSE,
    resolved_at     TIMESTAMPTZ,
    resolved_by     VARCHAR(50),
    action_taken    TEXT,

    CONSTRAINT chk_faa_type CHECK (
        alert_type IN ('TEMP_HIGH','TEMP_LOW','ACIDITY_DRIFT','SALINITY_OOB','SENSOR_MISSING')
    ),
    CONSTRAINT chk_faa_severity CHECK (severity IN ('WARNING','CRITICAL'))
);
-- 미해소 우선 / LOT별 / 심각도별 조회
CREATE INDEX IF NOT EXISTS idx_faa_open     ON fermentation_anomaly_alert(is_resolved, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_faa_lot      ON fermentation_anomaly_alert(lot_id);
CREATE INDEX IF NOT EXISTS idx_faa_severity ON fermentation_anomaly_alert(severity);
COMMENT ON TABLE fermentation_anomaly_alert IS '이상발효 알림 (임계값 이탈 / 센서 결측 / 이상등급)';

-- =====================================================================
-- 4. optimal_condition_recommendation (최적 절임 조건 추천)
--    SHAP/회귀 분석 기반으로 절임 LOT 단위 최적 조건을 추천한다.
-- =====================================================================
CREATE TABLE IF NOT EXISTS optimal_condition_recommendation (
    rec_id                  BIGSERIAL    PRIMARY KEY,
    source_lot_id           VARCHAR(30),                    -- 절임 LOT
    recommended_at          TIMESTAMPTZ  DEFAULT NOW(),
    -- 추천 조건
    rec_salt_density_pct    NUMERIC(5,2),                   -- 추천 염도 %
    rec_salt_temp_c         NUMERIC(5,2),                   -- 추천 절임 온도 ℃
    rec_salt_hours          NUMERIC(5,1),                   -- 추천 절임 시간 h
    rec_fermentation_temp_c NUMERIC(5,2),                   -- 추천 발효 온도 ℃
    confidence_score        NUMERIC(5,4),                   -- 추천 신뢰도 0~1
    basis_lot_count         INT,                            -- 학습 기반 LOT 수
    predicted_quality       VARCHAR(10),                    -- NORMAL/GOOD/EXCELLENT
    notes                   TEXT,

    CONSTRAINT chk_ocr_conf CHECK (
        confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)
    ),
    CONSTRAINT chk_ocr_quality CHECK (
        predicted_quality IS NULL OR predicted_quality IN ('NORMAL','GOOD','EXCELLENT')
    )
);
-- 최신 추천 조회 / 절임 LOT별 조회
CREATE INDEX IF NOT EXISTS idx_ocr_recommended ON optimal_condition_recommendation(recommended_at DESC);
CREATE INDEX IF NOT EXISTS idx_ocr_source_lot  ON optimal_condition_recommendation(source_lot_id);
COMMENT ON TABLE optimal_condition_recommendation IS '최적 절임/발효 조건 추천 (SHAP/회귀 분석 기반)';

-- =====================================================================
-- 시드 데이터 (개발/데모용) — 멱등성 보장(ON CONFLICT DO NOTHING)
--   기준일자: 2026-05-24
-- =====================================================================

-- ---- 5건 fermentation_lot (3 FERMENTING / 1 COMPLETED / 1 ABNORMAL) ----
INSERT INTO fermentation_lot
    (lot_id, source_lot_id, start_time, planned_end_time, actual_end_time,
     fermentation_temp_target, room_id, lot_status, input_qty_kg, output_qty_kg)
VALUES
    ('FE-20260524-001', 'SA-20260523-011', '2026-05-24 06:00:00+09', '2026-05-26 18:00:00+09', NULL,
     12.50, 'FR-01', 'FERMENTING', 1200.00, NULL),
    ('FE-20260524-002', 'SA-20260523-012', '2026-05-24 08:30:00+09', '2026-05-27 02:30:00+09', NULL,
     12.00, 'FR-02', 'FERMENTING', 980.00, NULL),
    ('FE-20260523-007', 'SA-20260522-009', '2026-05-23 22:00:00+09', '2026-05-26 10:00:00+09', NULL,
     13.00, 'FR-03', 'FERMENTING', 1450.00, NULL),
    ('FE-20260521-003', 'SA-20260520-004', '2026-05-21 07:00:00+09', '2026-05-23 19:00:00+09', '2026-05-23 18:20:00+09',
     12.50, 'FR-01', 'COMPLETED', 1100.00, 1062.00),
    ('FE-20260522-005', 'SA-20260521-006', '2026-05-22 09:00:00+09', '2026-05-24 21:00:00+09', NULL,
     12.50, 'FR-04', 'ABNORMAL', 1300.00, NULL)
ON CONFLICT (lot_id) DO NOTHING;

-- ---- 8건 fermentation_quality_prediction ----
-- FE-20260524-001: XGBoost(NORMAL) + SVR + LSTM
INSERT INTO fermentation_quality_prediction
    (lot_id, model_type, predicted_at, quality_class, quality_score,
     predicted_acidity, predicted_ripeness, predicted_completion_time,
     completion_mae_hours, r2_score, shap_features, model_version)
VALUES
    ('FE-20260524-001', 'XGBOOST', '2026-05-24 10:00:00+09', 'NORMAL', 0.9120,
     NULL, NULL, NULL, NULL, NULL,
     '{"temperature":0.34,"acidity":0.27,"salinity":0.17,"ph":0.13,"elapsed_hours":0.09}'::jsonb, '1.2.0'),
    ('FE-20260524-001', 'SVR', '2026-05-24 10:00:00+09', NULL, NULL,
     0.612, 0.745, NULL, NULL, 0.8740,
     NULL, '1.2.0'),
    ('FE-20260524-001', 'LSTM', '2026-05-24 10:00:00+09', NULL, NULL,
     NULL, NULL, '2026-05-26 17:10:00+09', 1.40, NULL,
     NULL, '1.2.0'),
    -- FE-20260524-002: XGBoost(CAUTION) + LSTM
    ('FE-20260524-002', 'XGBOOST', '2026-05-24 11:30:00+09', 'CAUTION', 0.7330,
     NULL, NULL, NULL, NULL, NULL,
     '{"temperature":0.41,"salinity":0.22,"acidity":0.19,"ph":0.11,"elapsed_hours":0.07}'::jsonb, '1.2.0'),
    ('FE-20260524-002', 'LSTM', '2026-05-24 11:30:00+09', NULL, NULL,
     NULL, NULL, '2026-05-27 04:05:00+09', 1.85, NULL,
     NULL, '1.2.0'),
    -- FE-20260523-007: XGBoost(NORMAL) + SVR
    ('FE-20260523-007', 'XGBOOST', '2026-05-24 09:15:00+09', 'NORMAL', 0.8650,
     NULL, NULL, NULL, NULL, NULL,
     '{"temperature":0.31,"acidity":0.30,"salinity":0.16,"ph":0.14,"elapsed_hours":0.09}'::jsonb, '1.2.0'),
    ('FE-20260523-007', 'SVR', '2026-05-24 09:15:00+09', NULL, NULL,
     0.588, 0.702, NULL, NULL, 0.8910,
     NULL, '1.2.0'),
    -- FE-20260522-005: XGBoost(ABNORMAL) — 이상발효
    ('FE-20260522-005', 'XGBOOST', '2026-05-24 07:40:00+09', 'ABNORMAL', 0.8870,
     NULL, NULL, NULL, NULL, NULL,
     '{"temperature":0.52,"acidity":0.21,"salinity":0.14,"ph":0.09,"elapsed_hours":0.04}'::jsonb, '1.2.0')
ON CONFLICT DO NOTHING;

-- ---- 4건 fermentation_anomaly_alert ----
INSERT INTO fermentation_anomaly_alert
    (lot_id, alert_type, severity, detected_at, sensor_value, threshold_value,
     message, is_resolved, resolved_at, resolved_by, action_taken)
VALUES
    ('FE-20260522-005', 'TEMP_HIGH', 'CRITICAL', '2026-05-24 07:35:00+09', 25.80, 25.00,
     '발효실 FR-04 온도 25.8℃ 초과 — 이상발효 위험. 냉각 조치 필요', FALSE, NULL, NULL, NULL),
    ('FE-20260522-005', 'ACIDITY_DRIFT', 'CRITICAL', '2026-05-24 07:38:00+09', 1.120, 0.900,
     '산도 1.12% 급상승 — 과발효 진행 중', FALSE, NULL, NULL, NULL),
    ('FE-20260524-002', 'TEMP_HIGH', 'WARNING', '2026-05-24 11:20:00+09', 21.30, 20.00,
     '발효실 FR-02 온도 21.3℃ 주의 임계 초과', FALSE, NULL, NULL, NULL),
    ('FE-20260523-007', 'SENSOR_MISSING', 'WARNING', '2026-05-23 23:40:00+09', NULL, NULL,
     'pH 센서 데이터 30분간 결측 — 센서 점검 필요', TRUE, '2026-05-24 00:15:00+09', 'kim.qc',
     '센서 케이블 재연결 후 정상화 확인')
ON CONFLICT DO NOTHING;

-- ---- 3건 optimal_condition_recommendation ----
INSERT INTO optimal_condition_recommendation
    (source_lot_id, recommended_at, rec_salt_density_pct, rec_salt_temp_c,
     rec_salt_hours, rec_fermentation_temp_c, confidence_score, basis_lot_count,
     predicted_quality, notes)
VALUES
    ('SA-20260523-011', '2026-05-24 10:05:00+09', 2.80, 11.50, 8.0, 12.50, 0.9210, 142,
     'EXCELLENT', '봄철 배추 함수율 높음 — 염도 2.8%, 절임시간 8h 권장'),
    ('SA-20260523-012', '2026-05-24 11:35:00+09', 3.00, 12.00, 7.5, 12.00, 0.8650, 142,
     'GOOD', '외관등급 B — 염도 소폭 상향 및 발효온도 12.0℃ 권장'),
    ('SA-20260522-009', '2026-05-24 09:20:00+09', 2.70, 11.00, 8.5, 13.00, 0.8980, 138,
     'EXCELLENT', '대형 배추 — 절임시간 8.5h 로 충분한 염투과 확보 권장')
ON CONFLICT DO NOTHING;

-- =====================================================================
-- 검증 쿼리 (참고)
--   SELECT lot_status, COUNT(*) FROM fermentation_lot GROUP BY lot_status;
--   SELECT model_type, COUNT(*) FROM fermentation_quality_prediction GROUP BY model_type;
--   SELECT severity, is_resolved, COUNT(*) FROM fermentation_anomaly_alert
--     GROUP BY severity, is_resolved;
-- =====================================================================
