# 结构入场事件的条件过滤研究：财务检查前协议

## 独立假设及边界

此前冻结模型对所有K线学习收益，不同入场机制混在同一总体。新假设先用已有10种明确不同的结构规则产生事件，再分别学习“该规则这次入场是否值得接受”。模型只能拒绝原规则事件，不能在规则没有信号时创造交易。

规则为原`structural_v1`的价值区拒绝、开盘平衡接受、三拍卖压缩逃逸、日区间突破失败、双幂跳跃延续、半方差恢复、价值占领迁移、位移缺口防守、位移原点防守、连续波动释放。原规则、1.5/3 ATR及成本空间保持不变；其纯规则财务失败已经保存，不能将纯规则重新发布。只有带冻结条件模型的新候选才走新验证。

对每条规则及方向使用2022/2023/2024训练标签，三年度总权重相同。固定24棵Huber提升树、深度2、最小叶50、学习率0.05、种子20261110；至少200个已观察标签、每年度至少20个，缺任一年度就明确不可用。不调用模型API，不回退为未过滤原策略。

原规则事件后预测扣费净空间必须>8bps。这里不比较反方向预测，因为反方向模型条件化的是另一类结构事件，不是同一总体；这条语义在本批财务结果之前确定。训练代理的96根删失、费用名义金额近似、无场景强平及后续信号干扰等局限仍存在，必须由原正式v4/留出和服务器门槛独立检验。

## 事件与训练数据证据

使用已冻结的`strategy-regime-training-input-20261110`，所有行情截止2024-12-14。Java事件导出只调用原规则，在每个信号时点仅暴露200根历史K线，不读取后面的标签；特征及潜在标签跨度有缺失K线则排除。每条规则/方向固定按最早事件间隔16根取样，与收益无关；标签可能重叠，不声称样本独立或显著性。

事件导出CLI为`StructuralTrainingEventsCli`，位于研究工作树`indsvr-local-structural-meta-strategies-20261110`。已用只读父研究类目录编译，并通过2项独立Java测试：20个原规则方向事件与原窗口一致、缺失K线及验证日期不能产生训练事件。本地提交`85c1206`。此时尚未编译完整Meta模型，不能把2项CLI测试描述为整批模型测试通过。

父规则源码和类目录冻结在`indsvr-local-regime-consensus-strategies-20261110`（70301c1），正是已通过49项Java测试的版本；新事件CLI输出不修改它。每个品种检查点保存输入K线、原规则声明、父类字节码及事件CLI字节码哈希，改变任一项则拒绝恢复。

北京时间14:59:22由进程16544启动本地训练，目录`E:\sourcecode\codex\_work\strategy-structural-meta-model-training-20261110`。入口`recovery.train_structural_meta_models`，参数`--input-dir <training READY>`、`--event-repo <meta worktree>`、`--rule-repo <frozen parent worktree>`、`--output-dir <model directory>`。不需要生产密钥，也不连接服务器。

读取`training.stdout.log`、`training.stderr.log`、`training-status.json`、`events/*/checkpoint.json`及最终`TRAINING_COMPLETE.json`。只因证据不足跳过的规则会逐项记录，不能静默降最低标签要求。已有工作流与新训练测试共46项Python测试通过。

## 必须继续的实施步骤

训练包完成后，固定模型和规则声明哈希。把原规则声明复制为Meta规则，原`setup`仅改名为`ruleSetup`；独立公共父类先调用这段规则，再做冻结模型净空间判断。增加逐项原规则一致性、Python/Java所有模型预测、无新增事件、窗口及未来访问、目录注册测试，再完整构建。不能在事件导出训练仍使用CLI字节码时重建该工作树，避免哈希及运行版本混用。

冻结源码后，仍按独立源码检查→验证预筛→正式/时序留出→仅合格源码上传→服务器365天回测→精确版本ACTIVE/库存审计推进。真实可用策略数只统计最终合格和独立逻辑，不按事件数、子模型数或训练样本数补数量。

## 模型、源码与测试已完成，完整验证已启动

16544训练已完成并结束。10种规则都具备三年度训练证据，冻结20个多空模型，无跳过项。模型包SHA-256为`5596de98188ab475c668b58acf68e59882f9681964b580720af6b61b735bc624`；原规则声明SHA-256为`97f46cfb659dc7542e65dc0e7dbf9a97de21c92f98a96c084b52709e1d8795a6`，复制前逐项核对一致。下表是历史训练标签，不是实盘成交或通过策略数：

| 规则 | 多头训练标签 | 空头训练标签 |
| --- | ---: | ---: |
| AuctionValueRejection | 7399 | 7571 |
| OpeningBalanceAcceptance | 4959 | 4696 |
| MultiAuctionBalanceEscape | 9369 | 9236 |
| FailedSessionAcceptance | 3083 | 3438 |
| BipowerJumpContinuation | 5167 | 5558 |
| SemivarianceRecovery | 4202 | 4754 |
| ValueOccupationMigration | 5416 | 5656 |
| DisplacementGapDefense | 9511 | 9999 |
| DisplacementOriginDefense | 1562 | 1648 |
| ContinuousVarianceRelease | 5795 | 5348 |

Java已嵌入冻结模型，新增7项模型/规则测试，连同事件CLI及其他研究共58项Java测试通过；工作流46项Python测试通过。验证原结构入场及风险目标逐项不变、模型只能过滤原事件、无效/零预测不回退、全部Python/Java预测一致、窗口及未来访问、全目录注册。研究本地提交`5a0c66e`，远端独立分支`codex/local-structural-meta-strategies-20261110`提交`d4610717e35d837691ba9f8fa84436ab456906a8`，核心Java blob与本地提交已核对。

北京时间15:07:23以15704启动cohort `structural_meta_v1`，目录`E:\sourcecode\codex\_work\strategy-structural-meta-cycle-20261110`。顺序为20个代表源码校验→1,000项预筛→正式/留出→仅合格固定源码上传→服务器365天复核和真实库存审计。所有条件未满足前仍不能计入100条目标，当前缺口仍按96记录。
