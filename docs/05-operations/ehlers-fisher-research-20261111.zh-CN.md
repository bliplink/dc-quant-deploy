# 明确递推Fisher新研究：旧规则保留，不靠变更口径凑数

## 08:34真实完整工程通过：优先读本段

19640/create1794356743.227481已自然结束，真实SOURCE_CONTRACT_COMPLETE SHA48b0d618812d40f6c15e57183d52eee453fc5e48c4c024bf31f99146c05e25e6，manifest仍af8d7b3a...。全部1762关键SHA、795产出class的完整成员/哈希、两份源/JAR、原seed与当前确定性导出完全一致、原validator和全年训练日志已独立重核，未有FAILED。

15项Java数学/64独立原始OHLC卷积oracle均通过；多/空两份真实35040根2023对照为966/980信号，研究与生成源全部7个信号/风险/退出字段0差异。完整187 Java回归真实通过，日志SHA9eff2b6ebc27b9d4317ff70f62f7c0de5e005b1634b4ed97b55dca35690daef6，regression-manifest SHA9138144ecc0e05083b67fb7cf2d4ad0608269c7e7d90b2790e0c8f8ee9bd6ef5；原349 Python回归证据保留。

完整终态快照`recovery/snapshots/ehlers-fisher-engineering-complete-20261111.json`包含两份真实生成源/JAR/seed/全年日志SHA与owner终态；初始等待/中间数学观察不覆盖。不要再按下文0/2或1/2重启19640。**工程通过不代表任何金融/留出/服务器资格，尚未启动本项正式金融。** 下一步在NEW工具树实现原run_case执行链及现有100队列结束后的单槽位绑定，真实全上下文预检通过才启动等待；不得修改已冻结工程树/Native或加第五个金融worker。

以下08:32及更早内容为预声明与中间观察历史；规则/源码未改，没有据正式结果调参。

2026-11-11 08:32北京时间观察。此项仅现有OHLCV、新隔离源码的工程验证；没有新金融资格、服务器上传/LLM调用、生产部署或架构更改。100真实合格实盘目标未完成。

## 为什么另立版本，而不是按亏损改参数

直接检查旧canonical all，而非只看202个fit-risk类：`FisherReversalHypothesis`固定20窗口/1.4极值后方向恢复/收盘越前根high或low；其`fisherTransform`只把close在high/low区间的位置映射到±1后取对数，**没有递推状态/平滑**。这是一个可定义的原始变换，不能只因命名不同就武断宣布旧金融失败是程序错误。

