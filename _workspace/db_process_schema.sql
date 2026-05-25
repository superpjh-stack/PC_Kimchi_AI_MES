-- =====================================================================
-- 꽃순이김치 제조AI 스마트공장 MES — 공정관리 모듈 스키마
-- 프로젝트: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션
-- DBMS    : PostgreSQL 15+
-- 담당    : 공정관리(공정실적 / 레시피 / 이상 알림)
--
-- 기존 db/init.sql 의 LOT FK 체인과 호환되도록 설계한다.
--   raw_material_intake(intake_lot_id)
--        -> salting_process(salting_lot_id)
--        -> fermentation_process(fermentation_lot_id)
--        -> packaging(packaging_lot_id)
--        -> shipping(shipping_lot_id)
--
-- 공정 코드(process_code) 체계 (기획서 7.3):
--   PROC01 입고/보관   PROC02 절단/전처리  PROC03 세척/절임
--   PROC04 세척/선별   PROC05 탈수         PROC06 혼합
--   PROC07 숙성/발효   PROC08 금속검출     PROC09 포장/출하
--
-- LOT 연결 규칙:
--   PROC01~PROC09 의 실적은 각 공정의 산출 LOT(lot_id) 단위로 기록한다.
--   물리 LOT 테이블이 존재하는 공정(PROC01/03/07/09)은 source_lot_id 가
--   상위 공정의 LOT(FK)와 연결되며, 중간 가공 LOT(절단/선별/탈수/혼합/금속검출)는
--   별도 마스터 테이블이 없으므로 lot_id 를 VARCHAR 로 보존하여 추적성을 유지한다.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 0. 공정 코드 참조용 ENUM 도메인 (선택적 — CHECK 제약으로 강제)
-- ---------------------------------------------------------------------
-- 공정 코드 9종을 CHECK 제약으로 검증한다.
--   PROC01~PROC09

-- =====================================================================
-- 1. process_result (공정 실적) — 9개 공정 공통 실적 테이블
--    공정별 세부 측정값은 details(JSONB)에 저장하고,
--    공통 핵심 필드(투입/산출/불량/작업자/시간)는 컬럼으로 정규화한다.
-- =====================================================================
CREATE TABLE IF NOT EXISTS process_result (
    result_id        BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    process_code     VARCHAR(10)  NOT NULL,                  -- PROC01~PROC09
    lot_id           VARCHAR(30)  NOT NULL,                  -- 해당 공정 산출 LOT
    source_lot_id    VARCHAR(30),                            -- 직전 공정 입력 LOT (추적 체인)
    product_code     VARCHAR(20),                            -- 제품 코드(KIM-BC-500 등, 혼합/포장공정)
    recipe_id        BIGINT,                                 -- 적용 레시피(혼합 공정)
    input_qty_kg     NUMERIC(10,2),                          -- 투입 수량(kg)
    output_qty_kg    NUMERIC(10,2),                          -- 산출 수량(kg)
    defect_qty_kg    NUMERIC(10,2) DEFAULT 0,                -- 불량 수량(kg)
    defect_code      VARCHAR(10),                            -- 불량 사유 코드(DEF-001 등)
    yield_rate       NUMERIC(5,2),                           -- 수율(%) = output/input*100
    worker           VARCHAR(50),                            -- 작업자(현장 성명 또는 사번 자유입력)
                                                            -- [설계 의도] users.user_id(BIGINT) FK 미연결.
                                                            -- 현장 작업자는 시스템 계정 없이 성명 직접 입력 허용.
                                                            -- 추후 사용자 통합 시 VARCHAR→BIGINT 마이그레이션 필요.
    equipment_code   VARCHAR(20),                            -- 설비 코드
    start_time       TIMESTAMP    NOT NULL,                  -- 공정 시작 일시
    end_time         TIMESTAMP,                              -- 공정 종료 일시 (진행중이면 NULL)
    status           VARCHAR(15)  DEFAULT 'IN_PROGRESS',     -- IN_PROGRESS/COMPLETED/HOLD
    details          JSONB        DEFAULT '{}'::jsonb,       -- 공정별 가변 측정값(염도/pH/온도/수분율 등)
    remark           TEXT,
    created_at       TIMESTAMP    DEFAULT NOW(),

    CONSTRAINT chk_pr_process_code CHECK (
        process_code IN ('PROC01','PROC02','PROC03','PROC04','PROC05',
                         'PROC06','PROC07','PROC08','PROC09')
    ),
    CONSTRAINT chk_pr_status CHECK (status IN ('IN_PROGRESS','COMPLETED','HOLD')),
    CONSTRAINT chk_pr_qty CHECK (
        (input_qty_kg IS NULL OR input_qty_kg >= 0) AND
        (output_qty_kg IS NULL OR output_qty_kg >= 0) AND
        (defect_qty_kg IS NULL OR defect_qty_kg >= 0)
    )
);
-- 핵심 인덱스: 공정코드 + 등록시각 (공정별 최신 실적/기간 집계)
CREATE INDEX IF NOT EXISTS idx_presult_code_created ON process_result(process_code, created_at DESC);
-- LOT 추적 조회
CREATE INDEX IF NOT EXISTS idx_presult_lot          ON process_result(lot_id);
CREATE INDEX IF NOT EXISTS idx_presult_source_lot   ON process_result(source_lot_id);
CREATE INDEX IF NOT EXISTS idx_presult_status       ON process_result(status);
COMMENT ON TABLE process_result IS '9개 공정 공통 실적 데이터 (공정코드별 details JSONB)';
COMMENT ON COLUMN process_result.details IS '공정별 세부 측정값. 예) PROC03: {"salt_temp":12.3,"salt_density":2.8,"salt_ph":5.8}';

