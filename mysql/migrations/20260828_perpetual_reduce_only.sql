-- Keep this file synchronized with
-- dbscripts/DB/saas_perpetual_reduce_only_20260828.sql.

SET @schema_name = DATABASE();

SET @add_position_side = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE dc_orders ADD COLUMN position_side varchar(16) DEFAULT NULL COMMENT ''持仓方向'' AFTER oc_type',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema = @schema_name AND table_name = 'dc_orders' AND column_name = 'position_side'
);
PREPARE stmt FROM @add_position_side;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @add_reduce_only = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE dc_orders ADD COLUMN reduce_only tinyint(1) NOT NULL DEFAULT 0 COMMENT ''只减仓'' AFTER position_side',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema = @schema_name AND table_name = 'dc_orders' AND column_name = 'reduce_only'
);
PREPARE stmt FROM @add_reduce_only;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE dc_orders
SET reduce_only = 1
WHERE oc_type = 'ClOSE';
