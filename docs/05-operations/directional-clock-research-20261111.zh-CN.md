# 方向变化事件时钟：OHLCV新假设与固定源码研究队列

2026-11-11 01:57接续。目标仍是100条真实独立、生产合格策略，尚未完成。只用现有OHLCV，不增加资金费率/OI/采集或服务架构，不调用DeepSeek。工程通过、信号数、作用域数都不是合格或上线数。

## 先排除旧机制，不以改名字凑数

开始曾考虑历史形态近邻；检查canonical源码后发现已有`KernelAnalogueForecastHypothesis`：六维滚动特征、核权重、已观测8根标签、有效样本和收缩预测。没有再改邻居数、方向或版本来算新机制。

旧`EventDurationForecastHypothesis`的事件是突破前12根最高/最低价，比较事件到达时间并依赖历史8根收益标签；旧`SwingStructureBreakoutHypothesis`用三段固定32根高低区间与当前区间突破。本次则只对过去完成收盘构建阈值反转路径，没有预测标签或固定区间突破；仍有共同的趋势/转折敞口，不声称统计独立或盈利。

两方向统一一个保守机制组`directional_change_overshoot_clock`，canonical cohort `directional_clock_v1`。以后若本地合格，必须再对当前同单元精确ACTIVE源码作机制复核，不能提前批准上线。

## 金融前固定规则

协议`recovery/strategy_research_directional_clock_protocol_20261111.json`，SHA `24e0a4b691de35b00aef038dbe88db254027631d4358cf448cf3bcdfce18e36e`。

- 160根热身、最多200根可见数据；在最后128根完成收盘内重建有限路径，不冒充无限期持久事件历史。
- 阈值为当前之前20根平均真实波幅的2倍，整个128根重建中保持同一阈值；当前bar不进入这个阈值。只用收盘，绝不推断同一bar内高低点先后顺序。
- 从未知方向的运行高低收盘开始，首次达到阈值才确认方向。随后收盘距当前方向极值达到阈值即反转，一根bar最多确认一次。
- 已完成腿从前pivot极值到新极值：超越幅度为`max(幅度-阈值,0)`，持续时间为两个极值bar的索引差，不把事后的确认延迟加入时长；不用未来确认pivot。
- 当前bar必须恰好确认进入声明方向。两方向各需最近两条完整腿，时长都>0。同方向两腿超越/时长之和严格大于相反方向的1.25倍；用精确分数交叉乘法比较，不用epsilon。两条同向腿各需至少半个阈值超越，最近反向腿超越不超过其均值。
- 当前正成交量、实体方向一致，所有可见OHLC有效且量非负；ATR14初始stop1.5/take3，沿用ATR20显式EMS保护及firstStep至少0.5%。没有参数搜索网格。

金融仍用原v4实际执行器、2024-12-15～2025-10-12主期、严格0.20或更高前向贡献及其余全部门槛。仅主期全过才执行完全分离2025-10-13～12-13的62天空参锁定留出、fit/optimizer调用0；之后才可固定源上126正常编译、最近完整365日、场景/基线/发布器。不改任何生产配置、风控或持仓。

## 独立工程和保留的失败

新隔离Native工作树`indsvr-local-directional-clock-20261111`、工具树`dc-quant-deploy-directional-clock-20261111`。原4332/24052/20660所在树、源码、helper、输入、负结果完全没改。

V1工程目录`strategy-directional-clock-engineering-20261111-v1`保留manifest、FAILED和编译日志：测试误调用不存在的`hypotheses(String)`；改用项目既有系统属性+`selectedHypotheses()`并恢复属性。只修测试调用，不改交易规则、阈值或原validator，未观察本假设金融结果。

V2目录`strategy-directional-clock-engineering-20261111-v2`：16项测试通过，包括64条独立慢速区间极值枚举oracle与在线状态机逐腿完全一致、精确小数阈值/严格1.25边界、跳空每bar一次、平极值首索引、未来/非法输入、两方向真实合成setup、全部风险字段独立原始OHLC计算、当前bar不污染历史阈值、前缀不看未来和canonical all登记。

两份实际导出源码均过原validator、独立编译与BTC2023全年35040根原CLI逐字段对照：多161、空193信号，均0差异且非零；工程不是金融盈利证明。