-- =====================================================================
-- 2. process_recipe (레시피 마스터)
--    버전 관리 + 승인 워크플로우(작성→검토→승인)
--    레시피 변경 시 구 버전 is_active=FALSE, 신 버전 INSERT
-- =====================================================================
CREATE TABLE IF NOT EXISTS process_recipe (
    recipe_id        BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recipe_code      VARCHAR(20)  NOT NULL,                  -- 레시피 코드(PRD-BC-500 등)
    product_code     VARCHAR(20)  NOT NULL,                  -- 제품 코드(KIM-BC-500)
    recipe_name      VARCHAR(100) NOT NULL,                  -- 레시피명
    version          VARCHAR(10)  NOT NULL,                  -- 버전(v1.0, v2.1 등)
    is_active        BOOLEAN      DEFAULT TRUE,              -- 현행 사용 여부
    valid_from       DATE         NOT NULL DEFAULT CURRENT_DATE, -- 유효 시작일
    valid_to         DATE,                                   -- 유효 종료일 (NULL=현행)
    approval_status  VARCHAR(15)  DEFAULT 'DRAFT',           -- DRAFT/REVIEW/APPROVED/REJECTED
    created_by       VARCHAR(30),                            -- 작성자(성명/사번, users FK 미연결 — worker 주석 참조)
    reviewed_by      VARCHAR(30),                            -- 검토자(품질담당자)
    reviewed_at      TIMESTAMP,
    approved_by      VARCHAR(30),                            -- 승인자(관리자)
    approved_at      TIMESTAMP,
    notes            TEXT,
    created_at       TIMESTAMP    DEFAULT NOW(),

    CONSTRAINT uq_recipe_code_version UNIQUE (recipe_code, version),
    CONSTRAINT chk_recipe_approval CHECK (
        approval_status IN ('DRAFT','REVIEW','APPROVED','REJECTED')
    )
);
-- 핵심 인덱스: 제품별 현행 레시피 조회
CREATE INDEX IF NOT EXISTS idx_precipe_product_active ON process_recipe(product_code, is_active);
CREATE INDEX IF NOT EXISTS idx_precipe_code           ON process_recipe(recipe_code);
COMMENT ON TABLE process_recipe IS '제품별 레시피 마스터 (버전관리 + 승인 워크플로우)';

-- process_result.recipe_id → process_recipe FK (혼합/포장 공정에서 사용)
ALTER TABLE process_result
    DROP CONSTRAINT IF EXISTS fk_presult_recipe;
ALTER TABLE process_result
    ADD CONSTRAINT fk_presult_recipe
    FOREIGN KEY (recipe_id) REFERENCES process_recipe(recipe_id);

-- =====================================================================
-- 3. recipe_ingredient (레시피 원료 구성)
--    표준 배합 비율 + 허용 범위(min/max)
-- =====================================================================
CREATE TABLE IF NOT EXISTS recipe_ingredient (
    ingredient_id    BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recipe_id        BIGINT       NOT NULL REFERENCES process_recipe(recipe_id) ON DELETE CASCADE,
    material_code    VARCHAR(20)  NOT NULL,                  -- 원재료 코드(MAT-BC 등)
    material_name    VARCHAR(50)  NOT NULL,                  -- 원재료명(배추 등)
    standard_ratio   NUMERIC(5,2) NOT NULL,                  -- 표준 배합 비율(%)
    min_ratio        NUMERIC(5,2),                           -- 최소 허용 비율(%)
    max_ratio        NUMERIC(5,2),                           -- 최대 허용 비율(%)
    unit             VARCHAR(10)  DEFAULT 'kg',              -- 단위
    sort_order       INTEGER      DEFAULT 0,                 -- 표시 순서

    CONSTRAINT chk_ingredient_ratio CHECK (
        standard_ratio >= 0 AND standard_ratio <= 100 AND
        (min_ratio IS NULL OR max_ratio IS NULL OR min_ratio <= max_ratio)
    )
);
CREATE INDEX IF NOT EXISTS idx_ringredient_recipe ON recipe_ingredient(recipe_id);
COMMENT ON TABLE recipe_ingredient IS '레시피 원료 배합 구성 (표준비율/허용범위)';

