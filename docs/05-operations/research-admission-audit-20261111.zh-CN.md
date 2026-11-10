# 研究准入复核：严格贡献门槛与固定策略参数衔接

2026-11-11接续；仍只OHLCV、固定源码、本地正式及分离留出、服务器正常编译/回测/发布。不使用DeepSeek，不放宽金融资格，不重放已消费窗口。以下既有实际财务观察与人工软件诊断严格分开，不能相加当作新增策略。

## 新LINK原始通过，不符合严格发布前准入

完整目录出现`catalog_linkusdt_trend_c76c02a485c8`，假设`fr1_trend_rsi_pullback_long_s15_t30`，族`FitOnlyRiskTrendRsiPullbackHypothesis`，源SHA `569e9d3f93d312a4aaf402c448ddf6de2034aae9ec22bf5da27ede7ae2ec1ddb`。

原主期47笔/PF1.491248/回撤0.04698/OOS1，扣费验证803.019875、扣费前向200.958939、totalPnL1228.868244。原runner结果DTO的minForwardContribution仍为默认0；原标记qualified=true不等于严格资格。

按原20%底线及6位HALF_UP计算，200.958939 / 1228.868244 = **0.163532**，严格拒绝`forward_contribution_too_low`。分离留出虽有13笔/PF1.742732/扣费333.9879073，也不能覆盖主期门槛失败。原模态riskProfile3，留出锁3且fit/optimizer均0；不换档、版本或日期重试。

再次调用原`verified_observation`及9例FIT proof只读校验了完成marker、合同、源/JAR、种子、金融输出和原规则，严格判定一致。窗口已消费，0服务器提交/发布。原证据`strategy-fit-risk-full-catalog-20261110/admissions/catalog_linkusdt_trend_c76c02a485c8`；公开脱敏指标/精确哈希在`recovery/snapshots/fit-risk-strict-rejection-link-20261111.json`，只作为历史准入观察，绝不成为新训练或调参样本。

对应回归`test_consumed_strict_observation.py`只调用纯资格算术，不执行任何金融回放；确认“主期原始通过+留出盈利”不能绕过既有贡献门槛。Python完整191项通过。完整目录当前raw2/strict1，严格通过的仍只有已服务器失败的ADA/channel，不能把第二个raw计作新增合格。

## 无参数固定策略发布衔接：已观察，未修改发布器

检查本地冻结实际`StrategyAutoPublishService`和公开SIMSvr latest源码，发现固定参数政策的识别不一致：优化计划允许无维度、不要求优化证据，默认参数集是`[{}]`；后面的发布阈值方法却不区分策略类型，直接将bestParamSetJson=`{}`判为`best param set missing`。

公开源固定到`SKT-Walter/com.app.dc.simulation` revision `1e16598c04f052c4b93832c6f88a2472a0a48c07`，该条件与检查时latest相同。这不是对126当前容器JAR逐字节审计，不能由此断言现有4个ACTIVE都因本问题没有信号；此前几个新候选实际先在金融/场景门槛失败，仍维持原结论。

`FixedPolicyPublicationGateProbe.java`只调用未改实际类的优化计划和私有资格判断，使用人工构造的摘要，没有行情、回测、模型、DAO、publish方法、registry或网络调用。该控制试验不是一条真实盈利策略：

| 人工控制 | 原类实际结果 |
| --- | --- |
| 明确空schema/defaults | optimizationSupported=false；defaultParamSets=[{}]；expectsOptimizationEvidence=false |
| 全局原前提与足够场景/样本 | 全局判断空拒绝原因 |
| 所有金融摘要门槛人工满足，bestParams={} | best param set missing |
| 只将参数文本换为非空对照 | 阈值判断空拒绝原因；仅诊断对照，**绝不作为添加无用参数的方案** |
| 扣费前向为负 | fee adjusted forward pnl <= 0 |
| OOS失败 | oos gate not passed |
| 前向贡献不足 | forward contribution below threshold |
| 场景失败 | 原场景拒绝原因 |

真实执行完成目录`strategy-fixed-policy-publication-gate-probe-20261111`：

- manifest `10dc9c8111e10c75a5868c623d752b1d9f6a3f10e712cef0dc91bb111d80c060`。
- observation `ea549ee820e0f675912d0372c40c98fd5dc4efc63f747ea3d6e2b93bde398e8f`。
- 完成marker `4c4298f05db38fd2176bb33601485419bae4255e1bc51cdde50b905027895be9`。
- 探针源 `36b6dbd40a4318e126899abbc810820f1b36846d3d1975b87169d33c343176b6`。
- 原发布器class `08abf8b6df9757351c7659f3b4fefd920d83fb9c84cae2fdb049f426800ed344`，原优化器class `9bd8a9561f6af4618b9218f622815f9d9e755800c2704e7151658823ba387c9c`，运行前后SHA相同。

代码/复现入口`recovery/verify_fixed_policy_publication_gate.py`。只编译探针到新的私有输出目录，没有重编/覆盖冻结SIM/IND类或编辑生产代码、镜像、配置、风险及持仓。未对任何旧失败进行金融重放。

