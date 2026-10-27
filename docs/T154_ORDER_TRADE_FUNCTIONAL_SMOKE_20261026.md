# T154 — Order / Trade functional test STARTED, distinguish online API vs business smoke

**Date:** 2026-10-26, Mac / ARM64 T152 business code + exact original T153 isolated runtime.

## User question: "什么时候可以开始测试 Order/Trade?"

**It has started NOW**, as a real production-domain business smoke using isolated JUnit instances and original dual-RSA Common signed Netty WAL/custody. The live T153 Docker service candidates are `RECOVERING` *and intentionally contain NO Spring/Gateway business runtime*. **The inter-container HTTP/trader API is NOT ready**, and NO live tenant/robot transactions, production traffic or HA failover have been executed. Do not confuse the two test stages.

### Executed T154 reproducible functional smoke

With original existing Demo A/B RSA keys and exact T152 source heads:
- Order: `4b1c7d8fce274208f4d6f74d7b70998775ad0a35`
- Trade: `2811eb262317206ef840eec9312a597ce9916bc8`

Added `tools/t149-recovering-only/run-t154-order-trade-business-smoke.sh` (no Docker restarts or ZK mutations). Executed the script from the deployment worktree, and independently parsed every named Surefire XML report. **The results from the final fresh script run**:

| Service | Unique tests | Failures | Errors | Skipped |
|--|--:|--:|--:|--:|
| Order | **45** | 0 | 0 | 0 |
| Trade | **52** | 0 | 0 | 0 |
| Total | **97** | **0** | **0** | **0** |

The previous manual two-batch count of Order 47 included `TradeExecOrderLifecycleSyncTest` twice (two duplicated cases); fixed in the runner. **97 unique is the correct count.**

**Order 45** covers:
- Production `OrderManager`, `OrderStateJournal`, original RSA A/B signed WAL with real local Netty replication and certificate custody; one partition original order New + cancellation.
- OrderBook, TIF (IOC/FOK etc), self-trade prevention, market-order safety, pending NEWING and cancellation, mass cancel, lifecycle partial fill callbacks, real asynchronous trade callbacks/timeout and WAL-before-business mutation.
- Real classes, original RSA and actual loopback TCP are used in relevant tests; no live Order HTTP/Gateway and no cross-service production fill.

**Trade 52** covers:
- `OrderFacade` -> `CheckManager` and five checks -> `ProcessOrder` risk -> Common original RSA A/B signed local Netty WAL/Custody -> actual free/frozen balance and positions; replay and conflicts.
- Financial state, margin, insufficient-funds rejection, idempotency/deduplication, account balance, positions, cash, funding, execution affected state, ADL, bankruptcy, MySQL posting unit test and recovery-applier.
- The `MySqlDBTradeDaoPostingTest` is an isolated test, NOT an assertion that official MySQL/Projection is running.

**Actual invocation**
```bash
bash tools/t149-recovering-only/run-t154-order-trade-business-smoke.sh \
  /Users/kong/.webcodex-worktrees/ordersvr-7caf41e5-4661a89e \
  /Users/kong/.webcodex-worktrees/tradesvr-e0df3a38-9e0f452a \
  /Users/kong/Documents/Codex/2026-10-18/referenced-chatgpt-conversation-this-is-an/work/common-ha-netty-v19-control-cache/v19-quorum-secrets
```

Actual final markers:
```
T154_REAL_BUSINESS_ORDER_PASS {'tests': 45, 'failures': 0, 'errors': 0, 'skipped': 0}
T154_REAL_BUSINESS_TRADE_PASS {'tests': 52, 'failures': 0, 'errors': 0, 'skipped': 0}
T154_ORDER_TRADE_REAL_FUNCTIONAL_SMOKE_97_OF_97_PASS
```
No GitHub Actions usage; all Maven calls `-o` on Mac.

### What blocks ONLINE API/real Order + Trade E2E next

The currently deployed `local/otc-t153-ordersvr:common-e1-candidate` and `local/otc-t153-tradesvr:common-e1-candidate` are intentionally `RECOVERING`. Both actual `OrderSvr.main` and `TradeSvr.main` execute `CommonRecoveryOnlyProcess.serve(...)` and `return`, *skipping* `ServerGwWrapper.StartCertifiedBusiness`, when `phase=RECOVERING`. No business Spring, no user sessions/REST/trade handler, no public writer port. This is a **correct fenced state**, not a mere port routing issue. Changing a config flag or manually writing READY without original zero-ACK WAL and installed business replay would violate the Common recovery invariant.

To begin online API E2E in the isolated environment, in order:
1. Wire genuinely authenticated original historical zero-WAL/CommitIndex/Custody *for each original voter* to T153 Common `OriginalVoterZeroWal`; the current Genesis-only directory does **not** prove historical absence.
2. Run real Order/Trade Spring domain state machines in **fenced, non-listening recovery** mode; Common fresh E1 `CommonCertifiedFreshGenesisInstall` must use actual exclusive journal baselines + durable `REPLAY_COMPLETE`. Re-verify original RSA, Common same-ZK-session manifests, node lease CAS and replay memory state.
3. Shut down/retire old RECOVERING listener and use Common external ZK certified READY transition; only then bootstrap actual `CommonCertifiedNodeRuntime` and Spring business. Do not add Order-/Trade-owned election/replication/READY algorithms.
4. **Next actual online smoke:** new tenant and trader account + deposit, Order limit placement/cancel, Trade initial margin reservation, crossing fills, balance/position changes and Projection watermark reconciliation. Follow with SIGKILL A→B→A while transactions continue, then 10/50/200 tenants.

**Go/No-Go:** standalone genuine domain business functionality: **GO and tested**. Online inter-container business / Order+Trade transaction: **NO-GO** until authentic Common installation/READY. HA role reversal: **NO-GO**. No credible clock ETA yet; it depends on finishing live physical audit and runtime wiring, not more isolated DTO tests.

The separate T153 isolated 5 service candidates + 3 ZooKeeper and original T84 demo remain unchanged by T154.