-- =====================================================================
-- 4. recipe_process (레시피 공정 기준)
--    절임 염도/온도/시간, 발효 온도/시간 기준값
-- =====================================================================
CREATE TABLE IF NOT EXISTS recipe_process (
    rproc_id              BIGINT     GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recipe_id             BIGINT     NOT NULL REFERENCES process_recipe(recipe_id) ON DELETE CASCADE,
    process_code          VARCHAR(10) NOT NULL,              -- 적용 공정(PROC03/PROC07 등)
    pickling_salt_rate    NUMERIC(5,2),                      -- 절임 염도 기준(%)
    pickling_temp_min     NUMERIC(5,2),                      -- 절임 온도 최소(°C)
    pickling_temp_max     NUMERIC(5,2),                      -- 절임 온도 최대(°C)
    pickling_time_hour    NUMERIC(6,2),                      -- 절임 시간 기준(h)
    fermentation_temp     NUMERIC(5,2),                      -- 발효 목표 온도(°C)
    fermentation_time_hour NUMERIC(6,2),                     -- 발효 목표 시간(h)

    CONSTRAINT chk_rproc_code CHECK (
        process_code IN ('PROC01','PROC02','PROC03','PROC04','PROC05',
                         'PROC06','PROC07','PROC08','PROC09')
    ),
    CONSTRAINT chk_rproc_temp CHECK (
        pickling_temp_min IS NULL OR pickling_temp_max IS NULL
        OR pickling_temp_min <= pickling_temp_max
    )
);
CREATE INDEX IF NOT EXISTS idx_rprocess_recipe ON recipe_process(recipe_id);
COMMENT ON TABLE recipe_process IS '레시피별 공정 기준값 (절임/발효 조건)';

-- =====================================================================
-- 5. process_alarm (공정 이상 알림)
--    이상 감지 규칙(기획서 4.3) 발생 시 기록.
--    WARNING / CRITICAL 2단계, OPEN / RESOLVED 처리 상태.
-- =====================================================================
CREATE TABLE IF NOT EXISTS process_alarm (
    alarm_id         BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lot_id           VARCHAR(30),                            -- 대상 LOT
    process_code     VARCHAR(10)  NOT NULL,                  -- 발생 공정 코드
    alarm_level      VARCHAR(10)  NOT NULL,                  -- WARNING / CRITICAL
    alarm_type       VARCHAR(50)  NOT NULL,                  -- 유형(염도초과/pH이상/온도초과/금속검출 등)
    message          TEXT         NOT NULL,                  -- 알림 메시지
    measured_value   NUMERIC(10,3),                          -- 감지 측정값
    threshold_value  VARCHAR(50),                            -- 기준/임계값(범위 표현 포함)
    status           VARCHAR(10)  DEFAULT 'OPEN',            -- OPEN / RESOLVED
    resolved_by      VARCHAR(30),                            -- 처리자
    resolved_at      TIMESTAMP,                              -- 처리 일시
    resolve_note     TEXT,                                   -- 처리 내용
    created_at       TIMESTAMP    DEFAULT NOW(),

    CONSTRAINT chk_alarm_level  CHECK (alarm_level IN ('WARNING','CRITICAL')),
    CONSTRAINT chk_alarm_status CHECK (status IN ('OPEN','RESOLVED')),
    CONSTRAINT chk_alarm_code CHECK (
        process_code IN ('PROC01','PROC02','PROC03','PROC04','PROC05',
                         'PROC06','PROC07','PROC08','PROC09')
    )
);
-- 핵심 인덱스: 활성 알림 + 심각도 (현황판 / 알림 목록)
CREATE INDEX IF NOT EXISTS idx_palarm_status_level ON process_alarm(status, alarm_level);
CREATE INDEX IF NOT EXISTS idx_palarm_lot          ON process_alarm(lot_id);
CREATE INDEX IF NOT EXISTS idx_palarm_created       ON process_alarm(created_at DESC);
COMMENT ON TABLE process_alarm IS '공정 이상 감지 알림 (WARNING/CRITICAL, OPEN/RESOLVED)';

-- =====================================================================
-- 샘플 데이터
-- =====================================================================

-- process_recipe 2개 (현행 + 구버전 폐기)
INSERT INTO process_recipe
    (recipe_code, product_code, recipe_name, version, is_active, valid_from, valid_to,
     approval_status, created_by, reviewed_by, reviewed_at, approved_by, approved_at)
