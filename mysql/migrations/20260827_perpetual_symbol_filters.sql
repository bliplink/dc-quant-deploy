-- Keep this file synchronized with
-- dbscripts/DB/saas_perpetual_symbol_filters_20260827.sql.

SET @schema_name = DATABASE();

SET @add_min_order_qty = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE dc_symbol ADD COLUMN min_order_qty varchar(45) DEFAULT NULL COMMENT ''最小下单量'' AFTER qty_tick_size',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema = @schema_name AND table_name = 'dc_symbol' AND column_name = 'min_order_qty'
);
PREPARE stmt FROM @add_min_order_qty;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @add_min_notional = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE dc_symbol ADD COLUMN min_notional varchar(45) DEFAULT NULL COMMENT ''最小名义金额'' AFTER max_order_qty',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema = @schema_name AND table_name = 'dc_symbol' AND column_name = 'min_notional'
);
PREPARE stmt FROM @add_min_notional;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE dc_symbol
SET min_order_qty = COALESCE(NULLIF(TRIM(min_order_qty), ''), qty_tick_size),
    min_notional = COALESCE(NULLIF(TRIM(min_notional), ''), '5.00000000')
WHERE symbol = 'BTCUSDT';