本项依据[John Ehlers原文Figure4](https://c.mql5.com/forextsd/forum/68/using_the_fisher_transform.pdf)另立清楚声明的中间价递推版本：rolling median-price extrema、输入0.33/0.67状态、输出0.5历史项、边界保护。原公式是方法来源，不是收益证据；不宣称atanh变换自动保证市场高斯分布、概率校准或盈利。

没有先看本项的新正式/留出结果再选参数。**旧源码、在跑完整目录、旧Fisher所有版本/负结果均原样保留**；新原生分支从c74214d隔离，未修改旧运行树。两方向与旧raw-transform近亲同归一个保守Fisher机制家族，不宣称新经济独立性；以后若本地真通过，仍须当前实盘同行源码/信号复核，不把两个版本当两条独立策略重复计数。

## 金融前固定的具体规则

协议`recovery/strategy_research_ehlers_fisher_protocol_20261111.json`，SHA55a0f4910e792c837523f4fc9357c5cde0cdb8f126dcc60ccc9a477bd192b8a3，source_cohort=ehlers_fisher_v1；工程启动前已与程序提交668f5e7。

- 保留旧20周期和1.4极值/价格确认，不复制原文默认10周期；输入是已完成bar的(high+low)/2，区间极值也基于这些中间价，而不是close或整根high/low。
- 每次只使用当前最多200根已完成bar，至少180根；对结束于t-1的160个归一化观测，从同一x=0/F=0开始递推，t-2和t-1结果共享种子，禁止各自重置造成假转折。**这是明确的有限历史变体，不是声称与无限历史IIR逐点等价**。
- 状态x=.33*z+.67*oldX，x>.99置.999、x<-.99置-.999；F=.5*ln((1+x)/(1-x))+.5*oldF。归一化区间完全平坦时z=0、衰减旧状态，这是预声明的零区间适配，不填价格/收益。
- 多：F[t-2]<=−1.4、F[t-1]>F[t-2]且C[t]>H[t-1]；空镜像。F只看确认bar之前的历史，确认bar价格不能改变过去的F。
- 沿用原ATR14止损1.5/止盈3和ATR20 EMS全部7个输出字段/几何保护、当前正成交量/所有可见OHLCV有效性；不增加参数网格、虚假可调参数、未来状态或服务依赖。

`ef1_recursive_fisher_long/short`只是两方向；100个10品种×5场景×2方向作用域不是100个合格/独立策略。原主期2024-12-15～2025-10-12、strict贡献>=0.20、独立62日2025-10-13～12-13、空锁参/0优化及服务器完整365日/scene/费用/OOS/样本/同行门槛不变。

## 实际验证与当前状态

新增9项Python导出/冻结/输入与协议拒绝测试、完整**349 Python通过46.782秒/退出0**；原日志ehlers-fisher-tests-b3eb78d86d1f4e91bf939222662c89b5/unittest.log，SHAd0c7c992c4f8514737b56a5ce30ec25b0f234cc5f69d2f82b54c874faa917d74。

实际Java源码编译和**15项数学测试通过**，含64组独立原始OHLC卷积oracle；oracle在clamp分段展开输入几何权重，并展开输出滤波器，不调用生产递推函数。另有中间价而非close、无未来、共享种子、平价/边界、双向非零合成覆盖、全7字段ATR风险、缩放/坏报价/热身/历史上限保护。数学日志SHA0e20247e6fa312ed1ba3ce4c15a209bb75375cae6f6cb636161f3f8bf152cf7d。

08:32真实首BTC/trend long已完成原生成源码validator和2023年35040根对照，966研究/导出信号、0差异；short原validator/全年对照和完整至少187 Java回归仍未结束，SOURCE_CONTRACT_COMPLETE尚未声称存在。966训练信号不是正式成交样本/盈利资格，不为提高数量调整触发逻辑。

## 冻结入口与接续

- Native：E:/sourcecode/codex/_work/indsvr-local-ehlers-fisher-20261111，源fbee33ee9e7bdf0e63fe447832d1f2d1a7f5d24e。
- 独立研究分支bliplink/com.app.dc.indsvr/codex/local-ehlers-fisher-20261111，公开提交e95120f7e949f4729e8a32174c0ae8fb19245c50；5个目标blob逐一核对与本机Git blob一致，未改latest、不触发生产镜像。
- 工具：E:/sourcecode/codex/_work/dc-quant-deploy-ehlers-fisher-20261111，源668f5e710c1654c843e077646e04694c8b31de88。
- 实际owner19640/create1794356743.227481/module recovery.verify_ehlers_fisher；工程根strategy-ehlers-fisher-engineering-20261111-v1，日志strategy-ehlers-fisher-engineering-launch-20261111-v1/{stdout,stderr}.log。
- manifest af8d7b3a4034833d799bf384db491b72d89071d6dd6ba52e12d6ecb5519cad81，冻结1762关键文件/1501参考class/68JAR/本树全部Python/原训练输入/Java选择和环境选项；原3GiB/8GiB守卫不降低。

启动及后续数学观察分开保存在`recovery/snapshots/ehlers-fisher-engineering-start-20261111.json`。**本工具树全部Python/Native从真实启动后冻结**，后续正式排队工具另开树；不因资源等待/轮询超时重启19640，不覆盖失败尝试、不杀计算孩子。须两份真实源码validator/全年非零0差异、完整187+回归、最终全哈希及真实SOURCE_CONTRACT_COMPLETE后，才可在另树准备原run_case金融队列，等待现有队列自然完成并全量核验后替换一个槽位，不加第五个worker。

本次命令行Git代理127.0.0.1:7897和直连443均终态连接失败，无远端写入；已改用连接的GitHub接口保存研究分支。超过1MiB的contents接口可能返回空content却有正确blob SHA，不能把它当空源码。通过git/blobs读取原已验证大文件（不打印正文）、只插入声明的新cohort/all注册，创建blob后与本机完整2,134,017字节源码的Git SHA6d6b47941c73443af2a232cc598c8979efa23faf严格相等，再核对全部目标tree；没有重写或截短原2MiB研究主类。

其它原金融24052/21204/13568与训练证明3948不变；固定空参数发布器修复仍待单独授权。下一步完成真实工程后走原正式/留出/服务器门槛，不把数学、源码公开或进程启动当作金融/实盘通过。
