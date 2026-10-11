# Mac Demo Common 统一 HA 协议与 MD 故障准入阶段验收（2026-10-11）

## 本轮完成且实际验证的内容

### Common 共用恢复协议

Common `saas-crypto` 在既有 `ReplicatedStateMachine`、`PartitionStateMachineRegistry`、`StateMachineRecoveryCoordinator` 之上新增纯恢复期工具 `ReplicaGapRecoveryAdvice`：

- commit `4054560`：解析来自正确 partition、正确发送 Epoch、正确 ACK 累积序号的 `GAP`，**只有接收端明确请求**跨 Epoch `SNAPSHOT_BEGIN` 才返回 true。拒绝普通 GAP、同 Epoch、未来 Epoch、非法数字、错误分区和不连续 ACK。
- commit `3a77c61`：覆盖两种合法边界：新 Epoch 快照 Begin 在落后副本的旧 seq **之前或之后**；仍约束 Begin 位于 `(0, targetSeq]`，由业务服务独立证明它是真实当前 Epoch、完整且持久化的 Snapshot Begin。Common 不执行任何 Journal rebase、不修改分区 Assignment、不授予 READY。
- **Common Java 8 Maven 全量测试 170/170 PASS**。
- 两个提交已快进推送 GitHub `com.app.common/saas-crypto`，尚未发布 Maven Central，现网 Common Jar 没有替换。

### Order 消费 Common 接口（独立联调，尚未线上启用）

- 在当前已通过真实 10 租户 Order 故障恢复验收的 `4c7df72` 上创建独立分支 `codex/order-use-common-gap-20261011`，commit `e885491`，将 Order 发送端重复的跨 Epoch GAP 字符串判断收敛到 `ReplicaGapRecoveryAdvice.requiresSnapshotBegin`，在独立校验真实 SNAPSHOT_BEGIN 事件后调用 `requireVerifiedBegin`。
- 使用 **本地隔离 Maven 开发版本**，严格依赖链 `Common → com.app.dc → Order`，未覆盖 Mac 正在运行的依赖版本：
  - `Common 3.0.17-dev4054560-20261011-SNAPSHOT`（对应源码已包含 `3a77c61`，本地验证用途）。
  - `com.app.dc 0.0.4-dev4054560-20261011-SNAPSHOT`。
  - Order 改源码后重新编译；`OrderReplicationCatchUpIntegrationTest` **16/16 PASS**；Order 全量回归 **323 项，0 失败 / 0 错误 / 1 跳过**。
- 为避免远端构建因 Central 尚未提供新 Common class 而失效，Order 消费端提交**只推到独立验证分支**，没有合并/强推到 `OrderSvr saas-crypto`。后续稳定后统一 Common 正式版本号，更新 `com.app.dc` 依赖并正式启用业务服务引用。当前 Mac 上的 Order A/B/C 仍为上一轮已正式验收的 `dc-saas/ordersvr:cluster-dev-local-orderepoch-4c7df72-20261011`。

### MD 故障门禁实盘检查

- 更新 `scripts/check-md-failover-preflight.py` 支持 `--expected-image`，可明确锁定 `dc-saas/mdsvr:cluster-dev-local-...`；不再误把正在运行的 Mac 本地镜像判为缺少审核。仍拒绝 `latest`、不可信镜像名，而且**始终只读、始终禁止进程故障注入**。
- 新增测试：**11/11 PASS**。带本地镜像锁运行，证据 `~/.opentradingcore/local-common-protocol-20261011/artifacts/md-failover-local-lock-20261011.json`。
- **MD 256/256 分区 READY**，A/B 各 128 Primary，全部 256 个分区有候选恢复副本，MDSvrA/B/C 的 ephemeral ZK 节点存在，容器均运行锁定本地镜像。
- `decision=BLOCKED`、`canInjectMdPrimaryFault=false`：当前缺少权威 Order 最新完整市场数据镜像证明、旧 MD Publisher Fencing 和原子 CAS 切主、提升后完整市场镜像 Epoch 校验、Robot 对单恢复证明。**没有**进行 MD SIGKILL，也没有绕过这些检查。
- MD 应以 Order 全量最新完整市场镜像重建派生盘口，不额外引入 MD-to-MD 全量日志复制。

## 后续仍必须完成

1. **统一公共框架真正接管运行恢复**：Order、Trade 的 StateMachine 的 Apply/Snapshot/Restore 已实现，但 `*.cluster.stateMachine.commonBinding.enabled` 默认关闭，仍缺通用 Primary 认证来源传输、完整提交水位来源、独占恢复屏障与 READY 外部门禁的线上联合验收。不能把纯 Common 协议辅助类完成，误说成所有恢复路径已被 Common 接管。
2. **完整 Common 版本链发布**：本地已经验证新 Common 通过 `com.app.dc` 给 Order 使用，尚需固定 release GAV、中央仓库发布与 GitHub Actions 构建，随后 Trade/MD 视其业务需要复用。不要把隔离的 `0.0.4-dev...` 作为长期生产依赖。
3. **MD 可信自动接管**：以 Order 现有权威市场 Snapshot 为唯一恢复数据源，落实 MD old publisher fencing 和恢复后全量市场覆盖证明；补对应集成和真实故障注入。
4. **Archive 跨边界恢复与删除门禁**：验证旧 Epoch Archive+活动 CQ、落后副本重建、Snapshot 校验、Projection watermark；证明所有依赖消失后才能按保留策略归档删除。当前不删除任何旧归档。
5. **10 → 20 → 50 → 100 → 200 租户**：以真实 Order TPS、长尾延迟、CPU/GC、IO、日志体积、HA failover 稳定性为门禁，不以租户数量或 Robot 活动挂单数代替订单 TPS。