| 证据 | SHA-256 |
| --- | --- |
| 工程manifest | `97335efd05b13d1a037a3fdad811ad3d00652e2bd46514f3a7cb861c4b1389f6` |
| 工程完成marker | `adc5ba0fe2b048e46eda9508a11239e710baf2e1a3a316fa8d6d590af5a0b0cf` |
| BTC多源 / 本地JAR | `f005d37eaf66bf456274757b1bf2015b1fb1aee043433c8fa1fa68aab25c411d` / `8533f73b0184905cfa991299c0b8c9e0e8ce46cb0e7e3d4f8f04d7a16daad6d4` |
| BTC空源 / 本地JAR | `77a7bc8b2242a25f5bfe604a5d60a22338f90b7f85cf780df42402ed65dd0694` / `2ee414fd763aa6e9c0c8ce30a2553a0e8527829be5b5919323d1333875ff09a3` |

完整Java研究回归139项通过，目录`strategy-directional-clock-regression-20261111`，manifest `c5fcf128dedd0c938e729c8e9e7ba6f72de0ff454f942513b00f012b416c068e`，日志SHA `4ac1297805015a46c0ec828d3b3ae427c70bc75d52a46b776c506c5365acfdcf`。Python全量190项通过，包含原OHLCV批次默认调用不变、source hook不让贡献失败进入留出、半完成不重放、完成失败复用及不能重命名机制、等待后工具哈希变化拒绝等。

Native本地commit `bcef111`，远端独立分支`codex/local-directional-clock-20261111`已推 `d67b000b909e2259e61924b893989b5efe8d8d51`，tree `17c6567df3d642fe712fb5f5be4b3a81ca00ddcf`。5个blob与本地Git逐项核对，Core只加cohort/all登记4行。镜像workflow实查只在latest触发，研究分支不部署生产，没有POM/API/共享包修改。

## 已启动等待器，尚未金融回测

新`clone_temporal_protocol_view`只验证并复制原完整市场字节到独立READY视图，不改变旧输入/日期/场景；新READY SHA `b648ac43c3ffc3162dfd4e3d200c180641630c96d70c90924e982592c6802e19`，目录`strategy-directional-clock-temporal-input-20261111`。若源SHA不符或目标已存在即拒绝，不覆盖旧视图。

工具本地commit `0ab6bf9`。只在新工具树的`run_ohlcv_profile_proxy_batch.run_case`增加显式源码工厂/身份字段hook，默认原4模式行为及实际v4/strict/留出执行代码保留；原20660使用的另一工具树未修改。新`run_directional_clock_batch`复用该原执行链，避免另写弱门槛执行器；不含SSH、模型、导入或发布路径。

01:53:55以27328启动（create_time=1794333235.826844），目录`strategy-directional-clock-formal-20261111`，日志`strategy-directional-clock-formal-launch-20261111`。manifest `a7b7a09c2b995ce660d1deefae84bddecf67c07f03fe61ecb9c528abcce03852`，冻结10品种×5场景×2方向的100作用域，仅一个机制组。当前`WAITING_FOR_BOUND_PROFILE_BATCH`、0/100，无金融子目录和服务器写入；100不是100条独立合格策略。

它绑定精确20660、创建时间、完整命令/输出目录和父manifest `cce5da0df561e347ab2062810e48326cbab16879d630a64cfaa68c43fb4c8af0`。必须该OHLCV批次真正200完成、无FAILED、状态/完成marker/200条原金融检查点与身份吻合，才接续；父进程消失不是完成。等待后及逐作用域再次验证固定工具/协议/源哈希，等待后还校验工程类；自身持有OS排他锁、内存/磁盘护栏。部分尝试保留并拒绝盲目重跑。

现有资源链：4332平衡批次真正400完成→20660 OHLCV代理200→27328事件时钟100；完整目录24052另以最多2隔离worker持续运行。01:55实测为367/400/本地2、411/19,599/raw1/strict1/errors空，两个新批次均仍等待；后续必须核对实际PID/创建时间/module和小status，不能读取并发大账本或重启已交接终止的12040。

最近服务器库存仍以17:31:21UTC已验证快照为准：4当前运行资格、另2过贡献，本轮0新增发布；不是4条全部满足新发布要求。新候选一旦严格通过，需要机制复核后固定源正常服务器验证，不能因排队/工程通过提前记为上线。目标继续。
