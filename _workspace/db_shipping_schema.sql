-- =====================================================================
-- 꽃순이김치 제조AI 스마트공장 MES — 포장출하관리 모듈 스키마
-- 프로젝트: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션
-- DBMS    : PostgreSQL 15+
-- 담당    : 포장출하관리 (포장실적 / 포장검사 / 출하주문 / LOT추적 / 클레임)
--
-- LOT 체인 (전 모듈 공통):
--   raw_material_lot(lot_id)
--        -> salting_lot   (process_result PROC03 의 lot_id 로 표현)
--        -> fermentation_lot (process_result PROC07 의 lot_id 로 표현)
--        -> packaging_lot(lot_id)            ← 본 스키마가 추가하는 포장 LOT
--        -> shipping_order(order_id)         ← 출하 단위(주문)
--
--   포장 LOT 형식 : PK-YYYYMMDD-NNN  (예: PK-20260524-001)
--   출하 주문번호  : SO-YYYYMMDD-NNN  (예: SO-20260524-001)
--   클레임 번호    : CL-YYYYMMDD-NNN  (예: CL-20260524-001)
--
--   packaging_lot.source_lot_id 는 발효 LOT(fermentation_lot)을 가리킨다.
--   본 프로젝트에서 발효/절임 LOT 은 별도 물리 마스터 테이블 없이
--   process_result(PROC07/PROC03) 및 raw_material_lot 으로 추적되므로
--   source_lot_id 는 FK 없이 VARCHAR 로 보존하여 Traceability 를 유지한다.
--
-- 테이블 구성:
--   1. packaging_lot          포장 LOT 마스터 (포장 실적 단위)
--   2. packaging_inspection   포장 검사 (출하 전 품질 검사)
--   3. shipping_order         출하 주문
--   4. shipping_lot_mapping   출하 주문 ↔ 포장 LOT 매핑
--   5. claim_record           클레임 관리 (역추적 + 원인분석)
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. packaging_lot — 포장 LOT 마스터
--    혼합/발효를 거친 산출물을 제품 단위로 포장한 1배치 = 1 LOT.
--    lot_status 워크플로우:
--      PACKED     포장 완료 (검사 전)
--      INSPECTED  출하 전 품질 검사 합격
--      SHIPPED    출하 완료
--      HOLD       보류 (검사 불합격 / 금속검출 / 클레임 연관 등)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS packaging_lot (
    lot_id            VARCHAR(30)  PRIMARY KEY,                  -- PK-YYYYMMDD-NNN
    source_lot_id     VARCHAR(30),                              -- fermentation_lot 연결(FK 없음 — 상단 주석 참조)
    packaging_date    DATE         NOT NULL DEFAULT CURRENT_DATE,-- 포장일
    product_code      VARCHAR(20)  NOT NULL,                    -- 제품 코드 (KIM-BC-300 등)
    line_no           VARCHAR(10),                              -- 포장 라인 번호 (LINE-01 등)
    operator          VARCHAR(50),                              -- 포장 작업자 (성명/사번 자유입력)
    input_qty_kg      DECIMAL(10,2) NOT NULL,                   -- 투입 수량(kg)
    output_units      INTEGER      NOT NULL,                    -- 포장 완료 단위 수
    defect_units      INTEGER      DEFAULT 0,                   -- 포장 불량 단위 수
    metal_detection   BOOLEAN      DEFAULT FALSE,               -- 금속검출 통과 여부(TRUE=통과)
    lot_status        VARCHAR(20)  DEFAULT 'PACKED',            -- PACKED/INSPECTED/SHIPPED/HOLD
    barcode           VARCHAR(50)  UNIQUE,                      -- 바코드/QR (제품 추적)
    created_at        TIMESTAMPTZ  DEFAULT NOW(),

    CONSTRAINT chk_pklot_status CHECK (
        lot_status IN ('PACKED','INSPECTED','SHIPPED','HOLD')
    ),
    CONSTRAINT chk_pklot_product CHECK (
        product_code IN ('KIM-BC-300','KIM-BC-500','KIM-BC-1000','KIM-BC-2000','KIM-BC-5000')
    ),
    CONSTRAINT chk_pklot_qty CHECK (
        input_qty_kg >= 0 AND output_units >= 0 AND
        (defect_units IS NULL OR defect_units >= 0)
    )
);
-- 핵심 인덱스: 포장일 + 제품 (일별/제품별 실적 집계)
CREATE INDEX IF NOT EXISTS idx_pklot_date_product ON packaging_lot(packaging_date DESC, product_code);
CREATE INDEX IF NOT EXISTS idx_pklot_source       ON packaging_lot(source_lot_id);
CREATE INDEX IF NOT EXISTS idx_pklot_status       ON packaging_lot(lot_status);
COMMENT ON TABLE packaging_lot IS '포장 LOT 마스터 (제품 단위 포장 실적, 금속검출 결과)';
COMMENT ON COLUMN packaging_lot.source_lot_id IS '직전 발효 LOT(fermentation_lot). LOT 역추적 체인의 연결고리';
COMMENT ON COLUMN packaging_lot.metal_detection IS 'TRUE=금속검출 통과(정상), FALSE=미검사/검출됨';

