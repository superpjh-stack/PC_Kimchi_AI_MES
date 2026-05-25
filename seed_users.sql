-- =============================================================================
-- 꽃순이김치 제조AI MES — 초기 사용자 시드 데이터
-- Project: SF26179540 / 로뎀솔루션
-- Generated: 2026-05-25
--
-- 비밀번호 (bcrypt rounds=12):
--   admin    → Admin1234!
--   manager1 → Manager1234!
--   quality1 → Quality1234!
--   operator1→ Operator1234!
--
-- 주의: 운영 배포 전 비밀번호를 반드시 변경할 것!
-- 변경 방법: python -c "import bcrypt; print(bcrypt.hashpw(b'NewPass!', bcrypt.gensalt(12)).decode())"
-- =============================================================================

-- =====================================================================
-- 1. 역할 기본 데이터
-- =====================================================================
INSERT INTO roles (role_code, role_name, description) VALUES
    ('ADMIN',    '관리자',   '전체 시스템 관리 — 사용자/역할/권한/설정 등 모든 기능'),
    ('MANAGER',  '공장장',   '생산/품질 관리 — KPI 목표 수정, 출하 승인 등'),
    ('QUALITY',  '품질담당', '품질 검사 및 기준 관리 — 라벨 승인, 품질기준 수정'),
    ('OPERATOR', '작업자',   '공정 실적 입력 — 원재료 LOT 등록, 생산 실적 등록')
ON CONFLICT (role_code) DO NOTHING;

-- =====================================================================
-- 2. 역할별 권한 (role_permissions) — 메뉴 코드 기준
-- =====================================================================
-- ADMIN: 전체 메뉴 R/W
INSERT INTO role_permissions (role_id, menu_code, can_read, can_write)
SELECT r.role_id, menu_code, TRUE, TRUE
FROM roles r,
     (VALUES
         ('DASHBOARD'), ('MATERIAL'), ('FERMENTATION'), ('SHIPPING'),
         ('PROCESS'), ('DATA'), ('KPI'), ('MASTER'), ('SYSTEM'), ('AGENT')
     ) AS menus(menu_code)
WHERE r.role_code = 'ADMIN'
ON CONFLICT (role_id, menu_code) DO NOTHING;

-- MANAGER: 시스템 제외 R/W (데이터·시스템은 읽기만)
INSERT INTO role_permissions (role_id, menu_code, can_read, can_write)
SELECT r.role_id, menu_code, TRUE, can_write
FROM roles r,
     (VALUES
         ('DASHBOARD', TRUE), ('MATERIAL', TRUE), ('FERMENTATION', TRUE),
         ('SHIPPING', TRUE), ('PROCESS', TRUE), ('DATA', FALSE),
         ('KPI', TRUE), ('MASTER', FALSE), ('SYSTEM', FALSE), ('AGENT', TRUE)
     ) AS menus(menu_code, can_write)
WHERE r.role_code = 'MANAGER'
ON CONFLICT (role_id, menu_code) DO NOTHING;

-- QUALITY: 품질·기준정보 R/W, 나머지 읽기
INSERT INTO role_permissions (role_id, menu_code, can_read, can_write)
SELECT r.role_id, menu_code, TRUE, can_write
FROM roles r,
     (VALUES
         ('DASHBOARD', FALSE), ('MATERIAL', FALSE), ('FERMENTATION', FALSE),
         ('SHIPPING', FALSE), ('PROCESS', FALSE), ('DATA', TRUE),
         ('KPI', FALSE), ('MASTER', TRUE), ('SYSTEM', FALSE), ('AGENT', FALSE)
     ) AS menus(menu_code, can_write)
WHERE r.role_code = 'QUALITY'
ON CONFLICT (role_id, menu_code) DO NOTHING;

-- OPERATOR: 공정·원재료 R/W, 나머지 읽기
INSERT INTO role_permissions (role_id, menu_code, can_read, can_write)
SELECT r.role_id, menu_code, can_read, can_write
FROM roles r,
     (VALUES
         ('DASHBOARD', TRUE, FALSE), ('MATERIAL', TRUE, TRUE), ('FERMENTATION', TRUE, FALSE),
         ('SHIPPING', TRUE, FALSE), ('PROCESS', TRUE, TRUE), ('DATA', TRUE, FALSE),
         ('KPI', FALSE, FALSE), ('MASTER', TRUE, FALSE), ('SYSTEM', FALSE, FALSE), ('AGENT', FALSE, FALSE)
     ) AS menus(menu_code, can_read, can_write)
WHERE r.role_code = 'OPERATOR'
ON CONFLICT (role_id, menu_code) DO NOTHING;

-- =====================================================================
-- 3. 초기 사용자 (hashed_password = bcrypt rounds=12)
-- =====================================================================
INSERT INTO users (username, full_name, email, hashed_password, department, is_active) VALUES
    (
        'admin',
        '시스템관리자',
        'admin@kkotsooni.com',
        '$2b$12$36gVKHz8N7amVuKHYstn3e6/8cFEKSFR.gtaQmkjMhryRbQ9OKTM.',
        'IT팀',
        TRUE
    ),
    (
        'manager1',
        '생산공장장',
        'manager@kkotsooni.com',
        '$2b$12$wFshv.DO37QV1Mz5OZaAk.P0Wmfymg.r3Ss/Xb5MkaxQ2A6hTvBZS',
        '생산팀',
        TRUE
    ),
    (
        'quality1',
        '품질담당자',
        'quality@kkotsooni.com',
        '$2b$12$I3bon.LJqHOqjG1p7ko8GeFQigOMFAXeJ38dIXxxgeysCnd7bC/WS',
        '품질팀',
        TRUE
    ),
    (
        'operator1',
        '현장작업자1',
        'operator@kkotsooni.com',
        '$2b$12$kC.b9GTjjQ6bInI2JBgXcO3JfWiBHeTQGb7yplGtPVDNQEpr8IjRC',
        '생산팀',
        TRUE
    )
ON CONFLICT (username) DO UPDATE
    SET hashed_password = EXCLUDED.hashed_password,
        is_active       = EXCLUDED.is_active;

-- =====================================================================
-- 4. 역할 부여 (user_roles)
-- =====================================================================
INSERT INTO user_roles (user_id, role_id)
SELECT u.user_id, r.role_id
FROM users u, roles r
WHERE (u.username = 'admin'     AND r.role_code = 'ADMIN')
   OR (u.username = 'manager1'  AND r.role_code = 'MANAGER')
   OR (u.username = 'quality1'  AND r.role_code = 'QUALITY')
   OR (u.username = 'operator1' AND r.role_code = 'OPERATOR')
ON CONFLICT DO NOTHING;

-- =====================================================================
-- 실행 확인용 조회
-- =====================================================================
-- SELECT u.username, u.full_name, r.role_code
-- FROM users u
-- JOIN user_roles ur ON u.user_id = ur.user_id
-- JOIN roles r ON ur.role_id = r.role_id
-- ORDER BY u.username;
