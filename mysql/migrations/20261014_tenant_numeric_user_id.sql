-- Required by AdminSvr TenantUserService numeric 12-digit per-tenant IDs.
-- MySQL 8.0 syntax; independent guarded DDL works on both fresh and
-- historical Demo tenant tables. No user rows are modified or renumbered.
-- Server allocates unique 1..9999 tenant_id through AUTO_INCREMENT.
SET @has_tenant_id := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='dc_tenant' AND COLUMN_NAME='tenant_id'
);
SET @migrate_tenant_id := IF(@has_tenant_id=0,
  'ALTER TABLE dc_tenant ADD COLUMN tenant_id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT, ADD UNIQUE KEY uq_tenant_numeric_id (tenant_id)',
  'SELECT 1');
PREPARE migrate_tenant_id FROM @migrate_tenant_id;
EXECUTE migrate_tenant_id;
DEALLOCATE PREPARE migrate_tenant_id;

SET @has_next_user_no := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='dc_tenant' AND COLUMN_NAME='next_user_no'
);
SET @migrate_next_user_no := IF(@has_next_user_no=0,
  'ALTER TABLE dc_tenant ADD COLUMN next_user_no BIGINT UNSIGNED NOT NULL DEFAULT 1',
  'SELECT 1');
PREPARE migrate_next_user_no FROM @migrate_next_user_no;
EXECUTE migrate_next_user_no;
DEALLOCATE PREPARE migrate_next_user_no;

-- The application serializes allocations via SELECT dc_tenant ... FOR UPDATE.
-- Existing tenants receive unique generated tenant IDs and next user number 1.
-- They keep all existing technical user IDs; new numeric users are allocated
-- only after checking for a collision in the existing dc_users table.
