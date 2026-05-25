-- =============================================================================
-- 꽃순이김치 제조AI MES — AI 대시보드 모듈 스키마 (PostgreSQL)
-- Project: SF26179540  |  Module: AI 대시보드 (생산/품질/발효/출하 현황 분석)
-- 개발: 로뎀솔루션 주식회사
--
-- 본 스키마는 "집계 뷰(VIEW) + 알림 요약 테이블"로 구성된다.
--   - VIEW 들은 기존 운영 테이블(process_result, fermentation_timeseries,
--     process_alarm 등)을 재정의하지 않고 SELECT 만 한다. (참조 전용)
--   - dashboard_alert_summary 만 신규 물리 테이블로 생성한다.
--
-- 참조(재정의 금지) 테이블:
--   process_result        (process_code, lot_id, input_qty_kg, output_qty_kg,
--                          defect_qty_kg, start_time, end_time)
--   fermentation_timeseries (lot_id, recorded_at, temperature, acidity,
--                          salinity, ph, dissolved_oxygen)
--   process_alarm         (alarm_id, lot_id, process_code, alarm_type,
--                          severity, message, is_resolved, created_at)
--   pipeline_status       (stage_name, status, last_updated)
--   data_quality_check    (rule_id, rule_name, table_name, issue_count,
--                          check_status, checked_at)
--
-- 공정 코드 약속:
--   PROC07 = 숙성/발효, PROC09 = 포장/출하  (생산/출하 집계 기준)
--
-- 생성 순서: VIEW → dashboard_alert_summary TABLE → 시드
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. v_production_daily — 일별 공정별 생산량 / 불량률 집계
--    대시보드 "생산현황 분석" 탭의 일별 생산량 bar chart 데이터 원천.
--    output_qty_kg 합계와 (불량kg / 투입kg) 기반 불량률(%)을 공정코드별로 집계.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_production_daily AS
SELECT
    DATE(pr.start_time)                              AS work_date,        -- 작업 일자
    pr.process_code                                  AS process_code,     -- 공정 코드
    COUNT(*)                                         AS lot_count,        -- 처리 LOT 수
    COALESCE(SUM(pr.input_qty_kg), 0)::NUMERIC(14,2) AS input_kg,         -- 총 투입량
    COALESCE(SUM(pr.output_qty_kg), 0)::NUMERIC(14,2) AS output_kg,       -- 총 산출량
    COALESCE(SUM(pr.defect_qty_kg), 0)::NUMERIC(14,2) AS defect_kg,       -- 총 불량량
    -- 불량률(%) = 불량kg / 투입kg * 100 (투입량 0 이면 NULL 방지)
    ROUND(
        100.0 * COALESCE(SUM(pr.defect_qty_kg), 0)
        / NULLIF(SUM(pr.input_qty_kg), 0), 2
    )                                                AS defect_rate_pct   -- 불량률(%)
FROM process_result pr
GROUP BY DATE(pr.start_time), pr.process_code;


-- -----------------------------------------------------------------------------
-- 2. v_fermentation_status — 활성 발효 LOT별 현재 상태
--    fermentation_timeseries 의 LOT별 "최신 1행"을 DISTINCT ON 으로 추출한다.
--    대시보드 "발효상태 모니터링" 탭의 활성 LOT 카드 데이터 원천.
--    상태 판정(정상/주의/이상)은 산도(acidity) 기준 룰을 뷰 내에서 계산:
--      산도 < 0.4  또는  > 0.9  → 이상(ABNORMAL)
--      산도 0.7 ~ 0.9              → 주의(WARNING)
--      그 외                        → 정상(NORMAL)
--    (산도 0.6~0.8 적정 발효, 0.9 초과 과발효 가정 — 기준서 룰 기반)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_fermentation_status AS
SELECT DISTINCT ON (ft.lot_id)
    ft.lot_id                                        AS lot_id,           -- 발효 LOT ID
    ft.recorded_at                                   AS recorded_at,      -- 최신 측정 시각
    ft.temperature                                   AS temperature,      -- 온도(°C)
    ft.acidity                                       AS acidity,          -- 산도(%)
    ft.salinity                                      AS salinity,         -- 염도(%)
    ft.ph                                            AS ph,               -- pH
    ft.dissolved_oxygen                              AS dissolved_oxygen, -- 용존산소
    -- 산도 기반 상태 판정 룰
    CASE
        WHEN ft.acidity IS NULL                        THEN 'NORMAL'
        WHEN ft.acidity < 0.4 OR ft.acidity > 0.9      THEN 'ABNORMAL'
        WHEN ft.acidity >= 0.7                         THEN 'WARNING'
        ELSE 'NORMAL'
    END                                              AS ferment_status    -- 발효 상태
FROM fermentation_timeseries ft
-- LOT별 최신 측정값만: lot_id 그룹 내 recorded_at 내림차순 첫 행
ORDER BY ft.lot_id, ft.recorded_at DESC;


-- -----------------------------------------------------------------------------
-- 3. v_quality_trend_7d — 최근 7일 품질 추세 (전 공정 통합 일별 불량률)
--    대시보드 "품질현황 분석" 탭의 불량률 추세 line chart 데이터 원천.
--    공정 구분 없이 일자별로 전체 불량률을 집계한다(완제품 관점 근사).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_quality_trend_7d AS
SELECT
    DATE(pr.start_time)                              AS work_date,        -- 작업 일자
    COALESCE(SUM(pr.input_qty_kg), 0)::NUMERIC(14,2)  AS input_kg,        -- 총 투입량
    COALESCE(SUM(pr.output_qty_kg), 0)::NUMERIC(14,2) AS output_kg,       -- 총 산출량
    COALESCE(SUM(pr.defect_qty_kg), 0)::NUMERIC(14,2) AS defect_kg,       -- 총 불량량
    -- 일별 통합 불량률(%)
    ROUND(
        100.0 * COALESCE(SUM(pr.defect_qty_kg), 0)
        / NULLIF(SUM(pr.input_qty_kg), 0), 2
    )                                                AS defect_rate_pct   -- 불량률(%)
