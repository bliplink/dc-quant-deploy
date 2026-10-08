# Robot 报价稳定态快速路径（2026-10-08）

状态：**代码已提交至 `bliplink/com.app.dc.robotsvr` `saas-crypto`，尚未上线；性能收益必须由现网/隔离测试后测量，不能把减少查询上限等同实测 TPS 提升。**

## 真实热点

`RobotWorker.runOnce()` 每轮先查询当前机器人活动挂单，然后正常执行 sweep、对账及最后一次确认查询。在 `reconcile()` 中，旧的非冷启动分支按 Sell/Buy 两边轮流运行 `placeMissingSide()` 和 `confirmSideAndCancelExtras()`，每次再独立请求 `openRobotOrders()`。对于已经完全匹配、没有新挂单/撤单的稳定盘口，意味着 1 次初始查询 + 最多 4 次重复逐边查询 + 1 次最终确认；但多数时候不需要执行下单、撤单。

## 已提交的变更

- `RobotWorker.canSkipUnchangedQuoteReconciliation`：只在当前开放的挂单与目标价格/剩余数量/双边档位严格完全匹配、`pendingQuoteVisibility` 为空、买卖两侧的取消保护时间均结束时，跳过冗余的逐边 `reconcile()`。
- **保留原有最后一次新的活动订单查询与 `exactTargetVisible` 验证**，检测客户在前后快照之间吃掉挂单；不改变 `sweep()`、库存检查、Hedge、租户 lease、行情过期或 circuit breaker。
- 非稳态或存在部分成交、重复报价、桥接额外挂单、未确认挂单、取消保护期时，仍执行原有 `placeMissingSide/confirmSideAndCancelExtras` 补单/撤单流程。
- 新增 `RobotStableQuoteFastPathTest` 覆盖严格匹配、pending/settle 保护、部分成交/改价、重复/额外报价与缺失证据等。
- 稳定态的理论上限查询数从每周期约 6 次降至 2 次，实际需核对调用链并观察真实 GW/OrderSvr 请求量；**不应跳过第二次权威查询以继续压缩开销**，那会影响 Quote visibility 安全。

## Projection 的事实边界

现网生成配置的 `ProjectionSvr/config/application.properties` 设置 `projection.binary.enabled=${ORDER_CLUSTER_ENABLED}`、`projection.trade.binary.enabled=${TRADE_CLUSTER_ENABLED}`，并配置 binary worker stripes=4、fetchMaxRecords=500。源码 `ProjectionEventStore.append()` 则是单条 `ingestCommittedEvent` 事务入口，**不能未经运行时验证就把其逐条事务成本当成当前主路径瓶颈**。特别注意 Order/Trade committed journal 的连续水位、每分区顺序和 Projection P232/P054 历史 GAP 仍在；任何批量写库应首先定位实际启用的 binary worker 实现，然后做 fail-closed 水位一致性测试，不应直接更改单条入口并宣称现网收益。

## 部署/验收门禁

1. `RobotSvr` `saas-crypto` 最新 GitHub Actions Maven test/build 与 ghcr amd64/arm64 publish 成功后，固定不可变 image SHA。
2. 隔离回归：50/50 Robot 多周期报价、customer IOC/partial fill、Tape 补单、机器人 STOP 清单、stale quote/circuit breaker、桥接 2 秒、非匹配价变化，以及 10 秒 pending visibility，防止错误快速路径导致遗漏撤单或空盘口。
3. 部署后在相同 50 租户负载下，比较：`queryOpenOrder` 请求数/秒、Order STATE/COMMIT 次数、Robot RUNNING/DEGRADED、ZK session expiry、CPU PSI、下单 ACK p95/p99、实际业务 TPS。**未上线前不能报告实际下降百分比**。
4. 线上 Order A/B/C 仍需要独立完成 15 秒 ZK session 的安全 rollout / journal watermark、一致性门禁。本次 Robot 修改不会更改这些条件，也不得启动 200 租户压力测试。
