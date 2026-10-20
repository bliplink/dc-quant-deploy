-- Per-tenant, per-product matching/settlement mode. Existing products keep TRADE.
-- ORDER_ONLY uses OrderSvr's local execution bookkeeping, never TradeSvr funds.
-- The CREATE contract fixes this mode for the lifetime of each product.
SET @ddl = (SELECT IF(COUNT(*)=0,
  "ALTER TABLE dc_tenant_symbol ADD COLUMN matching_mode ENUM('TRADE','ORDER_ONLY') NOT NULL DEFAULT 'TRADE' AFTER market_indicator",
  'SELECT 1') FROM information_schema.columns WHERE table_schema=DATABASE()
  AND table_name='dc_tenant_symbol' AND column_name='matching_mode');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
