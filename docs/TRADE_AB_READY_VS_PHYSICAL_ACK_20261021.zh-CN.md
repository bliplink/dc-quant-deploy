# 2026-10-21｜Trade A/B 启动恢复完成，物理 ACK 仍阻断正式交易

## 真实执行与结果

用户要求尽快从租户注册验证 Python SDK 的 Trader/Broker、自定义产品、价格源、入金、委托/成交/持仓、私有 WS 以及最终一致性。前一轮新租户 `IU526F` 测试通过注册、自动审批、自定义来源/产品关联、匿名访问/跨租户隔离、Broker Key 签名认证和 Broker Python SDK 价格发布。后续在 Trade 查询/资金初始化因 `Gateway request failed` 和 `DEMO_CASH_OUTCOME_UNKNOWN` 停止，自动初始化处于 `FUND / NEEDS_RECONCILIATION`。该未知入金不得直接重试。

本轮检查：Trade A/B 原各自 0.5 CPU，B 896MiB；当前 Mac mini Colima 8 核 16GiB。在线 `docker update` 为 A 改到 **1 CPU / 1536MiB**、B 改到 **1.5 CPU / 1536MiB**，均未重启或清除业务 WAL，保留运行容器镜像 `local/dc-saas-tradesvr:tenant-scoped-20261019`。恢复过程 B 从原 100 多个本地主分区逐步达到 128，A 128/128，**两节点各自 128/128 当前代 Primary 本地 READY**；本地 Ready 日志与真实业务恢复是两个不同的条件，不得凭单个标志宣布 HA 成功。

后台未使用脚本伪造投票/ACK。真正的 ZooKeeper `/dc/cluster/tradesvr/controller/replication-health` 只读扫描：现有 36 条健康记录，其中 **14 healthy / 22 degraded**，其余没有已发布的真实同步健康行，**不是 256/256 HEALTHY**。例如 P001 当前健康记录 primary=TradeSvrB, replica=TradeSvrA, epoch=1, degraded=false, replicatedSeq=2；P008、P116 依旧 degraded。ZooKeeper `/dc/cluster/tradesvr/partitions` 的 256 READY 仅为路由元数据，不是物理 ACK。

## 诊断到的机制问题（不可绕开）

1. A/B Recovery Source HEAD 反复 `TRADE_RECOVERY_SOURCE_HEAD_UNSAFE`（业务尚未就绪）或接收端 `TRADE_REPLICA_ELECTED_FLEET_REPLAY_BLOCKED / recovery source HEAD unreachable`。在 256 Partition 强制复本提交启用的状态下，不能绕过签名 HEAD、可信 SNAPSHOT/WAL、Quorum 和本地物理 ACK。
2. Java Thread Dump 明确展示 `TradeSnapshotScheduler` 后台大快照持有 `TradeSnapshotStore` 对象监视器，在大量 `ExecutionDeduplicator` 序列化和磁盘写入期间，**TradePartitionLifecycleManager 的同步 Snapshot `load()` 等待同一对象锁**。这解释了旧版本 Trade-B 全量恢复非常慢，与严格复制状态本身不同；后续应在统一 Common/Trade 更新时优化快照写入与恢复锁的分区粒度、周期快照低优先级或启动恢复阶段限流，但不得修改 Snapshot 原子提交和 WAL 安全边界。
3. `DirectNettyReplicationTransport.close()` 当前 `group.shutdownGracefully().syncUninterruptibly()` 无明确有界关闭超时，真实线程栈看到恢复 worker 卡在 Netty promise；恢复机制应该在 Common 层明确每个请求、关闭和重试的时间预算，不能无限占用单线程 Fleet 恢复任务。
4. 调高 CPU 并不修复退化的 replica 或结果未知的入金，后续仍需要单独的可信自动追平和 authoritative funds/positions/orders/executions/Projection 水位对账。

## Python SDK 已验证边界

当前对外 SDK 为 `opentradingcore 0.1.9`（源码提交 `37e80d8`，API Docs healthy）。本轮实连 Gateway，对 `GAAKY8` 自定义产品 `QAA911F381USDT`、`IU526F` 自定义产品 `BTC003USDT` 分别验证 `products()`、`public_products()`、`wait_for_product()`、`snapshot()`、`ticker_24h()`，**10/10 只读接口通过**。

尝试再次执行新租户 `tests/test-custom-product-live-e2e.py --execute --with-traders --sdk-signed --verify-private-streams --near-simultaneous` 的真实入金、下单和撮合时，执行环境直接拦截，**没有运行，绝不可计为成功**。不允许改写命令或拆分交易请求绕过拦截。本轮未重新部署/清空 MySQL、Trade 数据；24 个 SaaS 容器仍运行。正式验收仍为 NO-GO。

## 资源持久化与下一步

为防止下一次 Compose 重建回退到 0.5 核 CPU，`config/trade-recovery-resource-20261021.yaml` 保存经验证的资源配置，**尚未对运行中的 Trade 执行 force-recreate**。下次有权限的操作环境先确认签名源端 HEAD、真实物理 WAL 追平和 256 分区健康 ACK，再在新注册租户上单次执行真实 Broker/Trader 下单撮合与完整资金/委托/成交/持仓权威对账。结果未知时必须保留 CID、日志和审计，不自动重复写入。
