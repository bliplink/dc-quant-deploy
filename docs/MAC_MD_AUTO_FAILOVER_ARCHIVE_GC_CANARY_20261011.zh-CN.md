# 2026-10-11：按用户要求开启 MD 自动主切与 Archive 自动删除验证（金丝雀）

## 结论（区分隔离执行和真实集群）

**已真正执行两类验证，但尚未在现有 10 租户生产形态上开启自动主切/归档删除。** 本轮先实际运行 MD 两阶段自动晋升/反向切换的隔离控制器测试，并在专用临时目录实际删除安全的归档文件、从备份恢复；随后使用**真正 Chronicle Queue 格式**执行归档移除→恢复原始 STATE_COMMIT 的业务侧隔离测试。

现网预检查再次取自 Mac ZooKeeper：**256/256 MD READY，MDSvrA=128 Primary、MDSvrB=128 Primary，MDSvrA/B/C 三个 ephemeral member 在线，所有分区有候选恢复者**；原本运行的三个 MD 容器均是旧 `dc-saas/mdsvr:cluster-dev-local-c3e1d45c6-20261011075101`。但严格 `check-md-failover-preflight.py` 返回 `decision=BLOCKED`（exit 2），**不能把此脚本改成简单 PASS 并强杀现网 MD 主节点**。

### 一、MD 自动切换：已执行的验证

- 新增 MD **独立验证分支** `codex/md-auto-failover-disposable-gates-20261011`，提交 `a5f6063`（仓库 `bliplink/com.app.dc.mdsvr`）。
- `MdImageRecoveryFailoverControllerTest.canaryAutomaticFailoverThenRoleReversalNeedsNewEpochMarketAndPublisherProof`：
  1. 单独的测试 Assignment `P077`，主 A 下线、控制器租约有效，旧发布者已被隔离；
  2. 在版本化 CAS 中 **READY(epoch1/A)→RECOVERING(epoch2/B)**；未取得完整 Order 镜像不得 READY，B 不得发布；
  3. 收到本 epoch 的全市场镜像与出版栅栏证明，CAS 到 **READY(epoch2/B)**；
  4. B 下线、A 作为旧 Learner 回归，控制器再次 CAS **RECOVERING(epoch3/A)**；
  5. **epoch2 的历史镜像/旧发布者证明不准套用到 epoch3**，连续返回 SNAPSHOT_UNPROVEN / FENCING_UNPROVEN，且盘口发布保持关闭；
  6. 为 epoch3 单独证明后 CAS **READY(epoch3/A)**，旧 B 仍禁止发布。总计 4 次严格 CAS。
- 定向测试 **17/17 PASS**，MD Java8 `mvn clean test` 全量 **127/127 PASS**。
- 这些 Controller/Safety/Membership/AssignmentStore 均为**测试隔离实现**，不是实际 ZooKeeper 主节点故障注入，不代表业务外部发布入口已完成 fencing。

### 二、现网 MD 自动主切目前真实阻断项

读取 `~/.opentradingcore/local-common-protocol-20261011/artifacts/md-explicit-enable-gate-20261011.json`：

1. `ORDER_CURRENT_FULL_MARKET_IMAGE_PROOF_MISSING`：Order 对 MD 当前分区全部活跃租户/市场的可认证 Image+增量连续水位尚未实证。
2. `MD_PROMOTION_FENCING_AND_CAS_CONTROLLER_NOT_CONFIGURED`：现网镜像不是新控制器，并且没有独立、安全的 `MdImageRecoveryFailoverController.Safety` 实现；直接设置 `enabled=true` 会因缺失 Safety Bean **fail-closed / 启动拒绝**。
3. `MD_RECOVERING_TO_READY_EPOCH_PUBLICATION_FENCE_UNATTESTED`：共享 Gateway/旧 publisher 的当前 epoch 禁发证明缺失。
4. `MD_PROMOTED_EPOCH_FULL_MARKET_IMAGE_NOT_ATTESTED`：接管者还没有证明全部市场全量 image 后的 delta watermark。
5. `ROBOT_POST_FAILOVER_ORDER_RECONCILIATION_NOT_ATTESTED`：Robot 交易委托和盘口对单尚未在接管后验收。

**MD 下一次真实 SIGKILL 只能在独立隔离集群/单 canary 分区带可信 Order image + publication fence 时执行**；现网十租户不做无证强切，以免已知 4/10 市场中断重新发生。

### 三、Archive 自动删除：已真正执行的验证

