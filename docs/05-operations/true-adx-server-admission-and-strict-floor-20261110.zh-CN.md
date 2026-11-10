# ADX服务器拒绝结果与本地发布前门槛复核

本记录截止2026-11-10 23:11北京时间。继续只用既有OHLCV，不使用DeepSeek生成/修复、不改服务架构。目标仍为100条真正生产合格且机制不重复的实盘策略，尚未完成。

## 当前结论

22:50:35生产只读快照：ACTIVE及当前运行资格均4；其中另过前向收益贡献单项的2条。不能将4条运行资格说成4条全部满足当前新增发布门槛。本轮新增发布0，按运行库存缺96；未操作现有持仓、风控或再次下线策略。

ADX固定200作用域全部完成，原结果标记通过2条。发布前只读复核后，仅UNI/trend符合既有20%贡献门槛；XRP/channel不符合。UNI已实际进入服务器正式最近365日回测并被拒绝，未发布。影线批次100/100，0通过。另两批23:11快照为188/400和70/19,599，均0原始通过标记，仍在运行。作用域、方向、类及档位数不能计为独立合格策略数量。

## 本地默认值缺陷及只读纠正

实际Java `BacktestModels.BacktestResult.minForwardContribution` 初始化为 `BigDecimal.ZERO`。冻结的本地直接runner没有填入优化计划的0.20；`LocalBacktestCli`只对null应用0.20默认，因此原始qualification标记可能漏掉贡献限制。交易/费用/选参对照并未覆盖此最终政策字段的传递，不能用信号或成交等价推断发布资格等价。

新增 `recovery/strict_primary_admission.py` 在上传前复核原始结果，要求：v4、不重叠OOS通过、至少20笔、PF至少1.20、回撤不高于0.15、扣费验证/前向均正，以及扣费前向/总PnL至少0.20；结果或种子计划要求更高时保留更高要求。比值按既有Java逻辑六位小数HALF_UP。缺失/非有限指标拒绝，不以默认0降低门槛。

`promote_qualified_catalog_candidates` 在limit、机制审批和网络提交前写单独strict审计并过滤；构造上传request时再次检查。没有更改历史PnL、原始通过标记、已消费窗口、源码、金融helper或在跑任务，不重放金融结果。已有旧结果必须额外复核，不能直接照原计数发布。

实际审计 `strategy-adx-strict-release-prepare-20261110/strict-local-admission-audit.json`：

| 固定候选 | 原始标记 | 费用调整前向/总PnL | 复核 |
| --- | --- | --- | --- |
| `catalog_uniusdt_trend_f78231bcd836` | 通过 | 1.026391 | 本地通过，服务器拒绝 |
| `catalog_xrpusdt_channel_e4ec89939f16` | 通过 | 0.015474 | 低于0.20，不上传 |

XRP原始39笔、PF1.48023、扣费验证301.296518、前向10.104428、总PnL653.000580；分离留出29笔、PF1.293102、扣费118.33859913，留出通过不能覆盖主期贡献失败。源SHA `074aca0a7fd2324e90cea7171717edcb706e638d931f54e312bbf0041ee0570e`。禁止用此失败调参、换版本或重挑窗口。

## UNI固定源码的真实服务器尝试

固定源 `catalog_uniusdt_trend_f78231bcd836`，机制组 `wilder_adx_directional_breakout`，`ta1_selective_adx_directional_breakout_long`。本地主期26笔、PF1.272630、回撤0.036329、扣费验证217.654719、前向464.404770、OOS1；分离2025-10-13至12-13留出7笔、PF3.341669、扣费1145.82247224，0拟合/优化。7笔留出仅符合旧门槛，不证明稳健或未来盈利。

提交前对22:37 ACTIVE精确版本/源码做私有核查，UNI/trend无已有同行；ADA20根突破回踩及LINK滚动DI代理与本源48根突破/递推WilderADX14/均线和量过滤有机制差别，但共同趋势暴露不能宣称统计独立。4个ADX方向保守归一组，未按版本凑数。生产源码私有备份不提交公共repo。

从原完成记录构造单条不可变promotion view，源码与原始结果字节核验，不重回测，不使用并发修改中的大结果账本。

- 正式窗口：2025-11-10至2026-11-09，完整365日；120/30/14，最少3折，FEE_ADJUSTED_PROFIT_FIRST。
- version `v1`；generation `gen_1569845603322617856`；candidate `cand_1569845616362708992`；backtest `bt_1569845617109295104`。
- external / EXTERNAL_SOURCE / EXTERNAL_IMPORT / external_java，无fallback，精确策略版本LLM调用0。
- 编译成功、回测执行成功，但15笔（不足20），PF2.361886、回撤0.027396、扣费验证+797.833266、扣费前向-178.859489、OOS0；总PnL933.774381。
- 场景shadow有725条、2184匹配bar和15笔交易；这不能覆盖前向亏损/OOS/样本失败。
- 正常publisher SKIP，原因为验证正但前向非正；精确名字registry为空，published=false。

该源码/版本/窗口已消费，保留失败，不重导入、不据服务器结果调参、不换日期强行通过。

证据目录：`strategy-true-adx-formal-20261110`、`strategy-true-adx-uni-promotion-view-20261110`、`strategy-95-server-true-adx-uni-20261110`、`strategy-live-inventory-adx-uni-post-20261110`。均在本机`_work`，不包含公共repo生产凭证。

## 上传源码、服务器存储源码与JAR分开证明

上传9218字节，SHA `26486bbad251606ca2ef270570292acd9386bcd2b68ef8a78d0a54ae4a910454`；服务器存储9217字节，SHA `8e424d51c624eaf2bbe8b8433a60542678a6914fcdec2f92f5d88eda64dcdf14`。只去掉末尾一个换行，实际字节比较确认等于上传的外部ASCII空白trim；不能声称两份原始SHA相同。

服务器精确版本JAR与candidate.checksum均为 `87c17e01e1f209622a0c10b4017af7a2ba8b674e2d23de34e9a4c109a128e8af`。新增 `compiled_source_audit.py` 只读核查准确candidate/version的源路径和JAR：仅允许完全一致或外部ASCII空白trim，内部代码、字符串或JAR校验变化均拒绝。本次已对真实服务器存量产物验证通过，无修改/再编译。

## 续接

1. 优先核查真实PID/创建时间/命令，不以状态文件或锁文件单独认定存活。23:11进程4332、12040仍存活且有对应子进程；8676、21320已结束，完成marker齐全，不重启。
2. 保持两批冻结研究继续，任何原始通过先过strict审计，再验证分离留出、工程哈希及真实同行机制。
3. 合格固定源经正常服务器编译、最近完整365日/场景/基线门槛及精确版本ACTIVE审计才计入新增实盘。
4. 不修改在跑金融代码来修DTO字段；本轮只读后裁决。后续新冻结批次若修字段传播，应另行证明最终政策路径，而非复用信号等价证明替代。
