-- Persist LoginSvr Open API authorization context in the session row.
-- Existing interactive sessions remain valid. Existing API/TenantAPI sessions
-- receive NULL snapshots and are intentionally rejected/re-authenticated by
-- LoginSvr after upgrade rather than regaining implicit scopes.

SET @ddl := (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE dc_users_session ADD COLUMN api_key_type varchar(32) NULL COMMENT ''trade/tenant/service API key class snapshot'' AFTER location',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema=DATABASE() AND table_name='dc_users_session' AND column_name='api_key_type'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE dc_users_session ADD COLUMN permissions varchar(512) NULL COMMENT ''Open API permission snapshot'' AFTER api_key_type',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema=DATABASE() AND table_name='dc_users_session' AND column_name='permissions'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE dc_users_session ADD COLUMN rate_limit_profile varchar(64) NULL COMMENT ''Open API rate-limit profile snapshot'' AFTER permissions',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema=DATABASE() AND table_name='dc_users_session' AND column_name='rate_limit_profile'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
