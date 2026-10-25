# T112 — Order/Trade real Common startup integration and strict recovery gate

**Date: 2026-10-25. Status: real Demo trading OFFLINE, HA NO-GO.**

## What actually changed

- Replaced unconditional fail-fast exceptions in OrderClusterAdapter.init and TradeClusterAdapter.init with executable checks for an installed CommonCertifiedNodeRuntime, its authenticated physical ownership grant, service identity, certified business recovery, and physical Primary WAL writer registry.
- Wired CertifiedBusinessCommandRegistry from the shared Common node runtime into the existing OrderStateJournal / TradeStateCoordinator dependency slot, not a second Order/Trade replication implementation.
- Strengthened the Spring writer bean: it cannot publish ANY physical business WAL writer before CommonBusinessRecoveryReadiness certifies business snapshot/replay and external READY. Blank WAL and a Common Netty ACK alone are insufficient.
- The business recovery witness interface is not currently implemented by a genuine production recovered-state proof source; there is NO fake-ready fallback. Current user-facing trading remains disabled.
- No new RSA keys were generated, no GitHub Actions used, and the existing dedicated Common signed WAL/Custody mechanism was retained.

## Exact source revisions and regression

| Repo | Branch | Git SHA | Full clean test results |
| --- | --- | --- | --- |
| Common | feat/common-t82-certified-custody-20261024 | 6f48996 | 498/498 PASS, 0 skipped |
| Shared DC | feat/t85-common-ha-integration-20261024 | c26ce05 | 44/44 PASS |
| Order | feat/t93-order-common-only-delete-20261024 | 5253929 | 167 tests, 0 failed, 2 skipped |
| Trade | feat/t92-trade-common-only-delete-20261024 | d660574 | 191/191 PASS |

Both new ARM64 business images contain the exact same Common Jar SHA-256:
73bf162265cdf259f5f54209e2cc9ee3907c82895b2a6ab53e76c0f2c122b06a,
and shared DC Jar SHA-256:
83d22da7c14762dc2c8670b56a590a1361610425cf17c6469fcf9955f7011366.

## Actual Demo Compose replacement and verified failure

- Order A/B/C candidate: local/otc-t112-ordersvr:ready-gate-5253929, image sha256:e5296ebafb206fe58eafa66d0e09b198354feae04db18b6c0ecef18b11990c25.
- Trade A/B candidate: local/otc-t112-tradesvr:ready-gate-d660574, image sha256:e8de1ced958a600aaefafd74f591935170a3d6c2d354a4d0e5782cf53b9128bd.
- Both images have dc.release.authorized=false. The private production .env.prod was updated atomically to T112 tags with a private backup; no credentials were committed.
- The five real service JVMs were recreated and launched using actual dc-saas Docker Compose, rather than the separate Common transport harness. All five stopped after explicit log messages:
  - Order A/B/C: FATAL_ORDER_COMMON_CLUSTER_STARTUP: ORDER_COMMON_CERTIFIED_NODE_RUNTIME_NOT_INSTALLED.
  - Trade A/B: FATAL_TRADE_COMMON_CLUSTER_STARTUP: TRADE_COMMON_CERTIFIED_NODE_RUNTIME_NOT_INSTALLED.
- Docker restart policy was disabled and failed services stopped, so no CPU-consuming restart storm remains. The other Demo Admin, MD, MySQL, ZK and Gateway services remain up. Trading functionality is unavailable.
- The read-only actual-container validator tests/t112/verify-live-business.sh returned exit 2 / NO-GO correctly. Docker Up at startup is NOT a certified READY condition.
- Previous old Order/Trade partition files were already deleted under the earlier user-authorized T109 reset; no additional MySQL, ZK or RSA data deletion was done here.

## Necessary next implementation, not optional

1. Implement a real Common CertifiedPersistedCustodySource / CertifiedSignedWalEvidenceVerifier based on durable original WAL, independently signed dual Custody receipt and old-owner fencing. Reuse existing Demo A/B/C RSA. Complete signed physical Fresh Genesis and ZooKeeper CAS manifest authorization. Never grant READY merely for an empty WAL file or by setting a property.
2. Activate the Common Spring/ZK node runtime with the exact signed 256-partition node inventory, real Netty addresses and per-node identity. Supply CommonBusinessRecoveryReadiness ONLY after authoritative OrderCommonRecoveryBinding / TradeCommonRecoveryBinding replay and external ZK READY attestation.
3. Fix remaining Order new/cancel/match/fill and Trade balance/position/dedupe write paths to stage BEFORE certified Common physical ACK and apply exactly once AFTER.
4. Restart the actual business services and run real cash-in, order, match, cancel and fund/position/Projection reconciliation, then automatic A-to-B-to-A SIGKILL and 10/50/200 tenant load/performance. These checks are NOT yet passed.

**Verdict:** real code integration, full regressions and ARM64 candidate deployment PASS; certified business startup, active trading and automatic failover NO-GO.
