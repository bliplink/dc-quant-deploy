-- Optional secondary price source for a tenant product. Only an enabled source
-- owned by the SAME location may be selected; a missing/freshness-failed
-- fallback does not authorize system/Binance price leakage.
ALTER TABLE dc_tenant_symbol
  ADD COLUMN fallback_data_source_id VARCHAR(64) DEFAULT NULL
  COMMENT 'Secondary price source for automatic TTL fallback' AFTER data_source_id;