-- ---------------------------------------------------------------------
-- 2. packaging_inspection — 포장 검사 (출하 전 품질 검사)
--    포장 LOT 별 출하 전 최종 품질 판정. 1 LOT 당 N건 가능(재검 포함).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS packaging_inspection (
    inspection_id       BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lot_id              VARCHAR(30)  NOT NULL REFERENCES packaging_lot(lot_id) ON DELETE CASCADE,
    inspector           VARCHAR(50)  NOT NULL,                  -- 검사자
    inspection_date     DATE         NOT NULL DEFAULT CURRENT_DATE,
    -- 검사 항목
    salinity_pct        DECIMAL(5,2),                           -- 염도(%)
    acidity_ph          DECIMAL(4,2),                           -- pH
    appearance_score    INTEGER,                                -- 외관 점수(1~5)
    fermentation_level  VARCHAR(10),                            -- FRESH/MILD/RIPE/OVERRIPE
    net_weight_g        DECIMAL(8,2),                           -- 내용물 중량(g)
    packaging_integrity BOOLEAN      DEFAULT TRUE,              -- 포장 밀봉 정상 여부
    -- 판정
    qc_result           VARCHAR(10)  NOT NULL,                  -- PASS/FAIL/HOLD
    fail_reason         TEXT,                                   -- 불합격 사유
    corrective_action   TEXT,                                   -- 조치 사항
    created_at          TIMESTAMPTZ  DEFAULT NOW(),

    CONSTRAINT chk_pkinsp_appearance CHECK (
        appearance_score IS NULL OR (appearance_score BETWEEN 1 AND 5)
    ),
    CONSTRAINT chk_pkinsp_result CHECK (qc_result IN ('PASS','FAIL','HOLD')),
    CONSTRAINT chk_pkinsp_ferment CHECK (
        fermentation_level IS NULL OR
        fermentation_level IN ('FRESH','MILD','RIPE','OVERRIPE')
    )
);
CREATE INDEX IF NOT EXISTS idx_pkinsp_lot    ON packaging_inspection(lot_id);
CREATE INDEX IF NOT EXISTS idx_pkinsp_result ON packaging_inspection(qc_result);
CREATE INDEX IF NOT EXISTS idx_pkinsp_date   ON packaging_inspection(inspection_date DESC);
COMMENT ON TABLE packaging_inspection IS '포장 LOT 출하 전 품질 검사 (염도/pH/외관/밀봉 + PASS/FAIL/HOLD 판정)';

