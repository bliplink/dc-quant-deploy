# 固定谐波相位 OHLCV 研究：工程验证已启动，尚未通过

观察时间：2026-11-11 06:34，北京时间。只做本地新研究，不改服务架构、不调用DeepSeek，不依据已消费金融结果调参。

## 与现有源码的关系

已检查canonical all的实际代码。DetrendedCycleReversalHypothesis使用20根DPO转向/当前突破；AutoregressiveResidualForecastHypothesis用自回归残差及已经观察到的8根标签条件样本。旧目录还含收益自相关、方差比、量价预测、Bayesian/ordinal及方向时钟。此次不是这些类的改名：新研究在固定64根已完成对数收益上计算谐波系数，直接向前投影其相位，不读取未来价格或标签。搜索旧all未发现同样的谐波系数/全能量/同频首次越线实现。

代码特征不同不等于经济独立，也不证明存在真实周期或未来盈利。多/空与品种/场景复制只归1个保守机制组，不把100作用域当100独立合格策略。晋级仍须当前ACTIVE同行的精确源码/信号复核。

## 预声明固定规则

- warmup100、最多可见200根；64个已完成close对数差，先减均值。
- 只比较整数频率bin2..8，取A²+B²最大的一个；升序严格大于选择，未做金融参数搜索。
- A=2/64Σ(r-均值)cos，B=2/64Σ(r-均值)sin。分母保留全时域能量Σ(r-均值)²，包括未参与选择频段的能量；选中谐波能量占比至少0.40。
- 将选定谐波投影到其后8个时点并求和，不把均值漂移加入预测。前后两滚动窗都须满足集中度、频率bin相同；side*投影由<0.0024首次到>=0.0024才入场，持续越线不重复触发。
- 全部可见OHLC有限/有效/正价格，volume有限非负，当前volume>0。非有限/零能量等直接拒绝，不隐式补数据。
- 保留原ATR14止损1.5/止盈3及显式ATR20 EMS、首档至少0.5%。parameterSchema/defaultParameters均空。
- 金融协议仍是2024-12-15～2025-10-12原主期、2025-10-13～12-13完全分离62日留出、严格前瞻贡献至少0.20，原其他样本/扣费/PF/回撤/OOS/场景/基线与服务器门槛不变。

新协议SHA256：`c0cf34715602c14e594e15214da88e717d26fa106e5c798b1d1dc98f2bc188bf`。

## 代码、测试与真实进程

Native隔离树：`E:/sourcecode/codex/_work/indsvr-local-harmonic-phase-20261111`，本地9574128；独立远端研究分支`codex/local-harmonic-phase-20261111`提交`7cea778e28c2953246a881ff9a47e8bc0c8445fa`。3份新src/test Java、canonical all/专属cohort注册和LF属性共5个目标blob已逐一核对。没有向生产latest推送，没有src/main、POM或镜像发布改动。远端采用原公开研究分支为父，保留其既有历史，不覆盖本地另有的旧模板资源/旧test差异；不声称整棵本地/远端树等同。

工具隔离树：`E:/sourcecode/codex/_work/dc-quant-deploy-harmonic-phase-20261111`，代码d974a12。6项新增导出/协议测试通过；完整292项Python回归46.244秒、退出0。日志`harmonic-phase-python-tests-7df548f9d2ba4c7283846359713d21c2/unittest.log`，原始SHA256 `48dd288509944bc7737876c1bb5b7eb7364ab9891c051f59afa6f3866ef18188`。PowerShell采集stderr会显示NativeCommandError包装，测试实际终态为OK/292、退出0；没有将失败测试当通过。

真实工程进程 **19572/create1794349879.7879152/module recovery.verify_harmonic_phase**，工作目录为新工具树；输出`strategy-harmonic-phase-engineering-20261111-v1`，日志`strategy-harmonic-phase-engineering-launch-20261111/{stdout,stderr}.log`。manifest **dae9f979f1293804d39b737c8f01ae0318552dfce77f308f5a310ffae6a540c2** 冻结1753关键文件、1501参考类、68 JAR，以及源/协议/原训练输入/全部本树顶层Python/Java工具选项和运行时成员。

06:34实际仍 **WAITING_FOR_ENGINEERING_RESOURCES / mathematics-compile / 0/2**，可用内存2909MiB、未达原3GiB守卫。**16项Java数学测试、64独立OHLC的复数DFT/直接卷积oracle、两向实际生成源原validator及35040根2023全年对照、完整至少188项Java回归均待实际执行。** 无FAILED、无SOURCE_CONTRACT_COMPLETE；Python通过不能替代这些要求，也没有金融资格。

新Native与本工具树全部Python现在已冻结。后续代码工作另开树；不重启19572、不修改它已绑定的源/预期SHA、降低守卫或杀计算子进程。完整快照：`recovery/snapshots/harmonic-phase-research-start-20261111.json`。

## 后续实际动作

先核对19572精确身份及小status/不可变日志，让工程自然执行；失败则保留原尝试、诊断真正语义缺陷，不重试金融。只有数学/原validator/两份全年非零信号0差异/全部188回归及最终marker与哈希真实完成，才在新树接原run_case/strict/独立留出，核验原父完整完成并复用串行槽位。此时尚未创建新的金融执行器或金融输出，更未接任何训练缓存。

旧24052完整目录、20660行情分布、23812时钟、21204 CUSUM、24444游程及3948训练矩阵均不变。0新增金融合格、0上传、0服务器发布；100真实生产合格目标仍未完成。固定空参数发布格式诊断的单独待确认事项不被此次研究视为已获批准。
