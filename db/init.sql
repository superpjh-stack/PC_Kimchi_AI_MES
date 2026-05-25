-- =====================================================================
-- 꽃순이김치 제조AI 스마트공장 MES — DB 초기화 스크립트
-- 프로젝트: SF26179540 (평창꽃순이(주)농업회사법인)
-- 개발: 로뎀솔루션 주식회사
-- DBMS : PostgreSQL 15+ (pgvector 확장 사용)
-- 핵심  : 전 공정 데이터는 LOT 단위로 연결되어 Traceability를 보장한다.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 0. 확장 모듈
-- ---------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector;        -- pgvector (임베딩 벡터 검색)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- UUID 생성

-- =====================================================================
-- 1. suppliers (공급처)
-- =====================================================================
CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id     VARCHAR(20)  PRIMARY KEY,        -- 공급처 코드
    supplier_name   VARCHAR(100) NOT NULL,           -- 공급처명
    region          VARCHAR(50),                     -- 지역/원산지
    contact         VARCHAR(50),                     -- 연락처
    quality_grade   VARCHAR(10)  DEFAULT 'B',        -- 공급처 품질등급(A/B/C)
    avg_defect_rate NUMERIC(5,2) DEFAULT 0.0,        -- 평균 불량률(%)
    is_active       BOOLEAN      DEFAULT TRUE,        -- 사용 여부
    created_at      TIMESTAMP    DEFAULT NOW()
);
COMMENT ON TABLE suppliers IS '원재료 공급처 마스터';