-- ---------------------------------------------------------------------
-- 3. shipping_order — 출하 주문
--    고객 주문 단위. 승인(approved_by) 후 출하 처리(SHIPPED) 가능.
--    order_status 워크플로우:
--      PENDING   주문 등록 (승인/피킹 전)
--      PICKING   LOT 할당/피킹 진행 중
--      SHIPPED   출하 완료
--      DELIVERED 배송 완료
--      CANCELLED 주문 취소
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shipping_order (
    order_id          BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_no          VARCHAR(30)  UNIQUE NOT NULL,             -- SO-YYYYMMDD-NNN
    customer_name     VARCHAR(100) NOT NULL,                    -- 고객명
    customer_code     VARCHAR(20),                              -- 고객 코드
    ship_date         DATE         NOT NULL,                    -- 출하 예정/완료일
    delivery_address  TEXT,                                     -- 배송지
    product_code      VARCHAR(20)  NOT NULL,                    -- 제품 코드
    ordered_units     INTEGER      NOT NULL,                    -- 주문 단위 수
    shipped_units     INTEGER      DEFAULT 0,                   -- 출하 완료 단위 수
    order_status      VARCHAR(20)  DEFAULT 'PENDING',           -- PENDING/PICKING/SHIPPED/DELIVERED/CANCELLED
    shipping_company  VARCHAR(50),                              -- 택배/운송사
    tracking_no       VARCHAR(50),                              -- 운송장 번호
    created_by        VARCHAR(50),                              -- 주문 등록자
    approved_by       VARCHAR(50),                              -- 출하 승인자(MANAGER/ADMIN)
    approved_at       TIMESTAMPTZ,                              -- 승인 일시
    created_at        TIMESTAMPTZ  DEFAULT NOW(),

    CONSTRAINT chk_so_status CHECK (
        order_status IN ('PENDING','PICKING','SHIPPED','DELIVERED','CANCELLED')
    ),
    CONSTRAINT chk_so_units CHECK (
        ordered_units >= 0 AND (shipped_units IS NULL OR shipped_units >= 0)
    )
);
CREATE INDEX IF NOT EXISTS idx_so_status     ON shipping_order(order_status);
CREATE INDEX IF NOT EXISTS idx_so_ship_date  ON shipping_order(ship_date DESC);
CREATE INDEX IF NOT EXISTS idx_so_customer   ON shipping_order(customer_code);
COMMENT ON TABLE shipping_order IS '출하 주문 (고객 주문 단위, 승인 후 출하 처리)';
COMMENT ON COLUMN shipping_order.approved_by IS '출하 승인자. MANAGER/ADMIN 권한만 승인 가능';

-- ---------------------------------------------------------------------
-- 4. shipping_lot_mapping — 출하 주문 ↔ 포장 LOT 매핑
--    1 주문은 여러 포장 LOT 에서 할당될 수 있다(N:M). LOT 추적의 핵심.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shipping_lot_mapping (
    mapping_id        BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id          BIGINT       NOT NULL REFERENCES shipping_order(order_id) ON DELETE CASCADE,
    lot_id            VARCHAR(30)  NOT NULL REFERENCES packaging_lot(lot_id),
    allocated_units   INTEGER      NOT NULL,                    -- 해당 LOT 에서 할당된 단위 수
    created_at        TIMESTAMPTZ  DEFAULT NOW(),

    CONSTRAINT uq_slmap_order_lot UNIQUE (order_id, lot_id),
    CONSTRAINT chk_slmap_units CHECK (allocated_units > 0)
);
CREATE INDEX IF NOT EXISTS idx_slmap_order ON shipping_lot_mapping(order_id);
CREATE INDEX IF NOT EXISTS idx_slmap_lot   ON shipping_lot_mapping(lot_id);
COMMENT ON TABLE shipping_lot_mapping IS '출하 주문-포장 LOT 매핑 (LOT 추적 / 출하 LOT 구성)';

