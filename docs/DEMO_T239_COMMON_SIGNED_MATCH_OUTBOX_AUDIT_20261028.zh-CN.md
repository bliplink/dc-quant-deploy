# T239｜Order 已认证撮合 Outbox 和 Trade 双方独立费率核验

时间：2026-10-28 14:09 CST，Mac Demo；分支 `saas-crypto`，仅本地源码/测试，本阶段没有替换运行中的订单或交易镜像。

## 本次实际变更

1. Order 提交 `d2453c3`：新增 `OrderCertifiedMatchOutbox`，不新增私有 WAL/选主机制。一个签名 `STATE_ATOMIC_MATCH_V1` 原子业务帧包含双方 `Filled` 后状态以及可重建的 Maker/Taker 结算事件，`recordCommitted` 只能从 Common `commitThenApply` 回调记录。收到任何未经 Common 物理认可的 API 请求不会凭空产生持久化待结算事件。
2. `OrderCommonFirstReadyWiring` 的真实 Cold E2 全量认证 WAL 恢复/在线 Replica 增量 WAL 回调接入 Outbox。整段帧经 `OrderSignedStateFrameCodec` 验证，再应用业务态和重建 outbox；每个分区独立替换，保证不串租户。重建时 Maker/Taker ExecID 稳定。
3. Outbox 保留全部尚未获可信 Trade Custody 确认的 matchKey，不因为普通 RPC `code=0` 或进程重启就假设结算完成。当前代码只有 Pending 的持久可重建视图，**没有自称已经做了消息投递或消费确认**。
4. Trade 提交 `221124a`：修正 Maker/Taker 双边资金计划错误地共享两名客户费率的潜在问题。现在各自读取 `makerMakerRate`、`makerTakerRate`、`takerMakerRate`、`takerTakerRate`，自身开仓手续费和后续平仓保证金估算用本人费率，新增不相同费率测试验证两边余额。
5. 单元回归：Order 112 主源码全量 Java8 编译、认证 Outbox/冷恢复/在线 Replica/跨分区拒绝/重放和此前撮合测试 **14/14 PASS**；Trade 163 主源码全量 Java8 编译，财务回归至少 **24/24 PASS**，另不相同费率子集 9/9 PASS。

## 最终验收仍 NO-GO

- 14:09 CST 实测运行容器：Order A/B T225、Trade A/B T230、MD A/B、Robot 均 RUNNING（各 0 restarts）；8 个启用租户 Robot 均 RUNNING，7 租户 40 单，R0F6CC 2 单。**不能由 RUNNING 推断 HA 可切或成交健康。**
- MySQL `dc_orders` 实测 0 行，UR4KF7 `dc_orders_execorders` 真实 last_qty>0 实测 0；原 T232 错误 `ORDER_COMMON_CROSSING_QUOTE_NEEDS_ATOMIC_MATCH` 的运行镜像仍未替换。真实成交链路未执行且不得标记 `Filled` 通过。
- 仍未完成：Order 已认证 Match Outbox -> 经可证明的服务间身份/签名源证明的 Trade 双人结算 RPC（不能只信网络收到的订单报告）；Trade 原始 Custody/commitIndex 回执 -> Order 签名 settlement ACK WAL；Crash 后双方 Saga 自动重试、Pending 确认；Projection 从 Common 已认证 WAL 拉取并更新委托/成交/手续费流水；Order/Trade A/B 连续自动互切与最终余额/委托/持仓/成交一致性；部分成交/复杂 CLOSE 路径。
- Common 当前可提供本地提交和双 Custody 的真实认证边界，但还没有提供**跨服务的可移植、可独立校验的 Order/Trade 业务提交证明与查询/消费协议**。不要在没有这部分证明时开启 `trade.common.certifiedPairFill.enabled` 或 Order 交叉撮合入口，也不要将普通 Trade `code=0` 作为可信清空 Outbox 的根据。
- 目前尚未推送远端、没有调用 GitHub Actions。保留现有 Demo Robot 报价，不修改旧数据。
