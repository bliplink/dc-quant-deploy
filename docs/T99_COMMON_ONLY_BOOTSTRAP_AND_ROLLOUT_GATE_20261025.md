# T99 — Order/Trade Common-only startup, actual isolated deployment, and rollout refusal

**Executed 2026-10-25 (Asia/Shanghai)** on Mac mini. GitHub Actions were not used. No production-like Demo Order, Trade, ZooKeeper, MySQL or persisted WAL volumes were modified.

## Existing Common is reused, NOT rebuilt

`com.app.common` Git `5ce1b3a` is unchanged. It supplies `NodeClusterControlManager`, `NodePartitionGrantTable`, direct Netty transport, group WAL fsync, CommitIndex, physical certificate custody and strict ACK, recovery transaction and replicated state machine APIs. No new WAL/consensus algorithm was invented in Order/Trade or moved from service code to Common.

**Important integration distinction:** the isolated Common+Demo proof uses service-side `DemoV19DurableRuntime`, `DemoDurableJournal`, and `DemoV19NodeGrantBridge` to compose the already implemented Common primitives with live ZooKeeper, peers, disk, signed receipts and business operation ACK. This orchestration is not yet a generic prewired Spring service available to Order/Trade via `@Autowired`. Business adapter classes compile and can call Common recovery, but neither service installs a physical Common quorum commit writer in the actual mutation hot path. This is the outstanding production integration, **not a request to implement another WAL engine**. The Demo acceptance was isolated; it did not validate real Order/Trade trading and automatic role reversal.

## GitHub changes and fresh regression

| Service | Branch | Latest Git SHA | Clean Maven regression |
| --- | --- | --- | --- |
| Order | `feat/t93-order-common-only-delete-20261024` | `7b41d0c` | 148 tests, 0 failures/errors, 2 skipped |
| Trade | `feat/t92-trade-common-only-delete-20261024` | `201055a` | 174 tests, 0 failures/errors, 0 skipped |

Both had earlier removed **31 and 43 service-owned HA Java classes** respectively and now contain zero `com.app.dc.service.cluster` Java sources or classes. Both preserve domain `state` callbacks, use the same Common artifact SHA-256 `cf309a09d10db3486b700517e0a5e62d3f5b86f03e41ca11cc0a9151b38c67e3`, and default to `*.common.cluster.required=true` to reject accidental standalone bypass.

T98 commits `1c01266`/`057beee` added main-thread exit on startup failure. **An actual isolated Docker deployment demonstrated those were insufficient:** `ServerGwWrapper.Start` schedules `SpringApplication.run` inside a ZooKeeper registration callback (`ServerGwWrapper$1.start`), so Spring's error did not propagate to the original Java `main()`. Both containers remained `running` after `ORDER_COMMON_WAL_ACK_CUSTODY_NOT_CONNECTED`/`TRADE_COMMON_WAL_AND_CUSTODY_ADAPTER_NOT_INSTALLED` exceptions. We did not misclassify this as PASS.

T99 commits `7b41d0c`/`201055a` added fatal exit in the real OrderStart/TradeStart `CommandLineRunner` callback that invokes the Common admission check. The full Maven suites still pass.

## T99 actual Docker images and isolated integration evidence

- Order image: `local/otc-t99-ordersvr:failfast-7b41d0c`, ID `sha256:47bbcb849e5d903c45149fbb0d578a4229a16e1a2c5436645e430621a0a836e1`.
- Trade image: `local/otc-t99-tradesvr:failfast-201055a`, ID `sha256:a2898308e41cc531a750624cc2000c63d62b7821e74bbef800faf60597317704`.
- Images were incrementally rebuilt from fully verified T98 ARM64/Common-only candidates; only the changed startup callback class was overlaid. Both preserve the one Common SHA and zero private service cluster class directory; both are labelled `dc.release.authorized=false` / `dc.release.gate=NO-GO`.
- Actual test used a dedicated container `otc-t97-private-zk` on an **internal-only isolated Docker network**, fresh Order/Trade test data dirs, and a private copy of the ATS configuration pointing only to localhost inside the isolated ZK network namespace. ZooKeeper SASL was disabled **only for this disposable, nonproduction ZK test**. No live ZK, MySQL, data or tenant endpoints were reachable. A singleton test ZK does NOT prove quorum HA. Temporary test services and private ZK are stopped and removed after evidence collection.
- **Before T99**: candidate Java application threw the above Common gate error, but Docker remained `running`, a dangerous false-positive. **T99 result** after starting both services under the same isolated-ZK scenario:

| Real Docker operation | Outcome |
|---|---|
| Order startup with Common physical writer missing | `exited` **exit code 1**; `FATAL_ORDER_COMMON_CLUSTER_STARTUP` and `ORDER_COMMON_WAL_ACK_CUSTODY_NOT_CONNECTED` logged |
| Trade startup with Common physical writer missing | `exited` **exit code 1**; `FATAL_TRADE_COMMON_CLUSTER_STARTUP` and `TRADE_COMMON_WAL_AND_CUSTODY_ADAPTER_NOT_INSTALLED` logged |
| Test data/Compose mutation | None; dedicated temporary namespace only |
| Funds/positions/matching/automatic A→B→A | **NOT RUN / NOT PASS** because Common durable writer/READY is not wired |

Trade also reported private-test MySQL refusal at one earlier startup attempt, independent of the Common failure. No false claim of real trading or resilience is justified from these bootstrap tests.

`python3 tests/verify-t99-common-only-images.py`: real-image bytecode gate PASS (same Common JAR, no old service cluster classes, mandatory Common and fatal callback present). `--strict-release` exits **2 / NO-GO**, because the physical Common WAL ACK/custody/snapshot/READY is not installed and no genuine HA evidence exists. **No T99 image was promoted into the active Demo Compose.**

## Remaining production work, no new cluster algorithm

1. Install one real **Common node controller/physical WAL and custody adapter** per Order/Trade process, identical in semantics to the Common+Demo validated runtime. Wire both existing business mutation entrypoints through Common's WAL fsync, Netty replica and signed CommitIndex + dual custody durable ACK; verify every permitted ACK is signed and that RPC/physical receipt failures deny writes. Do NOT reintroduce service-owned WAL/HA algorithms.
2. Wire Common's existing snapshot and committed replay transaction, physical old-owner revocation, and authenticated READY state to the existing business snapshot/restore adapters. Fail-close by default; no unverified ready flip, no local workaround or bypass.
3. First run isolated full **3-ZK, two-physical-Order + two-physical-Trade nodes, tenant, MySQL/Projection, robot maker/taker** functionality and recovery; then SIGKILL A→B→A with replica rejoin and money/orders/fills/positions/Projection authoritative reconciliation. Record WAL ACK p50/p95/p99, failover RTO, TPS, errors and undelivered/doubly applied events.
4. **Only after real positive acceptance**, update active Demo Compose images and smoke the live system; then 10/50/200 tenants and burst. Existing live Docker images/volumes remain unchanged.

**T99 decision: startup fail-closed and Docker process-health correctness PASS. Common physical business writer and end-to-end HA/deployment NO-GO.**
