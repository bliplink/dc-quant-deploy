# Order HA P246 recovery blocker — 2026-10-10

## Live evidence (read-only; do not automatically repair)

- `tests/verify-order-cluster-state-host.sh` failed at P246 with an assigned-snapshot mismatch.
- ZooKeeper `/dc/cluster/ordersvr/partitions/P246` reported epoch `1`, `READY`, primary `OrderSvrA`, replicas `OrderSvrB` and `OrderSvrC`, no learners.
- Snapshot metadata taken directly from the shared runtime data directory:

| Node | Snapshot seq | Committed state seq | Commit marker seq | Books | Orders |
| --- | ---: | ---: | ---: | ---: | ---: |
| OrderSvrA | 581136 (advanced during retries) | 578109 | 578110 | 1 | 97 |
| OrderSvrB | 2 | 0 | 0 | 0 | 0 |
| OrderSvrC | 2 | 0 | 0 | 0 | 0 |

- A's P246 journal baseline: `baselineSeq=578110`, `committedStateSeq=578109`, `commitMarkerSeq=578110`. B/C baselines remain at seq `2`, but their journals contain later records; do not infer in-memory order loss from snapshots alone.
- OrderSvrA repeatedly logged `ORDER_PARTITION_RECOVERY_FAILED`, `ORDER_PARTITION_SAME_EPOCH_RESTART`, `PARTITION_NOT_READY`, and `replica catch-up made no progress: ReplicationAck[status=GAP, partition=P246, epoch=1, replicatedSeq=578109, expectedSeq=578110]`.
- The affected tenant `DUJE16` for BTCUSDT (`location + ASCII U+001F + 4 + ASCII U+001F + BTCUSDT`) hashes to P246 with CRC32 modulo 256. Its enabled Robot was `DEGRADED`, reported no open orders and `RUNTIME_FAILURE: gateway TCP response is empty for cancelBatchOrder`. Other observed active robot tenants used different partitions and were `RUNNING`.
- This is a demonstrated *partition availability/catch-up failure*, not a proven loss of committed customer data; `READY` in ZooKeeper is not enough to establish runtime readiness.

## Likely mechanism requiring a safe regression fix

In `OrderReplicationManager.catchUp`, a lagging replica asks for the journal record after `578109`. The primary has archived the journal tail in a same-epoch rollback/promotion and redirects catch-up to a newer snapshot `SNAPSHOT_BEGIN`. In `OrderReplicaReplicationHandler`, journal rebase currently requires `batch.epoch > localEpoch`; the receiver with `localEpoch == batch.epoch == 1` responds with `GAP` again. The primary detects no progress and retries its promotion, while the request fence rejects DUJE16 order access. This source-level mechanism matches observed logs but must be reproduced in a dedicated integration test before any fix is deployed.

**Never** bypass the epoch fence or unconditionally install a new same-epoch snapshot: that could discard committed replica state. Any proposed recovery needs a proof that the transfer is an authoritative committed rollback checkpoint; the destination must not have committed state beyond the checkpoint. Verify snapshot checksum and restore journal+snapshot atomically. Preserve existing journals and snapshots for audit.

## Safe follow-up and promotion gates

1. Create an offline same-epoch rollback/catch-up regression reproducing the P246 sequence, and validate all existing cross-epoch, stale-epoch, no-double-primary, and committed-watermark protection tests.
2. Stage the fix in a dedicated disposable cluster first. Do not stop/kill production OrderSvr or replay ambiguous cancels to make the check pass.
3. Collect authoritative committed watermarks, order/execution IDs, balances, positions, open orders and Projection watermarks for P246. Require exact state agreement across assigned replicas, not just ZooKeeper READY.
4. Do not resume 200-tenant ramp or Order HA fault injection while P246 is unfenced or the full 256-partition verifier fails. Retest DUJE16's live quotes only after P246 is safe and READY.

## Test harness improvement

`tests/verify_order_cluster_assignments.py` now reports only safe fields (snapshot/committed/marker sequences, order count, short digest) when assigned snapshots differ; it never dumps orders, user IDs or payloads. The regression test asserts that sensitive order fields do not appear in diagnostics.

## 2026-10-10：受控修复进展（未部署）

