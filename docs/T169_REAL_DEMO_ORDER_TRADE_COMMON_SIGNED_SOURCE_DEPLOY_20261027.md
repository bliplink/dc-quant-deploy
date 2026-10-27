# T168 / T169 Direct Demo Order/Trade Deployment — 2026-10-27

## Confirmed actual operation

Replaced the **official** `dc-saas-ordersvr` and `dc-saas-tradesvr` stopped containers using `/Users/kong/dc-quant-deploy/compose.yaml` and the real `.env.prod`, host networking and existing database/Gateway. This was NOT an isolated test.

- T168 images `local/otc-t168-ordersvr:verified-serving-domain` and `local/otc-t168-tradesvr:verified-serving-domain` built on local ARM64, pinned to real Common Jar SHA256 `a2c3a5d3efcb578f627aa65b54066f498c835e2da7a1e1c7b227812073f66864`.
- T168 Order/Trade code includes Spring-managed actual OrderManager and Trade balance/position/order/dedup snapshot verification: re-open physically mounted Genesis E1 snapshot, hash it and compare byte-identical canonical in-memory business image. E1/no-ACK only; any later HEAD rejects, no synthetic READY.
- T169 builds `local/otc-t169-ordersvr:certified-historical-members` and `local/otc-t169-tradesvr:certified-historical-members` with identical Common Jar SHA256 `f3b63e03598c05476c660d4dc5adf21f83106b84aca79e7d751b2bca92595da3`. Order & Trade full Maven `test package` succeeded locally. No GitHub Actions.
- T169 Common now implements `CommonSignedReplayHandoffProof.SignedPreviousMembers` through `CommonOriginalE1SignedMembersSource`, which requires the real physical original dual RSA signed Genesis quorum, BOTH original signed zero-WAL birth receipts, BOTH original separately installed E1 business images and durable REPLAY_COMPLETE ledgers, exact RSA public key, and SAME original ZK session/lease. Order and Trade only inject this shared Common component.
- T169 real official Compose overlay `/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016/control/common-t167-direct-live/compose.t169-live.yaml` was used with existing `compose.t167-live.yaml` and `compose.t167-real-rsa.yaml`. Original T113 configuration files were preserved, with legacy lifecycle/failover/replication disabled in separate override copies; existing original RSA private/public keys were only mounted read-only.

## Exact real service startup blockers now

Official T169 Order A and Trade A both reached Common's *real signed original source* code and safely exited at:

```
COMMON_SIGNED_PREVIOUS_E1_MISSING:order.common.nodeRuntime.freshE1.namespace
COMMON_SIGNED_PREVIOUS_E1_MISSING:trade.common.nodeRuntime.freshE1.namespace
```

This is NOT merely a missing Spring Bean; a previously nonexistent fully-certified fresh E1 original namespace and original birth-time physical proof are **not** provisioned in the **official** ZK and official node data roots. T164 certs belong to separate isolated namespaces, cannot be copied in as if signed in production. Do NOT manually fill in a T164 path or fabricate an original birth timestamp.

Official other instances Order B/C and Trade B remain stopped on older T113. An earlier attempted bulk live secondary update was refused by execution safety checks; do not represent it as deployed.

Gateway robotRuntime / pilot H00001: `ERROR`, `SERVER.OrderSvr is not Online` and `SERVER.TradeSvr is not Online`; `open_order_count=0`. The live Robot has NOT resumed buy/sell quote submission or MD depth.

## What genuinely remains

1. **Actual official** Common ZK fresh namespace for all tenant-routed partitions (T164 only P090 is insufficient for pilot/25 tenants), signed original E1 membership, non-retroactive virgin WAL roots/birth evidence from original A/B, original business Genesis capture and durable replay. The real namespace must be verified by official ZK session, not external T164.
2. Common initial E1 (never-served and no ACK) -> authenticated higher-Epoch READY authorization **and physical WAL/CommitIndex/Custody writer setup**, not a raw ZK READY toggle. Existing `CommonOriginalE1FirstActivationStage` only allows E2 RECOVERING and does NOT yet authorize READY.
3. Order/Trade Spring must restore the signed business state into its **actual serving JVM**, and obtain independently authenticated Common writer registry before any Gateway startup. A standalone RECOVERING test JVM is not a substitute.
4. Verify official Gateway Online, real Robot `RUNNING` with positive `open_order_count`, bid and ask orderbook depth through MD and authenticated trade/cancel/Projection consistency. Run `tools/t149-recovering-only/verify-t165-live-demo-robot-quote.py`.

**Current result: official ARM64 source and Docker replacement executed; formal business service startup remains FAIL-CLOSED; Robot real quoting NO-GO.** No legacy Order/Trade self-owned HA enabled. No historical WAL or private keys modified. No Github Actions.