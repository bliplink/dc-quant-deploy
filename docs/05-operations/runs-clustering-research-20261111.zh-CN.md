# 游程聚集OHLCV研究：数学测试通过，真实源码工程验证尚未完成

记录时间：2026-11-11 05:36，北京时间。本轮新增一个固定研究机制，不是100条合格策略；目前未开始该候选的金融主期/留出，也没有新上传或发布，100条真实生产合格策略目标继续。

## 研究规则与去重边界

先检查原canonical all：`DirectionalPersistencePullbackHypothesis`实际用效率比/均线/回调，`BayesianTransitionForecastHypothesis`实际按转移状态收集已观察标签；未发现条件游程计数实现。因此另建 `runs_clustering_v1`，没有改名复用这些类，也不据它们失败的前瞻结果调参。

固定64条已完成close-to-close涨跌符号，窗口内剔除精确零变化；按剩余符号的连续同号段计数。采用[条件二值游程的均值及方差](https://www.itl.nist.gov/div898/handbook/eda/section3/eda35d.htm)构造标准化计数特征；前后两个窗口均至少11正/11负，只有当前Z<=-2、前一窗口Z>-2，且当前非零符号等于预声明方向时入场。100根预热、最多200可见bar；固定原ATR14 stop1.5/take3、原ATR20 EMS及0.5%首阶下限，无网格参数。

这是从统计量提出的交易研究规则，不是市场随机性显著性检验：滚动窗口重叠、收益依赖及首次越界筛选不支持iid显著性或盈利保证。数学实现不同也不证明与现有趋势暴露经济独立；多空两向统一计一个保守机制组，未来仍须核对实际当前实盘同业源码及信号，不能重复版本凑数。

协议在工程/金融前写入 `recovery/strategy_research_runs_clustering_protocol_20261111.json`：主期仍2024-12-15至2025-10-12；全分离留出仍2025-10-13至12-13、62天，至少0.20前向贡献、原样本/费用/OOS/场景和服务器门槛全部保留，不调已消费窗口。

## 代码与已有真实证据

新Native树：`E:/sourcecode/codex/_work/indsvr-local-runs-clustering-20261111`，本地提交 `c74214d92ddc56be5d1a72d059e685a633122612`；独立远端研究分支 `codex/local-runs-clustering-20261111` 已逐blob验证为 `b72e12522ee70ba6bbd12f10dcad5e9b7efcf65f`，树 `1f380e726ed2fcf1c72b3d2f4bcb0efeef0f3f00`。只有三份新test-source Java、原catalog四行登记及针对性LF属性；未动src/main/POM/生产分支。已读实际workflow，仅push latest触发镜像；本次没有发镜像或部署。

新工具树：`E:/sourcecode/codex/_work/dc-quant-deploy-runs-clustering-20261111`，源代码提交 `4fd2fb137cc6f2d765172710cf19819258b49df0`。新增固定导出器、6项导出/协议测试及实际工程验证入口；6项专测与完整273项Python回归通过，最终25.951秒、退出0。原始日志在私有目录 `runs-clustering-final-python-tests-80f777ced9b94e3ba1e8456c96a36a37/unittest.log`，SHA256 `65720ea9834ce72773d401a53fd01483ed66610e041beb6738c0e61723581bcb`。这些是软件测试，不是273条策略。

真实Java源码初始编译已成功，实际JUnit数学测试 **17/17通过**，日志SHA256 `7317db368820ee19da6d9efac7432a5860dacd660c702cabbe16486e8cd2c4b1`。覆盖小样本全部二值排列的独立矩估计、64份独立原始OHLC窗口/方向oracle（含实际构造正例）、精确零变化、边界/计数守卫、不重复触发、无未来数据、原风险所有字段及价格缩放。该记录不替代生成源码与原引擎的一致性验证。

## 当前权威工程进程与恢复约束

- PID `24796`，create_time `1794346150.2820573`，module `recovery.verify_runs_clustering`，05:29:10启动。
- 输出 `strategy-runs-clustering-engineering-20261111-v1`；启动日志 `strategy-runs-clustering-engineering-launch-20261111/{stdout,stderr}.log`。
- manifest SHA256 `c497bbf412bf8ec391b3f4d6bb9843427e016fd4a9c5c2ff0a404740ac32b11e`，冻结1745关键文件、1501份外部参考class、68运行JAR、全部本树顶层Python、训练输入、Java工具/选项及参考测试。
- 05:36实查进程精确身份存活，`WAITING_FOR_ENGINEERING_RESOURCES / source-compile:1 / completed0/2`，当时可用2864MiB，低于3072MiB。此前编译和17项数学测试已真完成；两个生成源码校验/全年35040根对照尚未完成，完整至少172项Java回归也尚未执行。
- 每个重阶段继续要求3GiB可用内存并重核完整冻结成员/字节，资源等待不是失败或终止。未关闭用户桌面应用、未杀旧金融孩子、未降低守卫。只读内存巡检表明主要占用是桌面应用/系统，不能擅自终止。

**本工具树全部顶层Python及上述Native源码现已冻结，不要在其内添加正式队列脚本或改代码。** 新工作另建worktree；不要因等待状态或一次观察超时重启24796。若真出现FAILED或进程消失，核对精确PID/create/module/output、日志和原manifest后诊断，保留旧尝试。当前没有失败重跑或金融观察。

## 后续实施

1. 继续精确观察24796，完成两份真实生成JAR、原validator、2023全年35040根非零信号/风险/退出字段0差异，以及全部旧155加新17的实际Java回归。只有真实SOURCE_CONTRACT_COMPLETE及全部源/类/日志哈希匹配才算工程完成。
2. 通过后在新工具树接原实际run_case、严格贡献裁决和62天留出；创建保持原市场字节的协议绑定输入。只替换已有计算槽位并验证父批次真实完成，不增加第五个金融worker，不改当前21204/23812/20660/24052。
3. 本地严格主期及独立留出都合格的新源，才做同业机制审核、上传固定源码到126编译/最近365天/正常发布；不使用DeepSeek生成或修复，现有失败不重放。

05:36并行队列快照：完整目录930/19,599、raw2/strict1（strict1仍旧ADA服务器失败源）；OHLCV111/200、0本地合格；时钟78/100；CUSUM训练矩阵4/20组、20/100证明，缓存仍未启用。原所有活动树未动，固定空参数发布格式修复仍待用户单独明确同意。生产策略数量不能由本研究源码或测试数推出。
