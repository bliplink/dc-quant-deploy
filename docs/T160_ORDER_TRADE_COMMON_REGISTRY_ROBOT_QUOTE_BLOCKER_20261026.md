# T160 — Order / Trade original E1 business registry, real isolated deployment

Date: 2026-10-26. All commands executed on local Mac Mini arm64 with Maven offline; no GitHub Actions. Scope is only existing T149 isolated five candidate service containers and 3 original ZK voters. **Business/Robot trading has NOT recovered.**

## Goal and exact completion criterion

User explicitly requires: **existing Demo Robot actually posts BUY and SELL limit orders, live Order book shows both levels and a user can cancel/trade**, not merely Docker Up, a synthetic book or a unit test. This has **NOT** occurred as of T160. Last observation: all five old official `dc-saas-ordersvr*`/`dc-saas-tradesvr*` stopped; `dc-saas-robotsvr` still alive but logs `quote cleanup pending ... status=ERROR`. Gateway logs still fail queryOpenOrder/queryTradePosition (392 failures in one 60-second sample). Do not claim quote PASS.

## What changed, actually tested, and deployed

- Common: add `CommonFencedRegisteredBusinessDomain` to enforce that every Common ZK E1 RECOVERING partition has already been explicitly registered with `PartitionStateMachineRegistry` during the actual business manager load. Disallows missing, stale epoch, unexpected partition, null registry; closes business managers fail-closed. `CommonRecoveryOnlyProcess.FencedBusinessInspection` now returns this strongly typed Loaded registry, and Common validates before retaining. No service-owned election, Netty replication or READY.
- Order: `OrderFencedRecoveringBusinessState` now registers **the very same** `OrderRecoveryStateMachine` instances it constructs for actual loaded OrderManager/OrderSnapshotManager in Common's registry.
- Trade: `TradeFencedRecoveringBusinessState` similarly registers the same `TradeRecoveryStateMachine` backed by the loaded real TradeBalance/Position/Order/Execution-Dedupe state.
- Common local Maven offline `install` including full suite PASS. Current Surefire summaries after focused T160 4 cases: **574 tests, 0 failures/errors/skips** (full suite began before T160 targeted extra cases were added, then targeted ran separately, so this is the latest accumulated report, not one single Maven invocation). Original Demo A/B RSA retained.
- Order/Trade recompiled with **exact same new Common JAR**, SHA-256 `f58acf90fd955b0edd50017b6bdf232949600e6af4fad37b090d97b3ddfce2a0`.
- Two genuine ARM64 new images built and reproduced byte-identical using source-pinned `build-t160-registered-business-images.sh`:
  - `local/otc-t160-ordersvr:registered-business-recovering` — `sha256:621d1502e571c35f44c7be58738b839c5559651826cfb9f0f25ade36d16e1fa4`
  - `local/otc-t160-tradesvr:registered-business-recovering` — `sha256:57d740b88372f348d79db8a4ca0ba7fb3bd1ef7068f35cfc5583524065e3fa60`
- Prepared a **separate** T160 override from original test config only, `prepare-t160-registered-business-overlay.sh`; validated five image/read-only config mounts and no published business ports, original T149 configs unchanged.
- Ran `deploy-t160-registered-business.sh` on the real existing T149 isolated stack. Docker recreated ONLY five candidate business JVMs. Initial launch correctly denied old ZK ephemeral lease owners; after natural expiration/retry each passed 12-second stability gate and emitted the Common-fenced original E1 main JVM state-capture marker:
  ```
  T160_MAIN_JVM_COMMON_ZK_FENCED_BUSINESS_LOAD_PASS ordersvr-a
  T160_MAIN_JVM_COMMON_ZK_FENCED_BUSINESS_LOAD_PASS ordersvr-b
  T160_MAIN_JVM_COMMON_ZK_FENCED_BUSINESS_LOAD_PASS ordersvr-c
  T160_MAIN_JVM_COMMON_ZK_FENCED_BUSINESS_LOAD_PASS tradesvr-a
  T160_MAIN_JVM_COMMON_ZK_FENCED_BUSINESS_LOAD_PASS tradesvr-b
  T160_FIVE_REAL_MAIN_JVMS_BUSINESS_STATE_LOADED_ZK3_T84_UNCHANGED_PASS
  ```