- OrderSvr 源码修复 [2b9bb47](https://github.com/bliplink/com.app.dc.ordersvr/commit/2b9bb475c817ef061e2d85a376e1649e0eaa5066)：仅在 Replica 需要恰好缺失的 rollback `STATE_COMMIT` 时，按序号/epoch/commit proof/对应前序状态事件从不可变 archive 补发；不跳过 GAP，也不允许同纪元强制覆盖快照。设置 `order.cluster.replication.archivedCommitRepairEnabled=false` **默认关闭**。
- 大序号回归测试 [46afba5](https://github.com/bliplink/com.app.dc.ordersvr/commit/46afba5ce372ca3e9a666fb3b6d0d8431beee036)：用真实 P246 附近的 578109/578110/578111 序号模拟跨快照恢复，定向测试 13/13 通过；扩大 HA/Journaling/快照覆盖 70/70 通过。
- 最新 [Actions #38020361516](https://github.com/bliplink/com.app.dc.ordersvr/actions/runs/38020361516) **SUCCESS**，已发布 GHCR 双架构镜像 `ghcr.io/bliplink/ordersvr:sha-46afba5`（linux/amd64、linux/arm64）；Mac mini 已成功拉取 ARM64 镜像，但**没有替换或重启 dc-saas-ordersvr A/B/C**（仍为 `sha-26b01eb`）。
- 对现网 P246 原始 archive 进行了只读检查：seq=578110 `STATE_COMMIT` 引用 seq=578109 `STATE_REMOVE`，epoch、eventType、eventId、version 均匹配；这不能替代三副本完整 state hash、Projection watermark 和崩溃恢复一致性验收。
- 归档回收机制见 [WAL 生命周期设计](ORDER_WAL_SNAPSHOT_ARCHIVE_RETENTION_DESIGN_20261010.zh-CN.md)。只读盘点的 518 个归档目录目前全部保持 HOLD；禁止直接按年龄删除。下一步是隔离集群与受控分区验收、权威数据对账，随后再决定是否启用修复开关。

## 2026-10-10 follow-up: A/B/C raw WAL cross-check (read-only)

- Inspected all three nodes' **256** snapshot partitions: **255** were identical by content; only **P246** differed. This is snapshot comparison only, not live committed-state attestation.
- Independently compared raw Chronicle CQ journal record encodings by exact `(partition, epoch, seq)` and SHA-256 fingerprints without exposing order IDs, payload, or account secrets.
- `578109 STATE_REMOVE` matches in primary `OrderSvrA` immutable rollback archive and both `OrderSvrB`/`OrderSvrC` active journals.
- `578110 STATE_COMMIT` in primary archive matches `OrderSvrB` active journal **byte-for-byte**; it is **absent** in `OrderSvrC` active journal.
- `578111 SNAPSHOT_BEGIN` on primary `OrderSvrA` active journal matches `OrderSvrB` active journal. `OrderSvrC` lacks this continuation. The old archived seq=578111 is a different historical branch and **must not be replayed** in place of the new active seq=578111.
- Added `scripts/check-order-rollback-archive-witness.py`, a read-only witness and CI regression. It verifies the archived `STATE_COMMIT` proof, rejects a conflicting replica prefix and duplicate/ambiguous archive, and reports only event types and abbreviated SHA-256 fingerprints. Output always includes `canAutoApplyRepair=false` and `deletionAuthorized=false`.
- The above narrows the immediate observed missing marker to **Replica C**. It does not justify a live restart: runtime accepted committed watermark, state hash, Projection durability and stable assignment leases must be verified separately, along with a documented rollback path.

Read-only invocation:

```bash
python3 scripts/check-order-rollback-archive-witness.py \
  --data-root "$RUNTIME/data" \
  --partition P246 --epoch 1 --committed-state-seq 578109
```


## 2026-10-10 live rollout hazard: 128 primaries per node and strict two-replica ACK

Read-only ZooKeeper scan retrieved all **256** partition assignments and reported **128 Primary partitions on OrderSvrA, 128 on OrderSvrB, and 0 on OrderSvrC**. All 256 ZooKeeper assignments claim `READY`, even though P246's runtime fence repeatedly returns `PARTITION_NOT_READY`; the administrative assignment state therefore **must not** be treated as runtime health.

The deployed A/B/C configuration has `order.cluster.replication.consistencyMode=SYNC_PER_RECORD`, `order.cluster.replication.required=true`, and `order.cluster.failover.minimumLiveSynchronizedReplicas=2`. In current `OrderReplicationManager.replicateToAssignedReplicas`, **every assigned replica** is contacted and its ACK validated; a single unavailable or non-progressing replica can block a synchronous commit. For P246, A has B and C as assigned replicas. Thus simply restarting C (although it has no Primary assignments) could block unrelated partitions while it is unavailable, and restarting A can disturb 128 Primary partitions. Rolling a new Docker image onto these nodes without a controlled maintenance/drain/reconfiguration protocol is **not safe**.

The read-only witness [`scripts/check-order-rollback-archive-witness.py`](../scripts/check-order-rollback-archive-witness.py) (commit [`6946a30`](https://github.com/bliplink/dc-quant-deploy/commit/6946a30f06604448856949b96b0c44f9838b4ada)) confirmed identical archived/replica state at 578109; A archive and B journal matching the `STATE_COMMIT` at 578110; only C missing that marker; A/B both have matching **new branch** `SNAPSHOT_BEGIN` at 578111. Six synthetic positive/negative cases and GH Actions 38024052581 passed. Additionally, an offline Java/Chronicle test mounted the actual A archive **read-only** in a network-isolated Maven container and successfully returned that exact 578110 marker (0 errors, 0 skips); this test is [committed in OrderSvr](https://github.com/bliplink/com.app.dc.ordersvr/commit/769e01b942113b306aae54951e37ca21046f32bf).

**Next live rollout prerequisites**: record a specific write-quiescence or safe CAS membership/drain plan for the 128 Primary assignments per active node; produce a rollback plan including previous GHCR images, unchanged WAL and control-plane epochs; verify no conflicting higher committed state and matching state hash/Projection watermark; then opt in **only P246** with both `archivedCommitRepairEnabled=true` and `archivedCommitRepairPartitions=P246`. Do not disable synchronous ACKs, relax `minimumLiveSynchronizedReplicas`, force ZK `READY`, or delete archived journal files to simplify the rollout. No live OrderSvr nodes were restarted by this investigation.
