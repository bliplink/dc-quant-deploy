-- OpenTradingCore per-tenant symbol identity.
-- Preserve existing dc_symbol rows as global fallback templates (location='').
-- Roll out only with matching Admin/Order/Trade/MD/Liq consumers.
ALTER TABLE dc_symbol
  ADD COLUMN location VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin
  NOT NULL DEFAULT '' AFTER id;

CREATE UNIQUE INDEX uq_dc_symbol_tenant_code
  ON dc_symbol(location, symbol);

-- dc_tenant_symbol PK(location,security_id) remains the source of enable/disable
-- and source binding. QuerySymbol and trading clients hide disabled products.
