# T141 — Mandatory signed replay BEFORE Common business Netty listener

Date 2026-10-26; local dev Mac, existing RSA keys only, no Robot changes.

## Concrete root cause fixed

Before T141, formal Order/Trade Spring `certifiedCommonNode()` constructed/started `CommonCertifiedNodeRuntime` and bound its Netty listener BEFORE the separate `certifiedWriters()` bean checked `CommonBusinessRecoveryReadiness`. This allowed a physical replication listener to be visible with no restored business image, despite refusing normal front-door business writes. Order also remained accidentally on an unguarded bootstrap after the first code change; a mandatory reflection test caught it. Neither service now invokes the unguarded production entry.

## Single Common engine and unchanged externally authenticated READY

- Common `CommonCertifiedNodeBootstrap.openAndStartWithZkFencingAndReplay` now requires the bound business replay attestation before any RSA/WAL/node initialization, rechecks after constructing the physical partition census, then `CommonCertifiedNodeRuntime.startWithBusinessReplay` rechecks **inside the synchronized Netty bind critical section** before publishing a physical listener.
- Both Order and Trade pass the same `CommonBusinessRecoveryReadiness` bean into this same Common bootstrap; there are no duplicated service-side elections, WAL pipelines or old-Epoch fencers. Existing `certifiedWriters()` check is retained as defense in depth. Runtime still independently requires real signed ZooKeeper ownership, pinned RSA custody and exact current Epoch.
- Negative RSA test: no restored business replay → no physical WAL directory or socket. Replay revoked while constructing the physical node → fails closed before listener opens and disposes physical resources. Real Order/Trade mandatory startup tests enforce the new argument to prevent backsliding.
- Low-level Common-only original Netty protocol bootstrap without business replay remains for internal Common tests ONLY. It is not a formal Order/Trade entry; do not call it from a service.

## T141 independently verified results

- **Common full regression:** 546 tests, 0 fail, 0 skipped (existing A/B RSA).
- **Order full regression:** 171 tests, 0 fail, 4 skipped.
- **Trade full regression:** 195 tests, 0 fail, 2 skipped.
- Local ARM64 official Docker images `local/otc-t141-ordersvr:unified-common` and `local/otc-t141-tradesvr:unified-common` built after `mvn clean package` using SAME `3.0.22-t141-pre-netty-certified-business-readiness-20261026-SNAPSHOT.jar`, SHA256 `583be42c5cc0c39581a21503eb0cbf54a78ea0c4b3af0b75cc9f8360d8e29f73`, verified independently in each container.
- Same Common T141 artifact ran real 3-ZK independent C witness before faults, A SIGKILL → B real original signed survivor source registry and local ACK → A rejoin/catchup → B SIGKILL → A E3 continues: **PASS**, evidence `/Users/kong/.opentradingcore/t124-live-kill-runs/20261026081835`, `/tmp/t141-REAL-Common-demo-two-physical-kills.log`.

## Formal business deployment remains NO-GO

- Order's handlers still invoke legacy `recordCommand` and `beginSynchronousBatch` and fail closed; Trade's old money/position mutation path still requires unavailable `requireWritable` permission. The staged prepared-state commit/APPLY adapters exist but do not yet fully drive live matching or accounting.
- Common physical registry is attached in production Spring and proven in Demo, but Order/Trade don't yet invoke real signed `installSignedSurvivor` recovery with a service-specific ZK signed stage and original durable baseline. Recovery-only listener has no verified source handlers installed yet. READY phase selection remains a startup phase rather than fully automatic live handover. A fresh signed service Genesis, recovery-only state replay → external CAS READY → Common writer must be built and tested.
- Five old Order/Trade formal containers remain Exited(143). T84 Demo is still running; no live routing changes. No GH Actions and no unapproved live rollout. No external Python SDK functional acceptance, no 256 partitions, 10/50/200 tenant pressure, or funds/position/order/projection reconciliation have passed.