-- ---------------------------------------------------------------------
-- 5. claim_record — 클레임 관리
--    고객 클레임 접수 → 원인분석 → 조치 → 재발방지. lot_id 로 역추적.
--    status 워크플로우: OPEN -> INVESTIGATING -> RESOLVED -> CLOSED
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS claim_record (
    claim_id              BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_no              VARCHAR(30)  UNIQUE,                  -- CL-YYYYMMDD-NNN
    order_id              BIGINT       REFERENCES shipping_order(order_id),
    lot_id                VARCHAR(30),                          -- 해당 포장 LOT (역추적용, FK 없음)
    claim_date            DATE         NOT NULL DEFAULT CURRENT_DATE,
    customer_name         VARCHAR(100),                         -- 클레임 고객명
    claim_type            VARCHAR(30)  NOT NULL,                -- QUALITY/DELIVERY/FOREIGN/LABELING/OTHER
    claim_content         TEXT         NOT NULL,                -- 클레임 내용
    severity              VARCHAR(10)  DEFAULT 'NORMAL',        -- MINOR/NORMAL/MAJOR/CRITICAL
    root_cause            TEXT,                                 -- 원인 분석
    corrective_action     TEXT,                                 -- 조치 사항
    recurrence_prevention TEXT,                                 -- 재발 방지 대책
    status                VARCHAR(20)  DEFAULT 'OPEN',          -- OPEN/INVESTIGATING/RESOLVED/CLOSED
    resolved_at           TIMESTAMPTZ,                          -- 처리 완료 일시
    resolved_by           VARCHAR(50),                          -- 처리자
    created_at            TIMESTAMPTZ  DEFAULT NOW(),

    CONSTRAINT chk_claim_type CHECK (
        claim_type IN ('QUALITY','DELIVERY','FOREIGN','LABELING','OTHER')
    ),
    CONSTRAINT chk_claim_severity CHECK (
        severity IN ('MINOR','NORMAL','MAJOR','CRITICAL')
    ),
    CONSTRAINT chk_claim_status CHECK (
        status IN ('OPEN','INVESTIGATING','RESOLVED','CLOSED')
    )
);
CREATE INDEX IF NOT EXISTS idx_claim_type   ON claim_record(claim_type);
CREATE INDEX IF NOT EXISTS idx_claim_status ON claim_record(status);
CREATE INDEX IF NOT EXISTS idx_claim_date   ON claim_record(claim_date DESC);
CREATE INDEX IF NOT EXISTS idx_claim_lot    ON claim_record(lot_id);
COMMENT ON TABLE claim_record IS '고객 클레임 관리 (접수→원인분석→조치→재발방지, LOT 역추적)';

-- =====================================================================
-- 샘플 데이터
-- =====================================================================

-- 1. packaging_lot 8건 (다양한 제품 코드, 상태)
--    source_lot_id 는 발효 LOT(FE-YYYYMMDD-NNN) 형식으로 LOT 체인 연결
INSERT INTO packaging_lot
    (lot_id, source_lot_id, packaging_date, product_code, line_no, operator,
     input_qty_kg, output_units, defect_units, metal_detection, lot_status, barcode)
VALUES
    ('PK-20260524-001', 'FE-20260521-001', '2026-05-24', 'KIM-BC-500',  'LINE-01', '김포장', 2100.00, 4150,  8, TRUE, 'SHIPPED',   'BC500-20260524-001'),
    ('PK-20260524-002', 'FE-20260521-002', '2026-05-24', 'KIM-BC-300',  'LINE-01', '김포장', 1200.00, 3950, 12, TRUE, 'INSPECTED', 'BC300-20260524-002'),
    ('PK-20260524-003', 'FE-20260521-003', '2026-05-24', 'KIM-BC-1000', 'LINE-02', '박포장', 3000.00, 2960,  5, TRUE, 'PACKED',    'BC1000-20260524-003'),
    ('PK-20260523-001', 'FE-20260520-001', '2026-05-23', 'KIM-BC-2000', 'LINE-02', '박포장', 4000.00, 1980,  3, TRUE, 'SHIPPED',   'BC2000-20260523-001'),
    ('PK-20260523-002', 'FE-20260520-002', '2026-05-23', 'KIM-BC-500',  'LINE-01', '김포장', 1500.00, 2970, 18, TRUE, 'INSPECTED', 'BC500-20260523-002'),
    ('PK-20260523-003', 'FE-20260520-003', '2026-05-23', 'KIM-BC-5000', 'LINE-03', '이포장', 5000.00,  990,  2, TRUE, 'SHIPPED',   'BC5000-20260523-003'),
    ('PK-20260522-001', 'FE-20260519-001', '2026-05-22', 'KIM-BC-300',  'LINE-01', '김포장', 900.00,  2960, 40, FALSE,'HOLD',      'BC300-20260522-001'),
    ('PK-20260522-002', 'FE-20260519-002', '2026-05-22', 'KIM-BC-1000', 'LINE-02', '박포장', 2500.00, 2470,  6, TRUE, 'INSPECTED', 'BC1000-20260522-002');

