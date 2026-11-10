# UNI趋势突破：本地通过、服务器拒绝

2026-11-11接续。这里只记录固定源码的一次完整服务器尝试，不代表新增实盘策略。仍只用OHLCV、禁止DeepSeek服务端生成/修复、不放宽原门槛。

## 本地固定证据

策略`catalog_uniusdt_trend_4b3620782701`，假设`fr1_atr_trend_breakout_long_s15_t30`，族`FitOnlyRiskAtrTrendBreakoutHypothesis`。来自原400作用域平衡队列，四档是同一FIT政策，不是四条独立策略。

| 检查 | 原主期 | 完全分离留出 |
| --- | --- | --- |
| 日期 | 2024-12-15～2025-10-12 | 2025-10-13～12-13 |
| 交易数 | 28 | 7 |
| PF / 最大回撤 | 1.48339 / 0.050394 | 4.965273 / 0.030625 |
| 扣费验证 / 前向 | 665.040121 / 386.529273 | 扣费总收益2030.50698512 |
| 参数 | 原四档逐折FIT，模态3 | 锁参3，fit/optimizer调用均0 |

主期totalPnL918.967708、OOS1、严格前向贡献0.420612，符合既有0.20。留出只有7笔，虽通过原门槛，不能据此声称稳健或未来盈利。

- 源SHA `c4655316e3c88dda87b3ba4022a78f773708b5518f8793b5d50770f8127cdeaf`。
- 本地JAR `95ff2e9d5ef51ff13fbc9e8f1c6346f5b81a8e879dca2ee35120a326bad580b6`。
- 平衡队列manifest `f046c3dad656c2fc990125e1d4d679e9abf6edeb5343fbff06fb26e68975e8da`。
- admission manifest `2c7a9c9b5ce96ce44ac3c89b3c3e5250e70b1cb1eff10c39def9748bc15fb84e`。
- results `84233d237a9b35c3a0a5a9c74269a0c1aa28ab04f3dda713d45c188c43acb984`。
- primary `117b5f9d7afe83042a0d28632926038d0efaf3d54350fd9ff21a8edf6e1d8032`；holdout `9ecb9715cb62093b50efa72e9ccb94cdbe2bcfd4b3a53ae7c5adbed9152460ad`。

原证据在`strategy-fit-risk-balanced-scope-20261110/admissions/catalog_uniusdt_trend_4b3620782701`。只原样复制该单条results/frozen到`strategy-risk-uni-promotion-view-20261111`，不改原结果、不重放金融窗口、不读取并发大账本。

## 机制复核

17:10:51UTC库存及17:10:59UTC精确ACTIVE源码备份匹配4个当前版本，没有UNI/trend同行。新源warmup190，要求前30均线高于前150均线、150均线相对16根前上升，本收盘超过前30均线加ATR20且超过前48根最高价；ATR14初始风险及ATR20显式EMS退出。审核只批准一个`ma_atr_48bar_trend_breakout`实例。

之前失败的真实ADX UNI候选同样有突破敞口，不能重启或计作成功；本政策使用48根最高价、30/150均线和ATR位移，不是该源的48根收盘、50/150均线、ADX/DI与量条件。四档政策和整个400队列在那个服务器结果之前已冻结，不是根据失败重新调参。并不声称统计正交。私有同行源留在`strategy-risk-uni-peer-review-20261111`，不公开提交。

## 服务器终态：未发布

prepare-only、原源码validator和strict审计均通过。实际轮询器9920已结束，不要重新启动或再次导入。

- v1；generation `gen_1569882971064819712`；candidate `cand_1569882990006296576`；backtest `bt_1569882990786437120`。
- 服务器17:12:49UTC实测最近完整日期2026-11-09，实际窗口2025-11-10～2026-11-09，365日、120/30/14、FEE_ADJUSTED_PROFIT_FIRST、四档原FIT政策。
- 实际18笔，PF3.75903、回撤0.022914、totalPnL2197.612941、扣费验证2031.016727、扣费前向**-659.209476**、OOS0。
- 服务器自身FIT的代表参数是`riskProfile=2`，不是本地代表3；保持原政策，没有根据服务器结果换档重试。
- 场景725记录/2184匹配bar/18笔，sceneQualificationPass=true，不覆盖前向/OOS门槛。发布器实际`SKIP`，原因`validate_pnl > 0 but forward_pnl <= 0`。
- 回测执行SUCCESS、candidate READY不代表ACTIVE；`published=false`、该名字registry版本空，零新增上线。

精确版本external / EXTERNAL_SOURCE / EXTERNAL_IMPORT / external_java，LLM调用0、无fallback。源码上传38027字节，服务器存储38027字节，规范化仅相同package后的空行及外部ASCII空白；tokens unchanged。存储SHA `4f3efd1f8730e43297d29e19dafdb06a8537162d1daae6d097ea776420dd7e54`，服务器JAR及candidate.checksum均 `bc57925a51faf5dac910f1ed27d544e1c89b5d4b55a1dce2b23a753e6e8d324f`。源码/编译产物审计通过，不把相同字节数或0LLM单独当作证明。

服务器全证据`strategy-95-server-fit-risk-uni-20261111/catalog_uniusdt_trend_4b3620782701`，含request/submission/status/source-only-audit/outcome/live；启动日志`strategy-95-server-fit-risk-uni-launch-20261111`。17:17UTC库存仍4运行资格、另2过贡献。这个失败源及窗口已消费，不改风险档、换版本或挑旧日期重试。
