-- OpenTradingCore per-tenant symbol identity.
-- Preserve old dc_symbol rows as global fallback rule templates (location='').
-- Do NOT run until Admin/Order/Trade/MD querySymbol consumers are upgraded.
ALTER TABLE dc_symbol
  ADD COLUMN location VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin
  NOT NULL DEFAULT '' AFTER id;

CREATE UNIQUE INDEX uq_dc_symbol_tenant_code
  ON dc_symbol(location, symbol);

-- Existing dc_tenant_symbol PK(location, security_id) remains authoritative
-- for enable/disable and source binding. Disabled products are excluded from
-- trading querySymbol, Order, Trade, market data, risk and liquidation.
