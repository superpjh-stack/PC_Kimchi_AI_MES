-- =====================================================================
-- 꽃순이김치 제조AI 스마트공장 MES — AI Agent 통합관리 모듈 스키마
-- 프로젝트: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션
-- DBMS    : PostgreSQL 15+
-- 담당    : AI Agent 통합관리 (통합 질의 / 추천·의사결정 / 상태 / 문서 인덱스)
--
-- 기획서 7장(AI Agent 통합관리) 기준.
--
-- 본 스키마는 db_system_schema.sql 과 상호 보완 관계이다.
--   - ai_agent_log     (system_schema): 사용자/시스템관리 관점의 단순 질의 로그
--   - ai_query_history (본 스키마)     : AI Agent 통합관리 관점의 질의 이력
--                                        (의사결정 승인·만족도·연관 LOT·참조문서 확장)
--   ⚠️ ai_agent_session / ai_agent_log 는 다른 스키마 소유 → 본 파일에서 재정의 금지.
--
-- 테이블 구성:
--   ai_query_history   — AI 질의 이력 (모든 Agent 타입 통합, 승인·만족도 포함)
--   ai_recommendation  — AI 추천 / 의사결정 지원 항목
--   ai_system_status   — AI 엔진 / Agent 컴포넌트 상태 모니터링
--   ai_document_index  — Vector DB 문서 인덱스 (pgvector 문서 메타데이터)
--
-- Agent 타입 표준 (CLAUDE.md RAG Agent 정의):
--   INTAKE     — 원재료 입고 Agent (🥬)
--   SHIPPING   — 포장·출하 Agent  (📦)
--   INTEGRATED — 통합 질의 Agent  (🤖)
-- =====================================================================

