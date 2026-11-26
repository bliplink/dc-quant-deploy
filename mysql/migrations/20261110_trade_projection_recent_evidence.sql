-- Keep live acceptance reads bounded by their recent window as history grows.
SET @missing_recent_postings := (
  SELECT COUNT(*) = 0 FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'dc_trade_projection_mutation'
    AND index_name = 'idx_trade_projection_recent_type'
);
SET @ddl := IF(@missing_recent_postings,
  'ALTER TABLE dc_trade_projection_mutation ADD INDEX idx_trade_projection_recent_type (entity_type,source_type,create_time), ALGORITHM=INPLACE, LOCK=NONE',
  'DO 0');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @missing_recent_events := (
  SELECT COUNT(*) = 0 FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'dc_trade_projection_event'
    AND index_name = 'idx_trade_projection_event_create_time'
);
SET @ddl := IF(@missing_recent_events,
  'ALTER TABLE dc_trade_projection_event ADD INDEX idx_trade_projection_event_create_time (create_time), ALGORITHM=INPLACE, LOCK=NONE',
  'DO 0');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
