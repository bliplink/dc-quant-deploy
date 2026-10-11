# Common 已提交 WAL 前缀证明：Order / Trade 真实 Chronicle 联调（2026-10-11）

## 执行结论

**本轮推进了源码、提交并通过了隔离测试；没有声称线上已经完成 Common recover() 接管。** 保留 Mac Demo 当前 10 租户、不重置数据、不换在线镜像、不触发真实 MD 主节点故障、不删除 Archive。

- Common `com.app.common` `saas-crypto` 最新提交：`9bf3593`。
- Order 独立分支 `codex/order-durable-primary-common-source-20261011` 最新：`9ad58be`。
- Trade 独立分支 `codex/trade-durable-primary-common-source-20261011` 最新：`5255e88`。
- 新 Common 仍**未发布正式 Maven Central 版本**，Order/Trade 的新 Common 接口未合并进正式发布分支，也没有引入现网 GHCR；不要用测试 GAV 替代正式发布链。

## 1. Common：累计提交验证

新增 `CommittedWalPrefixVerifier`，输入为与业务无关的 `WireRecord`（`STATE` / `STATE_COMMIT` / `OTHER`）。调用者负责从各自 Order/Trade 的真实 JournalRecord / marker JSON 转为此结构。

- 从被签署的 SnapshotSeq 开始，必须逐一完整验证到被签署的 `committedHeadSeq`，Epoch 不得回退。
- `STATE_COMMIT` 验证真实 `stateSeq`、`stateEpoch`、事件类型和事件 ID 与**此前已看到的 STATE**一致，可累计提交此前尚未逐笔确认的 STATE；篡改或引用不存在的 STATE 拒绝。
- 旧的重复 marker 不得使累计 HEAD 回退，任何仍然处于 pending 的业务 STATE 都不能通过 `requireComplete()`，即使全部 WAL 帧 HMAC / seq 通过也不行。
- 内部 pending window 上限 65,536；业务端另将单次增量 WAL HEAD 限为 **4,096** 条，超限要求新 Snapshot，不在订单热路径执行。
- 现有 `RecoveryTransferFrame.Verifier` 已验证随机 Challenge、Primary、ZK 版本、每帧 HMAC、Snapshot SHA256、WAL 位置及 Epoch；`CommittedWalPrefixVerifier` 再验证**业务提交语义**。
- **边界**：此 Common 审计器不执行 `apply`、`restore`、Promotion、READY 或归档删除；尚需将验证完成的流绑定 `StateMachineRecoveryCoordinator.recover` 的 durable recovery transaction。
- 本轮 Common 全量 Java8 Maven 测试：**193/193 PASS，0 失败、0 跳过**。

## 2. Order：可签署快照之后的已提交 WAL HEAD

- `OrderDurablePrimaryHeadAuthority`：在 ZK 物理 Primary/Stat.version/epoch 校验及 `OrderPartitionBarrier.quiesce` 下，允许 `committedHeadSeq` 超过落盘 SnapshotSeq。
- `OrderCommitWatermark.scan` 必须证明真实持久化 Journal 的完整水位；候选 WAL 末尾必须恰好是最新 `STATE_COMMIT`，`hasUncommittedState()` 必须为 false，差距不得大于 4096。
- `OrderCommittedWalPrefix.requireCertified` 只读真实 `OrderPartitionJournal.replay()`，检查严格连续 seq，将真实 `STATE_UPSERT/STATE_REMOVE` 和 `OrderStateCommit` marker ID / Epoch 等解析到 Common 校验器，并要求严格达到源端签名 HEAD。
- 真实 Chronicle Queue 集成测试 `OrderCommittedWalPrefixTest` 验证：正确的 STATE→COMMIT 可以认证；添加未提交新状态后拒绝；损坏 marker JSON 拒绝；**实际 CQ4 记录序列经同一随机 Challenge 签名为 `RecoveryTransferFrame`，验证 Snapshot SHA+WAL HMAC 并完成累计 STATE/COMMIT 检查**。注意此集成为**隔离 Java 测试**，不是已开放业务 WAL 下载端口。
- Order 全量测试：**334 项，0 失败，0 错误，1 skip**。

## 3. Trade：不猜 Snapshot 旧 Commit Marker

