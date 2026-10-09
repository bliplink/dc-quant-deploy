# 场景、策略选择、信号与下单链路运维

本文用于排查“长时间没有交易”以及安全补充候选策略。判断顺序必须是：场景是否刷新、是否有合格候选、选择结果、信号结果、QuantSvr 风控、APSSvr 订单与成交。不能只看成交表得出服务异常的结论。

## 1. 权威链路

```text
MDSvr K 线
  -> INDSvr 场景识别
  -> INDSvr 按 symbol + scene + text 选择已通过资格门槛的 live 策略
  -> INDSvr 执行策略并产生 signal/no_signal
  -> QuantSvr 消费信号、检查账户状态与风控
  -> APSSvr 接受订单并返回订单/成交事实
  -> QuantSvr 投影到 ClickHouse
```

排查时依次查看：

- `deepseek_market_scene_analysis`：场景、置信度和更新时间。
- `strategy_scene_selection`：`SELECT` 或 `NO_TRADE`，以及候选数量和原因。
- `strategy_live_registry`：精确匹配 `symbol + scene + text` 的 ACTIVE 策略及最新资格证据。
- `signal`：每根已闭合 K 线对应的 `signal`、`no_signal` 或选择不可交易结果。
- `quant_signal_block_event`：信号到达 QuantSvr 后的明确阻断阶段。
- `quant_order`、`quant_trade`：投影；真实执行争议以 APSSvr 权威账本为准。

## 2. 信号经济性一致性

INDSvr 实盘执行与 SIMSvr 回测必须使用相同的开仓经济性规则。默认参数是：

```properties
strategy.runtime.signalEconomics.enabled=true
strategy.runtime.signalEconomics.estimatedRoundTripCostPct=0.08
strategy.runtime.signalEconomics.minTargetCostMultiple=2.0
strategy.runtime.signalEconomics.minStopCostMultiple=1.5
strategy.runtime.signalEconomics.minNetRewardRisk=1.2
```

计算口径：

- `estimatedCost = entryPrice * 0.08%`，表示估算的往返交易成本。
- 目标距离至少为估算成本的 2 倍。
- 止损距离至少为估算成本的 1.5 倍，避免正常费用和微小波动吞噬止损空间。
- `netReward = targetDistance - estimatedCost`。
- `netRisk = stopDistance + estimatedCost`。
- `netReward / netRisk` 至少为 1.2。
- 平仓信号不受该开仓门槛阻断。
- 没有止损的历史策略仍执行目标距离检查；止损距离和净收益风险比检查只能在止损存在时执行。

修改这些参数时必须同时修改 INDSvr、SIMSvr 和部署生成配置，并用同一组边界用例验证，禁止形成“回测允许、实盘拒绝”或相反的口径漂移。

## 3. 安全补充候选策略

生产默认保持以下开关关闭：

```properties
live.weapon.inventory.replenish.enabled=false
```

原因是全市场每两小时自动补充会持续消耗模型和回测资源。日常使用现有 `dc.ind.workbench.live.strategy.gap.fill` 接口，显式提交缺失的 `symbol + scene`；接口会再次过滤已经满足库存的目标，并执行以下步骤：

1. 校验 K 线覆盖和场景证据。
2. 按近期失败、近通过候选和现有 live 参考构造不同变体。
3. 异步生成并编译候选策略。
4. 创建默认 365 天的正式回测任务。
5. 由 SIMSvr 按当前资格门槛判定，只有合格策略才允许发布。

缺口库存的统计口径必须与实盘选择一致：只有状态为 `ACTIVE`、精确匹配 `symbol + scene + text`，并且当前真实回测资格仍为合格的策略才计入库存。仅有 `ACTIVE` 注册记录但缺少或未通过当前资格证据时，仍然属于缺口。

显式传入 `gaps` 后，接口只能处理这些目标；即使过滤后目标数为 0，也必须直接返回 `targetCount=0`，不得回退为全市场缺口。只有未传 `gaps`、也未指定单品种时，才允许按全局库存发现目标。这条约束可防止一次定向运维请求意外消耗模型和回测资源去生成无关品种。

请求内容示例（外层 GW 请求格式按当前环境配置）：

```json
{
  "text": "15m",
  "requiredActiveCount": 2,
  "perSceneCount": 2,
  "maxTargets": 7,
  "gapFillTrigger": "OPS_CURRENT_SCENE_GAP",
  "qualityMode": "publish_first",
  "gaps": [
    {"symbol": "ADAUSDT", "scenes": ["trend"]},
    {"symbol": "BTCUSDT", "scenes": ["channel"]}
  ]
}
```

提交后必须观察 `strategy_generation_task -> strategy_candidate -> strategy_backtest_task -> backtest_result -> strategy_live_registry`。接口返回 accepted 只表示任务已进入异步队列，不表示已经通过回测或可以实盘。

Workbench 的 `online` 标志和运行时 `active` 判断也必须使用同一资格口径。注册表仍为 `ACTIVE`、但最新真实回测已经不合格时，不得显示为在线，也不得让旧的 `SELECT` 决策长期保留；运行时应清除这条失效选择，等待下一轮正式选策，而不是反复记录 `active_strategy_missing`。

## 4. 长时间无信号的判断

以下情况属于正常低频，而不是服务故障：

- 场景与选择持续刷新，只有少量当前场景存在合格候选。
- 已选策略每根闭合 K 线都返回 `no_signal`，且没有重复执行同一根 K 线。
- QuantSvr 没有收到开仓信号，因此没有风险阻断、订单或成交。

以下情况需要处理：

- 当前场景长期没有精确匹配的合格候选：按第 3 节定向补充。
- SIMSvr 与 INDSvr 经济性规则不一致：先统一规则，再生成或复核候选。
- signal 已产生但 QuantSvr 没收到：检查 GW/服务注册和信号频道。
- QuantSvr 已收到但没有订单：查看 `quant_signal_block_event` 和账户快照状态。
- APSSvr 有成交但 ClickHouse 没有：按 executionID 对账并使用显式投影修复流程。

不得为了验证链路而强制制造生产信号或放宽正式资格门槛。
