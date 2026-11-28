SET @ddl = IF(
  (SELECT COUNT(*) FROM information_schema.statistics
   WHERE table_schema=DATABASE() AND table_name='dc_users_posting'
     AND index_name='idx_posting_history_scope') = 0,
  'ALTER TABLE dc_users_posting ADD INDEX idx_posting_history_scope (location,user_id,create_time), ALGORITHM=INPLACE, LOCK=NONE',
  'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
