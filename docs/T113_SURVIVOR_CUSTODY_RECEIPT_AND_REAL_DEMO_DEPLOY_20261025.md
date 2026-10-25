# T113 — Survivor-side physically durable signed Custody quorum, actual Demo refresh

Date: 2026-10-25. This is an actual code, Maven, Docker and production-Compose integration update, not a simulated successful HA acceptance.

## Fixed Common ACK durability gap

Prior Common nodes copied signed WAL to A/B, certified the CommitIndex and installed the certificate on both disks, but the complete two-signature custody-installation quorum was persisted on the Primary only. Permanent loss of A could therefore strand B without independent receipt-quorum evidence of the acknowledged boundary.

Common change 1c2d89e:
- CommonCertifiedPartitionRuntime now installs DurableWalCustodyReceiptLedger and existing DurableWalCustodyReceiptControlHandler on both Primary and Replica.
- DirectNettyCertifiedBusinessTransport now sends both original independently signed installation receipts to B using the existing Netty control RPC, requires B to physically persist them and return the exact signed-quorum HEAD acknowledgement, then returns to the existing Primary durable ACK boundary.
- If B cannot fsync the quorum, the business operation does NOT receive strict client ACK, and the local writer is poisoned. Unacknowledged-but-fsynced WAL cannot be silently promoted to customer-confirmed state. Old-owner ZK revocation and business READY still require separate proof.
- Existing Demo RSA A/B were reused, no new keys issued. This does not implement a second cluster layer in Order or Trade.

Tests:
- 499 Common clean Maven tests / 0 failures / 0 skipped.
- Real Common Netty dual-receipt receipt ledger on B is required before ACK.
- Forced denial of B's durable receipt quorum RPC correctly denies client ACK.
- After A closes, opens only B physical WAL, signed physical Custody and independent two-signature receipt ledger, and reconstructs the authenticated prior commitment HEAD; refuses to infer READY from this without an independent old-owner fencer.
- These tests run independent logical JVM roles on one Mac, not multi-host HA.

## Source revisions and immutable local ARM64 images

- Common revision 1c2d89e, io.github.bliplink:com.app.common:3.0.22-t113-survivor-receipts-20261025-SNAPSHOT, SHA256 04ed6cca2d2f569dd961b1675853591b43705be952e1cbf48dc2da4ddc3976bc.
- Shared DC revision 2aa2dfd, version 0.0.5-t113-survivor-receipts-20261025-SNAPSHOT, SHA256 6c62d9a21cbc0e8926f523c35d9fc82191671c406daef670905a9e4c60d7c408.
- Order revision 2f4b98e, local/otc-t113-ordersvr:survivor-custody-2f4b98e, ARM64 image sha256:a284be835dd4f24937ec73df79759c30e7518dd1444a2c2a90e398f90cc76334.
- Trade revision 2f87223, local/otc-t113-tradesvr:survivor-custody-2f87223, ARM64 image sha256:adbcbfee79b0b21ba7c0cb9039e2ab8ab944e9a1dd51ee3120671ebb8fd44191.
- Locally clean-packaged both business modules: each image contains exactly ONE Common and ONE shared DC JAR at these exact hashes. No old service-private cluster class directory, no embedded *.pk8.
- No GitHub Actions, no Common central repository publication. Both image release labels dc.release.authorized=false.

## Actual Demo Compose deployment: fail-closed

The real /Users/kong/dc-quant-deploy private .env.prod was backed up to a local private file and re-pinned to the new T113 images. Actual Compose service recreation started all five Order A/B/C and Trade A/B Java mains. All five returned the clear same startup failure:
- Order: FATAL_ORDER_COMMON_CLUSTER_STARTUP: ORDER_COMMON_CERTIFIED_NODE_RUNTIME_NOT_INSTALLED.
- Trade: FATAL_TRADE_COMMON_CLUSTER_STARTUP: TRADE_COMMON_CERTIFIED_NODE_RUNTIME_NOT_INSTALLED.

The new five containers were stopped and Docker restart disabled to avoid restart storms. Admin, MySQL, ZooKeeper, MD, Gateway remain up, but the trading backend is OFFLINE. No fresh account, order, matching, balance, position, automatic A-B-A, authoritative watermark, latency SLO or 200 tenant performance passed. Old Order/Trade partitions were previously removed at T109 with user authorization; no additional business database or keys were cleared.

A read-only live gate tests/t113/verify-live-business.sh verifies actual image references, state, and fatal evidence; it returned exit 2 / NO-GO as intended.

## Work that still blocks REAL trade acceptance

1. Install a real per-partition CertifiedPersistedCustodySource based on genuinely surviving original persisted WAL, independently signed custody and complete persisted dual receipts, tied to signed previous-Epoch ZK membership and **real external old-owner fencing**. Existing Common source/verifier classes are present; the real Spring producer bean and fencer integration are missing.
2. Implement authenticated Fresh Genesis per partition (source-signed empty baseline, independent recipient sign-off, ZK CAS). No unsigned empty-file READY or reuse of stale ZK epochs. The previous user-authorized data reset alone does not confer write authority.
3. Install business replay/recovered committed watermarks and real CommonBusinessRecoveryReadiness for Order and Trade BEFORE exposing Common physical writers. Every mutation must be staged before quorum commit and applied exactly once after ACK. All order/cancel/match/fill and cash/position/trade paths must be audited.
4. After all three, deploy genuinely READY instances and run live maker/taker match, cancel, cash and position consistency/Projection reconciliation, automatic SIGKILL A→B→A, catch-up, no double primary, 10/50/200 tenants and strict ACK latency performance.

**Verdict: new physically durable survivor-side receipt quorum PASS; real Demo Order/Trade startup, trade functions and automatic HA NO-GO.**
