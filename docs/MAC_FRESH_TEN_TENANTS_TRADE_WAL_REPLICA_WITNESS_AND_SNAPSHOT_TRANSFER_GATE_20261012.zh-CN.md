# 10 户全新 Demo：Trade WAL 复制见证、角色切换与 V2 Snapshot 窗口门禁（2026-10-12）

## 已在运行中的 Mac Demo 验证

代码与配置采用 `dc-quant-deploy/saas-crypto`，运行目录为
`~/.opentradingcore/dc-saas-runtime-clean20261012`，
**不能在这套系统上运行旧归档版挂载的文件路径和重置脚本**。

21:03 后独立只读复核：10/10 租户 Robot `RUNNING`、
各 40 笔活动委托、买卖盘口各十档；24/24 容器运行，
Trade A/B 仍是 `dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261012-archive-recovery-0e798cc`，
均未重启或 OOM。三个公网链接
`https://opentradingcore.com/`、
`https://trade.opentradingcore.com/`、
`https://opentradingcore.com/api/` 均返回 HTTP 200；
Mac 的 Cloudflare Tunnel 进程仍存活。

### 独立 Trade 空分区角色反转

从真实 ZK 读取初始 `P000` 归属，
先用不写入的 `trade_cluster_transition_host.py`
生成并验证 ZK CAS 升 epoch 计划，再使用现有脚本
`run-trade-cluster-role-reversal-host.sh` 应用：
`TradeSvrA → TradeSvrB → TradeSvrA`；
两次均在目标 `TradeSvr` 收到本 epoch 的
`TRADE_PARTITION_READY`，且全体原有
20 条 MySQL Projection watermark 没有倒退。
脚本退出码 0，证据：
`~/.opentradingcore/local-ha-clean-20261012-v1/trade-empty-P000-role-reversal.log`
和 `trade-role-reversal-evidence/fresh-P000-empty-20261012210753-trade-role-reversal/`。
**此项只证明没有租户业务的分区切换成功；
尚未进行活跃账户、持仓和故障注入验收。**

### 10/10 活跃分区最新已提交 WAL 双端一致

使用 Java8 Maven 和 Chronicle Queue `readOnly(true)`，
在运行中以 **只读** bind mount 检查十个实际租户分区：
`P020 P095 P101 P122 P159 P161 P165 P174 P211 P249`。
每个分区均从其 Primary 尾部取最新
`STATE_COMMIT`，要求 Replica 中同序号
`STATE_COMMIT` 的 **完整原始编码数据严格相同**。
10/10 PASS、测试 0 失败。
各最新见证序号依次为
`12488 13502 11648 8558 7540 11914 8456 9138 11616 9312`，
epoch 均为 1。证据：
`~/.opentradingcore/local-ha-clean-20261012-v1/tenants-10-trade-wal-commit-witness.log`。
**这只是采样时刻的最新提交 marker 确认，
不是全历史账本与资金/持仓逐事件一致性证明。**

## 确认的下一步阻塞

Trade A/B 十个活跃分区的 `snapshot/Pnnn/latest.json`
仍为初次冷部署写入的 334 字节空基线，
`committedStateSeq=0`。两端 WAL 物理上均存在。
运行中确实启动了 `TradeSnapshotScheduler`，但参数为：

- `pollMillis=60000`（每分钟选最多一个本地主分区）；
- `maxAgeMillis=3600000`（一小时）；
- `minCommittedMutations=20000`；
- `recoveryTransferAware=false`。

当前十个分区的 WAL commit 序号均已大于 4096，
而 Common V2 的**单次复制恢复传输窗口最多 4096 WAL slots**。
现有镜像已经支持基于较小 WAL 窗口抢先生成 Snapshot，
但运行配置没有打开。即使物理 Replica WAL 尾部一致，
**也不得因此认为在线 SIGKILL 后、全新 Replica 追平或
Snapshot 回退机制已经验证通过**。

## 机制改进：可选恢复传输窗口 Snapshot 触发

新增两个公开部署配置参数，保持保守默认：

```
TRADE_CLUSTER_SNAPSHOT_TRANSFER_AWARE_ENABLED=false
TRADE_CLUSTER_SNAPSHOT_TRANSFER_MAX_WAL_SLOTS=2048
```

生成到 A/B `application.properties`：

```
trade.cluster.snapshot.periodic.recoveryTransferAware.enabled=...
trade.cluster.snapshot.periodic.recoveryTransferAware.maxWalSlots=...
```

经显式启用时，与 `TradeSnapshotScheduler` 的
`isTransferWindowDue()` 对接，在本分区 WAL 尾部
距离最近完整 Snapshot 达到 2048 slots 时提前生成
完整 Snapshot，保留距离 Common V2 4096 窗口上限的余量。
部署生成器预检禁止
非法 boolean、`0`、`4096` 和非数值阈值，
以及周期快照关闭却开启此选项的错误配置。
原来 `minCommittedMutations`、全量逻辑和 Gateway
业务传输不变。属于 **显式启用的部署参数**，
不是自动 GC、不是多数派确认、更不是激活物理 WAL 轮转。

`bash tests/test-trade-cluster-config.sh` 完整通过。
本轮**没有重启在线 A/B，也没有偷偷修改在线已加载配置**。
后续启用需评估快照 IO 开销和滚动升级时唯一 Replica
的同步 ACK 风险，或在下一次经授权的冷部署启用。

## 未执行的高风险环节

- 活跃持仓 Trade B SIGKILL、自动提升、恢复节点追平与角色反转；
- 快照生成与跨节点真正恢复成功的端到端证据；
- MD-C 原有 dff97ba epoch fence 修复集成；
- WAL 自动删除 / 物理同 epoch rotate；
- MySQL 完整历史交易、资金、持仓、Projection 权威对账；
- 50/100/200 多租户压测。

**旧运行目录仍隔离保留，未永久清理。**
