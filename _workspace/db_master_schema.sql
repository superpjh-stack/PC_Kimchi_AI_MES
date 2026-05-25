-- =============================================================================
-- 꽃순이김치 제조AI MES — 기준정보관리 모듈 스키마 (Master Data)
-- Project: SF26179540 | 평창꽃순이(주) | 로뎀솔루션
-- Module : 기준정보관리 (품질기준 / 작업표준(SOP) / 코드 / 공급업체)
-- Target : PostgreSQL 14+ (운영DB), pgvector 연동(별도 Vector DB 서버)
-- Plan ref: docs/01-plan/features/pm3-process-data-kpi-system.plan.md (Section 7)
-- =============================================================================

-- =============================================================================
-- 1. quality_standard — 품질 기준 (절임/발효/출하 공정별 기준값)
--    Plan 7.1: 공정별 정상 범위 / 경고 범위 / 단위 / 측정 방법 관리
-- =============================================================================
CREATE TABLE IF NOT EXISTS quality_standard (
    id                  BIGSERIAL PRIMARY KEY,
    process_code        VARCHAR(10)  NOT NULL,        -- 공정 코드 (PROC01~PROC09, code_master 참조)
    standard_item       VARCHAR(100) NOT NULL,        -- 기준 항목 (예: 발효 pH, 절임 염도)
    normal_min          DECIMAL(10,3),                -- 정상 범위 하한
    normal_max          DECIMAL(10,3),                -- 정상 범위 상한
    warning_min         DECIMAL(10,3),                -- 경고 범위 하한
    warning_max         DECIMAL(10,3),                -- 경고 범위 상한
    unit                VARCHAR(20),                  -- 단위 (°C, %, pH, 시간 등)
    measurement_method  VARCHAR(200),                 -- 측정 방법 (IoT 센서, 수동 기록 등)
    is_active           BOOLEAN     NOT NULL DEFAULT TRUE,
    valid_from          DATE        NOT NULL DEFAULT CURRENT_DATE,
    valid_to            DATE,                          -- NULL = 현행
    created_by          VARCHAR(50),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- 정합성: 정상 범위가 경고 범위 안에 포함되어야 함
    CONSTRAINT chk_qs_normal_range  CHECK (normal_min  IS NULL OR normal_max  IS NULL OR normal_min  <= normal_max),
    CONSTRAINT chk_qs_warning_range CHECK (warning_min IS NULL OR warning_max IS NULL OR warning_min <= warning_max)
);

-- 인덱스: 공정별 활성 기준 조회 (Plan 요구)
CREATE INDEX IF NOT EXISTS idx_qs_process_active ON quality_standard(process_code, is_active);
CREATE INDEX IF NOT EXISTS idx_qs_item           ON quality_standard(standard_item);

COMMENT ON TABLE  quality_standard IS '공정별 품질 기준값 (절임/발효/출하). 정상/경고 범위로 이상 감지에 사용';
COMMENT ON COLUMN quality_standard.process_code IS 'code_master(PROCESS) 참조 공정 코드';


