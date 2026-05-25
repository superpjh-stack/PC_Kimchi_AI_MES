---
name: db-schema-design
description: 꽃순이김치 MES PostgreSQL 스키마 및 pgvector 임베딩 스키마 설계 스킬. LOT 트레이서빌리티 데이터 모델, 발효 시계열 스키마, 비정형 문서 임베딩 설계 시 반드시 이 스킬을 사용하라. 트리거: DB 스키마, 테이블 설계, pgvector, LOT 트레이서빌리티, 발효 데이터 모델, 임베딩 스키마, DDL, 인덱스 설계.
---

# MES DB 스키마 설계 스킬

## 핵심 설계 원칙

### LOT 트레이서빌리티 — 최우선 원칙
모든 공정 테이블에 LOT ID FK 체인을 유지한다:
```
raw_material_intake.intake_lot_id
        ↓ (FK)
salting_process.intake_lot_id
        ↓ (FK)
fermentation_process.salting_lot_id
        ↓ (FK)
shipping.fermentation_lot_id
```
전 공정에서 임의의 LOT ID로 추적 조회가 가능해야 한다.

---

## PostgreSQL 주요 테이블 DDL

### 1. 원재료 입고 (raw_material_intake)
```sql
CREATE TABLE raw_material_intake (
    id               BIGSERIAL PRIMARY KEY,
    intake_lot_id    VARCHAR(50)  UNIQUE NOT NULL,
    supplier_id      INTEGER      NOT NULL,
    intake_date      DATE         NOT NULL,
    material_type    VARCHAR(50),                    -- 배추, 고추, 마늘 등
    weight_kg        DECIMAL(10,2),
    moisture_content DECIMAL(5,2),                   -- 함수율 (%)
    cabbage_size     VARCHAR(20),
    appearance_grade VARCHAR(10),                    -- 외관등급 (1~5등급)
    origin           VARCHAR(50),                    -- 원산지
    quality_status   VARCHAR(20) DEFAULT 'PENDING',  -- PENDING/PASS/FAIL
    created_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_intake_lot    ON raw_material_intake(intake_lot_id);
CREATE        INDEX idx_intake_date   ON raw_material_intake(intake_date);
CREATE        INDEX idx_intake_status ON raw_material_intake(quality_status);
```

### 2. 절임 공정 (salting_process)
```sql
CREATE TABLE salting_process (
    id               BIGSERIAL PRIMARY KEY,
    salting_lot_id   VARCHAR(50) UNIQUE NOT NULL,
    intake_lot_id    VARCHAR(50) NOT NULL REFERENCES raw_material_intake(intake_lot_id),
    start_time       TIMESTAMPTZ NOT NULL,
    end_time         TIMESTAMPTZ,
    target_salinity  DECIMAL(5,2),   -- 목표 염도 (%)
    actual_salinity  DECIMAL(5,2),   -- 실제 염도
    temperature      DECIMAL(5,2),   -- 온도 (°C)
    duration_hours   DECIMAL(6,2),   -- 절임 시간
    ph_value         DECIMAL(4,2),
    status           VARCHAR(20) DEFAULT 'IN_PROGRESS',
    created_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_salting_lot        ON salting_process(salting_lot_id);
CREATE        INDEX idx_salting_intake_lot ON salting_process(intake_lot_id);
```

### 3. 발효 공정 (fermentation_process)
```sql
CREATE TABLE fermentation_process (
    id                      BIGSERIAL PRIMARY KEY,
    fermentation_lot_id     VARCHAR(50) UNIQUE NOT NULL,
    salting_lot_id          VARCHAR(50) NOT NULL REFERENCES salting_process(salting_lot_id),
    start_time              TIMESTAMPTZ NOT NULL,
    predicted_end_time      TIMESTAMPTZ,    -- LSTM 예측 완료 시점
    actual_end_time         TIMESTAMPTZ,
    target_acidity          DECIMAL(4,2),
    status                  VARCHAR(20) DEFAULT 'IN_PROGRESS',  -- IN_PROGRESS/COMPLETED/ALERT
    ml_quality_prediction   VARCHAR(20),   -- 정상/주의/이상
    ml_quality_score        DECIMAL(5,4),
    shap_top_factors        JSONB,         -- SHAP 주요 영향 요인
    created_at              TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_fermentation_lot    ON fermentation_process(fermentation_lot_id);
CREATE        INDEX idx_fermentation_status ON fermentation_process(status);
```

### 4. 발효 시계열 데이터 (fermentation_timeseries) — LSTM 입력 최적화
```sql
CREATE TABLE fermentation_timeseries (
    id                  BIGSERIAL,
    fermentation_lot_id VARCHAR(50) NOT NULL REFERENCES fermentation_process(fermentation_lot_id),
    recorded_at         TIMESTAMPTZ NOT NULL,
    temperature         DECIMAL(5,2),   -- 발효 온도 (°C)
    acidity             DECIMAL(4,2),   -- 산도 (pH)
    salinity            DECIMAL(5,2),   -- 염도 (%)
    ripeness_score      DECIMAL(5,4),   -- 숙성도 지수
    outdoor_temperature DECIMAL(5,2),   -- 외기 온도
    outdoor_humidity    DECIMAL(5,2),   -- 외기 습도
    PRIMARY KEY (id, recorded_at)
) PARTITION BY RANGE (recorded_at);

-- 월별 파티션 생성 (예시: 2026년)
CREATE TABLE fermentation_timeseries_2026_01
    PARTITION OF fermentation_timeseries
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

CREATE INDEX idx_ts_lot_time ON fermentation_timeseries(fermentation_lot_id, recorded_at);
```

