-- Crypto Open API v1 API-key policy metadata.
-- Additive and safe for existing trader/Robot keys. Existing keys receive
-- backward-compatible trader defaults; tenant/service keys may later choose
-- narrower or broader scopes explicitly.

SET @ddl := (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE dc_users_api ADD COLUMN permissions varchar(512) NOT NULL DEFAULT ''MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE'' COMMENT ''comma-separated Open API scopes'' AFTER location',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema=DATABASE() AND table_name='dc_users_api' AND column_name='permissions'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE dc_users_api ADD COLUMN ip_whitelist text NULL COMMENT ''JSON array or comma-separated IP/CIDR allowlist'' AFTER permissions',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema=DATABASE() AND table_name='dc_users_api' AND column_name='ip_whitelist'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE dc_users_api ADD COLUMN expires_at varchar(30) NULL COMMENT ''UTC expiry timestamp for Open API use'' AFTER ip_whitelist',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema=DATABASE() AND table_name='dc_users_api' AND column_name='expires_at'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE dc_users_api ADD COLUMN rate_limit_profile varchar(64) NOT NULL DEFAULT ''TRADER_STANDARD'' COMMENT ''Open API rate-limit policy profile'' AFTER expires_at',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema=DATABASE() AND table_name='dc_users_api' AND column_name='rate_limit_profile'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE dc_users_api ADD COLUMN label varchar(128) NULL COMMENT ''operator supplied API key label'' AFTER rate_limit_profile',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema=DATABASE() AND table_name='dc_users_api' AND column_name='label'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl := (
  SELECT IF(COUNT(*)=0,
    'ALTER TABLE dc_users_api ADD COLUMN last_used_time varchar(30) NULL COMMENT ''last successful Open API authentication time'' AFTER label',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema=DATABASE() AND table_name='dc_users_api' AND column_name='last_used_time'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

UPDATE dc_users_api
SET permissions='MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE'
WHERE permissions IS NULL OR trim(permissions)='';

UPDATE dc_users_api
SET rate_limit_profile='TRADER_STANDARD'
WHERE rate_limit_profile IS NULL OR trim(rate_limit_profile)='';

-- The generic column default is trader-safe for legacy keys. Existing
-- tenant/service keys must be converted to their own permission class.
UPDATE dc_users_api
SET permissions='MARKET_READ,TENANT_READ,TENANT_WRITE',
    rate_limit_profile='TENANT_STANDARD'
WHERE lower(trim(type)) IN ('tenant','service')
  AND (
    permissions IS NULL
    OR trim(permissions)=''
    OR trim(permissions)='MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE'
  );

UPDATE dc_users_api
SET rate_limit_profile='TENANT_STANDARD'
WHERE lower(trim(type)) IN ('tenant','service')
  AND (rate_limit_profile IS NULL OR trim(rate_limit_profile)='' OR rate_limit_profile='TRADER_STANDARD');

SET @has_idx := (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='dc_users_api' AND index_name='idx_users_api_openapi'
);
SET @idx_sql := IF(@has_idx=0,
  'CREATE INDEX idx_users_api_openapi ON dc_users_api(location,api_key,enable,rate_limit_profile)',
  'SELECT 1');
PREPARE stmt FROM @idx_sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
