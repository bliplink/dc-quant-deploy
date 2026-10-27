# T152 — Original Genesis actual business bytes + Common E1 zero-WAL install handoff (2026-10-26)

Baseline: original isolated T149 macOS ARM64 3x ZooKeeper, Order-A/B/C and Trade-A/B all RECOVERING; preserved original signed Genesis Order P090 (A/B), P091 (C/B), Trade P090 (A/B); T84 Demo untouched.

## Completed and actually executed on Mac

- Actual `OrderSnapshotManager.captureBusinessImage` on an empty, injected business Manager at Common E1 seq0 matches the immutable original T150 RSA-certified business bytes exactly:
  - Order-A/P090 **PASS**;
  - Order-C/P091 **PASS**;
  - Nonempty tracked Order book with changed update ID cannot match signed empty Genesis **PASS**;
  - Deterministic business serialization repeated **PASS**.
  - Dedicated Order T152 JUnit **4/4 pass, 0 skipped**, original pinned sealed files loaded from T149 data volume.
- Actual `TradeBusinessSnapshotCapture.capture` across Trade account, position, data, order and execution-dedupe managers at original E1 seq0 matches T150 Trade-A/P090 signed bytes **PASS**. A populated account balance cannot match original empty Genesis. Dedicated Trade JUnit **3/3 pass**, 0 skipped.
- Full Maven offline with preexisting original Demo RSA and T150 original Genesis test files:
  - Order **182 tests, 0 failure/errors, 2 skipped** (Order P091 added as independent final targeted run after full suite);
  - Trade **216 tests, 0 failure/errors, 0 skipped**;
  - Common T152 **562 tests, 0 failure/errors/skips** including original dual-RSA E1 immutable image and newly added `CommonCertifiedFreshGenesisInstall` E1 zero-WAL transaction cases.
- Common T152 `CommonCertifiedFreshGenesisInstall` is the new **fresh initial E1 head=0** pathway: dual-RSA source reopening + actual registered business snapshot preflight; zero-WAL/fence census injected; real business barrier + durable journal baseline adapter, snapshot seal, `REPLAY_COMPLETE` ledger at seq0; recheck and in-memory replay gate; always **NOT external READY**.
- Existing T149 isolated 5 Common RECOVERING nodes repeatedly verified RSA Genesis 6/6, signed tamper rejection 3/3 and real Netty WAL/unsigned-control refusal with ZK leases 5/5 in previous pass.

## GitHub PRs

- [Common T152 PR #34](https://github.com/bliplink/com.app.common/pull/34): draft, new authenticated fresh E1 zero-WAL installer on Common PR #33 (#32 prerequisite).
- [Order T151/T152 PR #20](https://github.com/bliplink/com.app.dc.ordersvr/pull/20): draft, canonical E1 timestamp + real original-image Manager test in later commit (P090/P091).
- [Trade T146-T152 PR #37](https://github.com/bliplink/com.app.dc.tradesvr/pull/37): draft, T146–T148 previous unpublished chain + canonical E1 timestamp + original Trade Manager bytes test in later commit.
- [Deploy T150 PR #83](https://github.com/bliplink/dc-quant-deploy/pull/83): real isolated T149/T150 evidence and this T152 handoff. NO GitHub Actions builds.

## Answer to "When can deployment begin?"

**The isolated deployment already began at T149 and its containers are running. A new non-READY candidate image can be built/deployed immediately, but it will NOT yet accept trading.** Avoid a cosmetic image swap that provides no additional verified source or business-runtime integration.

The **trading-enabled isolated deployment** is blocked on:
1. Implement Common's concrete `LiveFreshCensus` with *actual 3-ZK Manifest generation/E1 RECOVERING, lease CAS/current session, E1 original node public RSA, physical zero-ACK WAL and no previous writer READY*, not a unit-test callback.
2. Start actual Order/Trade business managers as fenced, non-listening recovery states in the candidate environment; inject their `PartitionStateMachineRegistry`, exclusive real business mutation barrier, durable CQ JournalBaseline and `CommonCertifiedFreshGenesisInstall`, prove both original voters install with persistent E1 REPLAY_COMPLETE.
3. Under Common authority validate fresh ZK and writer old-owner retirement, perform certified READY transition **only after real install**, close prior RECOVERING Netty listeners before new business listeners. Verify basic order/trade/position/balance and full saga.
4. Perform automatic SIGKILL A→B→A under nonzero business transactions, reconcile Projection/watermarks. This validates operational readiness; test-on-one-Mac is not independent host resilience.

**Official/demo business container replacement still NO-GO.** Do not invent a clock-time ETA from this evidence. Do not rework Robot or introduce service-owned cluster/READY logic. The Common cluster remains the one implementation for Demo/Order/Trade.