- 新增 `scripts/run-archive-retention-gc-canary.py`（只有 `--execute-canary --report <new file>`），**程序自己创建独立 disposable root**，不能指定现有 Order/Trade archive 目录作为删除对象。
- 只有同时满足 Archive 归属、7 天保留期、至少 2 个副本 durable watermark、Projection 已消费、Snapshot durable、高可靠备份恢复、源端可恢复、0 活动 reader 时允许删除。
- 实际执行结果：**删除 1 个完全满足条件的隔离测试归档文件及归档目录，保留 1 个未来仍需使用的测试归档**。模拟的 backup 与原文件 SHA256 一致，删除后恢复同一提交标记。
- **8 类不安全条件**分别被拒绝：落后 Replica、落后 Projection、落后 Snapshot、读者仍占用、备份未验证、源端不可恢复、缺少副本、archive seq 超过证据水位。
- 新增 `tests/test_archive_retention_gc_canary.py`，**5/5 PASS**，旧生产风格只读盘点 `tests/test_order_archive_retention.py` **9/9 PASS**；CI `.github/workflows/validate-order-archive-retention.yml` 增加 disposable auto-GC 测试。
- 原始证据 `~/.opentradingcore/local-common-protocol-20261011/artifacts/archive-gc-user-enabled-canary-20261011.json`。

### 四、真实 Chronicle Queue 备份与丢失归档后的恢复

- Order 独立分支 `codex/order-durable-primary-common-source-20261011`，提交 `4558140`。
- 新增 `OrderPartitionJournalTest.disposableChronicleArchiveCanBeColdRestoredAfterCanaryGc`：临时目录创建实际 CQ4：STATE_REMOVE seq1、STATE_COMMIT seq2、未提交脏尾 seq3；执行 same-epoch rollback 得到真实 `.archive/P037-epoch8-seq3-...`。
- 先把真实 CQ archive 拷贝到独立测试备份并对每个文件留 SHA256；移除**仅测试生成**的 archive。重新打开 Order Journal，`archivedRollbackCommitMarker` 不得假装有来源；再按 SHA 从备份恢复真实目录，重启 Journal 并成功获得**同一个 seq2 / eventId / payload** 的业务提交证明。
- `OrderPartitionJournalTest` **11/11 PASS**；Order Java8 `mvn clean test` 全量 **339 项、0 失败、1 跳过**。
- 注意：此测试证明真实 CQ 归档的文件级冷备份重建和恢复 reader 功能，**不代表生产 Archive→Active 完整跨 epoch 追平已通过**。最小 Replica/Projection/backup proof 在 canary 上为受控 fixture，尚没有接入正式生产见证系统。

### 五、尚未开启的线上配置（不能混淆）

- **MD 现网** `md.cluster.failover.enabled=false` 保持原样。真正开启仍需同源数据/旧 owner 证明的 Safety Bean，Gateway 全市场发布防双主隔离、旧主重连重放时新 Epoch fencing、逐市场对账，且新镜像完成部署验收。
- **归档现网**所有原有 `.archive` **未删除**；目前无基于签名副本水位/Projection 回执/远端备份恢复的持续自动 GC 定时调度，不能拿“文件名年龄”当成清理授权。必须先接入真实保留期和可靠性见证后再逐个开启。
- **性能**：不得在线下单热路径做全盘扫描/批量 SHA/同步删除。归档保留控制应该在独立后台清理线程，优先限速、单 segment、可中断、再次证实水位再 rename 到 quarantine。

### 六、实验后 Mac 现网只读核验

- `tests/check-demo-tenants-readonly.py` 最终 **PASS_10_TENANT_SNAPSHOT**：10/10 Robot `RUNNING`，每个租户 40 活动单、双边盘口各 10 档。证据 `~/.opentradingcore/local-common-protocol-20261011/artifacts/after-md-archive-canary-tenants.json`。
- `tests/check-projection-consistency-host.sh` **PASS**：`orphan_mutations=0`、`trade_watermark_tail_mismatch=0`、`order_watermark_tail_mismatch=0`、`cross_partition_event_ids=0`；24 个 `dc-saas-` 容器运行。
- 用户要求的启用范围是**隔离 MD 控制器与自拥有的 GC 测试资源**；线上故障注入权限尚未取得来自所有权/业务一致性的技术证明，本轮无任何线上 Docker/配置、Order/Trade Journal、MD ZK 分区写操作和实际旧归档删除。

## 后续必要验收

1. 在独立真实 ZooKeeper namespace + 全市场 Order source 上提供真实 `Safety`，实测旧 publisher Fencing 后强杀 canary MD Primary，观察恢复中禁止发布，完整 market Image 和 delta 才 READY；随后重启旧节点并切回来。
2. 基于 Order/Trade 的 durable snapshots、所有合法 Replica/Learner、Projection 消费位点、活跃 reader/rollback branch 和远端可恢复备份，设计持续归档 GC 的可信 attestation provider；先对一个**真实但隔离的 CQ 分区**做全流程 Archive→Active 恢复，再允许真实归档 GC。
3. 对现有 10 租户只读健康巡检，保留所有失败瞬时窗口证据；不要因为实验通过就混淆生产镜像版本。
