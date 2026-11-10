# 真实 ADX 修复与固定源研究（2026-11-10）

仅既有OHLCV/历史场景，不增加资金费率或OI，不改服务架构，不调用DeepSeek生成/修复。目标仍是100条真正生产合格且不重复的策略；工程数和候选数不是合格数，也没有盈利保证。

## 原问题及固定规则

原418源目录中AdxDirectionalBreakout/SelectiveAdxBreakout的4方向，在进入财务之前被原SourceValidator拒绝：以14根DM/TR简单和计算DI，再把`abs(+DI--DI)`差值作为强度，并未计算ADX。本批不改名躲校验，另实现实际归一化DX及多期Wilder递推平均；旧失败/历史代码保留。

参考固定版本[ta4j 0.15 ADXIndicator](https://raw.githubusercontent.com/ta4j/ta4j/0.15/ta4j-core/src/main/java/org/ta4j/core/indicators/adx/ADXIndicator.java)、[PlusDIIndicator](https://raw.githubusercontent.com/ta4j/ta4j/0.15/ta4j-core/src/main/java/org/ta4j/core/indicators/adx/PlusDIIndicator.java)、[MMAIndicator](https://raw.githubusercontent.com/ta4j/ta4j/0.15/ta4j-core/src/main/java/org/ta4j/core/indicators/MMAIndicator.java)。生成源按原校验要求手写计算，仅独立测试调用真实库指标。限定当前可见最多200根重新播种/递推，不声称等同无限历史缓存ADX；数值对照使用同一可见窗口。零TR/零方向分母单独定义为中性、不生成交易，不把库可能的NaN说成数值一致。

规则在金融前固定：ADX14、额外ADX门槛20（新固定趋势条件，不是DI差值8/12的等价换算）；保留DI差值8/12、前24/48根收盘突破，精选版50/150均线斜率及20根成交量1.2倍条件。风险保持算术ATR14止损1.5倍/止盈3倍、原显式ATR20退出、firstStep最低0.5%。无参数网格；方向/精选开关形成4个固定源。

4方向预先保守归为同一`wilder_adx_directional_breakout`机制组，同单元最多一条按此组推进，不能按版本/指标公式/方向冒充新独立机制。还须比较当前ACTIVE同单元真实源码，不能仅因已有方向突破换成真实ADX就另算一条。发布工具新增校验：记录已声明的机制组，审核不能改为别的ID凑数；原财务、场景、基线和服务器门槛不变。

## 工程证明与源码

工作树`indsvr-local-true-adx-repair-20261110`，本地`365c458`；远端研究分支`codex/local-true-adx-repair-20261110`，revision `03ecd6c9814c95f62ce04195ebe14d8371660bf1`。只改研究代码/目录登记，无服务运行时/镜像/Maven发布；已确认工作流仅latest推送触发镜像，研究分支不部署生产。

- 8项ADX测试通过：真实参考数值（趋势/反向/震荡、7/14/28周期和前缀）、200根淘汰、非DI差值/单个DX、未来追加不改历史、四方向突破和全部风险字段、原源码校验、零幅度与热身/量保护。
- 4份BTC/trend源均通过原校验、独立编译及2023全年35040根实际运行时逐根对照，侧向/价格/止盈损/四退出字段及身份零差异；基础多661、基础空537、精选多283、精选空164次信号。这不是成交/收益证明。
- 新`true_adx_repair_v1`登记进公共`all`目录，目录/适配测试通过；金融用专用自包含导出器，不用通用旧导出器提取适配器依赖。完整研究模块100项Java回归、工具126项Python通过，均非实盘策略数量。

工程目录`strategy-true-adx-repair-engineering-20261110`，manifest SHA256=`7d1d085ceadd88a000244117b7ae37d699fdb97a1123c94a02ded381ba1407ab`；完整研究回归日志`strategy-true-adx-canonical-catalog-20261110/full-research-regression.log`。PowerShell的-D启动参数和原校验要求的显式minBars/方向风险保护均在金融前修复，未改校验器或据金融表现调数值。

## 原 v4/分离留出与续接

`strategy_research_true_adx_protocol_20261110.json`：主期2024-12-15～2025-10-12，至少3个原v4完整窗口；独立留出2025-10-13～12-13，完整62日。静态规则由同源代码绑定，schema/defaultParams为空，代表参数显式锁`{}`；留出0拟合/优化。已见历史行情/其他政策，不能声称是前瞻实盘或多重研究后的统计独立证据。

`prepare_fixed_protocol_view.py`创建`strategy-true-adx-temporal-input-20261110`，只复制已验证原行情/场景字节、更新本协议READY，逐文件SHA相同；父输入和两个在跑的400批次不改。

`run_true_adx_batch.py`冻结10品种×5场景×4方向共200作用域。PID8676于20:50:26启动，目录`strategy-true-adx-formal-20261110`，日志`strategy-true-adx-formal-launch-20261110`。每项先核对同源制品/该品种2023训练信号（零信号须如实标记为未覆盖，不当资格通过），再由`FixedSourcePrimaryReplayCli`直接调用原SliceOptimizedWalkForwardRunner/LocalBacktestCli资格方法，不重写成交/成本，只允许一个空参数集。主期通过才运行原已验证OfflineTemporalReplayCli的新62日留出。原始主期引擎结果先落盘，所有失败保留。

源/JAR/seed、市场、场景、协议、助手、引擎/配置/工程证明绑定；复用已完case须验证全部哈希。半完成case停止诊断，不覆盖重跑；8676仍活着时绝不能重复启动。该程序无SSH、模型、导入或发布调用。本地全过后仍要机制复核→固定源码导入→服务器最近完整365天→原发布器，不能直接写实盘表。

21:07快照24/200、0新合格/0发布/0错误，其余继续。源码及规则已消费金融结果，不能调参重试旧窗口。目标没有完成。

### 21:22首条主期通过者的隔离留出拒绝

批次已至少47/200，0新增全门槛合格。`catalog_bnbusdt_range_9f1c75a667dd`（基础ADX突破多、BNBUSDT/range）原v4主期通过：34笔、PF1.536316、DD0.023111、OOS=1、扣费验证245.376049、扣费前瞻97.509290。随后同源固定空参数`{}`执行2025-10-13～12-13留出，25笔、PF0.561118、DD0.098052、扣费Pnl=-844.71411228，`passed=false`、fit/optimizerInvocations均0。最终`separate_chronological_holdout_failed`，不得把主期通过当作新增策略，未上传/发布，不重调这条源后重测同一留出。

证据目录`strategy-true-adx-formal-20261110/candidates/catalog_bnbusdt_range_9f1c75a667dd`；批次manifest SHA256=`965ed4ecd8f30ccbc0bab5681e78e67ac8780f1ae75eb8f54cc62bb00fe7f5e7`。源码SHA256=`af105d9d2d4e9cf265dc3a1528b5bd86c8d2397990bbc364c258f84df1b51f7c`；`primary.json`=`28c6423eb0459b22ff4de287b0ce08a144c0fcfb4b60e6fd29cf76c05c4902ee`，`holdout.json`=`9b810457804d54663016256cfee0c61f34c1e55c8026a7097760634ad277bffd`，`local-pre-admission.json`=`3c56b477000987cc1cf8f7b11d61374d27bbdbd9a5ec887518d9a5306f934815`。检查点保存上述哈希，续接只校验复用，不重跑已消费观察。

用户本次明确回复仍为仅现有OHLCV、不改服务架构；不采集资金费率/OI、不调用服务端生成。对应实现/协议已推送dc-quant-deploy latest `7099e700f3fef193907b26c79127bcd48b424cb7`，远端ref已只读核实。

### 21:27状态文件故障与仅训练工程续接

21:24核查发现7012已退出，并非仍在运行：21:20:43写入第330项`status.json.tmp`替换`status.json`时WinError5。此前PowerShell读取/输出大状态文件与故障时间重合，判定为文件共享冲突的可能原因，不当作策略或源码校验失败。对330份独立`contract.json`逐一重新校验原manifest、唯一hypothesis、源码/JAR哈希和四档信号：1320档全部零差异、全部非零信号；wrapper/exporter哈希未变，未执行金融回放。

故障标记和临时状态分别保留为`FAILED-20261110-212043.json`及`status-at-failure-330.json`，没有删除或覆盖证据。确认原7012及同module进程均不在后，以完全相同源码、参数、目录和manifest续接，PID22576于21:27:50启动，日志`strategy-fit-risk-catalog-contract-resume-20261110-2127`。原330检查点仅核对复用，继续剩余训练源码检查，不是新金融尝试。Windows实际测试显示仅给读取句柄设置FILE_SHARE_DELETE仍不足以保证本机os.replace目标成功，因此未采用未经验证的“共享读取修复”；该试验代码已撤除，公共原子写入器和在跑金融脚本均未改。续跑期间不再读取/打印大型live status，以静态已完成contract计数观察；完成后才读总状态。

21:27金融状态为ADX61/200、平衡风险97/400，均0新增全门槛合格、0发布；进程8676/4332继续。服务器最近实测仍20:36的4条运行资格，缺96；不把330份工程检查当成金融通过数量。

## 旧批次完整收尾及另两线

旧245项已结束：186 OOS、18 PF、15扣费前瞻、16前瞻贡献、4旧额外留出、1扣费验证未过，5旧通过；5条全分离留出均失败。21108/9876已退出，父FORMAL_COMPLETE、WATCH_COMPLETE、cycle_complete一致，不再报告在跑。20:36:38收尾服务器只读核实ACTIVE/运行资格仍4，另过前瞻贡献单项2，缺96，0新增发布。

四档风险前33项另只读核对：30有成交、14少于20笔、29 PF<1.2、2 DD>0.15、29扣费验证非正（可重叠）；四档均被选中过，每折4fit/1validate，未执行forward/full-period/独立留出。证据`strategy-fit-risk-progress-audit-20261110-2020.json`；不把33项部分市场结论推广全部或据此调冻结参数。

21:07另两进程仍活：7012工程292/400，4332平衡金融73/400/0新合格。各阶段数量不能相加当实盘库存；新会话先核实实际进程及status/FAILED/终态标记再继续，不因旧PID或短暂无日志重启。
