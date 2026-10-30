-- OpenTradingCore tenant product -> data source, 2026-10-19.
-- Metadata-only additive schema. Does NOT enable BROKER_PRICE_* features
-- or rewrite the current MD/APS price subscriptions.
--
-- One data source can be referenced by multiple tenant products.
-- One product has one optional data source. NULL retains the legacy
-- direct product-price behavior until the binding is explicitly activated.
--
-- Composite (location, data_source_id) key prevents cross-tenant binding.
CREATE TABLE IF NOT EXISTS dc_tenant_data_source (
  location VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  data_source_id VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  source_name VARCHAR(120) NOT NULL,
  source_type VARCHAR(16) NOT NULL COMMENT 'BINANCE or CUSTOM',
  source_symbol VARCHAR(64) NOT NULL COMMENT 'Independent external ticker e.g. BTCUSDT',
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  config_json JSON DEFAULT NULL COMMENT 'Provider options; NEVER plaintext credentials',
  create_by VARCHAR(64) NOT NULL,
  update_by VARCHAR(64) NOT NULL,
  create_time VARCHAR(30) NOT NULL,
  update_time VARCHAR(30) NOT NULL,
  PRIMARY KEY (location, data_source_id),
  KEY idx_tenant_data_source_enabled (location, enabled, source_type),
  CONSTRAINT chk_tenant_data_source_type CHECK (source_type IN ('BINANCE','CUSTOM'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Tenant-owned independent price/index source definitions';

-- Column/index/foreign key are applied independently for repeat-safe Mac deploys.
SET @ddl=IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='dc_tenant_symbol' AND column_name='product_name')=0,
 'ALTER TABLE dc_tenant_symbol ADD COLUMN product_name VARCHAR(128) DEFAULT NULL', 'SELECT 1');
PREPARE migrate FROM @ddl; EXECUTE migrate; DEALLOCATE PREPARE migrate;
SET @ddl=IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='dc_tenant_symbol' AND column_name='data_source_id')=0,
 'ALTER TABLE dc_tenant_symbol ADD COLUMN data_source_id VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL', 'SELECT 1');
PREPARE migrate FROM @ddl; EXECUTE migrate; DEALLOCATE PREPARE migrate;
SET @ddl=IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='dc_tenant_symbol' AND index_name='idx_tenant_symbol_source')=0,
 'ALTER TABLE dc_tenant_symbol ADD INDEX idx_tenant_symbol_source (location,data_source_id)', 'SELECT 1');
PREPARE migrate FROM @ddl; EXECUTE migrate; DEALLOCATE PREPARE migrate;
SET @ddl=IF((SELECT COUNT(*) FROM information_schema.table_constraints WHERE table_schema=DATABASE() AND table_name='dc_tenant_symbol' AND constraint_name='fk_tenant_product_data_source')=0,
 'ALTER TABLE dc_tenant_symbol ADD CONSTRAINT fk_tenant_product_data_source FOREIGN KEY (location,data_source_id) REFERENCES dc_tenant_data_source (location,data_source_id) ON UPDATE RESTRICT ON DELETE RESTRICT', 'SELECT 1');
PREPARE migrate FROM @ddl; EXECUTE migrate; DEALLOCATE PREPARE migrate;
