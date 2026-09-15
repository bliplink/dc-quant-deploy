SET @schema_name = DATABASE();

SET @ddl = IF(
  (SELECT COUNT(*) FROM information_schema.statistics
   WHERE table_schema=@schema_name AND table_name='dc_orders'
     AND index_name='idx_order_history_scope') = 0,
  'ALTER TABLE dc_orders ADD INDEX idx_order_history_scope (location,user_id,create_time), ALGORITHM=INPLACE, LOCK=NONE',
  'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = IF(
  (SELECT COUNT(*) FROM information_schema.statistics
   WHERE table_schema=@schema_name AND table_name='dc_orders_execorders'
     AND index_name='idx_exec_history_scope') = 0,
  'ALTER TABLE dc_orders_execorders ADD INDEX idx_exec_history_scope (location,user_id,create_time), ALGORITHM=INPLACE, LOCK=NONE',
  'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
