# 本地准入 V2：时间隔离与锁定参数

21:07接续：[真实ADX修复及固定源v2批次](true-adx-repair-research-20261110.zh-CN.md)。旧245/接续器完整结束，5条严格留出全部失败，21108/9876已退出。新ADX修复完成独立指标/信号工程证明，8676继续200项固定源研究；三个正在跑的任务以新文档和实时状态为准。生产20:36收尾仍4/缺96，没有新增发布，100条目标未完成。

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

## 每折选参和验证窗口对照已完成

`verify_fit_validation_replay.py` 使用BTC 2023全年35040根训练行情，比较3个代表源×3套正式窗口配置，共9项；工程场景夹具轮换目标场景/不交易，明确不得用于金融资格。`FitOnlyValidationReplayCli` 反射调用现有SliceOptimizedWalkForwardRunner的buildSlices、selectBestParamForSlice、runWindow、mergeValidatePhase和代表参数方法，保留真实成本/复利/经济性过滤。每折严格执行4次fit、1次validate；WindowGuard在进入引擎前拒绝forward或全期执行。

完整不改的v4作为训练期参考，9项均逐折参数、fit分数、验证收益、逐笔验证交易/费用/退出字段、PF、回撤、拒绝原因及代表参数一致。3族分别为TrendPullback、RsiAtrEnvelopeReentryLong、SceneControlledBreakout；trend/range/breakout窗口的折数分别5/6/8，验证交易分别138/148/127、23/19/22、77/87/84。另把2023-05-01起所有OHLC乘1.2，保留此前120天以及所有时间/成交量不动，每个用例的首折四档fit试验分数和选择均不改变。没有读取新留出绩效。

证据：`strategy-fit-validation-replay-oracle-20261110/audit.json`，9/9 complete；manifest SHA256=`5b29252b6355097ae408dddef3ca0cc02f89d3b3c39339ce03253db7ee551399`。真实执行类字节码、助手源、配置均绑定；后续改动必须重新做工程证明，不能覆盖已经消费的金融记录。

## 新参数方案财务筛选已开始

`verify_fit_risk_catalog.py` 正在为全部400方向编译冻结源、调用原源码validator，并在2023训练行情逐根比较4档信号的全部风险字段。每个方向单独制品目录，可并行2项，只有主线程写总账。不要求稀有规则在这一个品种年份一定有信号；零信号必须明确标注，不能当作有交易覆盖的参数证明。源码数量/参数档数不是独立策略或资格数量。

`run_fit_risk_admission.py` 只允许源/JAR与四档训练证明完全匹配的固定候选进入新流程，先跑真正的fit+validate并隐藏forward/full-period，再检查原有必要验证门槛（20笔、PF1.2、DD0.15、扣费验证>0）。通过后用`FitOnlyPrimaryReplayCli`直接执行完整原v4、调用原LocalBacktestCli私有qualificationReason；还要求其验证交易、指标和代表参数与预筛完全相同。仅原主期门槛全通过才调用独立62天留出，参数锁定为主期代表档，0次拟合。没有SSH、数据库写入、自动发布或模型调用入口。每个金融尝试强制新证据目录；失败及STARTED标记保留，不允许当参数搜索重跑。

首个真实结果：`strategy-fit-risk-admission-pilot-20261110-long`，BTC/trend、`fr1_trend_pullback_long_s15_t30`，67笔、PF0.694573、DD0.035195、扣费验证-1231.814573，代表riskProfile=3。必要验证门槛失败，未执行forward/full-period或62天留出，不上传/发布，不因其表现修改同源政策。

当前仍未完成：全部400方向工程检查、新政策跨品种/场景筛选、合格源的独立机制复核、服务器365天验证和发布后实盘参数持久化审计。不能把离线工程对照当作生产上线完成。旧245项截至19:31为180/245，旧协议通过1，但新增完全分离留出通过0。生产库存最近服务器审计仍为4、缺96，本轮没有新增上线。

## 19:39继续：跨品种/场景固定研究队列

BTC趋势回调空头亦未过必要验证门槛，扣费验证-976.880222，证据`strategy-fit-risk-admission-pilot-20261110-short`；没有执行其前瞻或新留出，不修改该政策以重测。

