# LINK均线回调策略：本地通过、服务器拒绝的完整记录

2026-11-10 23:34北京时间。目标继续是100条独立、真正生产合格策略；本轮没有新增上线，不放宽门槛、不改变架构或使用DeepSeek生成/修复。

## 本地新完成候选

平衡四档批次出现`catalog_linkusdt_trend_46e6647d07dd`，假设`fr1_trend_pullback_long_s15_t30`，族`FitOnlyRiskTrendPullbackHypothesis`。源SHA `90f2b78ae82c0aff5b7a9fc0bad69ee31a1a3796fb409ad1df7fe00f1483f05b`，本地JAR `6da68a38f1bac9636426aede873319cdfd3d6d42baf26c24e5330d7302b195b9`。

主期2024-12-15～2025-10-12：52笔、PF1.464169、回撤0.057591、扣费验证741.364244、前向596.496677、总PnL1213.588369、OOS1；严格贡献比0.491515，超过既有0.20。主期真实FIT各折在预声明四档中选择，模态代表参数`riskProfile=2`，不是读取forward后另挑一档。

完全分离2025-10-13～12-13留出：11笔、PF1.582022、回撤0.02871、扣费193.63493778，锁参2，fitInvocations=optimizerInvocations=0；留出通过不保证未来盈利。完成marker、金融输出/来源/JAR/协议与真实9例fit-oracle哈希均已核对，原输出未修改/重放。

- 原始终态证据：`strategy-fit-risk-balanced-scope-20261110/admissions/catalog_linkusdt_trend_46e6647d07dd`。
- 队列manifest `f046c3dad656c2fc990125e1d4d679e9abf6edeb5343fbff06fb26e68975e8da`。
- admission manifest `263ed055241c11d68452ee3650b7861524c4380f9baa40cc40899d5382c33b84`。
- primary `560a7febf0bc572d8c248718cf66c4f6af89f1422ec9fa174f13e3b7b429f100`。
- holdout `be8d4043588b30f5465b92e497f6adfb4e860d45264c7dbdc2cdb3e6c1eda182`。

从此单条已完成admission原样复制results/frozen建立`strategy-risk-link-promotion-view-20261110`，没有读取/改写并发大账本来制造新结果。

## 机制与当前同行复核

15:26:35UTC库存和15:26:41UTC私有源码备份匹配4个当前ACTIVE精确版本。LINK/trend仅`lcr1_link_tre_66fbd6eb@v2`，源码SHA `7b23faa3e9fb98e16b0bc774169cb8677aae329a74a5b0835021333c35436598`：向下突破前24根最低价、14根方向差、SELL，固定百分比退出。

新源仅BUY：SMA50>SMA180、180均线比16根前上升、前收盘低于当时SMA20且本收盘收复当前SMA20；200根可见窗口、ATR14初始风险、ATR20显式退出，四档是同一政策而不是4条独立策略。审核只批准一个`ma_trend_pullback_reclaim`机制实例，不把与空头方向不同本身当作独立理由；其具体回调收复触发不同于边界突破。共同LINK/trend风险存在，不声称统计正交。

私有同行备份保留于`strategy-risk-link-peer-review-20261110`，不提交公共repo。source-bound审核覆盖同单元精确名字/版本和源码，原场景/基线/服务器门槛不变。

## 服务器真实结果：不通过，不重试

prepare-only及原源码校验通过。第一次启动进程18972遗漏`--validator-classes`，在本地参数检查退出，未SSH/导入；日志留在`strategy-95-server-fit-risk-link-launch-20261110`。后补齐参数、以26664启动同一固定源；不能把第一次本地退出计作服务器尝试。

实际只导入一次：

- version v1，generation `gen_1569856642168709120`，candidate `cand_1569856651803025408`，backtest `bt_1569856652545417216`。
- external / EXTERNAL_SOURCE / EXTERNAL_IMPORT / external_java，精确版本LLM调用0，无fallback。
- 2025-11-10～2026-11-09完整365日，120/30/14、FEE_ADJUSTED_PROFIT_FIRST、四档原FIT候选和0.20门槛，未根据结果改配置。
- 编译/回测执行SUCCESS，57笔、PF0.837932、回撤0.128312、扣费验证-944.861887、扣费前向-270.499246、OOS0；总PnL-437.955236。实际best_param_set为`{"riskProfile":2}`。
- 场景726记录、3018匹配bar、57笔，scene qualification失败。正常publisher SKIP，`scene fee-adjusted pnl <= 0`；published_live=0，精确名字registry为空。

窗口及源已消费，不以改风险档、换版本或挑日期重试。不发布、不操作现有策略/持仓/风控/服务；没有生产发布，因此不能声称已完成此候选的实盘参数持久化验证。

## 编译源码审计及本地报告补齐

导入器将package声明后的空白规范为两个换行，并去掉源码末尾换行。该源上传/服务器存储均37624字节但SHA不同：上传`90f2b78a...f1483f05b`，存储`36e3431f8bf58db8d1442b34e196aeaa5c714a185689b4b889dd8ff01c75a741`。逐字节差异仅新增package后的空行、删末尾换行；类名、包名和主体内容不变。

最初只容许outer trim的本地审计正确拦截该差异并退出；这是回测之后的审计失败，不是导入失败。随后只读检查当前版本源码/JAR/任务/库记录，不再次导入或回测。核对实际`StrategyCodeCompileService.normalizeSource`后，审计仅新增“相同package + 两个换行 + 原body（只trim外部ASCII空白）”精确候选变换；class/API重写、内部空白、字符串、注释或包名变化仍失败，绝不直接接受整个服务器sanitize逻辑。

服务器JAR SHA与candidate.checksum均 `90a44982c04e24f588b4d4ae0ca90cdb1a4a5b66c28459d28384be5162c5afa9`。真实只读审计通过，另补写本地`source-only-audit.json`/`outcome.json`/`live.json`，保留先前异常和完整差异证据。诊断中SQL列名误用`best_param_set_json`的只读错误也保留，实际列`best_param_set`，未改库。

证据：`strategy-95-server-fit-risk-link-20261110`及`strategy-95-server-fit-risk-link-launch-v2-20261110`。157项Python工具测试通过，包含仅允许确定package空白变换、拒绝其他变更的回归。

## 最新库存与续接

15:33:40UTC/23:33:40北京时间生产只读快照`strategy-live-inventory-risk-link-post-20261110`：ACTIVE及当前运行资格4，另过贡献单项2，本轮0新增发布；仍缺96（按运行库存口径）。

23:34两批仍真实运行：4332为217/400、1本地严格通过但该条服务器失败；12040为97/19,599、0本地通过。请核对实际PID/创建时间/module与最新小状态再继续。原helper、源码、规则、负结果冻结；不能重启已终结ADX/影线批次。[训练启动合并优化](four-profile-launch-batching-20261110.zh-CN.md)已证8组32档及真实新作用域源/JAR相同，但尚未切换在跑队列；先验证安全检查点交接再集成，不并发覆盖其合同目录。
