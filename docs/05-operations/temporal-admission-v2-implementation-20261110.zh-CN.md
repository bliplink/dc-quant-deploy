# 本地准入 V2：时间隔离与锁定参数

本轮继续仅用既有 OHLCV 和已存历史场景，不新增资金费率/OI，不改服务架构，不调用服务端代码生成或修复，不改变生产资格门槛。

## 发现的旧协议边界

真实样本 `catalog_ethusdt_channel_4a0b9c87e1c5` 的主回测是2024-12-15～2025-10-12，额外留出重放却是2025-08-12～2025-10-12。第3折forward覆盖8/12～8/23；第4折fit亦覆盖8/12～8/23，validate覆盖8/24～9/22，forward覆盖9/23～10/6。证据 `strategy-temporal-boundary-audit-20261110/eth-legacy-admission.json`；原信封SHA256为 `37a1c75dd12c9cee6e63db83d134232b1cf2e202feaf3ee7499fdaad8d65c4fa`。

该固定源的参数维度为空，没有发生动态重选参。问题是这两项检查不能证明完全分离的时间留出；旧留出函数也未显式绑定主回测选出的参数，不能直接给四档风险新策略使用。此前文档称“本地双重合格”仅表示旧协议两项门槛通过，应更正这一独立性表述。原金融结果、失败和已消费前瞻全部保留，不覆盖、不借此重调失败版本。

当前245项旧协议批次继续完成原冻结研究，`formal/semantic-review.json` 已设为空审批集，合格项只defer、不直接导入。旧协议失败项不得借V2重新包装；已经通过旧主回测及旧额外留出的固定源，可以在不重跑主回测、不改任何源参数的前提下增加更严格的全新分离留出。

## 新冻结协议

`recovery/strategy_research_temporal_protocol_20261110.json` 明确：

- 主期：2024-12-15～2025-10-12，保持原v4完整滚动fit/validate/forward及至少3折。
- 分离留出：2025-10-13～2025-12-13，仍保留完整62个日历日，紧接主期，不缩短、不跳过。
- 留出参数：主期已选出的代表参数冻结。四档策略不能默认回到档0，也不能在留出再次拟合；固定源显式锁定空参数表。
- 进入新发布工具前，所有本地候选必须有 `local_temporal_holdout_v2` 信封、完整主期边界、同源SHA、参数一致性及留出0次拟合/优化证明。原成本、交易数、PF、回撤、OOS、前瞻贡献、场景和服务器发布门槛不减。
- 数据是新政策假设的历史检验，不是前瞻实盘盈利证据。研究已尝试大量规则，不能声称这些市场数据对研究者完全未见或统计独立。

## 数据准备，全部只读

`export_temporal_holdout_extension.py` 经Paramiko known_hosts严格校验连接126，核验主机名和ClickHouse UTC，只SELECT既有K线/已存historical_kline_scene；没有生成场景标签或调用模型。为校验接缝，多导出2025-10-11～12-13：10品种各6144根行情、128条12小时场景，原重叠两天逐值Decimal相同，没有容差放宽。10:51:09 UTC全部完成，导出manifest SHA256=`981bf7450a6f32dd6dff0b45a514898c2090c75023cfd1dbce3191f04f026b37`。

新输入目录 `strategy-temporal-research-input-20261110` 由 `assemble_temporal_research_input.py` 创建，所有旧文件字节前缀保持不变，只追加更晚记录；旧READY及原目录不改。新READY SHA256=`8d919223d4d8de9b80de01e01fb38a2b15418d3e7f33ff0725157eb7ba9bccaa`。不存在重复/错序K线，场景日历覆盖完整。这个数据准备过程不读取任何新策略留出收益。

## 离线真实执行器与参数链验证

`recovery/java/OfflineTemporalReplayCli.java` 直接组装已有VersionedBacktestRunner、BacktestTradeService、BacktestMetricService、ExecutionStressService和真实运行时，不启动服务、不访问数据库或HTTP。费用/经济性配置从当前正式配置及已有注解默认值解析并记录，不关闭过滤器。源和JAR、行情、场景均核验哈希；无optimizer入口。

`verify_offline_temporal_replay.py` 仅使用BTC 2023-05-01～7-01训练行情和明确标记的人工工程场景标签，比较3种代表源码×4档，共12个有实际交易的用例。全部逐笔交易、费用、PF、回撤、执行压力扣费结果及旧LocalHoldoutReplay门槛一致。证据 `strategy-temporal-replay-oracle-20261110-livepath/audit.json`，manifest SHA256=`5ef0221d51f94bab334fb9be0d9a1fea1e581d5f7b2cbc3c4416fad8f82704e7`。

另调用真实publisher参数函数、INDSvr实盘注册行toDefinition及BuySellSignalFacade，逐根验证发布参数到运行时的全部信号风险字段。候选参数metadata与实盘平面参数JSON使用不同入口；初版测试用错候选入口的失败已保留，未据此改任何共享库。首个编译时把DAO接口当类的诊断亦保留。数据库持久化/生产实装发布仍需未来真正合格候选上线后审计，不能把离线值流验证当作该部分已完成。

## 首条真实补充留出结果

旧批次 `catalog_ethusdt_range_1d7dd3e1790d`（ETH/range、Aroon趋势延续）主回测已通过：23笔、PF1.652593、扣费验证348.967896/前瞻338.203982、OOS=1；旧额外留出8笔、PF4.779627。源码SHA=`1003d064d76a1c0f6c27e003c450f47688aa8eb46ced27173ae0d6cfb2f21ab6`，不含参数优化维度。

`supplement_temporal_holdout.py` 核对原金融信封、源、冻结目录及原门槛全部通过后，只编译同一源码，再做新的62天留出，没有重跑主回测。结果8笔、PF=0、扣费后-731.84678459（回测初始资金10000模型单位，并非新增实盘损失），未通过，不上传/发布。证据 `strategy-temporal-supplement-eth-aroon-20261110`。该留出已消费，不能修改同版参数、换名或重跑来改善分数。

## 当前仍未完成的工作

四档风险原型的源码/信号工程证据保留，但每折fit四档选择、validate-only汇总与完整真实v4的逐折等价仍未完成，不能先跑400方向金融筛选。接下来应复用实际SliceOptimizedWalkForwardRunner的选参和窗口方法，训练期先验证；随后冻结新主期流程，只有主期及分离留出全部通过且机制复核通过的固定源才进入服务器365天验证/原发布器。

旧245项会继续产出研究证据；截至19:06:17为129/245，旧协议通过1，但新增完全分离留出通过0。生产库存最近服务器审计仍为4、缺96，本轮没有新增上线。源码、工具和边界修复持续记录于dc-quant-deploy。