-- =====================================================================
-- 1. ai_query_history (AI 질의 이력)
--    모든 Agent 타입(INTAKE/SHIPPING/INTEGRATED)의 질의/응답을 통합 저장.
--    의사결정 지원을 위한 승인(is_approved) 및 사용자 만족도(feedback_score) 포함.
-- =====================================================================
CREATE TABLE IF NOT EXISTS ai_query_history (
    query_id         BIGSERIAL    PRIMARY KEY,
    session_id       VARCHAR(50),                          -- 세션 식별자(대화 묶음)
    user_id          BIGINT,                               -- 질의 사용자 (users.user_id 가정)
    agent_type       VARCHAR(20)  NOT NULL,                -- INTAKE/SHIPPING/INTEGRATED
    query_text       TEXT         NOT NULL,                -- 사용자 질의
    response_text    TEXT,                                 -- AI 응답 (PENDING 단계엔 NULL)
    response_time_ms INT,                                  -- 응답 지연(ms)
    context_lots     VARCHAR[],                            -- 질의 연관 LOT ID 목록
    referenced_docs  JSONB        DEFAULT '[]'::jsonb,     -- 참조 문서 [{title, doc_type, score}]
    is_approved      BOOLEAN      DEFAULT NULL,            -- 의사결정 승인: NULL=미결 / TRUE / FALSE
    approved_by      VARCHAR(50),                          -- 승인/거절 처리자
    approved_at      TIMESTAMPTZ,                          -- 승인/거절 시각
    feedback_score   INT          CHECK (feedback_score BETWEEN 1 AND 5),  -- 만족도 1~5
    created_at       TIMESTAMPTZ  DEFAULT NOW(),

    CONSTRAINT chk_qh_agent_type CHECK (
        agent_type IN ('INTAKE','SHIPPING','INTEGRATED')
    )
);
CREATE INDEX IF NOT EXISTS idx_qh_agent_time   ON ai_query_history(agent_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_qh_user_time    ON ai_query_history(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_qh_session      ON ai_query_history(session_id);
CREATE INDEX IF NOT EXISTS idx_qh_approval     ON ai_query_history(is_approved);
-- 미결(NULL) 의사결정 항목 빠른 조회용 부분 인덱스
CREATE INDEX IF NOT EXISTS idx_qh_pending      ON ai_query_history(created_at DESC)
    WHERE is_approved IS NULL;
-- 연관 LOT 역추적(traceability) 가속용 GIN 인덱스
CREATE INDEX IF NOT EXISTS idx_qh_context_lots ON ai_query_history USING GIN (context_lots);

-- =====================================================================
-- 2. ai_recommendation (AI 추천 / 의사결정 지원 항목)
--    질의 결과로부터 파생된 추천·경고·승인 권고 등을 카드 단위로 저장.
-- =====================================================================
CREATE TABLE IF NOT EXISTS ai_recommendation (
    rec_id           BIGSERIAL    PRIMARY KEY,
    query_id         BIGINT       REFERENCES ai_query_history(query_id) ON DELETE SET NULL,
    agent_type       VARCHAR(20)  NOT NULL,                -- INTAKE/SHIPPING/INTEGRATED
    rec_type         VARCHAR(30)  NOT NULL,                -- 추천 유형(아래 CHECK)
    title            VARCHAR(200) NOT NULL,                -- 추천 제목
    content          TEXT         NOT NULL,                -- 추천 본문
    confidence_score DECIMAL(5,4),                         -- 신뢰도 0.0000~1.0000
    action_required  BOOLEAN      DEFAULT FALSE,           -- 조치 필요 여부
    priority         VARCHAR(10)  DEFAULT 'NORMAL',        -- LOW/NORMAL/HIGH/CRITICAL
    lot_id           VARCHAR(30),                          -- 관련 LOT ID
    is_actioned      BOOLEAN      DEFAULT FALSE,           -- 처리 완료 여부
    actioned_by      VARCHAR(50),                          -- 처리자
    actioned_at      TIMESTAMPTZ,                          -- 처리 시각
    expires_at       TIMESTAMPTZ,                          -- 추천 만료 시각
    created_at       TIMESTAMPTZ  DEFAULT NOW(),

    CONSTRAINT chk_rec_agent_type CHECK (
        agent_type IN ('INTAKE','SHIPPING','INTEGRATED')
    ),
    CONSTRAINT chk_rec_type CHECK (
        rec_type IN ('QUALITY_ALERT','OPTIMAL_CONDITION','SUPPLIER_EVAL',
                     'SHIPPING_APPROVAL','CLAIM_ANALYSIS')
    ),
    CONSTRAINT chk_rec_priority CHECK (
        priority IN ('LOW','NORMAL','HIGH','CRITICAL')
    )
);
CREATE INDEX IF NOT EXISTS idx_rec_agent       ON ai_recommendation(agent_type);
CREATE INDEX IF NOT EXISTS idx_rec_type        ON ai_recommendation(rec_type);
CREATE INDEX IF NOT EXISTS idx_rec_lot         ON ai_recommendation(lot_id);
CREATE INDEX IF NOT EXISTS idx_rec_created     ON ai_recommendation(created_at DESC);
-- 미처리 고우선순위 추천 빠른 조회용 부분 인덱스 (/recommendations/active)
CREATE INDEX IF NOT EXISTS idx_rec_active      ON ai_recommendation(priority, created_at DESC)
    WHERE is_actioned = FALSE;

-- =====================================================================
-- 3. ai_system_status (AI 엔진 / Agent 상태 모니터링)
--    AI Server → MES 헬스체크 결과를 컴포넌트별 단일 행(UPSERT)으로 유지.
-- =====================================================================
CREATE TABLE IF NOT EXISTS ai_system_status (
    status_id        BIGSERIAL    PRIMARY KEY,
    component        VARCHAR(30)  NOT NULL,                -- INTAKE_AGENT/SHIPPING_AGENT/ML_ENGINE/VECTOR_DB
    status           VARCHAR(20)  NOT NULL,                -- ONLINE/OFFLINE/ERROR/DEGRADED
    last_query_at    TIMESTAMPTZ,                          -- 마지막 질의 처리 시각
    avg_response_ms  INT,                                  -- 최근 평균 응답(ms)
    error_count_1h   INT          DEFAULT 0,               -- 최근 1시간 오류 수
    error_message    TEXT,                                 -- 최근 오류 메시지
    checked_at       TIMESTAMPTZ  DEFAULT NOW(),           -- 헬스체크 시각

    CONSTRAINT uq_sys_component CHECK (
        component IN ('INTAKE_AGENT','SHIPPING_AGENT','ML_ENGINE','VECTOR_DB')
    ),
    CONSTRAINT chk_sys_status CHECK (
        status IN ('ONLINE','OFFLINE','ERROR','DEGRADED')
    ),
    UNIQUE (component)
);
CREATE INDEX IF NOT EXISTS idx_sys_status ON ai_system_status(status);

-- =====================================================================
-- 4. ai_document_index (Vector DB 문서 인덱스 — pgvector 문서 메타)
--    실제 임베딩 벡터는 Vector DB 서버(pgvector)에 저장하고,
--    운영DB 에는 임베딩 진행 상태/버전/청크수 등 메타데이터만 관리한다.
-- =====================================================================
CREATE TABLE IF NOT EXISTS ai_document_index (
    doc_id        BIGSERIAL    PRIMARY KEY,
    doc_type      VARCHAR(30)  NOT NULL,                   -- SOP/QUALITY_STANDARD/HACCP/MANUAL/CLAIM
    title         VARCHAR(200) NOT NULL,                   -- 문서 제목
    version       VARCHAR(20)  DEFAULT '1.0',              -- 문서 버전
    chunk_count   INT          DEFAULT 0,                  -- 임베딩 청크 수
    embed_status  VARCHAR(20)  DEFAULT 'PENDING',          -- PENDING/PROCESSING/COMPLETED/FAILED
    source_file   VARCHAR(500),                            -- 원본 파일 경로/URL
    uploaded_by   VARCHAR(50),                             -- 업로더
    updated_at    TIMESTAMPTZ  DEFAULT NOW(),

    CONSTRAINT chk_doc_type CHECK (
        doc_type IN ('SOP','QUALITY_STANDARD','HACCP','MANUAL','CLAIM')
    ),
    CONSTRAINT chk_doc_embed_status CHECK (
        embed_status IN ('PENDING','PROCESSING','COMPLETED','FAILED')
    )
);
CREATE INDEX IF NOT EXISTS idx_doc_type   ON ai_document_index(doc_type);
CREATE INDEX IF NOT EXISTS idx_doc_status ON ai_document_index(embed_status);

-- =====================================================================
-- 시드 데이터
-- =====================================================================

-- 5-1. ai_system_status — 4개 컴포넌트 초기 ONLINE
INSERT INTO ai_system_status
    (component, status, last_query_at, avg_response_ms, error_count_1h)
VALUES
    ('INTAKE_AGENT',   'ONLINE', NOW() - INTERVAL '3 minutes',  820, 0),
    ('SHIPPING_AGENT', 'ONLINE', NOW() - INTERVAL '8 minutes',  910, 0),
    ('ML_ENGINE',      'ONLINE', NOW() - INTERVAL '1 minute',  1450, 0),
    ('VECTOR_DB',      'ONLINE', NOW() - INTERVAL '2 minutes',  220, 0)
ON CONFLICT (component) DO NOTHING;

-- 5-2. ai_query_history — 샘플 질의/응답 5건
INSERT INTO ai_query_history
    (session_id, user_id, agent_type, query_text, response_text,
     response_time_ms, context_lots, referenced_docs, is_approved,
     approved_by, approved_at, feedback_score, created_at)
VALUES
    ('sess-20260524-001', 1, 'INTAKE',
     '강원농산 최근 입고 배추의 품질 이력을 알려줘',
     '[INTAKE Agent] 강원농산 최근 3개월 입고 LOT 12건 중 외관등급 A 비율 83%, 평균 함수율 94.2%로 입고 기준(≥90%)을 충족합니다. 1건(LOT-RM-20260510-007)에서 함수율 미달 경고 이력이 있습니다.',
     870, ARRAY['LOT-RM-20260510-007','LOT-RM-20260518-003'],
     '[{"title":"공급처 평가 기준서 v1.3","doc_type":"QUALITY_STANDARD","score":0.91},
       {"title":"원재료 입고 작업표준서","doc_type":"SOP","score":0.84}]'::jsonb,
     NULL, NULL, NULL, 5, NOW() - INTERVAL '2 hours'),

    ('sess-20260524-002', 1, 'SHIPPING',
     '출하LOT SH-20260523-011 출하 승인 가능한지 검토해줘',
     '[SHIPPING Agent] 해당 LOT은 금속검출 PASS, 관능검사 합격, pH 4.3(기준 4.2~4.5)로 출하 승인 기준을 충족합니다. 출하 승인을 권고합니다.',
     1120, ARRAY['SH-20260523-011'],
     '[{"title":"완제품 출하 승인 기준서 v2.0","doc_type":"QUALITY_STANDARD","score":0.95}]'::jsonb,
     TRUE, 'manager01', NOW() - INTERVAL '50 minutes', 4, NOW() - INTERVAL '1 hour'),

    ('sess-20260524-003', 2, 'INTEGRATED',
     '오늘 발효 진행 중인 LOT 중 이상발효 위험이 있는 건이 있어?',
     '[통합 Agent] 발효 진행 LOT 8건 중 FM-20260524-002 LOT에서 산도 상승률이 평소 대비 1.7배로 ML 엔진이 주의(0.62) 등급을 예측했습니다. 온도 재확인을 권고합니다.',
     1560, ARRAY['FM-20260524-002'],
     '[{"title":"절임/발효 기준서 v3.1","doc_type":"QUALITY_STANDARD","score":0.88}]'::jsonb,
     NULL, NULL, NULL, NULL, NOW() - INTERVAL '35 minutes'),

    ('sess-20260524-004', 2, 'INTAKE',
     '배추 입고 시 외관등급 판정 기준이 뭐야?',
     '[INTAKE Agent] 외관등급은 A(결점 없음), B(경미한 외피 손상), C(반려)로 구분하며, 절단면 변색·동해·병해 여부를 육안 검사합니다. 상세 절차는 작업표준서 4.2절을 참고하세요.',
     640, NULL,
     '[{"title":"원재료 입고 작업표준서","doc_type":"SOP","score":0.93}]'::jsonb,
     NULL, NULL, NULL, 5, NOW() - INTERVAL '20 minutes'),

    ('sess-20260524-005', 3, 'SHIPPING',
     '최근 클레임 중 식감 불량 원인 분석해줘',
     '[SHIPPING Agent] 최근 30일 클레임 7건 중 식감 관련 3건은 모두 발효 과숙(산도 4.6 초과) LOT에서 출하된 것으로 분석됩니다. 발효 완료 시점 예측 정확도 개선이 필요합니다.',
     1340, ARRAY['SH-20260501-004','SH-20260507-009'],
     '[{"title":"클레임 대응 매뉴얼 v1.2","doc_type":"CLAIM","score":0.89},
       {"title":"완제품 출하 승인 기준서 v2.0","doc_type":"QUALITY_STANDARD","score":0.71}]'::jsonb,
     NULL, NULL, NULL, 4, NOW() - INTERVAL '10 minutes');

