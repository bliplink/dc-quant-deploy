-- Broker API v1: independent tenant price and liquidity sources.
-- Additive and reapply-safe. Defaults preserve existing SYSTEM/SYSTEM tenants.
-- IMPORTANT: migrate before rolling ManagerSvr builds that read these columns.
-- Broker mode transitions require a separately audited state machine that
-- revokes only system-maker-owned quotes; writing BROKER directly is not enough.
SET @current_schema = DATABASE();
SET @stmt_sql = IF(
 (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@current_schema
   AND TABLE_NAME='dc_tenant' AND COLUMN_NAME='price_source')=0,
 "ALTER TABLE dc_tenant ADD COLUMN price_source ENUM('SYSTEM','BROKER') NOT NULL DEFAULT 'SYSTEM'",
 'SELECT 1');
PREPARE bps FROM @stmt_sql; EXECUTE bps; DEALLOCATE PREPARE bps;
SET @stmt_sql = IF(
 (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@current_schema
   AND TABLE_NAME='dc_tenant' AND COLUMN_NAME='liquidity_source')=0,
 "ALTER TABLE dc_tenant ADD COLUMN liquidity_source ENUM('SYSTEM','BROKER') NOT NULL DEFAULT 'SYSTEM'",
 'SELECT 1');
PREPARE bls FROM @stmt_sql; EXECUTE bls; DEALLOCATE PREPARE bls;
SET @stmt_sql = IF(
 (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@current_schema
   AND TABLE_NAME='dc_tenant' AND COLUMN_NAME='source_config_version')=0,
 'ALTER TABLE dc_tenant ADD COLUMN source_config_version BIGINT UNSIGNED NOT NULL DEFAULT 1',
 'SELECT 1');
PREPARE bcv FROM @stmt_sql; EXECUTE bcv; DEALLOCATE PREPARE bcv;
SET @stmt_sql = IF(
 (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=@current_schema
   AND TABLE_NAME='dc_tenant' AND COLUMN_NAME='source_switch_state')=0,
 "ALTER TABLE dc_tenant ADD COLUMN source_switch_state ENUM('ACTIVE','SWITCHING','FAILED') NOT NULL DEFAULT 'ACTIVE'",
 'SELECT 1');
PREPARE bss FROM @stmt_sql; EXECUTE bss; DEALLOCATE PREPARE bss;
