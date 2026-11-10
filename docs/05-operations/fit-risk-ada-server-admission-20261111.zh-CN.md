# ADA通道重入：完整目录首个本地严格通过、服务器拒绝

2026-11-11 01:31北京时间。新本地结果已真实走完固定源码导入、编译、最近365日回测及正常发布器；最终零发布。目标仍是100条独立生产合格策略，尚未完成。

## 原结果校验，没有重放

完整目录控制器24052首先严格通过的候选为`catalog_adausdt_channel_1055249e7caf`，假设`fr1_atr_envelope_two_bar_reentry_long_s20_t40`，族`FitOnlyRiskAtrEnvelopeTwoBarReentryHypothesis`。

调用原`verified_observation`和`require_proof`只读复核：完成marker、金融输出SHA、源/JAR/合同、同字节seed、四档candidateParameters、原9例真实FIT oracle与现行SIM类/配置均吻合；没有重跑或改写金融结果。未根据旧大账本的默认minForwardContribution=0认定发布资格，实际复核仍至少0.20。

| 检查 | 原主期 | 完全分离留出 |
| --- | --- | --- |
| 日期 | 2024-12-15～2025-10-12 | 2025-10-13～12-13 |
| 交易数 | 34 | 14 |
| PF / 最大回撤 | 1.548996 / 0.039517 | 1.392691 / 0.023809 |
| 扣费验证 / 前向 | 587.178037 / 352.328189 | 扣费总收益98.58372895 |
| 参数 | 四档逐折FIT、代表2 | 锁参2，fit/optimizer均0 |

主期totalPnL895.306046、OOS1、严格贡献0.393528。留出只有14笔，过既有门槛不等于未来盈利；未新增或降低门槛以凑数。

- 原计划SHA `59944b8d1fcb4f504cb129e29c49956da064e5c6270bce1409b47b6db2a1c347`。
- 源SHA `c03526e268fed5079d20b2898ab7f7fcd61b74b9f03776eb9918b831fd62fae4`。
- 本地JAR `5c3e97ad173c1b20ba00aeb50092d31705c0e5e336b84e3be33a2f0a810a479a`。
- admission manifest `0dead60e1a1c0eca90399c04e4b1bde6ac4f7b05ee7be2d3036e07a4191c5895`。
- results `4152a518be4cb7a89d5c45657ccf23f00b2d8630d66854b44b50d5d3610e1dfe`。
- primary `c9583f9fe381b8be743fb79265d5c815b7170d03cf1514ade4abad905f20be1d`；holdout `af37e933823c2da4f0c26aa9ef6fc5e763530d98d0b9aa215d4bb65914ce2dfd`。

原始目录`strategy-fit-risk-full-catalog-20261110/admissions/catalog_adausdt_channel_1055249e7caf`。单条results和frozen原样复制到`strategy-risk-ada-promotion-view-20261111`，results SHA逐字节相同。原live队列与工具树没有修改。

## 机制复核与生产前检查

17:24:38UTC新库存、17:24:44UTC私有精确源码备份一致：4个ACTIVE，没有ADA/channel同行。当前ADA/trend是20根突破/回测机制，不是本政策的平坦包络重入。

本源warmup160，i-3之前96均线与i-35之前96均线漂移绝对值不超过1.2%，用前ATR24构造均线减1.8ATR边界；i-2低点跌破、i-1收盘收复、当前收盘突破i-1最高价才买入。ATR14初始风险基础2/4，原四档由FIT选，ATR20显式EMS退出且首档保护不小于0.5%。只批准一个`flat_ma_atr_envelope_two_bar_reentry`机制实例，不把风险档/方向当独立数量，不声称与其他资产风险统计正交。

17:26:27UTC实测hostname仍prod-mooncake-standby、服务器最近完整日2026-11-09。最初只读时钟探针因本机PowerShell传递双引号发生语法错误，未连接/写服务器；保留输出后改用无空格date格式只读成功，没有重复提交。单条prepare-only、strict审计、源validator成功后才启动实际导入。

## 服务器终态

实际本地轮询器13068一次导入后正常结束；不要重启它或重试该源。

- v1；generation `gen_1569886857502711808`；candidate `cand_1569886863546703872`；backtest `bt_1569886864318455808`。
- 2025-11-10～2026-11-09完整365日，120/30/14、FEE_ADJUSTED_PROFIT_FIRST、原四档FIT候选；服务器代表`riskProfile=0`，不是本地2，没有根据结果改参数。
- 31笔、PF0.713167、回撤0.072818、totalPnL-591.543715、扣费验证**-866.883370**、扣费前向**-16.743743**、OOS0。
- 场景726记录/3504匹配bar/31笔，qualification=false；publisher `SKIP`，原因为`scene fee-adjusted pnl <= 0`。
- 服务器编译/回测任务SUCCESS、candidate READY，精确名字registry为空、published=false；没有新增实盘策略。

外部源导入external / EXTERNAL_SOURCE / EXTERNAL_IMPORT / external_java，精确版本LLM调用0、无fallback。上传38189字节，存储38189字节，仅package空行/末端ASCII空白规范化、tokens unchanged；存储SHA `a7e75dc4d07b3d5d8d6ad2747b213f35928e066e5bc507a15685218763415ba0`。服务器JAR及candidate.checksum均 `279a53041f5fbb3a6acd653f9e3746504f0923b50c4add1902c9eb4119468bed`，compiled_source_verified=true。

证据`strategy-95-server-fit-risk-ada-20261111/catalog_adausdt_channel_1055249e7caf`包含原请求、提交响应、终态、源码产物审计、outcome和live；日志`strategy-95-server-fit-risk-ada-launch-20261111`。私有同行源保留在`strategy-risk-ada-peer-review-20261111`，不提交公开repo。没有改镜像/配置/风控/持仓、重启服务或直接写registry。

## 新库存及接续

17:31:21UTC / 01:31:21北京时间只读生产快照`strategy-live-inventory-risk-ada-post-20261111`：ACTIVE及当前运行资格4，另过贡献单项2，本轮新增发布0。4不等于4条全部符合当前新发布要求，更不等于已完成100条。

当前时间隔离V2严格通过的新增候选累计4（真实ADX1、平衡队列2、完整目录1），服务器复验现已4条全部失败；不是4条新增上线。更早固定源ETH/channel也曾本地通过后服务器失败，另列历史批次，不通过重复版本或方向相加计实盘。

01:31原4332进度345/400、本地2；24052为352/19,599、raw1/strict1/errors空。原20660仍等待绑定4332真正BATCH_COMPLETE400后才开始新OHLCV分箱代理200作用域，等待不是回测通过。继续读取小status和实际PID/创建时间/module，不能据陈旧状态重启旧12040，不能重放已消费金融失败。参见[新OHLCV研究](ohlcv-profile-proxy-research-20261111.zh-CN.md)与[安全交接](full-catalog-batched-checkpoint-handoff-20261110.zh-CN.md)。