-- 5-3. ai_recommendation — 다양한 rec_type 5건
INSERT INTO ai_recommendation
    (query_id, agent_type, rec_type, title, content, confidence_score,
     action_required, priority, lot_id, is_actioned, expires_at, created_at)
VALUES
    (3, 'INTEGRATED', 'QUALITY_ALERT',
     '이상발효 조기 경보 — FM-20260524-002',
     '발효 LOT FM-20260524-002 의 산도 상승률이 평소 대비 1.7배로 감지되었습니다. ML 엔진 예측 등급은 주의(0.62)이며, 발효조 온도 및 염도 재확인을 권고합니다.',
     0.6200, TRUE, 'CRITICAL', 'FM-20260524-002', FALSE,
     NOW() + INTERVAL '12 hours', NOW() - INTERVAL '35 minutes'),

    (NULL, 'INTAKE', 'SUPPLIER_EVAL',
     '공급처 품질 등급 재평가 권고 — 강원농산',
     '강원농산의 최근 함수율 미달 경고(1건) 누적으로 분기 공급처 평가 등급 재산정을 권고합니다. 현재 A등급 유지 가능하나 모니터링 필요.',
     0.7400, FALSE, 'NORMAL', 'LOT-RM-20260510-007', FALSE,
     NOW() + INTERVAL '7 days', NOW() - INTERVAL '2 hours'),

    (NULL, 'INTEGRATED', 'OPTIMAL_CONDITION',
     '최적 절임 조건 추천 — 금일 배추 입고분',
     '금일 입고 배추(평균 함수율 94.5%, 외관 A)에 대해 ML 엔진이 추천하는 절임 조건은 염도 8.2%, 절임 시간 14시간입니다. 예측 발효 품질 점수 0.91.',
     0.9100, TRUE, 'HIGH', 'LOT-RM-20260524-002', FALSE,
     NOW() + INTERVAL '1 day', NOW() - INTERVAL '40 minutes'),

    (2, 'SHIPPING', 'SHIPPING_APPROVAL',
     '출하 승인 권고 — SH-20260523-011',
     '출하 LOT SH-20260523-011 은 금속검출 PASS, 관능검사 합격, pH 4.3 으로 출하 승인 기준을 충족합니다. 승인 처리를 권고합니다.',
     0.9500, TRUE, 'HIGH', 'SH-20260523-011', TRUE,
     NOW() + INTERVAL '2 days', NOW() - INTERVAL '1 hour'),

    (5, 'SHIPPING', 'CLAIM_ANALYSIS',
     '클레임 원인 분석 — 식감 불량 군집',
     '최근 식감 불량 클레임 3건이 발효 과숙(산도 4.6 초과) LOT에 집중되어 있습니다. 발효 완료 시점 예측 모델 재학습 및 출하 전 산도 재검 강화를 권고합니다.',
     0.8300, FALSE, 'NORMAL', NULL, FALSE,
     NOW() + INTERVAL '14 days', NOW() - INTERVAL '10 minutes');

