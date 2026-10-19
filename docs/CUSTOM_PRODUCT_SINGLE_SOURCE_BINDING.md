# Current price source per tenant product

Each enabled `(location, security_id)` has exactly one current `data_source_id`
link to an enabled, tenant-owned `dc_tenant_data_source`. The data source's
`source_symbol` is independent of the product's `security_id`.

- `CREATE`: save the tenant product and its one current source together.
  There is no ACTIVATE step.
- `BIND`: update that *one* source ID. The old binding ceases to be valid
  after the committed Admin querySymbol image is refreshed to MD, Order and
  Trade. Publishing a tick on the old source must not update that product.
- `UNBIND`: remove the product's source association; do not reuse the
  previously bound publisher price.
- Price selection: only the current source's mark/index quote can be used,
  and only while its source timestamp and TTL say it is valid. There is **no**
  comparison against a pre-switch quote, including no 1% limit.
- If the current quote is missing or stale, the effective quote must be
  unavailable. Never revert to the former data source automatically.
- Anonymous Trading Web uses tenant-scoped read-only `AdminSvr.querySymbol`;
  product/data-source administration remains authenticated.

This is **manual configuration switching**, not automatic provider failover.
The mistakenly implemented secondary-source migration and candidate code were
reverted before deployment. No `fallback_data_source_id` column is needed.

## Evidence and remaining live validation

MD Java regression validates old provider revocation, acceptance of the newly
bound source, current-price deviation greater than 80%, and expiry fail-closed.
These targeted tests are not a substitute for full Demo acceptance. Real tenant
`BIND`, APS price publish, MD-to-Trade/Liq streaming, two-trader matching and
Trade A/B failover remain to be accepted with authorized test sessions.
