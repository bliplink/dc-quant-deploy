-- Tenant operations dashboard scans the rolling 24h execution window by location.
SET @has_idx := (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'dc_orders_execorders'
    AND index_name = 'idx_exec_transact_time_location'
);
SET @ddl := IF(
  @has_idx = 0,
  'ALTER TABLE dc_orders_execorders ADD INDEX idx_exec_transact_time_location (transact_time,location)',
  'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
