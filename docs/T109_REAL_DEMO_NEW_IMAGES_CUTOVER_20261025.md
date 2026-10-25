# T109 — Actual Demo replacement with T108 Common-only Order / Trade: FAILED closed, old data discarded

**2026-10-25, Mac mini. User explicitly approved removing obsolete Order/Trade images, discarding old partition data, deploying new images and starting REAL service verification.** This is an **actual modification of the running Demo Compose**, not merely an isolated Common transport probe. The outcome is a **real startup failure / NO-GO**, so the trading backend is currently OFFLINE; web, Admin, MySQL, MD, gateway and ZooKeeper remain running. No real trading flow or automatic A→B→A passed. Do not report as healthy.

## Operations performed and independently checked

1. Identified actual Compose project `dc-saas` (`/Users/kong/dc-quant-deploy/compose.yaml`) and five old Order A/B/C / Trade A/B containers. Created an opt-in local Compose overlay explicitly pinning Order/Trade to the T108 candidate images.
2. Stopped all five old service JVMs. Moved old `data/OrderSvrA`, `data/OrderSvrB`, `data/OrderSvrC`, `data/TradeSvrA`, `data/TradeSvrB` folders aside *without moving MySQL or shared ZK/MD/APS folders*. Created five entirely new empty data directories.
3. First Compose recreate attempt **failed before Java**: `.env.prod` referenced a stale deployment root. Corrected runtime root to the actual live runtime path and retried. All five new ARM64 candidate containers were **created and actually started by production Compose**, rather than by a standalone Java integration harness.
4. The real Java main classes initialized far enough to emit explicit fail-closed errors, not any customer operation:
   - Order A/B/C: `FATAL_ORDER_COMMON_CLUSTER_STARTUP: ORDER_COMMON_WAL_ACK_CUSTODY_NOT_CONNECTED: refuse startup`.
   - Trade A/B: `FATAL_TRADE_COMMON_CLUSTER_STARTUP: TRADE_COMMON_WAL_AND_CUSTODY_ADAPTER_NOT_INSTALLED: refuse startup`.
   The Spring adapters currently contain intentional hard-deny branches (`OrderClusterAdapter.init()` and `TradeClusterAdapter.init()`) since a genuine production `CommonCertifiedNodeBootstrap` has not yet been wired to physical signed per-partition membership, ZK CAS and authenticated business recovery. **This failure is expected and proves that missing strict custody is not silently bypassed.**
5. Disabled `restart=unless-stopped` on these exact five failed T108 containers and stopped them, preventing restart storms. Their T108 image references remain visible in Docker. Other running Demo services remain unchanged.
6. Removed two unused old image tags (only after confirming no containers referenced them): `local/dc-saas-ordersvr:product-matching-mode-20261020`, `local/dc-saas-tradesvr:tenant-scoped-20261019`. Older Docker images with different tags may remain; this is not blanket `docker image prune`.
7. Updated the **private, untracked** production `.env.prod` atomically to make the new Order/Trade T108 image tags and correct `DEPLOY_ROOT` the default for future Compose operations. A secure private original-environment backup was preserved OUTSIDE Git; no secrets, RSA private keys, or config credentials were printed or committed. The overlay is also retained in the local T109 operation directory.
8. Per user authorization, permanently removed ONLY the five archived legacy Order/Trade partition data directories (about **102 GiB before cleanup**). Deletion completed successfully. Mac available space rose from ~**70 GiB to 147 GiB** (actual APFS free-space observation; do not equate net change to logical du sizes). New five partition directories remain empty. **This deletion is irreversible**; do not try to recover legacy Order/Trade data. MySQL still has OLD business data and must be reconciled/reset once the new fresh cluster is actually usable; do not silently mix it with fresh WAL.

## Actual Docker images after cutover

| Service | Actual new candidate | Startup state |
| --- | --- | --- |
| `dc-saas-ordersvr`, `dc-saas-ordersvr-b`, `dc-saas-ordersvr-c` | `local/otc-t108-ordersvr:common-zk-765d4b7` (`sha256:41f8291ba40f427e1a555507d86f6af54b5d5885654fef6180299ade0895ae8c`) | **Exited / forced shutdown after missing real Common WAL/Custody startup wiring** |
| `dc-saas-tradesvr`, `dc-saas-tradesvr-b` | `local/otc-t108-tradesvr:common-zk-5b110c8` (`sha256:ee0069f0eeb40249c662d113fe0b69d5e3a1830a24a069c2ad1f5262a10acbf0`) | **Exited / forced shutdown after missing real Common WAL/Custody startup wiring** |

The T108 binaries previously passed identical Common/Shared DC SHA verification, Common **496/496**, DC **41/41**, Order **166 tests / 2 skipped**, Trade **190/190**, and separate physical signed Netty probe **8/8**, but **NONE of those replace actual Order/Trade business functional and automatic HA acceptance**.

The new read-only actual Docker validator `tests/t109/verify-live-order-trade-common.sh` verifies the exact five new image names, real container state, restart count and fatal logs. It was **run against the real Demo** and correctly exited **2 / `T109_REAL_BUSINESS_STARTUP=NO-GO`**. Even if all JVM processes show `running` later, it returns 3 (non-PASS) until a separate authenticated business/fault injection gate is available.

## Concrete repair sequence — no private service-side cluster reimplementation

1. Wire actual Order and Trade Spring lifecycles into *existing Common* `CommonCertifiedNodeBootstrap` / `CommonCertifiedNodeRuntime`. Complete real `NodeClusterControlManager` with `ZkNodeScopedControlPlane` using authenticated physical genesis and `CertifiedNodeRecoveryGate.PhysicalVerifier` from a real persisted `CertifiedPersistedCustodySource`; do NOT register a success-returning dummy physical source or bypass `OrderClusterAdapter` / `TradeClusterAdapter`.
2. Reuse **previous Demo-created RSA** using read-only mounts. Map signed physical public keys to actual Order/Trade nodes and establish correct RF2 signed ZK voter assignment and peer Netty endpoints for all 256 partitions. Existing production ZK may still contain old epochs/assignments; authenticated fresh Genesis/old-owner fencing must be completed rather than silently granting READY because files are blank. If using a fresh isolated ZK, ensure production Gateway/MD/Projection connection configuration matches it at cutover.
3. Install real prepared-domain-command business logic: Order **new, cancel, modify, match/fill** and Trade **balance, position, execution/dedup** must stage BEFORE certified WAL/custody ACK; apply exactly once AFTER ACK. Current Order `OrderStateJournal.requireStagedBeforeMutation` and Trade `TradeStateCoordinator.requireWritable` deliberately reject unsafe mutation; do not remove until all business paths are atomic.
4. After verified business recovery/Genesis and physical READY, start Order/Trade A/B with consistent fresh MySQL/Projection state, register tenant, deposit, submit/cancel and match orders, fill, balance/position and watermark reconciliation; then real automatic SIGKILL primary A→B→A and recovered replica catch-up. Stress 10/50/200 tenants and 2–3x burst; strict ACK p50/p95/p99 must be measured and optimized (T108 single-sequence p50 still ~68ms in an 8-sample cold integration probe).
5. Only then remove the startup NO-GO and enable restart policies/production routing. Until then, do not make website trading look ready.

**Current operational status: T108 images are deployed as the five Compose service container definitions, old images/data removed as authorized, all five real business JVMs stopped after explicit COMMON_NOT_CONNECTED errors; trading OFFLINE / automatic HA NO-GO.**