-- 5-4. ai_document_index — SOP 2 / QUALITY_STANDARD 2 / HACCP 1
INSERT INTO ai_document_index
    (doc_type, title, version, chunk_count, embed_status, source_file, uploaded_by, updated_at)
VALUES
    ('SOP', '원재료 입고 작업표준서', '2.0', 48, 'COMPLETED',
     's3://kkotsooni-mes/docs/sop/intake_sop_v2.0.pdf', 'quality01', NOW() - INTERVAL '5 days'),
    ('SOP', '포장·출하 작업표준서', '1.4', 36, 'COMPLETED',
     's3://kkotsooni-mes/docs/sop/shipping_sop_v1.4.pdf', 'quality01', NOW() - INTERVAL '3 days'),
    ('QUALITY_STANDARD', '배추김치 품질 기준서', '2.1', 62, 'COMPLETED',
     's3://kkotsooni-mes/docs/quality/kimchi_quality_v2.1.pdf', 'quality01', NOW() - INTERVAL '7 days'),
    ('QUALITY_STANDARD', '완제품 출하 승인 기준서', '2.0', 41, 'PROCESSING',
     's3://kkotsooni-mes/docs/quality/shipping_approval_v2.0.pdf', 'manager01', NOW() - INTERVAL '2 hours'),
    ('HACCP', 'HACCP CCP 관리 기준서', '1.0', 55, 'COMPLETED',
     's3://kkotsooni-mes/docs/haccp/ccp_management_v1.0.pdf', 'admin', NOW() - INTERVAL '10 days');

-- =====================================================================
-- 끝 — 4개 테이블 (질의이력 / 추천 / 상태 / 문서인덱스)
-- =====================================================================