FROM process_result pr
WHERE pr.start_time >= (CURRENT_DATE - INTERVAL '6 days')  -- 오늘 포함 7일
GROUP BY DATE(pr.start_time)
ORDER BY work_date;


-- -----------------------------------------------------------------------------
-- 4. v_shipping_daily — 일별 출하량 / 포장량 (PROC09 포장/출하 기준)
--    대시보드 "출하현황 분석" 탭의 일별 출하량 bar chart 데이터 원천.
--    포장량 = output_qty_kg, 출하량은 양품(=산출 - 불량)으로 근사한다.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_shipping_daily AS
SELECT
    DATE(pr.start_time)                              AS work_date,        -- 출하 일자
    COUNT(*)                                         AS shipment_count,   -- 출하 건수(LOT)
    COALESCE(SUM(pr.output_qty_kg), 0)::NUMERIC(14,2) AS packaging_kg,    -- 포장량(kg)
    -- 출하량(kg) = 산출량 - 불량량 (양품 기준)
    COALESCE(SUM(pr.output_qty_kg - COALESCE(pr.defect_qty_kg, 0)), 0)::NUMERIC(14,2)
                                                     AS shipping_kg       -- 출하량(kg)
FROM process_result pr
WHERE pr.process_code = 'PROC09'   -- 포장/출하 공정만
GROUP BY DATE(pr.start_time);


-- -----------------------------------------------------------------------------
-- 5. dashboard_alert_summary — 대시보드용 알림 요약 (신규 물리 테이블)
--    실시간 알림 패널에 노출되는 요약 알림. 최대 100행 유지(트리거로 정리).
--    process_alarm(공정 원천 알림)과 별개로, 대시보드 표시 전용으로 가공된 알림.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dashboard_alert_summary (
    alert_id    BIGSERIAL    PRIMARY KEY,
    alert_type  VARCHAR(20)  NOT NULL,                 -- PRODUCTION/QUALITY/FERMENTATION/SHIPPING/SYSTEM
    severity    VARCHAR(10)  NOT NULL DEFAULT 'INFO',  -- INFO/WARNING/CRITICAL
    message     TEXT         NOT NULL,                 -- 알림 메시지(한글)
    module      VARCHAR(20),                           -- 발생 모듈명(생산/품질/발효/출하 등)
    is_read     BOOLEAN      NOT NULL DEFAULT FALSE,    -- 읽음 여부
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),    -- 생성 시각
    CONSTRAINT chk_dash_alert_severity CHECK (severity IN ('INFO','WARNING','CRITICAL'))
);

-- 인덱스: 미읽음 + 최신순 조회 (대시보드 알림 패널 기본 쿼리)
CREATE INDEX IF NOT EXISTS idx_dash_alert_unread
    ON dashboard_alert_summary(is_read, created_at DESC);
-- 인덱스: 타입별 필터
CREATE INDEX IF NOT EXISTS idx_dash_alert_type
    ON dashboard_alert_summary(alert_type, created_at DESC);


-- -----------------------------------------------------------------------------
-- 6. 최대 100행 유지 트리거
--    INSERT 후 행 수가 100을 초과하면 가장 오래된 행을 삭제한다.
--    (대시보드 요약 테이블이 무한히 커지는 것을 방지)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trim_dashboard_alerts()
RETURNS TRIGGER AS $$
BEGIN
    -- 행 수가 100건을 넘으면, 100건만 남기고 오래된 알림 삭제
    DELETE FROM dashboard_alert_summary
    WHERE alert_id IN (
        SELECT alert_id
        FROM dashboard_alert_summary
        ORDER BY created_at DESC, alert_id DESC
        OFFSET 100
    );
    RETURN NULL;  -- AFTER 트리거이므로 반환값 무시
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_trim_dashboard_alerts ON dashboard_alert_summary;
CREATE TRIGGER trg_trim_dashboard_alerts
    AFTER INSERT ON dashboard_alert_summary
    FOR EACH STATEMENT
    EXECUTE FUNCTION trim_dashboard_alerts();


-- =============================================================================
-- 7. 시드 데이터 — dashboard_alert_summary 샘플 알림 3건
--    (대시보드 알림 패널 초기 표시 확인용)
-- =============================================================================
INSERT INTO dashboard_alert_summary (alert_type, severity, message, module, is_read) VALUES
    ('FERMENTATION', 'CRITICAL',
     '발효 LOT FE-20260524-002 산도 0.95% 초과 — 과발효 위험, 즉시 점검 필요',
     '숙성발효', FALSE),
    ('QUALITY', 'WARNING',
     '금일 완제품 불량률 1.4% — 목표(1.0%) 초과, 포장 공정 점검 권고',
     '품질', FALSE),
    ('PRODUCTION', 'INFO',
     '금일 누적 생산량 24,500kg 달성 — 시간당 생산량 목표(3,000kg/h) 정상 추세',
     '생산', FALSE)
ON CONFLICT DO NOTHING;


-- =============================================================================
-- 참고: 뷰 사용 예시 (API 라우터 api_dashboard_router.py 에서 호출)
--   SELECT * FROM v_production_daily WHERE work_date >= CURRENT_DATE - 6;
--   SELECT * FROM v_fermentation_status;
--   SELECT * FROM v_quality_trend_7d;
--   SELECT * FROM v_shipping_daily WHERE work_date >= CURRENT_DATE - 6;
-- =============================================================================
