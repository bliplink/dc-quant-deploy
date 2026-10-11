# 2026-10-12 Order Snapshot crash-durability 加固与 MD/归档发布阻断项

## 本轮实际完成

通过 WebCodex 修改并推送 Order 仓库 `bliplink/com.app.dc.ordersvr` 提交 **`ce5948c`**，分支 `codex/order-durable-primary-common-source-20261011`。未合并到 `saas-crypto`，未构建/更新现网 Order 容器。

- `OrderPartitionSnapshotStore.save()` 在临时 `snapshot.json.tmp` 写入完成后，显式 `FileChannel.force(true)`，再要求**原子**替换 `snapshot.json`，拒绝旧实现的非原子 Move fallback。
- 原子 rename 完成后，明确 `force(true)` 分区目录（新建分区目录时还 force Snapshot 根目录），否则拒绝将写入视为成功。
- 在支持的 Linux 本地文件系统上允许通过；不支持原子 rename / 目录 fsync 的介质**fail closed**。此时可能已有文件重命名，但上层收到异常，不准从“写入完成”推导 Durable HEAD。
- 该工作只发生在低频 Snapshot 保存路径，非每笔订单复制、撮合热路径。来源签名仍须具备同步 Replica committed watermark、当前 ZooKeeper Primary/Stat/version 和业务 Snapshot SHA，不能仅凭 Snapshot 文件 fsync 直接 READY。
- 新增 `OrderPartitionSnapshotStoreTest.coldReopenAfterAtomicDurableReplaceNeverSeesTmpOrOldCommit()`，重新打开真实临时文件系统，确认 Snapshot ID、Epoch、Committed State 水位、Marker 水位以及旧 `.tmp` 清理。
- 专项 **4/4 PASS**，覆盖已有 70,000 条 reservation 的大 Snapshot。

## 完整 Java 8 回归证据

在 Mac 隔离源树 `~/.opentradingcore/local-common-protocol-20261011/source/ordersvr`，使用 Docker `maven:3.8.8-eclipse-temurin-8` 执行 `mvn -q clean test`。

- 首次全量 340 项，**1 失败、1 跳过**：`OrderReplicationBatcherTest.concurrentRecordsShareOneCumulativeAck` 并发调度敏感，期望 1 个发送批次而观察到 2；**没有忽略此项或更改生产复制代码**。
- 在完全相同的依赖/平台单独复测 `OrderReplicationBatcherTest` **2/2 PASS**。
- 第二次完整 `mvn -q clean test` **340 项、0 失败、0 错误、1 跳过**。单次通过不证明时序敏感用例已被根治，未来 CI 应继续监控或重构这项测试的确定性。

## 本轮收尾现网只读验证

Mac `tests/check-demo-tenants-readonly.py` 实际 **PASS_10_TENANT_SNAPSHOT**：10/10 Robot RUNNING、每租户各 40 活动委托、10 档双边盘口。原始文件 `~/.opentradingcore/local-md-release-candidate-20261011/artifacts/after-order-fsync-dev-tenants-20261012.json`。

`tests/check-projection-consistency-host.sh` **PASS**：Order/Trade watermark tail mismatch 均为 0、orphan mutations=0、cross-partition event IDs=0。MD-C 仍运行 `dc-saas/mdsvr:cluster-dev-local-md-shadow-120d6c9-20261012`，运行中、0 重启。此验收检查的是旧现网 Order/Trade + 新 MD-C Shadow，没有对未上线的 Order fsync commit 进行生产验收。

## 上线隔离边界

- 当前 10 租户业务数据、Order A/B/C 和 MD-A/B 主节点镜像均不变；仅前一轮 MD-C `120d6c9` Learner 只读恢复观测保持运行。
- MD 生产自动主切的 `ORDER_CURRENT_FULL_MARKET_IMAGE_PROOF_MISSING`、`MD_PROMOTION_FENCING_AND_CAS_CONTROLLER_NOT_CONFIGURED`、`MD_RECOVERING_TO_READY_EPOCH_PUBLICATION_FENCE_UNATTESTED`、`MD_PROMOTED_EPOCH_FULL_MARKET_IMAGE_NOT_ATTESTED`、`ROBOT_POST_FAILOVER_ORDER_RECONCILIATION_NOT_ATTESTED` 仍未从真实 ZooKeeper/Order/Gateway 消除。
- 这项 Snapshot fsync 加固解决本地磁盘 Crash Safety 的一个前提，**没有证明真实 SIGKILL → Recovery → READY → Role Reversal**。
- Archive GC 仍没有真实的**所有法定 Replica 最小持久 HEAD、Projection watermark、活动 reader 和远端备份恢复见证**，生产自动删除继续 HOLD。此次重新请求只读现场 Archive 盘点被执行环境安全检查拦截，因此不声称获得新清理授权，也没有删除任何业务归档。
- 下一步先让 Order Source HEAD 从当前经 fsync 的 Snapshot+同步 commit 证书得到物理节点可验证 HMAC，并在 MD Candidate 绑定当前全市场 Image/Delta 与 Gateway Publisher Epoch，随后单分区真实故障注入。GC 按可信 Replica/Projection/Backup 见证串联后仅限速删除已通过隔离恢复检验的单个 Archive。
