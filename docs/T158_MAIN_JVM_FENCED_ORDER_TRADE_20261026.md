# T158 — Order/Trade main-JVM Common-fenced business inspection (2026-10-26)

## Actual result and deployment

**PASS — not READY.** New T158 ARM64 Order/Trade images were deployed into the existing isolated T149 runtime's **five business candidate containers**, while preserving all three ZooKeeper container IDs and both T84 Demo JVM IDs. Not a production/official Demo swap, no API/Gateway/Robot routing, no customer writable ports.

This is the first successful **actual OrderSvr.main / TradeSvr.main JVM** invocation of domain managers under the **same Common recovery lease** (instead of T156's separate helper Java process). Config opt-in `*.common.nodeRuntime.inspectFencedBusiness=true` was enabled **only** on five copied T158 config files mounted through a separate Compose overlay; original T149 `application.properties` files remain unchanged. No service-owned election, WAL copying, local READY or custom cluster control.

### Verified build/replay evidence

- Common new `CommonRecoveryOnlyProcess` retains the existing genuine same-JVM Common `ZookeeperClient`, old-RSA identity, original strict RECOVERING control listener and ZK majority lease CAS, then calls a read-only domain loader **between two Common recovery lease validation checks**. The returned business object remains strongly referenced and closes upon lease loss/normal shutdown. The original recovery listener still strictly refuses customer WAL and READY.
- Common full offline Maven test+local install with original Demo A/B RSA: **569 tests / 0 failures / 0 errors / 0 skipped**. This is the build used in T158 images, original Common jar sha256 `0c7fc859ad9a1d141d157bc252f4a54ab65c0fff78321ca413f3d4a33d926925`.
- Order full T158 Maven test/package: **182 cases / 0 failures / 0 errors / 2 skipped**. Trade: **216 cases / 0 failures / 0 errors / 0 skipped**. Both used the exact same locally installed Common jar sha256 above.
- Local ARM64 `linux/arm64` images built, verified with an independent read-only `docker run --network none --read-only` check that each image has exactly one Common jar with the same SHA:
  - `local/otc-t158-ordersvr:fenced-main-jvm` — image ID `sha256:55055743ad6ea676c097d80bfb5f9cc17fc0946b3963bb320a8dea3cfa57e8dd`.
  - `local/otc-t158-tradesvr:fenced-main-jvm` — image ID `sha256:07e0878b621e743839a80d3801be3332f1ee82bbafbfe3bf3ba9bfa6d859a34d`.
- Executed `prepare-t158-fenced-inspection-overlay.sh`, which copy-stages five original isolated configs under the runtime's `t158-fenced-inspection` directory and verifies Compose merge replaces ONLY the five intended read-only config mounts and images, with NO host-published ports. All original configs unchanged.
- Executed `deploy-t158-fenced-inspection.sh`. It only recreates existing isolated `ordersvr-a,b,c` / `tradesvr-a,b`, leaving all three T149 ZooKeeper containers and the original T84 Demo unchanged. On immediate replacement the fresh JVMs correctly refused old ephemeral sessions; the script waited for natural ZK lease expiration, retried once, and demanded 12s additional stability and expected business-main JVM evidence.
- **All five real deployed main JVMs PASS**:
  ```
  T158_MAIN_JVM_COMMON_ZK_FENCED_BUSINESS_LOAD_PASS ordersvr-a
  T158_MAIN_JVM_COMMON_ZK_FENCED_BUSINESS_LOAD_PASS ordersvr-b
  T158_MAIN_JVM_COMMON_ZK_FENCED_BUSINESS_LOAD_PASS ordersvr-c
  T158_MAIN_JVM_COMMON_ZK_FENCED_BUSINESS_LOAD_PASS tradesvr-a
  T158_MAIN_JVM_COMMON_ZK_FENCED_BUSINESS_LOAD_PASS tradesvr-b
  T158_FIVE_REAL_MAIN_JVMS_BUSINESS_STATE_LOADED_ZK3_T84_UNCHANGED_PASS
  T158_NO_GO: historical zero-WAL/Custody, durable real install and READY not yet certified
  ```
  Each container logged `T157_COMMON_ZK_FENCED_*_MAIN_JVM_BUSINESS_INSPECTION_PASS` with `ready=false durableInstall=false`.
- A post-deployment attempt to re-execute the older T153 real RSA/Netty/ZK full suite against the new T158 image was **blocked by the execution environment safety check**, so do not claim that specific post-T158 suite passed. The five main JVMs and ZK listener underwent real lease admission and business capture; the older T153 tests passed previously, NOT post-T158.
- After this deployment, the Common code additionally strengthened the opt-in gate to reject a missing read-only business adapter BEFORE loading RSA or connecting ZK. This additional safety patch is **committed locally but NOT included in the two deployed T158 image IDs**. The additional focused Common tests are **9/9 PASS** (6 recovery-only + 3 loader lifecycle). Thus the deployed SHA and test count above correspond to the earlier validated T158 release, not that as-yet unrebuilt followup.

### Reproducing the actual isolated deployment

Original T149 runtime `/Users/kong/.opentradingcore/t149-order-trade-deploy-20261026`.

1. Compile Common from `codex/t157-common-fenced-business-inspection-20261026`, Order from `codex/t157-order-fenced-domain-inspection-20261026` and Trade from `codex/t157-trade-fenced-domain-inspection-20261026`; offline Maven with original Demo RSA. These are not merged yet.
2. Build the T158 two candidate images locally using the original per-service Dockerfiles, prebuilt target classes/dependency and the **same** Common binary, tag as above. No GitHub Actions.
3. Run:
   ```bash
   bash tools/t149-recovering-only/prepare-t158-fenced-inspection-overlay.sh \
     /Users/kong/.opentradingcore/t149-order-trade-deploy-20261026
   bash tools/t149-recovering-only/deploy-t158-fenced-inspection.sh \
     /Users/kong/.opentradingcore/t149-order-trade-deploy-20261026
   ```

### Why this is not an actual Order/Trade READY or Robot test

The extra in-main-JVM component is still a **read-only inspection using freshly constructed domain managers**, not the full Spring business runtime, and it does NOT install a real business WAL journal, historical zero-ACK certificate, original two-voter custody, completed durable business state Ledger, or publish authenticated external Common READY. The old RECOVERING source listener remains the only Netty endpoint. It never accepted new orders nor offered a Gateway trade listener. This deployment must not be substituted for the official `dc-saas-` Order/Trade containers; the latter are still stopped, Robot and Gateway containers are alive but the trading path is not functional.

**Next exact work to enable Robot:** Birth-time original-voter authenticated zero-WAL/CommitIndex/Custody physical evidence; connect the real loaded Order/Trade business state to Common's `CommonCertifiedFreshGenesisInstall` under exclusive business barrier and durable journal baseline; recover/reopen REPLAY_COMPLETE across real main JVMs; Common external certified READY; then replace official Demo and run one tenant's existing Robot through quote/cancel/fill/balance/positions/Projection and A→B→A HA.