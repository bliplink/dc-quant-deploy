-- Apply once to dc_tenant BEFORE deploying an AdminSvr version that creates 12-digit user IDs.
-- tenant_id is the independent numeric technical tenant identifier (1..9999).
-- tenant_code stays the tenant's unchanged business code; location stays the routing identity.
-- This migration does NOT UPDATE any existing user_id or trading records.
-- Auto-increment assigns stable numeric tenant IDs to existing tenant rows and
-- supplies a new ID on future INSERTs, without changing existing insert statements.
-- Take a database backup and verify id allocation before running this on a live cluster.
ALTER TABLE dc_tenant
  ADD COLUMN tenant_id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT AFTER location,
  ADD COLUMN next_user_no INT UNSIGNED NOT NULL DEFAULT 1 AFTER tenant_id,
  ADD UNIQUE KEY uq_tenant_numeric_id (tenant_id);

-- Verification: read-only queries after migration:
-- SELECT location, tenant_id, tenant_code, next_user_no FROM dc_tenant ORDER BY tenant_id;
-- SELECT COUNT(*), COUNT(DISTINCT tenant_id) FROM dc_tenant;
-- Numeric ID formatting/range (1..9999) is enforced by TenantUserService.