`prepare_fit_risk_scope_contract.py` 对每个明确品种/场景重新导出相应源，仍调用原validator、真实源编译、该品种2023全年35040根行情四档信号逐字段对照，所有源和训练行情/字节码核对哈希；不使用人工工程场景作为金融数据。ETH/range的首个跨品种源`catalog_ethusdt_range_b0b0117f812c`已完成4档证明（`strategy-fit-risk-scope-pilot-20261110-eth-range`），尚无该源金融结果。

`run_fit_risk_scope_batch.py` 已冻结并启动10品种×5场景×先前工程阶段固定8族的400项队列，cell内固定族顺序，无依据新金融成绩挑族、调参数；该8族可在第一阶段manifest中追溯。它们是400个作用域候选、8种待经济独立性复核的逻辑族，不是400个独立合格策略。与另一个“400方向源码工程检查”是不同计数维度，绝不能相加作为合格数。

队列目录`strategy-fit-risk-balanced-scope-20261110`；后台编排PID4332，日志`strategy-fit-risk-balanced-scope-launch-20261110`。每项先有四档训练合同，再跑validation-only；主期未过则不调用新留出。若出现异常/半完成金融标记，整批停止并保留证据，禁止自动覆盖重试。已经完成的BTC多头失败通过原manifest和结果哈希复用，不重复看前瞻。该编排完全本地，无发布/模型接口；合格项必须由后续审阅阶段处理，不能放任数量触发实盘。

源码工程检查PID7012，截至19:37完成38/400；原旧协议研究PID21108完成188/245。115项Python测试全通过，9组训练期实际选参/交易对照已通过，Java CLI编译通过。记录的运行PID和计数只代表这个时间点；换会话必须先核对进程、status.json与FAILED标记，不推断进程仍存活，不重跑已消费金融失败。生产最新已核实库存仍是18:10审计的ACTIVE4/runtime-qualified4（仅2条同时达到单项前瞻贡献门槛），缺96；没有新策略上线。

## 19:57 接续：三条新补充留出均失败，核清未注册版本

原冻结245项又出现三条旧协议通过者，均使用原始完全固定源、显式锁定空参数，仅做新2025-10-13～12-13的62天重放；原主期未重跑、原额外留出未重跑、源参数未改。三条均未通过：

| SOL/range固定源 | 新留出笔数 | PF | 扣费留出PnL |
| --- | ---: | ---: | ---: |
| `catalog_solusdt_range_383b0b4a3d9c`，MedianMAD确认 | 40 | 0.429943 | -2316.37308183 |
| `catalog_solusdt_range_1dde52f3736a`，MedianMAD重入 | 26 | 0.359133 | -1766.99284415 |
| `catalog_solusdt_range_1378d9afcc2a`，Hull趋势回调 | 31 | 0.489147 | -1407.57391336 |

分别保存到`strategy-temporal-supplement-sol-median-mad-20261110`、`strategy-temporal-supplement-sol-median-mad-reentry-20261110`、`strategy-temporal-supplement-sol-hull-pullback-20261110`。以上是初始10000模型单位的回测，不是新增实盘损失。两个MedianMAD变体在原17:50冻结清单中均已存在，重入变体的主回测在第一次SOL新留出前已结束；Hull源亦早已冻结，由未改动的旧批次独立产生原主期结果，没有依据新留出改阈值。两个MedianMAD仍应按同一位移回归机制保守去重，不能因触发阈值和类名不同就当作独立机制。连同此前ETH Aroon，4条旧通过源的新分离留出全部失败，0导入/0发布。

19:49:01北京时间经126已知host key只读复核，`strategy-live-inventory-20261110-1949/summary.json`：ACTIVE=4、当前运行资格=4、另过前瞻贡献单项=2，缺96。未注册但满足部分历史门槛的版本行8条，其中前瞻贡献通过3条；不是8个或3个新策略。

后3条均为`research_r33_uni_median_true_range_edge_fade_short`的v3/v6/v7。读取准确`java_source_path`并在运行容器内核验SHA，再只规范化package版本声明，证明v3/v5/v6/v7其余源码逐字相同：规范化SHA256=`b1e9d1141b211d166d91f5a69d30d8dfdd03e27f40c9d645f50314d271c9eeb0`，logicFingerprint均`282d6469b28dd8b4ed04a0f44f60ac33b709a2c3c93808a39adf307fdfe7ee3f`。源码副本及完整JSON保存在私有`strategy-unregistered-uni-audit-20261110`，不提交公开库。