VALUES
    ('PRD-BC-500', 'KIM-BC-500', '배추김치 500g', 'v2.1', TRUE,  '2026-04-01', NULL,
     'APPROVED', 'prod01', 'qc01', '2026-03-30 10:00', 'admin', '2026-04-01 09:00'),
    ('PRD-BC-500', 'KIM-BC-500', '배추김치 500g', 'v2.0', FALSE, '2026-01-01', '2026-03-31',
     'APPROVED', 'prod01', 'qc01', '2025-12-28 10:00', 'admin', '2026-01-01 09:00');

-- recipe_ingredient (현행 v2.1 = recipe_id 1)
INSERT INTO recipe_ingredient
    (recipe_id, material_code, material_name, standard_ratio, min_ratio, max_ratio, unit, sort_order)
VALUES
    (1, 'MAT-BC', '배추(탈수후)', 73.0, 71.0, 75.0, 'kg', 1),
    (1, 'MAT-MU', '무채',         10.0,  9.0, 11.0, 'kg', 2),
    (1, 'MAT-GO', '고추가루',      5.0,  4.5,  5.5, 'kg', 3),
    (1, 'MAT-GA', '마늘',          3.5,  3.2,  3.8, 'kg', 4),
    (1, 'MAT-JO', '멸치액젓',      3.0,  2.7,  3.3, 'kg', 5),
    (1, 'MAT-PA', '파',            2.0,  1.7,  2.3, 'kg', 6),
    (1, 'MAT-GI', '생강',          0.5,  0.4,  0.6, 'kg', 7);

-- recipe_process (v2.1)
INSERT INTO recipe_process
    (recipe_id, process_code, pickling_salt_rate, pickling_temp_min, pickling_temp_max,
     pickling_time_hour, fermentation_temp, fermentation_time_hour)
VALUES
    (1, 'PROC03', 2.2, 16.0, 20.0, 7.0, NULL, NULL),
    (1, 'PROC07', NULL, NULL, NULL, NULL, 18.0, 72.0);

-- process_result 샘플 (세척/절임 PROC03)
INSERT INTO process_result
    (process_code, lot_id, source_lot_id, input_qty_kg, output_qty_kg, defect_qty_kg,
     yield_rate, worker, equipment_code, start_time, end_time, status, details)
VALUES
    ('PROC03', 'PICKLING-20260523-003', 'CUT-20260523-003', 3200, 2850, 0,
     89.06, '이미경', 'EQ-SALT-01', '2026-05-23 14:00', '2026-05-23 14:35', 'COMPLETED',
     '{"salt_water_temp":10.5,"salt_temp":12.3,"salt_density":2.8,"salt_ph":5.8,"salt_hours":18,"salt_input_kg":320}'::jsonb);

-- process_alarm 샘플 (발효실 온도 경고)
INSERT INTO process_alarm
    (lot_id, process_code, alarm_level, alarm_type, message, measured_value, threshold_value, status)
VALUES
    ('FE-20260522-008', 'PROC07', 'WARNING', '온도초과접근',
     '발효실2 온도 9.1°C — 정상범위(0~10°C) 상한 접근. 확인 필요', 9.1, '0~10°C', 'OPEN'),
    ('PICKLING-20260523-003', 'PROC03', 'WARNING', 'pH주의',
     '절임조 pH 5.8 — 목표범위(5.0~7.0) 정상, 추이 모니터링 권장', 5.8, '5.0~7.0', 'OPEN');

-- =====================================================================
-- 뷰: 공정실적 + 수율 요약 (공정데이터 분석용)
-- =====================================================================
CREATE OR REPLACE VIEW process_analysis_view AS
SELECT
    process_code,
    DATE(start_time)                            AS work_date,
    COUNT(*)                                    AS lot_count,
    SUM(input_qty_kg)                           AS total_input_kg,
    SUM(output_qty_kg)                          AS total_output_kg,
    SUM(defect_qty_kg)                          AS total_defect_kg,
    ROUND(AVG(yield_rate), 2)                   AS avg_yield_rate,
    ROUND(100.0 * SUM(defect_qty_kg)
          / NULLIF(SUM(input_qty_kg), 0), 2)    AS defect_rate_pct,
    ROUND(AVG(EXTRACT(EPOCH FROM (end_time - start_time)) / 60.0), 1) AS avg_minutes
FROM process_result
WHERE start_time IS NOT NULL
GROUP BY process_code, DATE(start_time);
COMMENT ON VIEW process_analysis_view IS '공정별 일별 생산량/불량률/소요시간 집계 (분석화면)';

-- =====================================================================
-- 완료
-- =====================================================================
