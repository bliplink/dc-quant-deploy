# 四档训练校验的进程启动合并：证明与使用边界

研究范围仍是既有OHLCV，不改策略、金融执行器、已消费窗口或资格门槛，不调用生成模型。此项仅减少工程校验的JVM启动次数，不能当作新增合格策略，也尚未切换正在跑的两个冻结金融队列。

## 实际重复开销

`prepare_fit_risk_scope_contract`对每份作用域源码启动一次原源码校验器、再启动四次原逐根信号校验器。完成目录日志中一项合同约23～24秒、后续金融约16～21秒；这是本机当时的观测，不是跨机器吞吐保证。大量作用域重复启动JVM并解析依赖。

新增 `FourProfileParityBatchCli` 在一个JVM中先调用未改动的 `RepresentativeSignalParityCli --validate-source`，再依次调用同一个原CLI的风险档0/1/2/3。每次调用仍由原方法创建新策略类加载器、生成策略实例、registry、原始bar列表和逐字段比较；没有另写一个简化版校验器或复用策略实例。实际生成源每个profile均有独立init。

## 已完成训练证明

`verify_batched_fit_risk_parity`固定选择原先声明的8个工程代表族，使用同一BTC2023全年35040根训练数据、原源/JAR/编译类，对照旧流程保存的四份逐根信号结果及economics拒绝原因计数。8例/32档全部一致，原源码校验全过；未读取金融主期、forward或新留出。

- 证据：`_work/strategy-batched-parity-proof-20261110`。
- manifest SHA256：`dd95da361b9efaba3306277c924df9b056391209ac93aaea5a7f8b9f105620e1`。
- driver class SHA256：`51eb564bbb190882ea7bbf63413f77933ee9de4645988693d4631cfa8a0c73c1`。
- audit `state=complete`、cases8、profile_cases32、financial_validation_started=false、new_holdout_read=false、production_write=false。

新作用域工具 `prepare_fit_risk_scope_contract_batched` 强制该完整证明、所有case与bytecode/hash不变，再执行原导出器和编译器，输出明确新schema/新wrapper/proof哈希的合同。0信号保留为0，不冒充正覆盖；缺档/乱序/重复、少bar、任意不一致或改动bytecode均拒绝。

真实ADA/breakout样例使用旧已完成训练合同 `catalog_adausdt_breakout_8752102483e6`，不重做其金融结果，仅对照新工程路径：

- 假设`fr1_trend_breakout_short_s15_t30`；4档均250个训练信号、35040bar、0差异。
- 与原导出Java源码逐字节相同、四档合同结果相同；逐项读取两个JAR的entry内容也完全相同（不把ZIP时间戳元数据当作代码变化）。
- 新合同`b776b933d2fccfd9929fbf8ee08bab4c97d471c07775b2068c5fe56c3f66ce5a`，新manifest`ff04ba3a43e7340a56594659dafb2bc94f2db29038ad868ad6702ccf8cd42651`。
- 证据`_work/strategy-batched-scope-pilot-20261110`；旧合同及金融结果未覆盖/重跑。

Python工具全量先156项通过，增加服务器package规范化边界回归后157项通过。减少5次JVM启动为1次是执行结构事实；未做控制其他进程负载的ABBA吞吐实验，不据此声称整个金融队列已提速多少倍。

## 使用及后续集成

先运行 `python -m recovery.verify_batched_fit_risk_parity`，显式给出catalog、IND、SIM、training-input和新output。仅成功后运行 `python -m recovery.prepare_fit_risk_scope_contract_batched`，加`--batching-proof-dir`和明确hypothesis/symbol/scene；每次必须使用新的合同输出目录。

在跑的4332/12040原队列仍使用原冻结工具；没有中途修改源码、helper、计划或合同。接续时需要单独设计并证明安全的检查点交接/消费方案，保留所有已完成和部分金融结果，不能强杀子进程、重跑失败、盲目并发写原目录或声称本优化已经应用到旧队列。新合同可由未改动的`run_fit_risk_admission`检查消费，但这不等于当前队列已切换。