真实SUCCESS终态的原发布决定：v3 `validate score not better than active baseline`，v6/v7 `forward_score not better than active baseline`；不是“服务器漏发”。曾发布的v5在2026-11-10新复核（2025-11-09～2026-11-09）43笔、PF1.73191，但扣费前瞻-346.40719、OOS=0，已是OFFLINE。不得拿同源旧窗口的v3/v6/v7较好成绩恢复、凑数或绕过原基线比较。没有修改实盘注册行、交易/仓位/风控或触发新的服务端代码生成。

读取带中文任务payload的私有证据要明确UTF-8；Windows PowerShell默认编码会让ConvertFrom-Json报假性的坏JSON，Python UTF-8解析验证原件正常。不要因此重写原始任务或金融文件。

19:56快照：旧批次205/245，旧通过4、新分离通过0；平衡队列15/400、新通过0；源码工程检查至少84/400。三个主进程已重新确认存活，后续依真实状态继续，不重复失败窗口。目标仍未完成。

## 20:05 接续：本地补充留出自动接续器

新增`recovery/watch_fixed_primary_supplements.py`只跟随经实际进程身份验证的原父任务：绑定PID、创建时间、完整module命令及准确output目录，防止PID复用；不是只看lock或status文件。父任务写status后再写results，接续器须读到前后status字节相同、结果数和资格数一致的完整账本才处理。父任务错误、半完成留出、已完成观察被改/丢弃、源/主信封/输入/助手哈希错配都停下并写FAILED，不覆盖重试。

每条旧主期通过记录都调用既有`supplement_temporal_holdout`固定源路径，保持主期不重跑、新62天0拟合；已有4条失败仅核验原结果并复用。该工具没有SSH凭据、导入、生成或发布调用；主流程完成后仅形成WATCH_COMPLETE，本地新通过者仍须人工源码机制复核和正常服务器365天门槛，不会自动上线。

20:04:56启动PID9876，输出`strategy-fixed-primary-supplement-watch-20261110`，启动日志`strategy-fixed-primary-supplement-watch-launch-20261110`。实际日志已确认4/4旧失败均`reused=True`，没有重跑；初始父进度213/245、严格新资格0，仍在跟随。它的聚合results和frozen种子可供之后机制复核/发布准备读取，但绝不能把legacy_passes_seen当成新合格。

4项新保护测试通过，全套Python合计119项通过。该可选本地工具依赖已验证的psutil7.2.1/paramiko4.0.0（Python3.14），在独立研究环境可用`python -m pip install -r recovery/requirements-watch.txt`准备；本次使用本机已有依赖，没有安装/修改服务器。不要用Windows的`os.kill(pid, 0)`探测进程，也不要因为日志短暂无更新而重启原任务。

20:05其余研究仍运行：400方向训练工程112/400、跨单元金融22/400/0新合格、原固定源213/245/4旧通过。换会话先检查9876及原3个PID的真实进程和全部FAILED/状态文件；若进程已结束按终态诊断，不盲目再启动接续器或重跑已看窗口。生产最近只读核验仍4/缺96，目标继续进行。

20:12真实接续验证：接续器自动发现第五条旧通过固定源`catalog_uniusdt_range_d8e5c59e79f8`（UNI/range、`cx1_scene_close_break_short_s8_t15`），保留源SHA256=`f191e50e27b5606635733cbb23027fc2b5cfff0c795fa807992c8aa21c5d937b`，主信封SHA256=`86b4de14ed2b7830e952a99b28097b667313d9df93883546c373394abdcc9511`。新留出26笔、PF1.126816、DD0.032362、扣费-100.45605921，仍失败；fit/optimizer均0、主期未重跑、0生产写入。证据在接续器目录`candidates/catalog_uniusdt_range_d8e5c59e79f8`，不是仅靠测试宣布自动接续成功。

该观察已消费，不能调整同源止盈/止损或换名改善此留出。接续器仅在本次已绑定执行内防重复；跨新输出目录续接必须显式复用已有结果，不能省略旧结果重新回测，也没有宣称全局跨所有手工脚本的互斥锁已实现。20:12父研究219/245/5旧通过，严格新通过0；平衡研究26/400/0通过，训练源码132/400。四个实际进程均已核实存活，未变更生产库存或放宽门槛。