### 5. 포장/출하 (shipping)
```sql
CREATE TABLE shipping (
    id                  BIGSERIAL PRIMARY KEY,
    shipping_lot_id     VARCHAR(50) UNIQUE NOT NULL,
    fermentation_lot_id VARCHAR(50) NOT NULL REFERENCES fermentation_process(fermentation_lot_id),
    shipping_date       DATE,
    product_type        VARCHAR(50),
    weight_kg           DECIMAL(10,2),
    destination         VARCHAR(100),
    quality_status      VARCHAR(20),    -- APPROVED/PENDING/REJECTED
    defect_rate         DECIMAL(5,4),   -- 불량률 (목표: ≤ 0.01)
    approved_by         VARCHAR(50),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_shipping_lot  ON shipping(shipping_lot_id);
CREATE        INDEX idx_shipping_date ON shipping(shipping_date);
```

### 6. 품질 검사 (quality_inspection)
```sql
CREATE TABLE quality_inspection (
    id                BIGSERIAL PRIMARY KEY,
    lot_id            VARCHAR(50)  NOT NULL,
    lot_type          VARCHAR(30)  NOT NULL,  -- INTAKE/SALTING/FERMENTATION/SHIPPING
    inspection_time   TIMESTAMPTZ  DEFAULT NOW(),
    inspector_id      INTEGER,
    inspection_result VARCHAR(20),             -- PASS/FAIL/CONDITIONAL
    defect_type       VARCHAR(50),
    defect_count      INTEGER DEFAULT 0,
    notes             TEXT,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_qc_lot ON quality_inspection(lot_id, lot_type);
```

### 7. KPI 데이터 (production_kpi)
```sql
CREATE TABLE production_kpi (
    id                       BIGSERIAL PRIMARY KEY,
    kpi_date                 DATE NOT NULL,
    kpi_hour                 INTEGER,               -- NULL: 일별, 0~23: 시간별
    hourly_production_kg     DECIMAL(10,2),          -- 목표: 3,000 kg/h
    defect_rate              DECIMAL(5,4),            -- 목표: 0.01 (1.0%)
    fermentation_accuracy    DECIMAL(5,4),            -- 발효 품질 예측 정확도 (목표: ≥ 0.80)
    fermentation_time_mae    DECIMAL(6,2),            -- 발효 완료 예측 MAE (목표: ≤ 2시간)
    created_at               TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_kpi_date_hour ON production_kpi(kpi_date, kpi_hour);
```

---

## pgvector 스키마

### 문서 임베딩 (document_embeddings)
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE document_embeddings (
    id           BIGSERIAL PRIMARY KEY,
    doc_type     VARCHAR(50) NOT NULL,   -- SOP/FERMENTATION_GUIDE/QC_STANDARD/HACCP/EQUIPMENT_MANUAL/CLAIM_RESPONSE
    title        VARCHAR(200) NOT NULL,
    content      TEXT NOT NULL,
    embedding    vector(1536),           -- text-embedding-3-small 기준
    source_file  VARCHAR(200),
    version      VARCHAR(20),
    effective_date DATE,
    metadata     JSONB DEFAULT '{}',
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- IVFFlat 인덱스 (대량 문서 코사인 유사도 검색)
CREATE INDEX idx_doc_embedding ON document_embeddings
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_doc_type ON document_embeddings(doc_type);
```

### 검색 함수
```sql
CREATE OR REPLACE FUNCTION search_documents(
    query_embedding  vector(1536),
    doc_type_filter  VARCHAR(50) DEFAULT NULL,
    match_count      INTEGER DEFAULT 5
)
RETURNS TABLE (id BIGINT, doc_type VARCHAR, title VARCHAR, content TEXT, similarity FLOAT)
LANGUAGE sql STABLE AS $$
    SELECT id, doc_type, title, content,
           1 - (embedding <=> query_embedding) AS similarity
    FROM document_embeddings
    WHERE (doc_type_filter IS NULL OR doc_type = doc_type_filter)
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;
```

---

## DDL 생성 순서 (의존성 기준)
1. `raw_material_intake`
2. `salting_process`
3. `fermentation_process`
4. `fermentation_timeseries` + 파티션
5. `shipping`
6. `quality_inspection`
7. `production_kpi`
8. `document_embeddings` (pgvector, 별도 DB 서버)

---

## 인덱스 전략 요약

| 테이블 | 인덱스 | 이유 |
|--------|--------|------|
| 모든 LOT 테이블 | lot_id (UNIQUE) | LOT 추적 핵심 |
| fermentation_timeseries | (lot_id, recorded_at) | 슬라이딩 윈도우 범위 조회 |
| shipping | shipping_date | 일별 출하 집계 |
| quality_inspection | (lot_id, lot_type) | LOT별 검사 이력 |
| document_embeddings | embedding (ivfflat) | 벡터 유사도 검색 |
