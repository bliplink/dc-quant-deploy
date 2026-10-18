-- Align the clean tenant database with AdminSvr's numeric trader-ID allocator.
-- Tenant technical ID forms the first four digits of every new trader ID;
-- each tenant owns an independent 8-digit monotonically increasing suffix.
-- Safe to run repeatedly during a normal deployment.
SET @ddl = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE dc_tenant ADD COLUMN tenant_id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT, ADD UNIQUE KEY uq_dc_tenant_numeric_id (tenant_id)',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'dc_tenant' AND column_name = 'tenant_id'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE dc_tenant ADD UNIQUE KEY uq_dc_tenant_numeric_id (tenant_id)',
    'SELECT 1')
  FROM information_schema.statistics
  WHERE table_schema = DATABASE() AND table_name = 'dc_tenant' AND index_name = 'uq_dc_tenant_numeric_id'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE dc_tenant ADD COLUMN next_user_no BIGINT UNSIGNED NOT NULL DEFAULT 1',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'dc_tenant' AND column_name = 'next_user_no'
);
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Fail closed rather than allocate duplicate or out-of-range numeric identities.
SELECT IF(COUNT(*) = 0, 'PASS', 'INVALID_TENANT_NUMBER') AS tenant_number_check
FROM dc_tenant WHERE tenant_id NOT BETWEEN 1 AND 9999 OR next_user_no < 1 OR next_user_no > 99999999;
