# 影线反转语义修复：隔离源码与正式研究

仍只用现有OHLCV及已存历史场景，不改服务架构、不调用DeepSeek或服务端生成/修复。工程数、信号数、方向数和作用域数不是实盘合格数量；100条目标尚未完成，没有盈利保证。

## 由训练零信号定位缺陷，不是根据金融收益调参

原400方向/1600档训练检查全部完成，但SceneWickReversal多/空各四档在BTC 2023全年没有信号。对合法OHLC有lowerWick≤close-low、upperWick≤high-close；旧多头同时要求下影≥45%和收盘位置≤45%，旧空头同时要求上影≥45%和收盘位置≥55%，因此退化为等式边界及浮点极小邻域。只检查训练和源码几何，没有读取这两条规则的金融绩效来修改参数。

修复在全新`indsvr-local-wick-geometry-repair-20261110`树，不改任何旧400合同/三个在跑金融批次的源。事先固定解释为“拒绝低点后收在上半部，再由下一根已完成K线突破确认”，多头下影≥45%、收盘位置≥55%、下一收盘严格高于前高；空头镜像上影≥45%、收盘位置≤45%、下一收盘严格低于前低。这是明确的新修复假设，不是数学上唯一的盈利规则，也不是从收益搜索出的阈值。

核对真实构造函数后保留ATR14止损0.75、止盈1.5，不能按舍入名称`s8_t15`误写成0.8；保留64根热身、200根实际窗口、ATR20动态EMS退出（first=max(0.5,2×相对ATR百分比)，step=0.5×相对ATR百分比，另两退出first±step）。固定源码无参数网格，代表参数显式锁`{}`，不采用新风险搜索或留出重拟合。

两方向及旧影线版本都按`wick_rejection_confirmation`同一保守机制组审阅，不能换类名/方向/风险版本凑数量。只有同源机制审核、本地及服务器全部资格和原发布器真正通过，才计新增实盘。

## 先解决精确边界，再进入任何金融

首工程目录`strategy-wick-geometry-engineering-20261110`：8项测试/原validator通过，但BTC 2023全年多头独立原始OHLC参考2103次、生成源2102次，有1处不一致，原FAILED/源码/JAR/日志全部保留。例为2023-04-02 22:30前根O27943.60/H27975.50/L27917.50/C27953.60，下影26.10恰等于58×45%；二进制减法得到略小值，价格级相加比较则含边界。没有进行金融测试。

修复只明确原先已声明的含等号十进制报价边界：生成源用BigDecimal精确百分比乘法，独立原始OHLC参考用20倍/9倍/11倍整数交叉乘法，无epsilon；ATR/成本/风险数值不改。新增边界及镜像回归测试后，在新目录`strategy-wick-geometry-engineering-v2-20261110`完整重做工程，不覆盖首失败。

9项几何/原validator/因果性测试全部通过：旧等式退化网格、双向正常拒绝、严格下一根确认、错误收盘/不足影线拒绝、镜像及真实0.75倍风险、十进制边界、未来追加不改历史、200根淘汰、热身/零幅。两份源通过未改validator和独立编译，对BTC 2023全年35040根逐条对照侧向、身份、价格及全部退出字段：多2103、空1808，零差异；同窗原规则两方向均0。这不是交易盈利证明。

工程manifest SHA256=`d678d41542f1e93f09dc4e5bc9afc2e7d8d9dc27ae70c6ac66c6be85f6b59c22`。BTC/trend多源SHA256=`7165d36a5ac0aebbb073477d418cf0b0ffa5c9fc32312edbc19e7e5db74290c1`、JAR=`70d21274850235f81ceca54f023bb82056daaed4155cea4743a4ad4435cde192`；空源=`783a78b067c2cb669d693488081e00778b0a9c8d147b9d25e3a5cfc8fcf34f25`、JAR=`23af0d61ffd138643174b34b4d0b06a3456214a04437ff0240e8209407557b0f`。

## 目录登记、回归与代码

