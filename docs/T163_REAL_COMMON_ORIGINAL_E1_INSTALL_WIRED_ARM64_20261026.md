# T163 actual Common-certified original E1 install entry and isolated ARM64 run — 2026-10-26

## Source and build

- Common branch `codex/t158-common-fenced-business-main-jvm-20261026`, remote `c94699c148cef9fb6a0708571dbe00bf227c3cb7`. Full local tests: **584**, 0 failed, 0 errors, 0 skipped. Exact Common Maven Jar SHA256 `1f155c487ad1730744824cac80c77ecdfa8efcba78de6fb3dff0c8f79ac44208`.
- Order branch `codex/t158-order-fenced-main-jvm-20261026`, remote `c93c04a8d74834ed97b765024e88c072053f98e1`; local `b2516b51e5d162de84d004771ae3a620f81d9f99`, 182 total / 5 skipped / 0 failures.
- Trade branch `codex/t158-trade-fenced-main-jvm-20261026`, remote `de5f4333e6d35c0a6e6eb63ae5d35f34967fbfbe`; local `073b33543a460b5ce84d339e1e4802b0048b43f4`, 216 total / 2 skipped / 0 failures.
- ARM64 Order image `local/otc-t163-ordersvr:original-e1-install-hook`, ID `sha256:20eca65d945762bd340c3c71fc0eb7217bcc5c41d7b37cff4bad74cb22fc4287`.
- ARM64 Trade image `local/otc-t163-tradesvr:original-e1-install-hook`, ID `sha256:68d149a5ac2f8890f75f4cc6dce4321eb41e0fb5c3ff8e89feb29cf2461b6fb7`.
- Reproducible local builder `tools/t149-recovering-only/build-t163-original-e1-hook-arm64.sh` and isolated deployment `tools/t149-recovering-only/deploy-t163-original-e1-hook.sh`.

## Actual T163 isolated deployment verification

Updated all five previously isolated T149 Order/Trade JVMs. All five are running after authentic Common recovering ZK lease, original pinned RSA identity and loaded original business state machine census. The original 3 ZK container IDs and separate T84 Demo A/B container IDs were not changed. Zero externally published business ports, zero READY and zero customer WAL ACK.

T163 production recovery API, shared in Common, includes:

1. Genuine new E1 physical zero-ACK birth receipt (signed original RSA and fsynced at first never-existing WAL root creation; cannot retroactively mark preexisting directories as empty).
2. Exact original E1 signed Genesis preflight and business state machine registration census; original physical HEAD/Custody zero evidence and ZK ownership checked by the **same** live ZK session.
3. Common durable initial journal baseline, sealed checkpoint, durable install transaction ledger and exact `REPLAY_COMPLETE` proof.
4. Opt-in original source configuration requires same exact E1 ZK namespace, old trusted RSA public keys, both voter physical host identities/roots, original sealed quorum, local durable Genesis root, and durable transaction root.
5. OrderSvr/TradeSvr `main` passes actual business objects into Common's `CertifiedFreshBusinessInstaller`. With the default `installFencedFreshGenesis=false`, no installation occurs; old T149/T150 cannot be retroactively approved.

## Outstanding DEMO and Robot blocker — NO-GO

As of 2026-10-26 21:12 +08, official Robot heartbeat logged status `ERROR`, `open_order_count=0`, with Gateway [1003]/[1015] saying `SERVER.TradeSvr is not Online` and `SERVER.OrderSvr is not Online`. Official old Order/Trade remain exited.

T163 did **not** create a new isolated non-serving ZooKeeper namespace or issue actual birth-time signed physical zero WAL receipts for that namespace, and has not executed an actual production Common install in a service JVM. It only made the Common-same-JVM install entry reachable when all real inputs exist and passed read-only isolation deployment checks.

Next: create a genuinely new E1 namespace + per-voter virgin WAL directories, generate original RSA physical birth evidence using initial quorum, run actual Common durable install and restart/readback, complete authenticated signed READY CAS and physical WAL writer wiring; start real Order/Trade Spring services. Then verify Robot buy/sell quote submission and depth via Gateway/MD; only that is GO for user's requested goal. Do not substitute test-JVM quotes for live Robot or flip READY manually.

No GitHub Actions were invoked.