## 修复边界与当前接续

已向用户单独发出非阻塞确认：是否允许仅修复明确无参数固定策略的格式识别，原场景、样本、费用、OOS、20%或更高贡献及基线门槛全部保留、不改架构。在确认前不修改发布器，不加无用参数绕过，也不把软件诊断当生产资格。

若获准，必须在新的服务工作树修复并测试：只对明确、可验证的固定策略接受空map；可调策略缺参、缺失/畸形声明仍拒绝；合法固定源也必须经过所有原金融/全周期安全/场景/基线门槛。先核对126实际revision/产物，再沿正式构建/发布流程，不能替换在跑研究执行器。格式修复不挽回先前真实金融失败，旧失败源及窗口不重新导入或回测。

其它研究不因该确认停下。02:15实际验证4332仍389/400/原标记2，24052仍461/19,599/raw2/strict1/errors空，20660仍等待绑定4332真正完成400，27328仍等待20660真正完成200。下一步优先等原平衡批次终态、逐项只读审计原观察，并核验OHLCV代理自然接续；不得凭PID消失或旧status启动另一份进程。

## 02:27完成复核与实际接续（优先于上段历史状态）

原平衡4332在02:24:50最后记录400/400后自然退出；BATCH_COMPLETE真实400且无FAILED。逐条只读核验全部400份原admission：完成marker/原金融输出、源、JAR、合同和seed都匹配，1600份档位信号合同均为2023全年35040根/0差异，原9例真实FIT proof/正式类及4份冻结工具源码SHA也未变。唯一早期pilot观察复用1条，没有重跑。

首轮审计按“目前第一个存在的同名合同目录”取路径，在BTC短方向0c99306e8817被原合同SHA正确拦截；当时原观察使用单独准备的合同，后来完整400源码任务才产生同名全局合同。原admission绑定`3dc277ad80ad711bc1a864c98fb355a3368447915de9013c675af86ce896ed04`仍完整存在，不是金融结果损坏。改为按原manifest中的contract_sha256定位实际历史合同，再做全400只读校验，通过；只修审计路径选择，没有改预期SHA、合同、原文件或重做金融回放。

最终原因计数：必要验证门槛366、OOS19、分离留出6、扣费前向7、本地严格通过2，总计400。通过的仍是LINK均线回调及UNI趋势突破，已分别服务器失败，0新增发布。400是作用域观察数，不是400条独立合格策略。

完整脱敏审计摘要在`recovery/snapshots/balanced-fit-risk-completion-audit-20261111.json`：原完成marker SHA `ca23c7b181bcd8ab6a3a9564d0e681b7097d083e0b15ab27a2a8f015a6deb4b0`，终态results `fb1102739292c2b468780783c15950055fbe3c7f7159f60c98aac969e0d7f3bd`；全部原case marker/manifest/results的按名称排序摘要SHA `19439aabd2ba956583242b580200131782a085db1abc0f1697d6874484a6a68d`。

原20660没有重启，确认相同创建时间/module和原manifest后，真实产生helper编译类、source-contract、PRIMARY_STARTED及实际v4 Java子进程。第一条ADA/trend `catalog_adausdt_trend_9ac8633a998b`在18:26:19UTC完成，checkpoint再经原completed_case复核：7笔、PF0.14735、扣费验证-501.364361、前向-43.810772、OOS0，严格审计拒绝，**没有HOLDOUT_STARTED**。不是状态标签空转，也不会用这个已失败窗口去调分箱阈值。

- 该源SHA `19837d5b464d43ddb1ced08c1a9c036f035cd33bde966106e88462dc9cc97b6a`；checkpoint `0917c88e2e770a32b4ad682c65273fe624b37cf0489d4c7b9d58b7efcc74c551`。
- primary `e412ddc526f371dc84bdaf9ef97d3d532cbf75f9ad5888b1117aaefde02e7cf0`，原engine输出 `94f814584434568725fb33c96846894716eede0b10bb57c92198b99eb0bef249`。
- strict审计 `8669f2e8a06bb2660afe0802b0c143d932ccde22a3a6a79aae789486a737f42f`，原0.20底线在留出前有效。

OHLCV金融目录仍`strategy-ohlcv-profile-formal-20261111`、原日志`strategy-ohlcv-profile-formal-launch-20261111`，继续同一20660，不因开头旧WAITING标签重复启动。完整目录24052已486/19,599/raw2/strict1/errors空，原27328仍等待该OHLCV批次真正200完成。原4332已终态，不能再启动；旧12040仍是历史已交接进程。

公开保存未改探针的原始人工摘要观察`recovery/snapshots/fixed-policy-publication-gate-observation-20261111.json`，与私有原observation逐字节同SHA ea549ee8...。原实际Windows报告为CRLF，因此该单份证据限定`-text`禁用Git换行转换，不为了规范格式而改变原字节；新写的拒绝摘要单独限定LF。除了工作树测试，还核对Git入库blob原字节，避免本机测试通过而克隆后的证据SHA变化。新增“软件诊断不等于财务/发布”回归后Python完整192项通过。固定策略格式修复依然待用户确认，生产和在跑执行器没有改。
