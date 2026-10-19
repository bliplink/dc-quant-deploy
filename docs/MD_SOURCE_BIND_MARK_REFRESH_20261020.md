# Tenant source BIND/UNBIND market mark refresh — Demo rollout

## Contract and deployed revision

- A tenant product uses exactly one `dc_tenant_symbol.data_source_id`.
  The administrator explicitly switches it using an authorized `BIND`.
  There is **no standby source**, implicit failover, ACTIVATE or 1% deviation limit.
- MD accepts AdminSvr `querySymbol` images, revokes the old source and
  re-publishes the new effective mark for the existing tenant Trade topic.
  If the newly selected provider has no valid TTL price, publish a null mark
  immediately, so Trade and Liq do not keep using a previously valid price.
  UNBIND and provider removal likewise send a null mark.
- The source binding callback is invoked only if the effective source mapping
  changes. Repeated identical full images are not re-published.
- Only MD PRIMARY/READY markets publish risk marks; price changes do not
  authorize a previously non-READY market.
- Source: MD local checkout commit `e44d03c`.
- Demo Docker: `local/dc-saas-mdsvr:source-bind-mark-refresh-20261020`.
- Compose overlay retained at `config/md-source-bind-mark-refresh-20261020.yaml`.

## Validation performed

- MD binding / tenant routing / price / bridge JUnit: **27 passed**.
- MD TradeFacade/price/TTL targeted JUnit: **22 passed**.
- Liq mark freshness JUnit **4 passed**, Trade mark freshness **2 passed**.
- Candidate image built locally from the existing
  `local/dc-saas-mdsvr:enabled-public-products-20261019` image, overlaying
  the compiled `TenantSymbolSourceCatalog`, `BrokerTenantMarkPublishBridge`
  and `TradeFacade` classes. No database schema or tenant data changes.
- Rolled MD-C, MD-B, then MD-A. Each new JVM needed to recover its market
  snapshot and partition READY status. Brief `9000` market responses appeared
  during startup; affected markets returned `code=0` after readiness.
- Final checks: tenant `H2FIJU/BTCUSDT` market `code=0`, disabled
  `H2FIJU/BTC001USDT` `code=5004`, `H00000/BTCUSDT` `code=0`.
- MD-A must retain `MDSVR_CONFIG_NAME=MDSvrA` when composing deployments;
  otherwise its generic config breaks P210 primary routing.

## Still required for full product acceptance

**No actual tenant `BIND`/`CREATE` was executed** in this rollout, so the
MD-to-Trade/Liq refresh behavior is **tested locally but not yet live
end-to-end accepted**. Tenant `BTC003USDT` did not yet exist in the inspected
scoped symbol table. The attempt to perform authorized tenant-admin login
in a previous execution was blocked by the execution environment; do not
bypass authentication. Verify one authorized BIND and an APS CUSTOM price tick,
then perform two-trader matched-order and Trade A/B HA reconciliation.

No GitHub Actions, no Documents-folder access, no tenant data deletion.
