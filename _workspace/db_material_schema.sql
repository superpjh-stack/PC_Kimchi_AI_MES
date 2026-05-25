-- =====================================================================
-- 꽃순이김치 제조AI 스마트공장 MES — 원재료관리 모듈 스키마
-- 프로젝트: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션
-- DBMS    : PostgreSQL 15+
-- 담당    : 원재료관리 (입고 / 입고검사 / 선별 / 공급처 품질)
--
-- LOT 체인 (전 모듈 공통):
--   raw_material_lot(lot_id)              ← 본 스키마가 체인의 시작점
--        -> salting_lot(source_lot_id = raw_material_lot.lot_id)
--        -> fermentation_lot
--        -> packaging_lot
--        -> shipping_lot
--
--   원재료 LOT 형식: RM-YYYYMMDD-NNN  (예: RM-20260524-001)
--   본 모듈의 lot_id 는 공정관리(process_result.source_lot_id) 및
--   다른 모듈의 source_lot_id 로 참조되어 Traceability 를 보장한다.
--
-- 테이블 구성:
--   1. supplier                 공급처 마스터
--   2. raw_material_lot          원재료 LOT 마스터 (입고 단위)
--   3. incoming_inspection       입고 검사 (배추 품질 지표 + 판정)
--   4. material_selection        선별 데이터 (입고 후 선별 실적)
--   5. supplier_quality_score    공급처 월별 품질 점수 (집계)
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. supplier — 공급처 마스터
--    ※ 테이블 본체는 db_master_schema.sql 에서 정의 (적용 선행 필요).
--       원재료관리 모듈에 필요한 추가 컬럼만 여기서 확장한다.
--       적용 순서: db_master_schema.sql → db_material_schema.sql
-- ---------------------------------------------------------------------
ALTER TABLE supplier
    ADD COLUMN IF NOT EXISTS contact_name  VARCHAR(50),   -- 담당자명 (원재료 입고용)
    ADD COLUMN IF NOT EXISTS phone         VARCHAR(20),   -- 연락처
    ADD COLUMN IF NOT EXISTS email         VARCHAR(100),  -- 이메일
    ADD COLUMN IF NOT EXISTS region        VARCHAR(50),   -- 산지 지역 (강원 평창 등)
    ADD COLUMN IF NOT EXISTS registered_at DATE DEFAULT CURRENT_DATE,  -- 등록일
    ADD COLUMN IF NOT EXISTS notes         TEXT;          -- 비고

CREATE INDEX IF NOT EXISTS idx_supplier_region ON supplier(region);
COMMENT ON COLUMN supplier.region        IS '산지 지역 — 공급처 품질 분석 시 지역별 비교에 사용';
COMMENT ON COLUMN supplier.registered_at IS '공급처 등록일 (원재료관리 모듈 확장)';
COMMENT ON COLUMN supplier.contact_name  IS '담당자명 (원재료 입고 연락처)';
COMMENT ON TABLE  supplier               IS '공급업체 마스터 (db_master_schema.sql 정의 + 원재료관리 확장)';


-- ---------------------------------------------------------------------
-- 2. raw_material_lot — 원재료 LOT 마스터 (입고 단위)
--    입고 1건 = 1 LOT. LOT 추적 체인의 시작점.
--    lot_status 워크플로우:
--      RECEIVED   입고 등록 완료 (검사 전)
--      INSPECTING 검사 진행 중
--      PASSED     검사 합격 (후속 공정 투입 가능)
--      REJECTED   검사 불합격 (반품/폐기)
--      CONSUMED   후속 공정(절임)에 전량 투입 완료
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_material_lot (
    lot_id          VARCHAR(30)  PRIMARY KEY,                 -- RM-YYYYMMDD-NNN
    intake_date     DATE         NOT NULL,                    -- 입고일
    supplier_code   VARCHAR(20)  NOT NULL,                    -- 공급처 코드 (FK)
    material_code   VARCHAR(20)  NOT NULL,                    -- 재료 코드 (code_master MATERIAL 그룹)
    origin          VARCHAR(50),                              -- 원산지
    quantity_kg     NUMERIC(10,2) NOT NULL,                   -- 입고 수량(kg)
    unit_price      NUMERIC(10,2),                            -- 단가(원/kg)
    vehicle_no      VARCHAR(20),                              -- 입고 차량번호
    driver_name     VARCHAR(50),                              -- 운전기사명
    received_by     VARCHAR(50),                              -- 입고 담당자(성명/사번 자유입력)
    lot_status      VARCHAR(20)  DEFAULT 'RECEIVED',          -- 상태 (아래 CHECK)
    notes           TEXT,
    created_at      TIMESTAMPTZ  DEFAULT NOW(),

    CONSTRAINT fk_rml_supplier
        FOREIGN KEY (supplier_code) REFERENCES supplier(supplier_code),
    CONSTRAINT chk_rml_status CHECK (
        lot_status IN ('RECEIVED','INSPECTING','PASSED','REJECTED','CONSUMED')
    ),
    CONSTRAINT chk_rml_qty CHECK (quantity_kg > 0)
);
-- 핵심 인덱스: 입고일 + 공급처 (기간/공급처 필터), 상태별 조회
CREATE INDEX IF NOT EXISTS idx_rml_intake_date ON raw_material_lot(intake_date DESC);
CREATE INDEX IF NOT EXISTS idx_rml_supplier    ON raw_material_lot(supplier_code);
CREATE INDEX IF NOT EXISTS idx_rml_status      ON raw_material_lot(lot_status);
CREATE INDEX IF NOT EXISTS idx_rml_material    ON raw_material_lot(material_code);
COMMENT ON TABLE raw_material_lot IS '원재료 LOT 마스터 — LOT Traceability 체인의 시작점';
COMMENT ON COLUMN raw_material_lot.lot_id IS 'RM-YYYYMMDD-NNN. 후속 공정에서 source_lot_id 로 참조됨';


