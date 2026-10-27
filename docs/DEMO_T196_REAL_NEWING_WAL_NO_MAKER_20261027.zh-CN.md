# T196 | Real Order NEWING signed WAL: no maker/fills yet

Scope: Mac mini Demo; all backend service sources retained on saas-crypto worktrees; no GitHub Actions or deletion of physical WAL.

## Actual progress
1. Common's E2 nonzero dual-RSA original WAL cold-replay API and its business READY gate are compiled. Trade B signed E2 P246 cash history of 3 frames replayed under Spring DB pool initialization order. Real Trade B started and Gateway accepted physical TradeSvrB; Trade A stayed Up.
2. MDSvrA/B actual 256 partition read routing installed (128/128); per-market image publication still separately fenced.
3. Order A/B rebuilt and started with Common certified synchronous NEWING admission, and scoped tenant product-rule negative-lookup fallback capped at one DB refresh per 60 seconds. No legacy Cancel/Fill bypass.
4. Real R0F6CC/e2e-depth10 Robot progressed through MD and product lookup, creating physically identical Order A/B WAL P089 of 806808 bytes, SHA-256 80473fec0056d31fec18a92ff90fa2f0a729c8db1ae0c72634da1eb4adf73353.
5. tests/T196OrderWalQuorumProof.java independently proved actual physical A copy has 660 contiguous committed E2 WAL entries and dual independent RSA quorum from pinned original keys. This is a READ-ONLY business historical input, NOT READY/fill authorization.

## P0 FAIL / deliberate stop
- OrderManager reported 660 active orders, 0 makerAdds, 0 execReports, 0 trades. These are pending NEWING/SUSPENDED, not visible settled quotes.
- TradeCertifiedNewingAdmission is gated behind trade.common.certifiedOpenNewing.enabled=true, absent from currently deployed A/B configs; Trade rejected NEWING requests with TRADE_COMMON_UNCERTIFIED_BUSINESS_PATH_DENIED.
- A few externally arrived Trade callbacks then hit legacy Order mutation path ORDER_COMMON_ATOMIC_STATE_PRECOMMIT_REQUIRED. The correct certified OrderFacade.commitPreparedRiskAcceptedNew() already exists but only handles successful risk ACK; rejection/cancel/fill currently not certified.
- Robot queryOpenOrder returned some session-scoped errors but later gateway call stats showed successful queries, which excluded pending NEWING. Robot kept attempting 20 new quotes per cycle because they never became approved/makers.
- Scoped persistent action: disabled only dc_tenant_robot at (R0F6CC,e2e-depth10). Observed runtime_status=STOPPED and no additional Order writes (activeOrders stabilized 660, addRequests=0). Do NOT reenable yet. Original WAL, cash postings and dual custody preserved.
- This is NOT successful Robot pricing, real matching, trading, HA switching or data reconciliation. Actual market maker count remains zero.

## Required next engineering
1. End-to-end Trade CertifiedNewingAdmission on actual signed Common writer; exercise signed complete after-state for margin/positions/open orders/decision; enable only after test, prove A physical hot rejoin with same pinned original signing/history first.
2. Order callback state migration: signed risk-accepted NEW, maker publication only after invariant uncrossed match plan; signed reject, cancel, fill and reconcile pending attempts without duplicate WAL or mutable-first writes.
3. Robot worker must not retry new IDs while previous signed NEWING intents remain unconfirmed. Use bounded pending intent count + reconciliation against domain order state, not open maker list alone.
4. Verify Admin symbol stream/negative-lookup behavior against future new tenants; keep scoped enabled/trial expiry filters.
5. New clean tenant E2E automatic Robot start, 10 bid + 10 ask lasting multiple quote refreshes, real maker/taker fill, Order/Trade A/B SIGKILL alternating, balance/position/order/trade/Projection equality.

Current observation and code commits:
- Common c9eff3d, Order 6adaa35, Trade 800ffaa.
