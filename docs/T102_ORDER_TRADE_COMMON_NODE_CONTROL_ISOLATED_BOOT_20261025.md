# T102 — Order/Trade reuse existing Common node control, fail-closed isolated deployment

**Date:** 2026-10-25 (Mac mini, Asia/Shanghai); local Maven/Docker builds only, no GitHub Actions. **Not a production HA release.**

## Source/Git

| Service | Git branch | Latest SHA | Fresh `mvn -q -o clean test` |
| --- | --- | --- | --- |
| Order | `feat/t93-order-common-only-delete-20261024` | `5a98f7d` | 155 tests, 0 errors/failures, 2 skipped |
| Trade | `feat/t92-trade-common-only-delete-20261024` | `04ef40b` | 181 tests, 0 errors/failures, 0 skipped |

Both previously removed all service-private cluster engines (31 Order/43 Trade Java classes, zero `service.cluster` source/bytecode). Both use **exactly one** unmodified Common JAR SHA-256 `cf309a09d10db3486b700517e0a5e62d3f5b86f03e41ca11cc0a9151b38c67e3` from Common SHA `5ce1b3a`.

T100/T101 changes add Spring `OrderCommonControlWiring` and `TradeCommonControlWiring`. Each is ONLY dependency-injection configuration for **Common's existing** `ZkNodeScopedControlPlane`, `NodePartitionGrantTable` and `NodeClusterControlManager`: one manifest Watch, one node-scoped CAS renewal, Common's bounded locally cached fencing permits. This adds no new service WAL, replication, election, snapshot authority, or READY algorithm.

The wiring is OFF by default. Enabling requires explicit `order.common.control.enabled=true` or `trade.common.control.enabled=true`, distinct trusted ZK hosts/credentials, physical node ID, manifest/ephemeral lease path, owner token, TTL and background renewal settings, plus a REAL DI bean implementing **`CertifiedNodeRecoveryGate.PhysicalVerifier`**. Spring cannot open the new node-scoped ZK session before the physical verifier dependency is available. Missing/blank identity, verifier or invalid renewal/TTL are refused. Unit tests verify actual Spring context OFF-by-default and missing-verifier failure. A physical production verifier has **not** been installed; these beans are NOT enabled in live Demo.

T102 changes add `ApplicationFailedEvent` listeners via service `META-INF/spring.factories`. `ServerGwWrapper` starts Spring from a ZK callback, so failure before `CommandLineRunner` otherwise risks leaving Netty/ZK threads alive while Docker reports `Up`. Listeners exit process status 1 on Spring context failure and omit potentially sensitive exception details from their own fatal message. Existing T99 callback-level fail-fast remains.

## Built Docker images (real binary attestations)

| Service | Image | Docker image ID |
| --- | --- | --- |
| Order | `local/otc-t102-ordersvr:failclosed-5a98f7d` | `sha256:547a3df8f444c75b651b0bcb0ad5bc47d113462da6d04682a18d556b0e77c2bd` |
| Trade | `local/otc-t102-tradesvr:failclosed-04ef40b` | `sha256:b3990e8b9e47df935018354051b0504f1cc3ce6028fe2166f233066d6eca6ab8` |

Linux ARM64; both build upon full Common-only candidates, add the new Common-control wiring and Spring failed-event listener bytecode/resource, retain the pinned Common SHA and **`dc.release.authorized=false`**.

## Actual isolated startup/negative tests

A dedicated temporary internal Docker network and **new standalone ZK** were used, with private disposable copies of control config, no live Demo/mySQL/WAL volumes, and ZK SASL disabled **only** in this disposable test. Services were started with their respective `-D*.common.control.enabled=true` but WITHOUT any `CertifiedNodeRecoveryGate.PhysicalVerifier` bean. Expected and observed: **fail closed, exit status 1**.

- **Trade**: `exited/1` with `FATAL_TRADE_SPRING_CONTEXT_STARTUP` and missing `PhysicalVerifier` dependency, before Common grant or trading READY.
- The first concurrent **Order** attempt exited status 1 for an unrelated race: both services attempted to create the same legacy `/MDTService` ZK root simultaneously. That result was NOT accepted as validation of Common admission.
- **Order retested alone** with a fresh isolated ZK: `exited/1`, with `FATAL_ORDER_SPRING_CONTEXT_STARTUP`, missing `PhysicalVerifier`, and **no** ZK root creation race. This is the accepted Order negative-test result.
- Temporary test services/ZK/network/control config copies were cleaned. Production-like `dc-saas-ordersvr` A/B/C and `dc-saas-tradesvr` A/B remain on their prior 2026-10-19/20 images; no SIGKILL or trading fault injection.

`tests/verify-t102-common-control-images.py` checks BOTH actual image IDs/labels, pinned single Common JAR, no old HA classes, existing business recovery/snapshot bindings, exact Spring factory listener, mandatory Common physical verifier and existing fatal exit paths. Binary check PASS; `--strict-release` exits **2 / NO-GO** with eight explicit release blockers: both services' physical WAL/certificate-custody business ACK, authenticated snapshot production/READY, lack of release authorization and no actual two-node HA acceptance.

## Remaining mandatory execution before Demo replacement

1. Supply a **real physical verifier** from Common's existing durable WAL, CommitIndex and independently signed dual custody evidence; no fake proof or bypass. Certify Genesis, old owner retirement and higher-Epoch takeovers.
2. Inject Common's durable mutation/ACK/replica transport into Order's real order/cancel/match path and Trade's account/position/fill mutation path; strictly prohibit partial business mutation before a valid Common committed boundary. Preserve latency requirements; never do per-WAL ZooKeeper reads.
3. Connect already implemented business state-machine snapshot/replay callbacks to Common's full authenticated recovery transaction and only Common-issued READY, including Projection authority reconciliation.
4. Run real isolated **3-ZK + A/B Order + A/B Trade + MySQL + Projection + APIs + Robot**, actual cash-in/trading/matching/fills/cancel, then automatic A→B→A SIGKILL/catch-up/role reversal and no-loss/no-duplicate/split-brain checks. Measure p50/p95/p99 WAL ACK, failover RTO and TPS. **Only then** swap Demo images and expand to 10/50/200 tenant load.

**Verdict:** node-scoped Common control configuration and secure failure startup PASS; live business WAL ACK/custody, end-to-end HA and Demo replacement still **NO-GO**. Do not describe this as deployment of new Order/Trade into the live Demo.