-- ---------------------------------------------------------------------
-- 3. incoming_inspection — 입고 검사
--    배추 품질 지표(크기/중량/외관/함수율/신선도) + 합격 판정.
--    ML 발효 예측의 원재료 입력 feature 로도 활용된다.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incoming_inspection (
    inspection_id     BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lot_id            VARCHAR(30)  NOT NULL,                  -- 검사 대상 LOT (FK)
    inspector         VARCHAR(50)  NOT NULL,                  -- 검사자
    inspection_date   DATE         NOT NULL DEFAULT CURRENT_DATE,
    -- 배추 품질 지표 -------------------------------------------------
    cabbage_size      VARCHAR(10),                            -- SMALL/MEDIUM/LARGE/XLARGE
    weight_avg_kg     NUMERIC(5,2),                           -- 개당 평균 중량(kg)
    appearance_grade  VARCHAR(10),                            -- A/B/C (외관 등급)
    water_content_pct NUMERIC(5,2),                           -- 함수율(%)
    freshness_score   INT,                                    -- 신선도 점수 1~10
    -- 판정 -----------------------------------------------------------
    qc_result         VARCHAR(10)  NOT NULL,                  -- PASS/FAIL/CONDITIONAL
    rejection_reason  TEXT,                                   -- 불합격 사유
    corrective_action TEXT,                                   -- 시정 조치
    created_at        TIMESTAMPTZ  DEFAULT NOW(),

    CONSTRAINT fk_ii_lot
        FOREIGN KEY (lot_id) REFERENCES raw_material_lot(lot_id),
    CONSTRAINT chk_ii_freshness CHECK (
        freshness_score IS NULL OR freshness_score BETWEEN 1 AND 10
    ),
    CONSTRAINT chk_ii_qc CHECK (qc_result IN ('PASS','FAIL','CONDITIONAL')),
    CONSTRAINT chk_ii_size CHECK (
        cabbage_size IS NULL OR cabbage_size IN ('SMALL','MEDIUM','LARGE','XLARGE')
    ),
    CONSTRAINT chk_ii_grade CHECK (
        appearance_grade IS NULL OR appearance_grade IN ('A','B','C')
    )
);
CREATE INDEX IF NOT EXISTS idx_ii_lot       ON incoming_inspection(lot_id);
CREATE INDEX IF NOT EXISTS idx_ii_result    ON incoming_inspection(qc_result);
CREATE INDEX IF NOT EXISTS idx_ii_date      ON incoming_inspection(inspection_date DESC);
COMMENT ON TABLE incoming_inspection IS '입고 검사 — 배추 품질 지표 및 합격 판정 (ML feature 원천)';