-- =============================================================================
-- 2. sop_document — SOP/표준문서 메타데이터 (pgvector 임베딩 연동)
--    Plan 7.2: 작업표준서 업로드 → 임베딩 → 활성화 프로세스의 메타데이터 마스터
--    실제 임베딩 벡터는 Vector DB의 document_embeddings 테이블에 적재됨 (doc_id로 연결)
-- =============================================================================
CREATE TABLE IF NOT EXISTS sop_document (
    doc_id          VARCHAR(50)  PRIMARY KEY,          -- 문서 ID (예: PROC03_SOP_v1.2_20260101)
    doc_type        VARCHAR(20)  NOT NULL,             -- SOP/QC_STANDARD/HACCP/EQUIPMENT_MANUAL/CLAIM_RESPONSE
    process_codes   TEXT[]       DEFAULT '{}',         -- 해당 공정 코드 배열 (다중 선택)
    title           VARCHAR(200) NOT NULL,             -- 문서 제목
    version         VARCHAR(20)  NOT NULL,             -- 버전 (v1.0, v1.2 등)
    file_path       VARCHAR(500),                      -- 원본 파일 경로 (S3/로컬)
    chunk_count     INTEGER     NOT NULL DEFAULT 0,    -- 임베딩된 chunk 수
    embed_status    VARCHAR(20) NOT NULL DEFAULT 'PENDING', -- PENDING/PROCESSING/COMPLETED/FAILED
    is_active       BOOLEAN     NOT NULL DEFAULT FALSE,-- 활성화 여부 (검토 후 true)
    valid_from      DATE,                              -- 유효 시작일
    valid_to        DATE,                              -- 유효 종료일 (NULL = 현행)
    created_by      VARCHAR(50),                       -- 업로드자
    approved_by     VARCHAR(50),                       -- 승인자
    approved_at     TIMESTAMPTZ,                       -- 승인일시
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_sop_doc_type CHECK (
        doc_type IN ('SOP','QC_STANDARD','HACCP','EQUIPMENT_MANUAL','CLAIM_RESPONSE')
    ),
    CONSTRAINT chk_sop_embed_status CHECK (
        embed_status IN ('PENDING','PROCESSING','COMPLETED','FAILED')
    )
);

-- 인덱스: 문서 유형별 활성 문서 조회 (Plan 요구)
CREATE INDEX IF NOT EXISTS idx_sop_type_active ON sop_document(doc_type, is_active);
-- GIN 인덱스: 공정 코드 배열 검색 (특정 공정 관련 문서 조회)
CREATE INDEX IF NOT EXISTS idx_sop_process_codes ON sop_document USING GIN (process_codes);

COMMENT ON TABLE  sop_document IS 'SOP/표준문서 메타데이터. doc_id로 Vector DB의 document_embeddings와 연결';
COMMENT ON COLUMN sop_document.embed_status IS '임베딩 처리 상태. 백그라운드 태스크가 갱신';


-- =============================================================================
-- 3. code_master — 코드 마스터 (공통 코드 체계)
--    Plan 7.3: 공정/제품/불량/원재료/공급처/단위 코드 관리
-- =============================================================================
CREATE TABLE IF NOT EXISTS code_master (
    id              BIGSERIAL PRIMARY KEY,
    code_group      VARCHAR(20)  NOT NULL,             -- PROCESS/PRODUCT/DEFECT/MATERIAL/SUPPLIER/UNIT
    code            VARCHAR(30)  NOT NULL,             -- 코드값 (예: PROC03, DEF-001)
    code_name       VARCHAR(100) NOT NULL,             -- 코드명 (한글)
    code_name_en    VARCHAR(100),                      -- 코드명 (영문)
    sort_order      INTEGER     NOT NULL DEFAULT 0,    -- 표시 순서
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    description     TEXT,                              -- 코드 설명
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_cm_code_group CHECK (
        code_group IN ('PROCESS','PRODUCT','DEFECT','MATERIAL','SUPPLIER','UNIT')
    )
);

-- 인덱스: 코드 그룹별 활성 코드 조회 (Plan 요구)
CREATE INDEX IF NOT EXISTS idx_cm_group_active ON code_master(code_group, is_active);
-- UNIQUE: 그룹+코드 중복 방지 (Plan 요구)
CREATE UNIQUE INDEX IF NOT EXISTS uidx_cm_group_code ON code_master(code_group, code);

COMMENT ON TABLE code_master IS '공통 코드 마스터. (code_group, code) 조합이 유일';


-- =============================================================================
-- 4. supplier — 공급업체 마스터
--    Plan: 원재료관리 공급처 품질분석 / 입고 AI Agent 연계
-- =============================================================================
CREATE TABLE IF NOT EXISTS supplier (
    supplier_id     BIGSERIAL PRIMARY KEY,
    supplier_code   VARCHAR(30)  NOT NULL UNIQUE,      -- 공급업체 코드 (예: SUP-001)
    supplier_name   VARCHAR(100) NOT NULL,             -- 공급업체명
    contact         VARCHAR(50),                       -- 연락처
    address         VARCHAR(300),                      -- 주소
    material_types  TEXT[]       DEFAULT '{}',         -- 공급 원재료 유형 배열 (MAT-BC 등)
    quality_grade   VARCHAR(1)   DEFAULT 'B',          -- 품질 등급 A/B/C/D
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_sup_grade CHECK (quality_grade IN ('A','B','C','D'))
);

