# T142 / 2026-10-26 — Common-exclusive RECOVERING process for Order / Trade

## Fixed root cause

Earlier the formal RECOVERING phase was selected with Spring Bean conditions but still launched the entire Order/Trade Spring context. Business adapter initialization required `CommonCertifiedNodeRuntime` and a certified writer before recovery could finish; therefore PREPARING/RECOVERING could not boot, even though the Common recovery-only TCP listener itself was valid. This caused a circular start-up requirement and repeated formal business startup failures.

## Implementation (single Common engine)

`com.app.common.replication.CommonRecoveryOnlyProcess` now implements a **Spring-free, business-handler-free Common RECOVERING entry**. Order and Trade call it from their JVM main entrypoints **BEFORE** `ServerGwWrapper.StartCertifiedBusiness` on the exclusive `*.common.nodeRuntime.phase=RECOVERING` path. The service supplies only existing read-only RSA paths and a node alias; its ZooKeeper CAS, ephemeral lease, node RSA challenge, Netty transport, recovery-only RPC admission, revocation checks and control-plane polling are entirely implemented by the SAME Common `CommonRecoveringNodeRuntime` already tested in Demo. No reimplementation of election/replication in Order or Trade. The `READY` path is still the existing Common-certified full business Spring runtime.

Every startup checks: real regular properties file, Common-only/old-cluster mutual exclusion flags, strict case-sensitive phase, RSA enabled, physical node ID, explicit ZK endpoint, manifest/lease/token, pinned service ID, recovery listener interface and nonprivileged port. Load original RSA BEFORE creating ZooKeeper. Common runtime independently validates pinned RSA, actual RECOVERING partition census, session-owned CAS lease and non-routable state. On each control interval it rechecks majority CAS / assignment; a changed manifest or revoked lease fails closed and closes listener + ZooKeeper. It cannot issue a business or fake READY; the signed source operation table remains EMPTY until genuine physical head/source handlers are installed.

## Actual isolated execution (no access to live services)

- Common's focused unit tests verified both service modes, no opening ZooKeeper if RSA missing, failure on invalid phase/port, and existing Common recovering RPC tests verified business WAL and unsigned recovery RPC reject.
- **Both official ARM64 service images built cleanly**, `local/otc-t142-ordersvr:recovering-isolated` and `local/otc-t142-tradesvr:recovering-isolated`, one EXACT `3.0.22-t142-spring-free-recovering-only-20261026-SNAPSHOT` Common JAR SHA256 `4bdb568adc4ba74b70285c5974471c3cf8a6db555b8b47a55304122edb0d5e66`.
- With the already-created Demo original RSA mounted read-only, explicit ZK aliases and full recovery-only properties, **actual containers reached Common `ZookeeperClient.<init>`**. Because `--network none` is intentional, both exited with code 1, with **no Spring context / no Order or Trade business initialization**. This test proves the previous Spring circular dependency is bypassed, **not** a working ZK session or completed business recovery.

## Remaining nonnegotiable acceptance before live Order/Trade

1. Populate the recovery-only listener's signed source operations with original **service-specific** physical source (valid Snapshot/WAL, head, custody, surviving replica/old-owner fence), only through the Common typed signed control handlers; reject absent/unsigned services.
2. On fresh service cluster bootstrap, pin ORIGINAL RSA voter memberships and persist certified E1 Genesis. In RECOVERING, invoke the *real* `CommonCertifiedPhysicalEvidenceRegistry.installSignedSurvivor` and `OrderCommonRecoveryBinding.recover` / `TradeCommonRecoveryBinding.recover`, matching signed WAL watermarks and domain snapshot before Common publishes READY.
3. Make recovery-only → certified READY restart/transition automatic from validated Common state, without service-local election and with the original recovery listener fenced/closed before any trading listener. Never do a phase file flip as a substitute for external ZK signed READY.
4. Convert every actual Order matching, cancel and fill and Trade cash/position flow to deterministic staged **Common commit-before-apply**; legacy fail-closed guards cannot be deleted to unblock the containers.
5. Only after those pass: actual fresh Order/Trade business flow, SIGKILL A→B→A, authoritative balances/positions/orders/fills/Projection watermarks, then 256 partitions and 10/50/200 tenants. The old `dc-saas-ordersvr*` and `dc-saas-tradesvr*` containers must remain stopped until end-to-end evidence is satisfactory. Demo T84 remains running unchanged.

No Robot changes, no Github Actions compilation, no merging into mainline or production rollout.

## T142 final verification

- Common Maven full test: **549 tests, 0 fail/errors/skip**.
- Order full test: **171 tests, 0 fail/errors, 4 skips**. Trade full test: **195 tests, 0 fail/errors, 2 skips**.
- Actual `linux/arm64` candidate images are `local/otc-t142-ordersvr:recovering-isolated` and `local/otc-t142-tradesvr:recovering-isolated`; both contain exactly one identical Common T142 JAR hash `4bdb568adc4ba74b70285c5974471c3cf8a6db555b8b47a55304122edb0d5e66`.
- Actual Docker run: existing A original RSA mounted read-only at `/read-only-original-rsa`, app configured with `OrderSvrA@CommonHaDemoA` / `TradeSvrA@CommonHaDemoA`. `--network none` caused the independent Common `ZookeeperClient` to reject (exit 1); both had no legacy business Spring startup errors. Does **not** grant READY or confirm genuine ZooKeeper lease.
- Same pinned T142 Common runs authentic Demo 3-ZK with independently running C (E2/E3 signed custodial witness); real A JVM SIGKILL, B resumes certified local-mode trades and A catches up, real B SIGKILL, A certified E3 continues. **PASS**, final evidence `/Users/kong/.opentradingcore/t124-live-kill-runs/20261026084439` and `/tmp/t142-real-threeZK-Demo-two-SIGKILL-faults.log`.
- **Important outstanding lifecycle gap:** A separately launched RECOVERING-only JVM cannot silently claim READY. Its handler table is empty and cannot run service-specific actual Snapshot/WAL state restore yet. Original business recovery completion and replay evidence MUST be durably persisted and reverified on the READY service process bootstrap. The existing in-memory `CommonCertifiedBusinessReplayGate` cannot simply be transferred from a RECOVERING JVM to a READY JVM. Neither Common RSA validation nor the external ZK manifest may be skipped for this handover. These remain NO-GO.
