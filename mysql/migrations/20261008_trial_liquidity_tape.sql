-- Reapply-safe Tape columns for the durable trial bootstrap. Existing completed jobs remain disabled.
-- Tape cash requests have an independent no-retry reconciliation boundary.

SET @tape_migration_sql = IF(
  (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='dc'
    AND table_name='dc_tenant_liquidity_bootstrap' AND column_name='tape_enabled') = 0,
  'ALTER TABLE dc_tenant_liquidity_bootstrap ADD COLUMN tape_enabled tinyint(1) NOT NULL DEFAULT 0',
  'SELECT 1');
PREPARE tape_stmt FROM @tape_migration_sql;
EXECUTE tape_stmt;
DEALLOCATE PREPARE tape_stmt;

SET @tape_migration_sql = IF(
  (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='dc'
    AND table_name='dc_tenant_liquidity_bootstrap' AND column_name='tape_user_id') = 0,
  'ALTER TABLE dc_tenant_liquidity_bootstrap ADD COLUMN tape_user_id varchar(64) COLLATE utf8mb4_bin DEFAULT NULL',
  'SELECT 1');
PREPARE tape_stmt FROM @tape_migration_sql;
EXECUTE tape_stmt;
DEALLOCATE PREPARE tape_stmt;

SET @tape_migration_sql = IF(
  (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='dc'
    AND table_name='dc_tenant_liquidity_bootstrap' AND column_name='tape_api_key') = 0,
  'ALTER TABLE dc_tenant_liquidity_bootstrap ADD COLUMN tape_api_key varchar(255) COLLATE utf8mb4_bin DEFAULT NULL',
  'SELECT 1');
PREPARE tape_stmt FROM @tape_migration_sql;
EXECUTE tape_stmt;
DEALLOCATE PREPARE tape_stmt;

SET @tape_migration_sql = IF(
  (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='dc'
    AND table_name='dc_tenant_liquidity_bootstrap' AND column_name='tape_funding_request_id') = 0,
  'ALTER TABLE dc_tenant_liquidity_bootstrap ADD COLUMN tape_funding_request_id varchar(128) COLLATE utf8mb4_bin DEFAULT NULL',
  'SELECT 1');
PREPARE tape_stmt FROM @tape_migration_sql;
EXECUTE tape_stmt;
DEALLOCATE PREPARE tape_stmt;

SET @tape_migration_sql = IF(
  (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='dc'
    AND table_name='dc_tenant_liquidity_bootstrap' AND column_name='tape_funding_amount') = 0,
  'ALTER TABLE dc_tenant_liquidity_bootstrap ADD COLUMN tape_funding_amount decimal(35,16) DEFAULT NULL',
  'SELECT 1');
PREPARE tape_stmt FROM @tape_migration_sql;
EXECUTE tape_stmt;
DEALLOCATE PREPARE tape_stmt;

SET @tape_migration_sql = IF(
  (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='dc'
    AND table_name='dc_tenant_liquidity_bootstrap' AND column_name='tape_funding_confirmed') = 0,
  'ALTER TABLE dc_tenant_liquidity_bootstrap ADD COLUMN tape_funding_confirmed tinyint(1) NOT NULL DEFAULT 0',
  'SELECT 1');
PREPARE tape_stmt FROM @tape_migration_sql;
EXECUTE tape_stmt;
DEALLOCATE PREPARE tape_stmt;

SET @tape_migration_sql = IF(
  (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema='dc'
    AND table_name='dc_tenant_liquidity_bootstrap'
    AND index_name='uq_tenant_liquidity_tape_funding') = 0,
  'ALTER TABLE dc_tenant_liquidity_bootstrap ADD UNIQUE KEY uq_tenant_liquidity_tape_funding (tape_funding_request_id)',
  'SELECT 1');
PREPARE tape_stmt FROM @tape_migration_sql;
EXECUTE tape_stmt;
DEALLOCATE PREPARE tape_stmt;
