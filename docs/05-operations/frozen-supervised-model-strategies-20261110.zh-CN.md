# 本地冻结训练模型策略批次（2026-11-10）

## 训练边界与用途

本批是独立于滚动小样本统计批次的新假设：先在验证期之前的历史数据训练跨品种模型，将模型冻结成Java常量，线上只做本地数值推断。没有DeepSeek调用，没有服务器训练/生成代码，没有Python运行时依赖。

训练源仍是已冻结READY内10个品种的OHLCV。信号时间从 `2024-08-15` 起，16根15分钟收益标签的完整终点必须严格早于 `2024-12-15 00:00 UTC`；每隔16根取样，标签区间不重叠。正式研究验证从2024-12-15开始，因此训练绝不使用后续验证、留出期或服务器复核标签。

合计 **7,310** 条训练样本。该数量是历史训练标签，不是策略数、实盘交易量或盈利证据。模型训练误差及其派生误差空间只是信号构造规则，不代表正式的独立显著性或收益保证。

## 固定模型定义

4组特征：动量、相对价值、波动、价格/成交量形态。每组分别使用一个岭回归和一个浅层Huber梯度提升回归，共8个模型、16个多空方向。特征仅由最多200根已完成K线计算，并在训练和Java推断中使用相同归一化、裁剪和滚动边界。

超参数在观察本批验证财务结果前固定：岭回归alpha=200；提升模型24棵、深度2、最少叶样本100、学习率0.05、固定随机种子20261110。没有按品种网格搜索、按前瞻结果修改参数或挑选未来区间。

Java源码直接嵌入系数和树，不加载在线模型服务。信号仍使用既定1.5/3.0 ATR风险结构、原有16bps执行成本假设和保守的收益空间规则；之后必须接受与其他策略完全一样的正式v4、留出期、服务器回测及发布门槛。

## 数值一致性与数据证据

训练入口：`recovery/train_frozen_strategy_models.py`；测试：`recovery/test_train_frozen_strategy_models.py`。训练包位于 `E:\sourcecode\codex\_work\strategy-frozen-model-training-20261110`，其 `TRAINING_COMPLETE.json` 明确金融留出期未被评估、服务器/LLM调用为0。模型包SHA-256：

`eb9dcef1c06b207ec685d24fd4ae9287357f2e1e33af66ab83b6c7a59ea700d5`

已比较模型导出与sklearn预测，最大绝对差不超过约 `7e-17`；Java固定探针同时校验模型预测及Python/Java特征计算。Java的树节点明确复现sklearn的float32输入与double阈值比较。

另修复NumPy 2.x弱标量提升可能把double阈值舍入到float32的导出检查问题，新增边界回归测试。对当前4个提升模型、各7,310个训练样本做全量新旧比较，改变的训练预测均为0；因此没有修改本批冻结权重、派生误差空间或模型包，不涉及基于未来收益的重训/调参。证据为训练目录 `float-comparison-audit.json`。

研究工作树：`E:\sourcecode\codex\_work\indsvr-local-frozen-model-strategies-20261110`；本地提交 `bcd3a47`。研究、结构、统计和冻结模型Java测试合计36项通过。独立研究分支仅提交测试源码，不发布INDSvr生产镜像。

## 执行与接续

北京时间 **2026-11-10 14:11:07** 启动全流程，启动进程 **8108**。目录：`E:\sourcecode\codex\_work\strategy-frozen-supervised-cycle-20261110`。使用cohort `frozen_supervised_v1`，服务器复核仍固定2025-11-10～2026-11-09。

顺序为：冻结源/类哈希 → 16个代表源码逐个编译、服务端源码规则校验及验证月份信号一致性比较 → 800项验证预筛 → 正式/时序留出期 → 仅合格源码上传 → 服务器编译回测 → 真实ACTIVE/资格核验。16个源码已经通过预筛前检查，800项预筛已完成，14条进入正式回测；这不是14条可用实盘策略。

读取 `cycle-status.json`、`formal/status.json`、`formal/results.json` 和最终 `formal/cycle-summary.json` 获取最新状态。上传项必须含 `server/<strategy>/source-only-audit.json`，证明external_java及该版本LLM调用记录为0。

总体目标仍为100条真实合格、逻辑独立的库存。不同模型类名、同一逻辑的多版本或训练方向不能自动算作独立实盘策略。总体接续见 [持续目标](strategy-inventory-100-active-goal-20261110.zh-CN.md)。

## 本批最终结果

北京时间14:23完成全部流程：800项预筛、14条正式/留出期回测，1条本地双重合格，即ETH/range `catalog_ethusdt_range_6e2b04b639d5@v1`。仅这一条被上传，服务器固定源码编译成功、回测任务正常结束，但财务资格未通过：16笔、PF=0.665722、扣费验证收益=-453.959597、扣费前瞻收益=-171.732095、OOS=0；没有发布，不得重调同一版本后再试相同前瞻。

`source-only-audit.json`证明上传37,759字节、源码SHA与本地一致、provider=external、generationType=EXTERNAL_IMPORT、engine=external_java，该版本LLM调用数=0。最新库存快照2026-11-10 06:23:10 UTC仍是ACTIVE=4、合格=4、缺96。8108已结束，不能继续描述为运行中。

研究远端独立分支 `codex/local-frozen-model-strategies-20261110`，提交 `61908c61b1ae81de9b10720d35f5466436a59bc9`；本地研究提交和远端文件的Git blob逐项校验一致。接续为 [执行路径模型批次](execution-path-model-strategies-20261110.zh-CN.md)，不是放宽本批失败条件。
