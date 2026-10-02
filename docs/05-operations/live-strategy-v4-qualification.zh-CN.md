# 实盘策略 v4 资格门槛与持续复核

## 目的

INDSvr 只允许具有 `v4_non_overlapping_walk_forward` 证据且通过全部门槛的策略进入场景候选池。该机制必须保持 fail-closed，不能通过关闭资格门槛或启用未验证 fallback 来恢复交易。

生产门槛为：

- 样本外验证通过；
- 交易数不少于 20；
- Profit Factor 不低于 1.20；
- 最大回撤不高于 15%；
- 验证段和前瞻段的扣费后收益均为正。

## 2026-10-02 故障结论

连续两天没有订单和成交的直接原因是 INDSvr 没有产生新信号，不是行情、QuantSvr、APSSvr 或 ClickHouse 投影故障。

当时有 100 条 ACTIVE 注册记录，但只有 3 条同时满足 ACTIVE 与 v4 资格要求：

- 74 条缺少对应的 v4 回测证据；
- 23 条有证据但未通过门槛；
- 当前市场场景与少量合格策略的场景大多不匹配，唯一匹配的候选也被模型判定为 `NO_TRADE`。

任务表中最后一批 v4 重验完成于 2026-09-27。已有任务均正常结束，问题在于生产没有持续创建重验任务。

## 生产配置

```properties
strategy.live.recheck.auto.enabled=true
strategy.live.recheck.auto.cron=0 30 3 * * ?
strategy.live.recheck.defaultRangeDays=365
strategy.live.recheck.defaultEndDaysAgo=1
strategy.live.recheck.defaultCooldownHours=720
strategy.live.recheck.defaultLimit=8
strategy.live.recheck.defaultPriority=5

strategy.selection.backtest-qualification.enabled=true
strategy.selection.backtest-qualification.execution-model-version=v4_non_overlapping_walk_forward
strategy.selection.backtest-qualification.max-age-days=45
strategy.selection.backtest-qualification.min-trades=20
strategy.selection.backtest-qualification.min-profit-factor=1.20
strategy.selection.backtest-qualification.max-drawdown-pct=0.15
```

冷却时间设为 720 小时，使每日任务跳过最近 30 天已经复核过的策略，避免默认 24 小时冷却导致每天重复处理注册表前几条记录。每日上限保持 8 条，控制 SIMSvr 和 ClickHouse 压力，并能在证据 45 天过期前完成整个 ACTIVE 池的轮转。

## 手工恢复流程

1. 先调用只读接口 `dc.ind.strategy.library.audit`，确认 ACTIVE、缺失证据和不合格数量。
2. 根据当前场景，从每个品种选择少量 ACTIVE 策略；优先选择旧模型中交易样本充足、扣费后验证/前瞻收益为正、PF 和回撤较好的版本。
3. 通过 `dc.ind.workbench.live.strategy.recheck.run` 精确指定策略名、版本、品种和 `15m` 周期。每批不超过 8 条。
4. 重验任务必须保持 `live_recheck` 模式；该模式只验证，不自动发布新版本。
5. 等待本批全部进入 `SUCCESS` 或 `FAILED` 后，再提交下一批。不要在前一批仍为 `PENDING/RUNNING` 时持续堆积任务。
6. 调用 `dc.ind.strategy.library.audit` 复核 `activeQualifiedCount`，再检查 `strategy_scene_selection.payload.candidate_count` 是否恢复。

## 日常验收与告警

至少监控以下指标：

- `activeUnqualifiedCount` 和 `realistic_backtest_missing`；
- 各品种、各场景的合格 ACTIVE 策略数；
- 连续 `no_scene_candidates` 的场景选择次数；
- 最近一次 v4 回测任务创建和完成时间；
- 连续 24 小时无信号、无订单、无成交；
- live-recheck 的 `PENDING/RUNNING/FAILED` 数量和最长等待时间。

