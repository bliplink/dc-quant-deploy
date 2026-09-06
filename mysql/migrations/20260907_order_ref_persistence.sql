SET @schema_name = DATABASE();

SET @ddl = IF(
  (SELECT COUNT(*) FROM information_schema.columns
   WHERE table_schema=@schema_name AND table_name='dc_orders' AND column_name='ref_order_id') = 0,
  'ALTER TABLE dc_orders ADD COLUMN ref_order_id varchar(255) DEFAULT NULL COMMENT ''OCO/replace parent order id'' AFTER clord_id',
  'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = IF(
  (SELECT COUNT(*) FROM information_schema.statistics
   WHERE table_schema=@schema_name AND table_name='dc_orders' AND index_name='idx_order_ref') = 0,
  'ALTER TABLE dc_orders ADD INDEX idx_order_ref (location,user_id,ref_order_id,close_by,ord_status)',
  'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