-- ---------------------------------------------------------------------
-- 4. material_selection — 선별 데이터 (입고 후 선별 작업)
--    입고 LOT 의 투입량 대비 선별 통과량/제거량을 기록.
--    selection_rate_pct 는 GENERATED 컬럼으로 자동 계산.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS material_selection (
    selection_id      BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lot_id            VARCHAR(30)  NOT NULL,                  -- 선별 대상 LOT (FK)
    selection_date    DATE         NOT NULL DEFAULT CURRENT_DATE,
    operator          VARCHAR(50),                            -- 선별 작업자
    input_qty_kg      NUMERIC(10,2) NOT NULL,                 -- 투입량(kg)
    selected_qty_kg   NUMERIC(10,2) NOT NULL,                 -- 선별 통과량(kg)
    reject_qty_kg     NUMERIC(10,2) NOT NULL,                 -- 제거량(kg)
    -- 선별율(%) = 통과량 / 투입량 * 100  (자동 계산)
    selection_rate_pct NUMERIC(5,2)
        GENERATED ALWAYS AS (
            CASE WHEN input_qty_kg > 0
                 THEN ROUND(selected_qty_kg * 100.0 / input_qty_kg, 2)
            END
        ) STORED,
    reject_reason     VARCHAR(100),                           -- ROTTEN/PEST/SIZE/FOREIGN/OTHER
    notes             TEXT,
    created_at        TIMESTAMPTZ  DEFAULT NOW(),

    CONSTRAINT fk_ms_lot
        FOREIGN KEY (lot_id) REFERENCES raw_material_lot(lot_id),
    CONSTRAINT chk_ms_qty CHECK (
        input_qty_kg >= 0 AND selected_qty_kg >= 0 AND reject_qty_kg >= 0
        AND selected_qty_kg <= input_qty_kg
    )
);
CREATE INDEX IF NOT EXISTS idx_ms_lot  ON material_selection(lot_id);
CREATE INDEX IF NOT EXISTS idx_ms_date ON material_selection(selection_date DESC);
COMMENT ON TABLE material_selection IS '입고 후 선별 실적 — 선별율 자동 계산(GENERATED)';
COMMENT ON COLUMN material_selection.selection_rate_pct IS 'GENERATED: selected/input*100. 선별 효율 추세 분석에 사용';


-- ---------------------------------------------------------------------
-- 5. supplier_quality_score — 공급처 월별 품질 점수 (집계)
--    incoming_inspection 결과를 공급처×월 단위로 집계한 KPI 테이블.
--    배치(ETL) 또는 API 집계 호출로 갱신 (UNIQUE 로 멱등 UPSERT).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS supplier_quality_score (
    score_id          BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    supplier_code     VARCHAR(20)  NOT NULL,                  -- 공급처 코드 (FK)
    year_month        CHAR(7)      NOT NULL,                  -- 'YYYY-MM'
    total_lots        INT          DEFAULT 0,                 -- 해당 월 총 입고 LOT 수
    passed_lots       INT          DEFAULT 0,                 -- 합격 LOT 수
    pass_rate_pct     NUMERIC(5,2),                           -- 합격률(%)
    avg_freshness     NUMERIC(5,2),                           -- 평균 신선도 점수
    avg_water_content_pct NUMERIC(5,2),                       -- 평균 함수율(%)
    total_kg          NUMERIC(12,2),                          -- 총 입고량(kg)
    updated_at        TIMESTAMPTZ  DEFAULT NOW(),

    CONSTRAINT fk_sqs_supplier
        FOREIGN KEY (supplier_code) REFERENCES supplier(supplier_code),
    CONSTRAINT uq_sqs_supplier_month UNIQUE (supplier_code, year_month)
);
CREATE INDEX IF NOT EXISTS idx_sqs_supplier ON supplier_quality_score(supplier_code);
CREATE INDEX IF NOT EXISTS idx_sqs_month    ON supplier_quality_score(year_month DESC);
COMMENT ON TABLE supplier_quality_score IS '공급처 월별 품질 점수 집계 (공급처 랭킹/추세 분석)';


-- =====================================================================
-- 시드 데이터 (개발/시연용)
-- =====================================================================

-- 공급처 3건 (강원 배추 공급처) -----------------------------------------
INSERT INTO supplier
    (supplier_code, supplier_name, contact_name, phone, email, address, region, is_active, notes)
VALUES
    ('SUP01', '평창고랭지영농조합', '김배추', '033-330-1001', 'sup01@pcfarm.kr',
     '강원특별자치도 평창군 대관령면 횡계리 123', '강원 평창', TRUE, '대관령 고랭지 배추 주력'),
    ('SUP02', '정선산채영농법인', '이정선', '033-560-2002', 'sup02@jsfarm.kr',
     '강원특별자치도 정선군 임계면 송계리 45', '강원 정선', TRUE, '여름 배추 공급'),
    ('SUP03', '횡성친환경농장', '박횡성', '033-340-3003', 'sup03@hsfarm.kr',
     '강원특별자치도 횡성군 둔내면 우용리 78', '강원 횡성', TRUE, '친환경 인증 배추')
ON CONFLICT (supplier_code) DO NOTHING;

-- 원재료 LOT 5건 -------------------------------------------------------
INSERT INTO raw_material_lot
    (lot_id, intake_date, supplier_code, material_code, origin, quantity_kg,
     unit_price, vehicle_no, driver_name, received_by, lot_status, notes)
