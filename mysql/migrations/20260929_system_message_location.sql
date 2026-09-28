-- Preserve historical messages with NULL location. They remain invisible to
-- tenant-scoped readers until their ownership has been explicitly reviewed.
SET @has_system_message_location := (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema=DATABASE() AND table_name='dc_system_message' AND column_name='location'
);
SET @ddl := IF(@has_system_message_location=0,
  'ALTER TABLE dc_system_message ADD COLUMN location varchar(30) NULL AFTER id',
  'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_system_message_location_idx := (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='dc_system_message'
    AND index_name='idx_system_message_location_user'
);
SET @ddl := IF(@has_system_message_location_idx=0,
  'ALTER TABLE dc_system_message ADD INDEX idx_system_message_location_user (location,user_id,id,del_flag)',
  'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