-- 인덱스: 활성 공급업체 / 등급 필터 조회
CREATE INDEX IF NOT EXISTS idx_sup_active ON supplier(is_active);
CREATE INDEX IF NOT EXISTS idx_sup_grade  ON supplier(quality_grade);
-- GIN 인덱스: 공급 원재료 유형 배열 검색
CREATE INDEX IF NOT EXISTS idx_sup_material_types ON supplier USING GIN (material_types);

COMMENT ON TABLE supplier IS '공급업체 마스터. 품질 등급 및 공급 원재료 유형 관리';


-- =============================================================================
-- updated_at 자동 갱신 트리거 (4개 테이블 공통)
-- =============================================================================
CREATE OR REPLACE FUNCTION trg_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['quality_standard','sop_document','code_master','supplier'] LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS set_updated_at ON %I; '
            'CREATE TRIGGER set_updated_at BEFORE UPDATE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();', t, t);
    END LOOP;
END $$;


-- =============================================================================
-- 시드 데이터 (Plan 7.3 코드 체계 기준)
-- =============================================================================

-- 공정 코드 (PROCESS)
INSERT INTO code_master (code_group, code, code_name, sort_order, description) VALUES
    ('PROCESS','PROC01','입고/보관',1,'원재료 입고 및 창고 보관'),
    ('PROCESS','PROC02','절단/전처리',2,'배추 절단 및 전처리'),
    ('PROCESS','PROC03','세척/절임',3,'세척 및 소금 절임'),
    ('PROCESS','PROC04','세척/선별',4,'절임 후 세척 및 불량 선별'),
    ('PROCESS','PROC05','탈수',5,'탈수 처리'),
    ('PROCESS','PROC06','혼합',6,'양념 혼합'),
    ('PROCESS','PROC07','숙성/발효',7,'발효실 숙성'),
    ('PROCESS','PROC08','금속검출',8,'금속 이물질 검출'),
    ('PROCESS','PROC09','포장/출하',9,'포장 및 출하')
ON CONFLICT (code_group, code) DO NOTHING;

-- 불량 코드 (DEFECT)
INSERT INTO code_master (code_group, code, code_name, sort_order, description) VALUES
    ('DEFECT','DEF-001','부패/변질',1,'입고/발효'),
    ('DEFECT','DEF-002','이물질(금속)',2,'금속검출'),
    ('DEFECT','DEF-003','이물질(비금속)',3,'선별'),
    ('DEFECT','DEF-004','과발효',4,'발효'),
    ('DEFECT','DEF-005','미발효',5,'발효'),
    ('DEFECT','DEF-006','중량 불량',6,'포장'),
    ('DEFECT','DEF-007','포장 불량(밀봉)',7,'포장'),
    ('DEFECT','DEF-008','염도 이상',8,'절임/혼합'),
    ('DEFECT','DEF-009','외관 불량',9,'선별'),
    ('DEFECT','DEF-010','기타',10,'전 공정')
ON CONFLICT (code_group, code) DO NOTHING;

-- 원재료 코드 (MATERIAL)
INSERT INTO code_master (code_group, code, code_name, sort_order) VALUES
    ('MATERIAL','MAT-BC','배추',1),
    ('MATERIAL','MAT-MU','무',2),
    ('MATERIAL','MAT-GO','고추가루',3),
    ('MATERIAL','MAT-GA','마늘',4),
    ('MATERIAL','MAT-GI','생강',5),
    ('MATERIAL','MAT-JO','젓갈류',6),
    ('MATERIAL','MAT-SO','소금',7),
    ('MATERIAL','MAT-PA','파',8)
ON CONFLICT (code_group, code) DO NOTHING;

