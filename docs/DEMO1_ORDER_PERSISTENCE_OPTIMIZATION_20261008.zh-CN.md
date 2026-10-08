# demo=1 订单的持久化与复制优化审计（2026-10-08）

状态：**源码修改已提交；对当前 Mac mini A/B/C 未执行重启、镜像切换或业务数据改动。不能将此视为 HA 性能/稳定性验收通过。**

## 结论

`demo=1` 不等于“订单完全不持久化”。RobotSvr 的纯报价订单、IOC Sweep/Tape 确实将 `demo` 设置为 `1`（`TradingGatewayClient.markInternalDemo`）。Broker API/Trader API 下单被明确标记 `demo=0`。但 Robot 报价位于真实客户可成交的同一个 OrderBook；`CrossStrategy.shouldSkipForRobotIsolation` 对特殊 Robot Sweep 和 Tape Taker 做撮合隔离，却**不会禁止普通客户 Taker 撮合 Robot Maker**。成交会通过执行链路影响 TradeSvr 的资金、持仓、OpenOrder 和去重状态。

1. 老式 `MySqlDBOrderDao.putOrder/putExecOrder` 在 `enableSaveDBDemo=false` 且 `demo=1` 时跳过表写入。但是原先 **仍会先把对象放入异步 DAO 队列**。
2. 当前部署 `generate-saas-configs.sh` 的 `write_cluster_order_config`（OrderSvrA/B/C）明确配置 `dbType=rockdb`、`enableSaveDBDemo=false`、强制 journal、同步副本、Commit、Snapshot。旧 `OrderSvr` 单机配置才是 `dbType=mysql`。因此仅优化 MySQL DAO 对现网 HA **没有直接收益**。
3. `RockDBOrderDao.putExecOrder` 和 `putInactiveOrder` 也会跳过 `demo=1`，但**活动挂单**会进入异步任务并由 `putActiveOrder` 写入本地 RocksDB。同时，权威状态由 `OrderStateJournal` 的 STATE + STATE_COMMIT Chronicle journal 和同步 ACK 维护；`OrderManager.init` 在 cluster mode 跳过旧 DAO 的启动恢复。这里确实存在重复的 RocksDB mirror 写入。
4. `OrderProjectionDispatcher` 仍读取 committed journal（没有 `demo=1` 过滤），输出到 Projection 消费链。故不能从“旧 DAO 未写 MySQL”推断所有数据库和 Projection 写入均为零。

## 已提交的低风险源码优化

OrderSvr `saas-crypto`：
- `MySqlDBOrderDao`：如果 `enableSaveDBDemo=false`、`demo=1`，在异步入队前跳过（仍保留 `putOrder/putExecOrder` 的原过滤）；对 `demo=0` 和显式保存 Demo 没有改变；新增两项相关测试。
- `RockDBOrderDao`：仅当**集群启用 + journal 启用 + 同步 state replication.required=true + commit.required=true + enableSaveDBDemo=false + demo=1 + 非终态订单**时，跳过不再作为恢复依据的 RocksDB 活动状态镜像和异步入队。**终态 Demo 订单仍执行旧 active-key 删除**以清理从旧版本残留的数据，独立 standalone、可选复制、普通客户和显式启用 Demo 保存都维持原有方式。Demo 成交入队提前跳过（原 consumer 本已过滤）。新增四项覆盖终态/单机/非Demo/强制保存的测试。
- 不修改 `OrderStateJournal`、`OrderReplicationManager`、`TradeExecutionStateRecorder`、`OrderSnapshotManager`、`OrderProjectionDispatcher` 或 HA quorum/epoch，因此本轮**不能声称同步复制开销已消除或 TPS 已提升**。

## 为什么不能直接跳过 demo=1 的同步复制和 Chronicle 日志

- 挂在真实订单簿的 Robot Maker 可以被 `demo=0` 客户撮合；若 Demo Maker 在主节点故障后消失，但客户的执行确认、反向订单和资金已经提交，可能产生重复执行、重复补单、幽灵挂单或资金与订单不一致。
- 分区恢复依赖 commit watermark、journal sequence、快照、Order client idempotency。只跳过某些 `demo=1` journal record 会改变状态重放与 seq/epoch 的语义，并触发 Projection 的有序序列缺口。若要混合跳过，必须完整重设计双层订单簿、Snapshot、fencing、订单去重、撮合提交以及外部行情可执行性。
- Demo 专用、不允许客户真实交互的非可成交行情（合成展示深度）**可以**单独采用 `EPHEMERAL_QUOTE` 模式：报价只保存在 Robot/MDSvr 或独立缓存；节点恢复时报价清空并重新播种，成交前须在原子流程中升级成带同步副本与去重的真实订单/成交。必须显式标注“非可成交/可能重建”，不能将其混入真实客户可交易深度而伪装零丢单。
- 客户订单必须始终保持 `DURABLE_ORDER`；200 租户容量压测必须分别报告“纯 Demo 展示吞吐”和“持久化客户订单 TPS、完整 HA 故障恢复”的数据，不能把关闭同步复制后的吞吐冒充产品真实容量。

## 上线门禁

1. 确认最新 `saas-crypto` GitHub Actions Maven 测试、amd64/arm64 GHCR 推送均成功，记录不可变 image SHA/digest；不要依赖本地镜像。
2. 先在隔离环境回归 Robot quote place/cancel/reconcile、客户吃单、成交、余额/持仓、Order/Trade 两层去重，测试 Order Primary SIGKILL/Replica catch-up + role reversal，确保旧 RocksDB demo active-key 清理。
3. 当前 Mac mini 50 租户仍受高 CPU PSI、6 秒 ZK 会话和 Projection 权威水位缺口阻断；在获得安全滚动条件前**不得 force-recreate 现网 A/B/C**。
4. 部署后比较 `ROCKDB` activity、Order journal STATE/COMMIT record/s、CPU PSI、write syscalls、Robot 50/50、订单/成交一致性和真实业务 TPS，只有明确提升才保留策略。
