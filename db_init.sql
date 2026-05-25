-- =====================================================================
-- 꽃순이김치 제조AI MES — DB 초기화 통합 스크립트
-- 프로젝트: SF26179540 (평창꽃순이(주)농업회사법인) / 로뎀솔루션 주식회사
-- DBMS    : PostgreSQL 15+ (pgvector 확장 사용)
--
-- 실행:
--     psql -U postgres -d kimchi_mes -f db_init.sql
--
-- 적용 순서: 의존성 기준 (FK 대상 테이블 먼저 생성)
--     기준정보 → 시스템/사용자 → 공정 → 원재료 → 발효 →
--     포장출하 → 데이터 → KPI → AI Agent → 대시보드 VIEW
--
-- 비고:
--     - 각 스키마 파일은 CREATE TABLE IF NOT EXISTS / ON CONFLICT 로
--       작성되어 반복 실행해도 안전(멱등)하다.
--     - \i 는 db_init.sql 이 위치한 디렉터리(프로젝트 루트)를 기준으로
--       _workspace/ 하위 파일을 상대 경로로 적재한다.
-- =====================================================================

-- 트랜잭션 중 한 스키마라도 실패하면 전체 롤백 (부분 적용 방지)
\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------
-- 0. 확장 모듈 (pgvector / uuid)
-- ---------------------------------------------------------------------
\echo '=== [0/10] 확장 모듈 (vector, uuid-ossp) ==='
CREATE EXTENSION IF NOT EXISTS vector;        -- pgvector (임베딩 벡터 검색)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- UUID 생성

\echo '=== [1/10] 기준정보 (supplier, code_master, quality_standard, sop_document) ==='
\i _workspace/db_master_schema.sql

\echo '=== [2/10] 시스템/사용자 (users, roles, permissions, logs) ==='
\i _workspace/db_system_schema.sql

\echo '=== [3/10] 공정관리 (process_result, recipe, alarm) ==='
\i _workspace/db_process_schema.sql

\echo '=== [4/10] 원재료관리 (raw_material_lot, inspection, selection, supplier 확장) ==='
\i _workspace/db_material_schema.sql

\echo '=== [5/10] 발효관리 (fermentation_lot, prediction, anomaly, recommendation) ==='
\i _workspace/db_fermentation_schema.sql

\echo '=== [6/10] 포장출하관리 (packaging_lot, inspection, shipping_order, claim) ==='
\i _workspace/db_shipping_schema.sql

\echo '=== [7/10] 데이터관리 (pipeline_status, etl_log, edge_device, ai_dataset) ==='
\i _workspace/db_data_schema.sql

\echo '=== [8/10] KPI관리 (kpi_target, kpi_alert_config, kpi_report, kpi_daily_summary) ==='
\i _workspace/db_kpi_schema.sql

\echo '=== [9/10] AI Agent (ai_query_history, ai_recommendation, ai_system_status) ==='
\i _workspace/db_agent_schema.sql

\echo '=== [10/11] 대시보드 VIEW (v_production_daily, v_fermentation_status, ...) ==='
\i _workspace/db_dashboard_schema.sql

\echo '=== [11/11] Shadow Mode 승인 워크플로우 (approval_item) ==='
\i _workspace/db_approval_schema.sql

\echo '====================================================================='
\echo '=== DB 초기화 완료 — 꽃순이김치 제조AI MES (SF26179540)            ==='
\echo '====================================================================='