-- 제품 코드 (PRODUCT) — §7.3 제품 코드 체계 (기획서 2.4 포장 단위 기준)
INSERT INTO code_master (code_group, code, code_name, code_name_en, sort_order, description) VALUES
    ('PRODUCT','KIM-BC-300', '배추김치 300g',  'Baechu Kimchi 300g',  1, '소포장 — 가정용'),
    ('PRODUCT','KIM-BC-500', '배추김치 500g',  'Baechu Kimchi 500g',  2, '표준 소포장'),
    ('PRODUCT','KIM-BC-1000','배추김치 1kg',   'Baechu Kimchi 1kg',   3, '표준 대포장'),
    ('PRODUCT','KIM-BC-2000','배추김치 2kg',   'Baechu Kimchi 2kg',   4, '업소용'),
    ('PRODUCT','KIM-BC-5000','배추김치 5kg',   'Baechu Kimchi 5kg',   5, '대용량 업소용')
ON CONFLICT (code_group, code) DO NOTHING;

-- 단위 코드 (UNIT)
INSERT INTO code_master (code_group, code, code_name, sort_order) VALUES
    ('UNIT','C','섭씨온도',1),
    ('UNIT','PCT','퍼센트',2),
    ('UNIT','PH','pH',3),
    ('UNIT','HR','시간',4),
    ('UNIT','KG','킬로그램',5)
ON CONFLICT (code_group, code) DO NOTHING;

-- 절임/발효/출하 품질 기준 (Plan 7.1)
INSERT INTO quality_standard
    (process_code, standard_item, normal_min, normal_max, warning_min, warning_max, unit, measurement_method)
VALUES
    ('PROC03','절임 온도',  5.0, 20.0,  5.0, 25.0, '°C',  'IoT 센서'),
    ('PROC03','절임 염도',  2.0,  3.5,  1.5,  4.0, '%',   'IoT 센서'),
    ('PROC03','절임 pH',    5.0,  7.0,  4.5,  7.5, 'pH',  'IoT 센서'),
    ('PROC03','절임 시간', 12.0, 24.0, 10.0, 36.0, '시간','수동 기록'),
    ('PROC03','세척수 온도',5.0, 15.0,  3.0, 20.0, '°C',  'IoT 센서'),
    ('PROC07','발효 온도',  0.0, 10.0, -2.0, 15.0, '°C',  'IoT 센서'),
    ('PROC07','발효 pH',    4.0,  4.5,  3.8,  5.0, 'pH',  'IoT 센서'),
    ('PROC07','산도',       0.6,  1.0,  0.4,  1.3, '%',   'IoT 센서'),
    ('PROC07','발효 염도',  1.5,  2.5,  1.2,  3.0, '%',   'IoT 센서'),
    ('PROC09','완성품 pH',  3.8,  4.8,  3.5,  5.0, 'pH',  'pH 측정기'),
    ('PROC09','완성품 산도',0.5,  1.2,  0.4,  1.5, '%',   '적정법'),
    ('PROC09','냉장 보관 온도',0.0,10.0,-2.0, 12.0,'°C',  '온도계(CCP-2)'),
    -- §7.1 출하 완성품 추가 기준 (범위형 항목만 — 건수·합격여부 형식은 quality_standard 모델 부적합)
    ('PROC09','완성품 염도',  1.5,  3.0,  1.2,  3.5, '%',   '염도계')
ON CONFLICT DO NOTHING;

-- 공급업체 예시
INSERT INTO supplier (supplier_code, supplier_name, contact, address, material_types, quality_grade) VALUES
    ('SUP-001','대왕농산','033-330-1001','강원도 평창군', ARRAY['MAT-BC','MAT-MU'], 'A'),
    ('SUP-002','평창고추','033-330-1002','강원도 평창군', ARRAY['MAT-GO'], 'B'),
    ('SUP-003','남도젓갈','061-540-2003','전라남도 신안군', ARRAY['MAT-JO'], 'A')
ON CONFLICT (supplier_code) DO NOTHING;

-- =============================================================================
-- 끝. 생성 테이블: quality_standard, sop_document, code_master, supplier (4)
-- =============================================================================
