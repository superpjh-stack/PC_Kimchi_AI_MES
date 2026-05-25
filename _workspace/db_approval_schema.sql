-- =====================================================================
-- 꽃순이김치 제조AI 스마트공장 MES — Shadow Mode 승인 워크플로우 스키마
-- 프로젝트: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션
-- DBMS    : PostgreSQL 15+
-- 담당    : Shadow Mode 시범운영 (AI 추천 → 사람 승인 → 공정 반영)
--
-- CLAUDE.md 원칙:
--   "AI는 조회·분석·추천·경고. 작업자 승인 후 공정 반영 (파일럿 검증 단계)"
--
-- 테이블 구성:
--   approval_item — AI 추천/의사결정 승인 대기열 (감사 추적 포함)
--
-- 상태 흐름:
--   PENDING ──(승인)──▶ APPROVED ──▶ (배치/모듈이 공정 반영)
--           ──(거절)──▶ REJECTED
--           ──(24h 경과)──▶ EXPIRED
--
-- 항목 유형(item_type):
--   FERMENTATION_CONDITION — 절임/발효 조건 변경 추천 (공장장/관리자 승인)
--   SHIPPING_APPROVAL      — 출하 승인              (공장장/관리자 승인)
--   QUALITY_OVERRIDE       — 품질 기준 예외 처리    (공장장 승인)
--   LOT_STATUS_CHANGE      — LOT 상태 변경          (품질담당자/관리자 승인)
-- =====================================================================

-- =====================================================================
-- 1. approval_item (AI 추천/의사결정 승인 대기열)
-- =====================================================================
CREATE TABLE IF NOT EXISTS approval_item (
    item_id          BIGSERIAL    PRIMARY KEY,
    item_type        VARCHAR(30)  NOT NULL,                 -- FERMENTATION_CONDITION/SHIPPING_APPROVAL/QUALITY_OVERRIDE/LOT_STATUS_CHANGE
    title            VARCHAR(200) NOT NULL,                 -- 승인 항목 요약 제목
    ai_recommendation TEXT        NOT NULL,                 -- AI 가 추천한 내용(설명)
    current_state    JSONB,                                 -- 현재 공정 상태(스냅샷)
    proposed_change  JSONB,                                 -- AI 제안 변경 사항
    confidence       DECIMAL(5,4),                          -- AI 신뢰도 0.0000~1.0000
    lot_id           VARCHAR(30),                           -- 연관 LOT ID (트레이서빌리티)
    source_module    VARCHAR(20),                           -- FERMENTATION/SHIPPING/INTAKE
    status           VARCHAR(20)  NOT NULL DEFAULT 'PENDING', -- PENDING/APPROVED/REJECTED/EXPIRED
    requested_by     VARCHAR(50),                           -- 요청 주체(AI 모듈명)
    approved_by      VARCHAR(50),                           -- 승인/거절 처리자
    approved_at      TIMESTAMPTZ,                           -- 처리 시각
    approval_note    TEXT,                                  -- 승인 메모
    rejection_reason TEXT,                                  -- 거절 사유(거절 시 필수)
    expires_at       TIMESTAMPTZ  NOT NULL DEFAULT (NOW() + INTERVAL '24 hours'),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_approval_status
        CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED')),
    CONSTRAINT chk_approval_item_type
        CHECK (item_type IN ('FERMENTATION_CONDITION', 'SHIPPING_APPROVAL',
                             'QUALITY_OVERRIDE', 'LOT_STATUS_CHANGE')),
    CONSTRAINT chk_approval_confidence
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    -- 거절 시 사유 필수
    CONSTRAINT chk_rejection_reason
        CHECK (status <> 'REJECTED' OR rejection_reason IS NOT NULL)
);

-- 승인 대기열 기본 뷰(PENDING) 가속 — 신뢰도/만료 정렬
CREATE INDEX IF NOT EXISTS idx_approval_pending
    ON approval_item (status, confidence DESC, expires_at)
    WHERE status = 'PENDING';

-- 만료 배치(expires_at < NOW() AND status='PENDING') 가속
CREATE INDEX IF NOT EXISTS idx_approval_expiry
    ON approval_item (expires_at)
    WHERE status = 'PENDING';

-- LOT 기반 추적 조회
CREATE INDEX IF NOT EXISTS idx_approval_lot
    ON approval_item (lot_id)
    WHERE lot_id IS NOT NULL;

-- 이력/통계 조회 (유형·처리자·처리시각)
CREATE INDEX IF NOT EXISTS idx_approval_history
    ON approval_item (item_type, approved_by, approved_at DESC);

COMMENT ON TABLE approval_item IS
    'Shadow Mode 승인 대기열 — AI 추천을 사람이 승인/거절. 24h 미처리 시 EXPIRED.';
COMMENT ON COLUMN approval_item.confidence IS 'AI 신뢰도 0.0000~1.0000 (시각화 게이지용)';
COMMENT ON COLUMN approval_item.current_state IS '현재 공정 상태 스냅샷 (JSONB)';
COMMENT ON COLUMN approval_item.proposed_change IS 'AI 제안 변경 사항 (JSONB)';