-- 2. packaging_inspection 6건
INSERT INTO packaging_inspection
    (lot_id, inspector, inspection_date, salinity_pct, acidity_ph, appearance_score,
     fermentation_level, net_weight_g, packaging_integrity, qc_result, fail_reason, corrective_action)
VALUES
    ('PK-20260524-001', '정검사', '2026-05-24', 2.10, 4.30, 5, 'MILD',  502.50, TRUE,  'PASS', NULL, NULL),
    ('PK-20260524-002', '정검사', '2026-05-24', 2.05, 4.25, 4, 'FRESH', 301.20, TRUE,  'PASS', NULL, NULL),
    ('PK-20260523-001', '한검사', '2026-05-23', 2.20, 4.45, 5, 'RIPE', 2010.00, TRUE,  'PASS', NULL, NULL),
    ('PK-20260523-002', '한검사', '2026-05-23', 2.15, 4.35, 4, 'MILD',  498.30, TRUE,  'PASS', NULL, NULL),
    ('PK-20260522-001', '정검사', '2026-05-22', 2.30, 4.80, 2, 'OVERRIPE', 298.00, FALSE, 'FAIL',
        '밀봉 불량 및 과숙 진행(pH 4.80) — 외관 점수 2점', '전량 보류(HOLD) 처리, 해당 LINE-01 밀봉기 점검 의뢰'),
    ('PK-20260522-002', '한검사', '2026-05-22', 2.18, 4.40, 4, 'RIPE', 1005.00, TRUE,  'PASS', NULL, NULL);

-- 3. shipping_order 5건 (PENDING 2, SHIPPED 2, DELIVERED 1)
INSERT INTO shipping_order
    (order_no, customer_name, customer_code, ship_date, delivery_address, product_code,
     ordered_units, shipped_units, order_status, shipping_company, tracking_no,
     created_by, approved_by, approved_at)
VALUES
    ('SO-20260524-001', '롯데마트 평창점',   'CUST01', '2026-05-25', '강원 평창군 ○○로 12',   'KIM-BC-1000', 2000,    0, 'PENDING',   NULL,      NULL,            'sales01', NULL,      NULL),
    ('SO-20260524-002', '이마트 강릉점',     'CUST02', '2026-05-26', '강원 강릉시 △△대로 88',  'KIM-BC-300',  3500,    0, 'PENDING',   NULL,      NULL,            'sales02', NULL,      NULL),
    ('SO-20260524-003', '쿠팡 물류센터',     'CUST03', '2026-05-24', '경기 이천시 ▽▽로 200',   'KIM-BC-500',  4000, 4000, 'SHIPPED',   'CJ대한통운', '6012345678', 'sales01', 'manager01','2026-05-24 09:30+09'),
    ('SO-20260523-001', '하나로마트 원주점', 'CUST04', '2026-05-23', '강원 원주시 □□길 5',     'KIM-BC-2000', 1900, 1900, 'SHIPPED',   '한진택배',  '4598761230', 'sales02', 'manager01','2026-05-23 10:00+09'),
    ('SO-20260522-001', '신세계 본점 식품관','CUST05', '2026-05-22', '서울 중구 소공로 63',     'KIM-BC-5000',  900,  900, 'DELIVERED', '로젠택배',  '7711223344', 'sales01', 'admin',    '2026-05-22 08:30+09');

-- 4. shipping_lot_mapping 5건 (출하/배송 완료 주문에 포장 LOT 매핑)
INSERT INTO shipping_lot_mapping (order_id, lot_id, allocated_units)
VALUES
    (3, 'PK-20260524-001', 4000),   -- SO-20260524-003(쿠팡) <- KIM-BC-500 LOT
    (4, 'PK-20260523-001', 1900),   -- SO-20260523-001(원주) <- KIM-BC-2000 LOT
    (5, 'PK-20260523-003',  900),   -- SO-20260522-001(신세계) <- KIM-BC-5000 LOT
    (1, 'PK-20260524-003', 2000),   -- SO-20260524-001(롯데) <- KIM-BC-1000 LOT (PENDING, 사전 할당)
    (2, 'PK-20260524-002', 3500);   -- SO-20260524-002(이마트) <- KIM-BC-300 LOT (PENDING, 사전 할당)