- `TradeDurablePrimaryHeadAuthority`：在当前 ZK Primary/epoch/version 与 `TradeStateCoordinator.withPartitionIdLock` 下对磁盘 `latest.json` 流式 SHA256，并允许 bounded committed WAL HEAD 超过 snapshot。
- Trade Snapshot 元数据只有 committedStateSeq/epoch，**没有持久化旧 commit marker**。因此使用 `TradeCommitWatermark.scan(partition, snapshotSeq)` 读取原始真实持久化水位，不能以 `stateSeq+1` 猜测 marker。
- `TradeCommittedWalPrefix.requireCertified` 只读真实 Chronicle Journal，验证 `STATE_BATCH`、`STATE_COMMIT` 的累计 marker、连续性和最后的已签 HEAD；无已证 marker、未提交尾部、旧 Epoch 和大于 4096 的增量都拒绝。
- `TradeCommittedWalPrefixTest`：真实 CQ4 的 STATE_BATCH→STATE_COMMIT，再经同一 Challenge 的 Snapshot/WAL HMAC 帧及 Common Commit Pair 校验；附加未提交状态后拒绝，损坏 JSON 拒绝。
- Trade 全量测试：**238/238 PASS，0 失败、0 跳过**。

## 4. 在线 Mac Demo 的只读检查与 Robot 观察

- 本轮无在线镜像替换，容器 24 个运行。
- `tests/verify-order-cluster-state-host.sh`：**256/256 分区 READY**、`snapshot_sets_equal=256`、无 Learner；A 129 Primary、C 127 Primary、B 256 同步 Replica；原运行镜像未更新，3 个 Order 容器 OOM=false / restarts=0。
- `tests/check-projection-consistency-host.sh`：Order / Trade 投影水位 mismatch = 0；orphan mutations = 0，cross-partition event ID 重复为 0。
- 严格一次性 `tests/check-demo-tenants-readonly.py` **两次显示 FAIL**：首先 `UNV4GJ` Robot 39/40；第二次 `UNV4GJ` + `FT9B21` 39/40；但是 Robot 本身 RUNNING，全部租户双边盘口仍显示 10 档且有效。
- 对这两个租户再做 **8 次、约 22 秒**的只读 SQL 序列采样：两者起初和绝大多数时间均为 40 单，最后一次仅 `FT9B21=39`，未出现持续卡住或服务异常。这属于**可能的成交→补单短暂窗口**，不构成保证。完整证据：
  - `~/.opentradingcore/local-common-protocol-20261011/artifacts/post-committed-wal-prefix-10tenants.json`
  - `~/.opentradingcore/local-common-protocol-20261011/artifacts/robot-recheck-after-39.json`
  - `~/.opentradingcore/local-common-protocol-20261011/artifacts/robot-39-order-sampled-20261011.json`
- **保留严格验收 FAIL，不通过删减检查标准将其改写成 PASS**；建议下轮增加独立的只读时窗机器人健康度验收（例如 10 分钟、每 5 秒，一旦恢复超过阈值即记录恢复时间），并检查 `dc_tenant_robot.open_order_count` 与真正开放订单数量的来源一致性。

## 5. 与实际 HA 一键验收仍有差距

1. Common 的 `RecoveryTransferFrame` + 累计 Commit 审计器已经能消费真实 CQ4 样例，但**现有 Netty 控制通道仍仅部署了源端 HEAD 证明的默认关闭入口**；尚无经授权的实际增量 WAL 数据发送 API、每物理节点密钥安全轮换、TLS/mTLS、以及不可变文件 Staging 后的跨进程数据身份绑定。
2. 尚未把这条完整数据流真正接入 `StateMachineRecoveryCoordinator.recover` 和 `DurableRecoveryTransactionControl` 的 `INSTALLING→BASELINE_DURABLE→REPLAY_COMPLETE`，也未证明所有故障点失败后的 `NOT_READY`，因此不能开启 `commonBinding.enabled`。
3. 当前业务 source 的签名 HEAD 上限 4,096 个 WAL record，不能用于跨度更大或跨 Epoch 的生产 Archive→Active 全链路追平；要先完成可信 Snapshot/install + archived journal bounded forward replay + Active replay 及 SHA/watermark recheck。
4. 现有 MD 自动主切仍被外部门禁阻止：Order 全市场权威镜像、旧发布者 Epoch Fence、Gateway 映射、MD `RECOVERING→READY` 和 Robot 对单一致性尚未完成；不得跳过 `check-md-failover-preflight.py` 的 BLOCKED。
5. 不开放归档自动删除。必须经过备份可恢复性、全部 Replica/Learner/Projection 最小持久水位证明和配置保留期；Order P200 两份历史归档重叠 22,011 条一致的取证不能作为删除授权。
6. 正式 Maven Central 依赖链发布（Common→com.app.dc→Order/Trade），编译 GHCR ARM64/Linux，采用单分区灰度 + 故障注入 + 无丢单/无双主/无重复成交 + 资金持仓 Projection 对账后，才可逐步开启 Common 自动恢复。
