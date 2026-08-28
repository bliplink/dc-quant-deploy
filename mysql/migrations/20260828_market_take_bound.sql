-- Add a per-symbol market-order sweep boundary.
-- 0.05 means the market IOC may consume book levels no farther than 5%
-- from the best contra price observed when it enters OrderSvr.

SET @schema_name = DATABASE();

SET @add_market_take_bound = (
  SELECT IF(COUNT(*) = 0,
    'ALTER TABLE dc_symbol ADD COLUMN market_take_bound varchar(45) DEFAULT NULL COMMENT ''市价单最大扫单偏离比例'' AFTER min_notional',
    'SELECT 1')
  FROM information_schema.columns
  WHERE table_schema = @schema_name AND table_name = 'dc_symbol' AND column_name = 'market_take_bound'
);
PREPARE stmt FROM @add_market_take_bound;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE dc_symbol
SET market_take_bound = COALESCE(NULLIF(TRIM(market_take_bound), ''), '0.05')
WHERE symbol = 'BTCUSDT';