- **Post-T160 live test executed, NOT extrapolated** from T153:
  ```
  T150_POST_GENESIS_6_RSA_REOPEN_5_FENCED_PASS
  T153_LIVE_ZK_BOTH_LEASES_ORIGINAL_RSA_READONLY_6_OF_6_PASS
  T153_POST_RECREATE_6_SIGNED_GENESIS_5_NETTY_DENY_6_LIVE_ZK_ALL_PASS
  ```
  Tested real dual-RSA P090/P091 Genesis, real ZK and signed voter leases, and five Netty business/write deny gates. This is important because the previous post-T158 repeat was blocked by environment checks.
- Common / Order / Trade source changes committed to local worktrees and uploaded to their existing DRAFT GitHub PR branches:
  - [Common #36](https://github.com/bliplink/com.app.common/pull/36)
  - [Order #21](https://github.com/bliplink/com.app.dc.ordersvr/pull/21)
  - [Trade #38](https://github.com/bliplink/com.app.dc.tradesvr/pull/38)

## Exact controls before any Robot quote / business READY

T160 represents registered read-only domain instances, **NOT** actual durable E1 installation or real Spring business state. `CommonCertifiedFreshGenesisInstall.install` is still not called by the production Common recovery JVM. The `OriginalVoterZeroWal` adapter is a required independent authenticated physical 0-ACK/WAL/CommitIndex/Custody source and is NOT implemented; original signed E1 snapshot and currently empty disk do not demonstrate historical absence of a client-acknowledged WAL. The two labeled Docker volumes are on the SAME Mac physical host.

Need to provide a *fresh-born genuinely certified original E1* with signed physical initial zero-ACK witnesses, or a verified authoritative reconciliation from real old CommitIndex/Custody; inject actual fsynced business JournalBaseline + exclusive mutation barrier; run Common install and independently reopen ledger `REPLAY_COMPLETE` on all original voters; then Common external ZK certified READY and full Order/Trade Spring/Gateway trading admission and actual Robot orders. An RFC RF1/local async mode can be evaluated separately but cannot falsely claim quorum durability/HA; legacy T113 business-owned clusters should not be resurrected as a claimed new Common solution.

### Reproduction (isolated only)

```bash
bash tools/t149-recovering-only/build-t160-registered-business-images.sh \
  /Users/kong/.webcodex-worktrees/ordersvr-7caf41e5-4661a89e \
  /Users/kong/.webcodex-worktrees/tradesvr-e0df3a38-9e0f452a \
  /Users/kong/.webcodex-worktrees/t116-common-shared-gate-20261025-0841f867/target/com.app.common-3.0.22-t143-durable-signed-crossjvm-handoff-20261026-SNAPSHOT.jar

bash tools/t149-recovering-only/prepare-t160-registered-business-overlay.sh \
  /Users/kong/.opentradingcore/t149-order-trade-deploy-20261026

bash tools/t149-recovering-only/deploy-t160-registered-business.sh \
  /Users/kong/.opentradingcore/t149-order-trade-deploy-20261026

bash tools/t149-recovering-only/verify-t153-post-deploy.sh \
  /Users/kong/.opentradingcore/t149-order-trade-deploy-20261026 \
  /Users/kong/.webcodex-worktrees/ordersvr-7caf41e5/target/dependency
```

**Acceptance now: T160 Common-fenced original E1 main JVM business registry PASS; business durable install NO-GO; online Robot quote NO-GO.** Never replace official Demo service images with still-RECOVERING-only candidates or claim false READY.