独立`wick_geometry_repair_v1`及公共`all`均登记新两方向，旧cohort原样保留；专用自包含导出器不提取目录适配器依赖。新目录适配器逐项保留全部七个价格/退出值。完整Java研究回归111项通过，日志`strategy-wick-geometry-canonical-catalog-20261110/full-research-regression-v2.log`；Python工具141项通过，包含100作用域唯一性、同机制保守计数、半完成拒绝、主期失败不进入留出、旧失败校验复用不重放及机制ID不可篡改。

Java回归启动时的两个工程诊断保留：PowerShell ErrorActionPreference=Stop把javac普通stderr警告当作NativeCommandError；改为按真实returncode捕获后编译成功，随后补齐旧ADX测试类所在classpath，再完整执行111项。均未修改测试门槛/既有业务代码或金融记录。

IND本地提交`6343ae2`，研究分支`codex/local-wick-geometry-repair-20261110`远端revision=`d537bc3bf1e1c5ae38f806d3ee0b41e55eb402c4`、tree=`b9b97d382df8540af8f86d83aab9d95c12e8af7c`，6个blob均与本地Git逐项核对。确认该repo仅latest推送触发镜像，本研究分支不部署生产；没有修改POM、运行时服务或共享包。

## 固定源100作用域正式批次已实际启动

`strategy_research_wick_geometry_protocol_20261110.json`在金融前冻结主期2024-12-15～2025-10-12、至少3个原v4窗口；全分离留出2025-10-13～12-13完整62天、参数`{}`、0留出拟合/优化。协议SHA256=`ca6cee598617e11c147ed5064e0911d3571f338fbc52d409fed7ec70e933c529`。已见历史行情/其他政策结果，不宣称多重研究后的统计独立或前瞻盈利。

`prepare_fixed_protocol_view`只复制原已验证行情/场景字节到`strategy-wick-geometry-temporal-input-20261110`，逐文件SHA完全相同，旧输入不改；新READY SHA256=`49b77b83cc7d23779174ea17213cabcbfe12fa2b9c7e1044e5e38aaef0452786`。

`run_wick_geometry_batch.py`固定10品种×5场景×2方向共100作用域（只有一个机制组），严格检查9例真实fit/validate及12例实际锁参重放证明、原validator/reference字节码、工程3源/JAR/编译类、协议及全部数据。先检查实际该品种2023全年逐信号；再由未修改`FixedSourcePrimaryReplayCli`执行原v4/LocalBacktestCli资格方法，原主期全部通过才进入未修改OfflineTemporalReplayCli的分离留出。不复制成交/费用公式；只调用既有门槛。

PID21320于22:22:17启动，目录`strategy-wick-geometry-formal-20261110`，日志`strategy-wick-geometry-formal-launch-20261110`；金融manifest SHA256=`80045f6369d5c1189a2e046706f3156c95446fafc381c81d09e7d4708cfe4a13`。22:23已完成2/100、0完整合格/0发布，前两项原v4均未通过；不是只写代码、未执行金融。源/规则从首观察后不许改，旧失败全部保留。

每项原始主引擎结果先落盘，已完成checkpoint核对源码/seed/JAR/金融哈希后才复用；有半完成目录即停止诊断，不能覆盖重跑。OS持有runner锁防同目录并发；资源不足8GiB磁盘或1536MiB内存时仅等待，不删证据或改门槛。Windows不读/打印大型live结果账本，只查小状态和静态单项证据。

此工具没有SSH、模型、导入或发布调用。本地完整合格源必须先同源/机制复核，再仅上传固定源码到126编译、服务器最近完整365天和正常发布器；禁止直接写实盘表。新会话先核实21320/12040/8676/4332的实际PID、创建时间、准确module/输出、FAILED及状态，不按旧PID重复启动。22576已完成退出，旧7012/21108/9876亦均结束。

最近服务器实测仍为20:36的ACTIVE/运行资格4，另过前瞻贡献单项2、缺96；本轮没有新增服务器发布。其余三批继续原冻结源；源码证明或修复方向数不计入100条目标。
