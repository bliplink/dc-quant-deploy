-- Tenant-authoritative API key ownership; safe for repeated one-click deployments.
UPDATE dc_users_api SET location='' WHERE location IS NULL;
ALTER TABLE dc_users_api MODIFY COLUMN location varchar(64) NOT NULL DEFAULT '' COMMENT 'authoritative tenant location';

SET @has_idx := (SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='dc_users_api' AND index_name='idx_users_api_location_user');
SET @idx_sql := IF(@has_idx=0,
  'CREATE INDEX idx_users_api_location_user ON dc_users_api(location,user_id,enable)',
  'SELECT 1');
PREPARE stmt FROM @idx_sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
