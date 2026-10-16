# 2026-10-17 Mac Demo storage / Projection / ZooKeeper incident

## Evidence and changes

- At 05:51 CST the Mac data volume had only ~115 MiB free. ZooKeeper was exited, and Docker MySQL health check was unhealthy, although the MySQL TCP server continued accepting JDBC connections.
- Root cause of host disk growth: ProjectionSvr file logs, ~195 GiB from October 16 and ~64 GiB on October 17. The service repeatedly retried missing order-projection watermark queries, then continued retrying empty GAP responses.
- Deleted only one 4 GiB October 12 *unmounted test fixture* to free APFS metadata headroom. Removed the 195 GiB rotated Projection log file; it remained open by a host reader, so its allocated blocks were not necessarily reclaimed. Truncated the active Projection log in place, preserving the inode, reclaiming ~64 GiB of host capacity. Did NOT erase any current Trade, Order, MD, ZooKeeper, MySQL, Snapshot/WAL or recovery-ledger state.
- Through localhost JDBC 33306 applied the official idempotent migration from mysql/migrations/20260908_order_projection.sql. Verified that both dc_order_projection_event and dc_order_projection_watermark changed from absent to present. No destructive table changes.
- Backed up ZooKeeper bind-mounted persisted files (data/zookeeper and log/zookeeper) into ~/.opentradingcore/zookeeper-durable-pre-recreate-20261017.tar.gz. Did not reset ZooKeeper ownership or state.
- Docker Desktop backend is still BROKEN: existing ZooKeeper start and Compose recreate both returned overlayfs input/output error; image pull returned containerd metadata meta.db input/output error. Docker health checks fail with OCI runtime exec I/O errors. Do not run CAS, SIGKILL, failback or declare HA ready while ZK is unreachable.
- Current Projection JVM is still running with the previous log configuration. New Projection override on host will apply on normal JVM restart; do not claim it is hot-reloaded. Host free space was ~63 GiB at last check.

## Source fixes, tested and pushed

- Deploy branch fix/projection-bounded-log-20261017: Generate Projection Log4j RollingFileAppender with MaxFileSize 20MB and MaxBackupIndex 4, suppress the repeated empty GAP retry WARN stack in OrderProjectionBinaryConsumer while preserving errors elsewhere. Added exact official order-projection migration SQL to mysql/init/ for raw empty-database Compose boots. Dedicated generator/config tests PASS.
- Trade commit 8106568573e7ce4d8b1a764b6e6c80b5232a47b2: Default-off bounded batch source handoff for RSA-certified installed Genesis on B. It reuses the proved P001 business write fence, current ZK CAS and per-partition independent signed physical receipt, max 8 candidates/tick. Full 363 Trade tests PASS; NOT YET DEPLOYED because Docker backend is broken.
- GitHub Actions was not used.

## Resume only after Docker Desktop backend recovery

1. Use the official Docker Desktop diagnostics and normal restart; do NOT Purge/Reset Data. If I/O persists, do not attempt destructive Docker data-root surgery without safeguarding any unrelated container data.
2. Verify Docker containerd/overlayfs operations, ZooKeeper localhost port 32181, MySQL localhost port 33306 and Projection bounded log behavior. Confirm Order Projection tables exist.
3. Read current Trade/Order/MD assignments from live ZooKeeper and verify P001 business READY. Previously observed P001 elected B Epoch3; this does not establish the current state after the outage.
4. Deploy the local Trade fleet candidate with features default OFF, enable narrowly under live health guard, verify 128/128 owner split, then carry out sustained nonempty trades and finance/Projection reconciliation. A/B SIGKILL, replica catch-up and reverse takeover have NOT passed.
5. Only after Trade passes, validate Order on the same Common state machine.

No falsified READY, voter quorum, WAL ACK, replication health or stale-ZK owner assumptions.