-- 5. claim_record 3건 (QUALITY 2, DELIVERY 1)
INSERT INTO claim_record
    (claim_no, order_id, lot_id, claim_date, customer_name, claim_type, claim_content,
     severity, root_cause, corrective_action, recurrence_prevention, status, resolved_at, resolved_by)
VALUES
    ('CL-20260523-001', 5, 'PK-20260523-003', '2026-05-23', '신세계 본점 식품관', 'QUALITY',
        '5kg 업소용 김치에서 신맛이 과하다는 고객 클레임 접수. pH 측정 결과 출하 기준 하회 의심.',
        'MAJOR',
        '발효 LOT(FE-20260520-003) 숙성시간 과다(목표 +6h)로 산도 상승. 출하 검사 시 RIPE 판정되었으나 배송 중 추가 숙성 진행.',
        '잔여 동일 LOT 재고 전량 회수 및 출하 보류. 고객 교환 처리 완료.',
        '발효 완료 시점 ML 예측 알림 임계값 강화(목표시간 -2h 사전 경보). 5kg 업소용은 출하 직전 재검사 의무화.',
        'RESOLVED', '2026-05-24 14:00+09', 'qc01'),
    ('CL-20260522-001', NULL, 'PK-20260522-001', '2026-05-22', '온라인 직판 고객', 'QUALITY',
        '300g 제품 포장 밀봉 불량으로 국물 누수 발생. 수령 시 포장재 손상 확인.',
        'NORMAL',
        'LINE-01 밀봉기 히터 온도 저하로 실링 강도 미달. 해당 LOT 검사에서 FAIL/HOLD 판정된 물량 일부가 직판 채널로 유출.',
        '해당 LOT 전량 출하 중단(HOLD). 고객 전액 환불 및 신규 제품 재발송.',
        'HOLD LOT 의 채널 유출 차단 시스템 락 추가. 밀봉기 일일 점검 체크리스트 운영.',
        'INVESTIGATING', NULL, NULL),
    ('CL-20260524-001', 4, 'PK-20260523-001', '2026-05-24', '하나로마트 원주점', 'DELIVERY',
        '주문 1900개 중 지연 배송으로 진열 일정 차질. 운송사 배송 지연 클레임.',
        'MINOR',
        '한진택배 강원권 물량 폭주로 1일 배송 지연.',
        '익일 보상 배송 및 운송사 지연 사유서 수령.',
        '강원권 주요 거래처 출하는 D-1 출고 원칙 적용, 운송사 이원화 검토.',
        'CLOSED', '2026-05-24 16:30+09', 'sales02');

-- =====================================================================
-- 뷰: 일별 포장/출하 실적 요약 (대시보드/분석용)
-- =====================================================================
CREATE OR REPLACE VIEW shipping_daily_summary AS
SELECT
    pl.packaging_date                                   AS work_date,
    pl.product_code,
    COUNT(DISTINCT pl.lot_id)                           AS lot_count,
    SUM(pl.output_units)                                AS total_output_units,
    SUM(pl.defect_units)                                AS total_defect_units,
    ROUND(100.0 * SUM(pl.defect_units)
          / NULLIF(SUM(pl.output_units + pl.defect_units), 0), 2) AS defect_rate_pct,
    SUM(pl.input_qty_kg)                                AS total_input_kg
FROM packaging_lot pl
GROUP BY pl.packaging_date, pl.product_code;
COMMENT ON VIEW shipping_daily_summary IS '일별/제품별 포장 실적 집계 (생산량/불량률)';

-- 뷰: 클레임 유형별 집계 (최근 90일 분석용)
CREATE OR REPLACE VIEW claim_type_summary AS
SELECT
    claim_type,
    COUNT(*)                                            AS claim_count,
    COUNT(*) FILTER (WHERE status IN ('OPEN','INVESTIGATING')) AS open_count,
    COUNT(*) FILTER (WHERE severity IN ('MAJOR','CRITICAL'))   AS severe_count
FROM claim_record
WHERE claim_date >= CURRENT_DATE - INTERVAL '90 days'
GROUP BY claim_type;
COMMENT ON VIEW claim_type_summary IS '최근 90일 클레임 유형별 집계 (클레임 분석)';

-- =====================================================================
-- 완료
-- =====================================================================