-- =====================================================================
-- 2. raw_material_intake (원재료 입고)
--    intake_lot_id 가 전 공정 추적의 시작점이 된다.
-- =====================================================================
CREATE TABLE IF NOT EXISTS raw_material_intake (
    intake_lot_id   VARCHAR(30)  PRIMARY KEY,            -- 입고 LOT
    supplier_id     VARCHAR(20)  REFERENCES suppliers(supplier_id),
    material_name   VARCHAR(100) NOT NULL,               -- 원재료명(배추 등)
    intake_date     DATE         NOT NULL,               -- 입고일
    weight_kg       NUMERIC(10,2),                       -- 입고 중량(kg)
    cabbage_size    VARCHAR(10),                         -- 배추 크기(대/중/소)
    appearance_grade VARCHAR(5),                         -- 외관 등급(A/B/C)
    moisture_rate   NUMERIC(5,2),                        -- 함수율(%)
    origin          VARCHAR(50),                         -- 원산지
    inspection_result VARCHAR(10) DEFAULT '정상',         -- 입고 검사결과
    created_at      TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_intake_supplier ON raw_material_intake(supplier_id);
CREATE INDEX IF NOT EXISTS idx_intake_date     ON raw_material_intake(intake_date);
COMMENT ON TABLE raw_material_intake IS '원재료 입고 및 LOT 데이터';

-- =====================================================================
-- 3. salting_process (절임 공정)
--    intake_lot_id(입고LOT) -> salting_lot_id(절임LOT) 연결
-- =====================================================================
CREATE TABLE IF NOT EXISTS salting_process (
    salting_lot_id  VARCHAR(30)  PRIMARY KEY,            -- 절임 LOT
    intake_lot_id   VARCHAR(30)  REFERENCES raw_material_intake(intake_lot_id),
    start_time      TIMESTAMP,                           -- 절임 시작
    end_time        TIMESTAMP,                           -- 절임 종료
    salt_temp       NUMERIC(5,2),                        -- 절임 온도(°C)
    salt_density    NUMERIC(5,2),                        -- 절임 염도(%)
    salt_ph         NUMERIC(4,2),                        -- 절임 pH
    salt_hours      NUMERIC(5,2),                        -- 절임 시간(h)
    dehydration_rate NUMERIC(5,2),                       -- 탈수율(%)
    worker          VARCHAR(50),                         -- 작업자
    created_at      TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_salting_intake ON salting_process(intake_lot_id);
COMMENT ON TABLE salting_process IS '절임/전처리 공정 데이터';

-- =====================================================================
-- 4. fermentation_process (발효 공정)
--    salting_lot_id(절임LOT) -> fermentation_lot_id(발효LOT) 연결
-- =====================================================================
CREATE TABLE IF NOT EXISTS fermentation_process (
    fermentation_lot_id VARCHAR(30) PRIMARY KEY,         -- 발효 LOT
    salting_lot_id  VARCHAR(30)  REFERENCES salting_process(salting_lot_id),
    start_time      TIMESTAMP,                           -- 발효 시작
    expected_end_time TIMESTAMP,                         -- 발효 완료 예상시점(LSTM)
    actual_end_time TIMESTAMP,                           -- 실제 완료시점
    ferment_temp    NUMERIC(5,2),                        -- 발효 온도(°C)
    ferment_acidity NUMERIC(4,2),                        -- 발효 산도(pH)
    ferment_hours   NUMERIC(6,2),                        -- 숙성 시간(h)
    ambient_temp    NUMERIC(5,2),                        -- 외기 온도(°C)
    ambient_humidity NUMERIC(5,2),                       -- 외기 습도(%)
    ml_quality_pred VARCHAR(10),                         -- ML 품질 예측(정상/주의/이상)
    ml_confidence   NUMERIC(5,2),                        -- 예측 신뢰도(%)
    is_abnormal     BOOLEAN      DEFAULT FALSE,           -- 이상발효 여부
    created_at      TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ferment_salting  ON fermentation_process(salting_lot_id);
CREATE INDEX IF NOT EXISTS idx_ferment_pred     ON fermentation_process(ml_quality_pred);
CREATE INDEX IF NOT EXISTS idx_ferment_abnormal ON fermentation_process(is_abnormal);
COMMENT ON TABLE fermentation_process IS '숙성/발효 공정 데이터 (ML 예측 대상)';

-- =====================================================================
-- 5. fermentation_timeseries (발효 시계열) — recorded_at 기준 RANGE 파티셔닝
--    LSTM Sliding Window 입력용 고빈도 센서 데이터
-- =====================================================================
CREATE TABLE IF NOT EXISTS fermentation_timeseries (
    ts_id           BIGINT       GENERATED ALWAYS AS IDENTITY,
    fermentation_lot_id VARCHAR(30) NOT NULL,
    recorded_at     TIMESTAMP    NOT NULL,               -- 측정 시각(파티션 키)
    temperature     NUMERIC(5,2),                        -- 온도(°C)
    acidity         NUMERIC(4,2),                        -- 산도(pH)
    salt_density    NUMERIC(5,2),                        -- 염도(%)
    humidity        NUMERIC(5,2),                        -- 습도(%)
    PRIMARY KEY (ts_id, recorded_at)
) PARTITION BY RANGE (recorded_at);

-- 월별 파티션 (운영 중 신규 월 추가 가능)
CREATE TABLE IF NOT EXISTS fermentation_timeseries_2026_04
    PARTITION OF fermentation_timeseries
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE IF NOT EXISTS fermentation_timeseries_2026_05
    PARTITION OF fermentation_timeseries
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS fermentation_timeseries_2026_06
    PARTITION OF fermentation_timeseries
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

CREATE INDEX IF NOT EXISTS idx_ferm_ts_lot
    ON fermentation_timeseries(fermentation_lot_id, recorded_at);
COMMENT ON TABLE fermentation_timeseries IS '발효 시계열 센서 데이터 (월별 파티셔닝)';

-- =====================================================================
-- 6. packaging (포장)
--    fermentation_lot_id(발효LOT) -> packaging_lot_id(포장LOT) 연결
-- =====================================================================
CREATE TABLE IF NOT EXISTS packaging (
    packaging_lot_id VARCHAR(30) PRIMARY KEY,            -- 포장 LOT
    fermentation_lot_id VARCHAR(30) REFERENCES fermentation_process(fermentation_lot_id),
    product_type    VARCHAR(30),                         -- 제품 유형
    package_date    TIMESTAMP,                           -- 포장 일시
    package_qty     INTEGER,                             -- 포장 수량(box)
    weight_kg       NUMERIC(10,2),                       -- 포장 중량(kg)
    metal_detect_result VARCHAR(10) DEFAULT 'PASS',      -- 금속검출 결과
    defect_qty      INTEGER      DEFAULT 0,              -- 불량 수량
    worker          VARCHAR(50),
    created_at      TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pkg_ferment ON packaging(fermentation_lot_id);
COMMENT ON TABLE packaging IS '포장 공정 데이터';

-- =====================================================================
-- 7. shipping (출하)
--    packaging_lot_id(포장LOT) -> shipping_lot_id(출하LOT) 연결
-- =====================================================================
CREATE TABLE IF NOT EXISTS shipping (
    shipping_lot_id VARCHAR(30)  PRIMARY KEY,            -- 출하 LOT
    packaging_lot_id VARCHAR(30) REFERENCES packaging(packaging_lot_id),
    ship_date       TIMESTAMP,                           -- 출하 일시
    customer        VARCHAR(100),                        -- 거래처
    ship_qty        INTEGER,                             -- 출하 수량(box)
    approval_status VARCHAR(10)  DEFAULT '대기',          -- 출하 승인(승인/대기/반려)
    approver        VARCHAR(50),                         -- 승인자
    final_quality   VARCHAR(10),                         -- 최종 품질 등급
    created_at      TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ship_pkg      ON shipping(packaging_lot_id);
CREATE INDEX IF NOT EXISTS idx_ship_approval ON shipping(approval_status);
COMMENT ON TABLE shipping IS '출하 데이터';

-- =====================================================================
-- 8. quality_inspection (품질 검사)
--    lot_id + lot_type 으로 모든 공정의 검사 결과를 통합 관리
-- =====================================================================
CREATE TABLE IF NOT EXISTS quality_inspection (
    inspection_id   BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lot_id          VARCHAR(30)  NOT NULL,               -- 대상 LOT
    lot_type        VARCHAR(20)  NOT NULL,               -- LOT 유형(입고/절임/발효/포장/출하)
    inspect_date    TIMESTAMP    DEFAULT NOW(),
    inspect_item    VARCHAR(50),                         -- 검사 항목(염도/산도/금속/관능)
    measured_value  NUMERIC(10,3),                       -- 측정값
    standard_range  VARCHAR(50),                         -- 기준 범위
    result          VARCHAR(10),                         -- 결과(PASS/FAIL)
    inspector       VARCHAR(50),                         -- 검사자
    remark          TEXT
);
CREATE INDEX IF NOT EXISTS idx_qc_lot    ON quality_inspection(lot_id, lot_type);
CREATE INDEX IF NOT EXISTS idx_qc_result ON quality_inspection(result);
COMMENT ON TABLE quality_inspection IS '품질 검사 및 불량 데이터 (LOT+유형 기준)';

-- =====================================================================
-- 9. claim (클레임)
-- =====================================================================
CREATE TABLE IF NOT EXISTS claim (
    claim_id        BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shipping_lot_id VARCHAR(30)  REFERENCES shipping(shipping_lot_id),
    claim_date      DATE         NOT NULL,
    customer        VARCHAR(100),                        -- 클레임 제기 거래처
    claim_type      VARCHAR(50),                         -- 클레임 유형(이물/변질/포장불량 등)
    claim_content   TEXT,                                -- 클레임 내용
    cause_analysis  TEXT,                                -- 원인 분석
    action_taken    TEXT,                                -- 대응 조치
    status          VARCHAR(10)  DEFAULT '접수',          -- 처리 상태(접수/처리중/완료)
    created_at      TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_claim_ship ON claim(shipping_lot_id);
COMMENT ON TABLE claim IS '클레임 및 대응 이력';

-- =====================================================================
-- 10. production_kpi (KPI)
-- =====================================================================
CREATE TABLE IF NOT EXISTS production_kpi (
    kpi_id          BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kpi_date        DATE         NOT NULL,
    hourly_output_kg NUMERIC(10,2),                      -- 시간당 생산량(kg/h)
    defect_rate     NUMERIC(5,2),                        -- 완제품 불량률(%)
    utilization     NUMERIC(5,2),                        -- 가동률(%)
    achievement_rate NUMERIC(5,2),                       -- 계획 대비 달성률(%)
    created_at      TIMESTAMP    DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_kpi_date ON production_kpi(kpi_date);
COMMENT ON TABLE production_kpi IS '생산성/품질 KPI 일별 집계';

-- =====================================================================
-- 11. process_record (공정 실적)
-- =====================================================================
CREATE TABLE IF NOT EXISTS process_record (
    record_id       BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    process_type    VARCHAR(20)  NOT NULL,               -- 공정 유형
    lot_id          VARCHAR(30),                         -- 대상 LOT
    start_time      TIMESTAMP,
    end_time        TIMESTAMP,
    quantity_kg     NUMERIC(10,2),                       -- 작업 수량(kg)
    worker_count    INTEGER,                             -- 투입 인원
    utilization     NUMERIC(5,2),                        -- 가동률(%)
    worker          VARCHAR(50),
    remark          TEXT,                                -- 특이사항
    created_at      TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_precord_type ON process_record(process_type);
CREATE INDEX IF NOT EXISTS idx_precord_lot  ON process_record(lot_id);
COMMENT ON TABLE process_record IS '공정 실적 데이터';

-- =====================================================================
-- 12. recipe (레시피)
-- =====================================================================
CREATE TABLE IF NOT EXISTS recipe (
    recipe_id       BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recipe_name     VARCHAR(100) NOT NULL,               -- 레시피명
    product_type    VARCHAR(30),                         -- 제품 유형
    version         VARCHAR(10),                         -- 버전
    salt_temp       NUMERIC(5,2),                        -- 절임 온도(°C)
    salt_density    NUMERIC(5,2),                        -- 절임 염도(%)
    salt_hours      NUMERIC(5,2),                        -- 절임 시간(h)
    ferment_temp    NUMERIC(5,2),                        -- 발효 온도(°C)
    expected_ferment_hours NUMERIC(6,2),                 -- 예상 발효 시간(h)
    usage_count     INTEGER      DEFAULT 0,              -- 사용 횟수
    is_active       BOOLEAN      DEFAULT TRUE,
    created_at      TIMESTAMP    DEFAULT NOW()
);
COMMENT ON TABLE recipe IS '제품별 공정 레시피';

-- =====================================================================
-- 13. quality_standard (품질 기준)
-- =====================================================================
CREATE TABLE IF NOT EXISTS quality_standard (
    standard_id     BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    process_type    VARCHAR(20)  NOT NULL,               -- 공정
    item_name       VARCHAR(50)  NOT NULL,               -- 기준 항목
    standard_value  VARCHAR(50),                         -- 기준값
    tolerance       VARCHAR(30),                         -- 허용 오차
    unit            VARCHAR(20),                         -- 단위
    updated_at      TIMESTAMP    DEFAULT NOW(),
    updated_by      VARCHAR(50)
);
CREATE INDEX IF NOT EXISTS idx_qstd_process ON quality_standard(process_type);
COMMENT ON TABLE quality_standard IS '공정별 품질 기준값';

-- =====================================================================
-- 14. document_embeddings (pgvector) — SOP/기준서/매뉴얼 임베딩
--     RAG AI Agent 검색 대상 (OpenAI text-embedding 1536차원 기준)
-- =====================================================================
CREATE TABLE IF NOT EXISTS document_embeddings (
    doc_id          BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    doc_name        VARCHAR(200) NOT NULL,               -- 문서명
    doc_type        VARCHAR(30),                         -- 유형(SOP/발효기준서/QC기준/HACCP/설비매뉴얼)
    version         VARCHAR(10),
    chunk_index     INTEGER      DEFAULT 0,              -- 청크 순번
    content         TEXT,                                -- 원문 청크
    embedding       VECTOR(1536),                        -- 임베딩 벡터
    created_at      TIMESTAMP    DEFAULT NOW()
);
-- 벡터 유사도 검색 인덱스 (IVFFlat, 코사인 거리)
CREATE INDEX IF NOT EXISTS idx_doc_embedding
    ON document_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_doc_type ON document_embeddings(doc_type);
COMMENT ON TABLE document_embeddings IS '비정형 문서 임베딩 (pgvector RAG 검색)';

-- =====================================================================
-- 15. users (사용자)
-- =====================================================================
CREATE TABLE IF NOT EXISTS users (
    user_id         VARCHAR(30)  PRIMARY KEY,            -- 사용자 ID
    user_name       VARCHAR(50)  NOT NULL,               -- 이름
    role            VARCHAR(20)  NOT NULL,               -- 역할(관리자/생산담당/품질담당/현장작업자)
    department      VARCHAR(50),                         -- 부서
    password_hash   VARCHAR(200),                        -- 비밀번호 해시
    is_active       BOOLEAN      DEFAULT TRUE,            -- 상태
    last_login      TIMESTAMP,                           -- 마지막 로그인
    created_at      TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
COMMENT ON TABLE users IS '시스템 사용자';

-- =====================================================================
-- 16. system_log (시스템 로그)
-- =====================================================================
CREATE TABLE IF NOT EXISTS system_log (
    log_id          BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at     TIMESTAMP    DEFAULT NOW(),
    log_level       VARCHAR(10),                         -- INFO/WARN/ERROR
    user_id         VARCHAR(30),                         -- 작업 사용자
    action          VARCHAR(100),                        -- 작업
    target          VARCHAR(100),                        -- 대상
    detail          TEXT                                 -- 상세
);
CREATE INDEX IF NOT EXISTS idx_log_level ON system_log(log_level);
CREATE INDEX IF NOT EXISTS idx_log_time  ON system_log(occurred_at);
COMMENT ON TABLE system_log IS '시스템 작업 로그';

-- =====================================================================
-- 17. alert_config (알림 설정)
-- =====================================================================
CREATE TABLE IF NOT EXISTS alert_config (
    config_id       BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    config_key      VARCHAR(50)  NOT NULL UNIQUE,        -- 설정 키
    config_value    VARCHAR(100),                        -- 설정 값
    description     VARCHAR(200),                        -- 설명
    notify_methods  VARCHAR(100),                        -- 알림 방법(이메일/SMS/팝업)
    recipients      TEXT,                                -- 수신자
    updated_at      TIMESTAMP    DEFAULT NOW()
);
COMMENT ON TABLE alert_config IS '알림 임계값/수신자 설정';

-- =====================================================================
-- 샘플 데이터 INSERT
-- =====================================================================

-- suppliers 4개
INSERT INTO suppliers (supplier_id, supplier_name, region, contact, quality_grade, avg_defect_rate) VALUES
    ('SUP01', '강원농협',     '강원 평창', '033-330-1001', 'A', 0.8),
    ('SUP02', '충북원예',     '충북 괴산', '043-830-2002', 'B', 1.4),
    ('SUP03', '전남청정',     '전남 해남', '061-530-3003', 'A', 0.9),
    ('SUP04', '고랭지영농',   '강원 정선', '033-560-4004', 'B', 1.6)
ON CONFLICT (supplier_id) DO NOTHING;

-- users 5명
INSERT INTO users (user_id, user_name, role, department, password_hash, is_active, last_login) VALUES
    ('admin',   '김철수', '관리자',     '경영지원팀',   'hashed_pw_admin',  TRUE, '2026-05-23 08:12'),
    ('prod01',  '박민준', '생산담당',   '생산1팀',     'hashed_pw_prod01', TRUE, '2026-05-23 07:45'),
    ('qc01',    '이영희', '품질담당',   '품질관리팀',   'hashed_pw_qc01',   TRUE, '2026-05-23 09:02'),
    ('qc02',    '정수진', '품질담당',   '품질관리팀',   'hashed_pw_qc02',   TRUE, '2026-05-23 08:50'),
    ('field01', '최동훈', '현장작업자', '생산1팀',     'hashed_pw_field01',TRUE, '2026-05-23 06:30')
ON CONFLICT (user_id) DO NOTHING;

-- recipe 4개
INSERT INTO recipe (recipe_name, product_type, version, salt_temp, salt_density, salt_hours, ferment_temp, expected_ferment_hours, usage_count) VALUES
    ('포기김치 표준', '포기김치', 'v2.1', 18.0, 2.2, 7.0, 18.0, 72, 342),
    ('깍두기 표준',   '깍두기',   'v2.0', 19.0, 2.4, 6.0, 19.0, 60, 256),
    ('열무김치 표준', '열무김치', 'v1.5', 17.0, 2.0, 5.0, 20.0, 48, 174),
    ('백김치 표준',   '백김치',   'v1.4', 16.0, 1.7, 6.0, 16.0, 96, 113);

-- quality_standard 10개
INSERT INTO quality_standard (process_type, item_name, standard_value, tolerance, unit, updated_by) VALUES
    ('절임',     '염도',     '2.0~2.5%',   '±0.2%',  '%',    'qc01'),
    ('절임',     '온도',     '16~20°C',    '±1°C',   '°C',   'qc01'),
    ('절임',     '시간',     '6~8시간',    '±0.5h',  'h',    'prod01'),
    ('발효',     '온도',     '15~22°C',    '±1°C',   '°C',   'qc01'),
    ('발효',     '산도',     '0.35~0.55',  '±0.05',  'pH',   'qc01'),
    ('발효',     '숙성시간', '48~96시간',  '±4h',    'h',    'qc02'),
    ('탈수',     '함수율',   '82~88%',     '±2%',    '%',    'prod01'),
    ('금속검출', '민감도',   'Fe ≤1.5mm',  '-',      'mm',   'qc02'),
    ('포장',     '불량률',   '≤1.0%',      '-',      '%',    'admin'),
    ('출하',     '최종품질', '정상',       '-',      '등급', 'qc01');

-- =====================================================================
-- 뷰(VIEW)
-- =====================================================================

-- 뷰 1: lot_traceability_view — 입고→절임→발효→포장→출하 전 공정 LOT 연결 추적
CREATE OR REPLACE VIEW lot_traceability_view AS
SELECT
    rmi.intake_lot_id                       AS 입고LOT,
    s.supplier_name                         AS 공급처,
    rmi.material_name                       AS 원재료,
    rmi.intake_date                         AS 입고일,
    sp.salting_lot_id                       AS 절임LOT,
    sp.salt_density                         AS 절임염도,
    sp.salt_hours                           AS 절임시간,
    fp.fermentation_lot_id                  AS 발효LOT,
    fp.ferment_temp                         AS 발효온도,
    fp.ml_quality_pred                      AS 발효품질예측,
    fp.is_abnormal                          AS 이상발효여부,
    pkg.packaging_lot_id                    AS 포장LOT,
    pkg.product_type                        AS 제품유형,
    sh.shipping_lot_id                      AS 출하LOT,
    sh.approval_status                       AS 출하승인상태,
    sh.ship_date                            AS 출하일
FROM raw_material_intake rmi
    LEFT JOIN suppliers           s   ON rmi.supplier_id        = s.supplier_id
    LEFT JOIN salting_process     sp  ON rmi.intake_lot_id      = sp.intake_lot_id
    LEFT JOIN fermentation_process fp ON sp.salting_lot_id      = fp.salting_lot_id
    LEFT JOIN packaging           pkg ON fp.fermentation_lot_id = pkg.fermentation_lot_id
    LEFT JOIN shipping            sh  ON pkg.packaging_lot_id    = sh.packaging_lot_id;

COMMENT ON VIEW lot_traceability_view IS '전 공정 LOT 연결 추적 뷰 (Traceability)';

-- 뷰 2: daily_kpi_view — 일별 생산/품질 KPI 집계
CREATE OR REPLACE VIEW daily_kpi_view AS
SELECT
    pr.work_date                            AS 일자,
    pr.total_qty                            AS 일생산량_kg,
    ROUND((pr.total_qty / NULLIF(pr.work_hours, 0))::numeric, 1) AS 시간당생산량_kg_h,
    COALESCE(qc.defect_rate, 0)             AS 불량률_pct,
    pr.avg_util                             AS 평균가동률_pct
FROM (
    -- 공정실적 기반 일별 생산량/가동률 집계
    SELECT
        DATE(start_time)                    AS work_date,
        SUM(quantity_kg)                    AS total_qty,
        SUM(EXTRACT(EPOCH FROM (end_time - start_time)) / 3600.0) AS work_hours,
        ROUND(AVG(utilization), 1)          AS avg_util
    FROM process_record
    WHERE start_time IS NOT NULL AND end_time IS NOT NULL
    GROUP BY DATE(start_time)
) pr
LEFT JOIN (
    -- 품질검사 기반 일별 불량률(FAIL 비율) 집계
    SELECT
        DATE(inspect_date)                  AS qc_date,
        ROUND(100.0 * SUM(CASE WHEN result = 'FAIL' THEN 1 ELSE 0 END)
              / NULLIF(COUNT(*), 0), 2)     AS defect_rate
    FROM quality_inspection
    GROUP BY DATE(inspect_date)
) qc ON pr.work_date = qc.qc_date;

COMMENT ON VIEW daily_kpi_view IS '일별 KPI 집계 뷰 (생산량/가동률/불량률)';

-- =====================================================================
-- 초기화 완료
-- =====================================================================