VALUES
    ('RM-20260520-001', '2026-05-20', 'SUP01', 'MAT-BC', '강원 평창', 3200.00,
     1150.00, '강원80가1234', '최운송', '한입고', 'PASSED', '대관령 고랭지 배추'),
    ('RM-20260521-001', '2026-05-21', 'SUP02', 'MAT-BC', '강원 정선', 2800.00,
     1080.00, '강원81나5678', '정기사', '한입고', 'PASSED', '정선 노지 배추'),
    ('RM-20260522-001', '2026-05-22', 'SUP01', 'MAT-BC', '강원 평창', 3100.00,
     1170.00, '강원80가1234', '최운송', '김입고', 'REJECTED', '함수율 초과 의심'),
    ('RM-20260523-001', '2026-05-23', 'SUP03', 'MAT-BC', '강원 횡성', 2500.00,
     1250.00, '강원82다9012', '박기사', '김입고', 'PASSED', '친환경 인증 배추'),
    ('RM-20260524-001', '2026-05-24', 'SUP02', 'MAT-BC', '강원 정선', 2950.00,
     1090.00, '강원81나5678', '정기사', '한입고', 'RECEIVED', '검사 대기')
ON CONFLICT (lot_id) DO NOTHING;

-- 입고 검사 5건 (LOT 1:1) ----------------------------------------------
INSERT INTO incoming_inspection
    (lot_id, inspector, inspection_date, cabbage_size, weight_avg_kg,
     appearance_grade, water_content_pct, freshness_score, qc_result,
     rejection_reason, corrective_action)
VALUES
    ('RM-20260520-001', '정품질', '2026-05-20', 'LARGE', 2.80,
     'A', 93.50, 9, 'PASS', NULL, NULL),
    ('RM-20260521-001', '정품질', '2026-05-21', 'MEDIUM', 2.30,
     'A', 92.10, 8, 'PASS', NULL, NULL),
    ('RM-20260522-001', '정품질', '2026-05-22', 'LARGE', 3.10,
     'C', 96.80, 4, 'FAIL', '함수율 96.8% 기준(95%) 초과, 외관 C등급',
     '공급처 통보 및 반품 처리'),
    ('RM-20260523-001', '김검사', '2026-05-23', 'MEDIUM', 2.45,
     'B', 91.20, 7, 'CONDITIONAL', '외관 일부 점무늬 발견',
     '선별 강화 조건부 합격'),
    ('RM-20260524-001', '김검사', '2026-05-24', 'MEDIUM', 2.35,
     'A', 92.50, 8, 'PASS', NULL, NULL)
ON CONFLICT DO NOTHING;

-- 선별 데이터 3건 (합격 LOT 대상) --------------------------------------
INSERT INTO material_selection
    (lot_id, selection_date, operator, input_qty_kg, selected_qty_kg,
     reject_qty_kg, reject_reason, notes)
VALUES
    ('RM-20260520-001', '2026-05-20', '선별조A', 3200.00, 3040.00, 160.00,
     'SIZE', '소형 배추 선별 제거'),
    ('RM-20260521-001', '2026-05-21', '선별조A', 2800.00, 2660.00, 140.00,
     'ROTTEN', '겉잎 부패 일부 제거'),
    ('RM-20260523-001', '2026-05-23', '선별조B', 2500.00, 2300.00, 200.00,
     'PEST', '병충해 점무늬 강화 선별')
ON CONFLICT DO NOTHING;

-- 공급처 월별 품질 점수 6건 (2개 공급처 × 3개월) ------------------------
INSERT INTO supplier_quality_score
    (supplier_code, year_month, total_lots, passed_lots, pass_rate_pct,
     avg_freshness, avg_water_content_pct, total_kg)
VALUES
    ('SUP01', '2026-03', 12, 11, 91.67, 8.5, 93.20, 38500.00),
    ('SUP01', '2026-04', 14, 13, 92.86, 8.7, 93.10, 44200.00),
    ('SUP01', '2026-05', 10,  9, 90.00, 8.6, 93.80, 31200.00),
    ('SUP02', '2026-03',  8,  8, 100.00, 8.2, 92.40, 22400.00),
    ('SUP02', '2026-04',  9,  8, 88.89, 8.0, 92.70, 25100.00),
    ('SUP02', '2026-05',  7,  7, 100.00, 8.3, 92.10, 19850.00)
ON CONFLICT (supplier_code, year_month) DO NOTHING;

-- =====================================================================
-- 검증 쿼리 (수동 확인용)
--   SELECT lot_id, supplier_code, lot_status FROM raw_material_lot ORDER BY intake_date;
--   SELECT supplier_code, year_month, pass_rate_pct FROM supplier_quality_score ORDER BY 1,2;
-- =====================================================================