没有成交本身不一定是故障，但“市场数据正常且所有品种长期没有场景候选”必须告警。恢复标准是资格池和候选池恢复健康，不是强行制造一笔交易。

## 2026-10-02 首批恢复记录

首批按当前市场场景精确提交了 8 条 ACTIVE 策略重验，8 条任务均进入 `SUCCESS` 终态，证明 INDSvr、任务表和 SIMSvr 消费链路正常。资格结果为：

- 1 条通过：BTCUSDT channel 策略，交易数 23、PF 1.834、最大回撤 1.53%，验证段和前瞻段扣费后收益均为正；
- 3 条因交易数不足 20 被拒绝；
- 3 条因样本外验证未通过被拒绝；
- 1 条因前瞻段扣费后收益不为正被拒绝。

刷新资格快照后，ACTIVE 合格数由 3 增加到 4，缺少 v4 证据的 ACTIVE 数由 74 降至 70。随后手工刷新 BTCUSDT 场景选择，结果从 `no_scene_candidates` 变为 `SELECT`，候选数为 1。

本批拒绝率为 7/8，达到“停止扩大重验、转入策略质量分析”的条件。因此未继续堆积下一批任务；后续由每天 8 条、30 天冷却的定时轮转逐步补齐证据，并根据失败原因改进策略逻辑和样本覆盖。

## 2026-10-02 INDSvr 冷启动恢复修复

首批复核恢复 BTCUSDT channel 候选后，INDSvr 重启暴露出一个独立问题：进程内选策缓存为空时，`getSelectedStrategy` 先把空的 `selectedAt` 当成“选策已过期”并直接返回，导致持久化在 ClickHouse 中的最新选策记录没有机会通过单点查询重新载入。表现为行情和场景都正常，但闭线执行记录为 `selected_strategy_blank`。

INDSvr 提交 `6753e80` 调整了判断顺序：只有缓存中实际存在选策值时才执行缓存过期判断；冷缓存继续进入 DAO 查询并恢复选策。对应回归测试覆盖“启动初始化时 DAO 暂不可用、随后恢复”的场景，确保无需等待下一次定时选策即可恢复已有结果。

生产验收要求：

- 容器镜像 revision 为 `6753e80` 或其后继版本，容器保持 `running` 且 `RestartCount=0`；
- 重启后 APSSvr、MDSvr、SIMSvr 和 QuantSvr 连接恢复，配置的品种均进入 `READY`；
- 下一根 15 分钟自然闭线时，BTCUSDT 不再出现 `selected_strategy_blank`；
- 允许策略正常返回无信号，但必须先进入 `strategy_selected`/策略执行路径；
- 不以强制下单作为恢复标准，也不为制造成交而放松 v4 资格门槛。

自然闭线验收已于 14:15 完成：BTCUSDT 依次进入 `bar_received`、`scene_resolved`、`strategy_selected`、`strategy_active` 和 `strategy_primary_no_signal`，确认冷启动选策恢复有效。

该次验收又发现历史窗口只有 `barCount=1`。根因是 INDSvr 启动时 APSSvr 尚未连通，首次 `queryKline` 失败后返回空结果，但 PriceInput 仍把品种标为 `READY`，且连接恢复后只重新请求 ticker，没有重试历史 K 线。后续修复要求空历史结果 fail-closed 为 `FAILED`，保留目标品种，并在 APSSvr 连通后按 `1s` 首次延迟、`3s` 间隔、最多 `5` 次重新装载；历史数据真实装载并完成订阅后才能标记 `READY`。

生产部署验证中，10 个品种首次均正确进入 `FAILED`，第二轮恢复时每个品种装入 50 根 15m K 线并全部进入 `READY`。同时发现升级后的第一根自然 K 线可能早于每分钟一次的 ACTIVE 策略装载任务约 2 秒到达，因而被 fail-closed 为 `active_strategy_missing`。INDSvr 后续增加启动预热：启动后 3 秒主动装载 ACTIVE 注册表，失败时每 3 秒重试，最多 5 次；定时分钟级刷新保持不变。
