# ATR 退出批次：正式验证断点续跑

批次目录为 `strategy-volatility-exit-cycle-20261110-contractfix`，不是已在源码检查阶段结束的首轮目录。20/20 源码及全字段信号合同通过；1,000 项验证预筛有 13 项通过，按既定每单元缺口/机制去重规则选出 10 项正式候选。预筛通过不是正式合格，更不是上线。

原进程 20448 在正式验证入口结束：10 项均因 `RepresentativeSignalParityCli` 初始化时缺少 `StrategyCompileException` 失败，尚未进入正式财务回放或读取留出结果。新增的类型化诊断需要 INDSvr 的 `target/classes`；正式工具旧类路径只有研究 test-classes 与 SIM 运行时。现统一加入 INDSvr 主类目录，未改变策略、数据、校验器或资格门槛。

10 份原始 signal-parity.log、正式 manifest/results/status 已复制到 `formal-classpath-error-evidence`，保留原失败证据。Windows 旧版 Copy-Item 不能复制个别超长路径编译 class，因此此副本不作为完整编译产物备份；诊断日志均存在，原目录也未删除。

`run_local_source_strategy_cycle --resume-from local_formal_holdout` 先重新计算原有 catalog/input/source/class 冻结清单并要求完全相同，再校验 SOURCE_CONTRACT_COMPLETE 与 SCREEN_COMPLETE 的 campaign SHA、无生产写入及留出未读取标记。正式工具仍按原 manifest/checkpoint 保存所有已完成财务结果，不重跑失败的金融结果。服务器阶段续跑还要求匹配的 FORMAL_COMPLETE 和完整结果账本。

北京时间 16:15:45 启动续跑 PID 8508，16:22:18 已完整结束并核验服务器，当前不再运行。75 项 Python 回归测试通过。10/10 正式回测完成、0 执行错误、0 合格、0 上传/发布；7 条 OOS、1 条费用调整前瞻不为正、1 条 PF、1 条时序留出失败。库存仍为 4、缺 96，最终证据为本批 formal/cycle-summary.json。

继续研究版本见[正式口径训练标签协议](formal-payoff-label-research-protocol-20261110.zh-CN.md)。不改本批失败候选的参数重跑，也不因预筛通过而绕过正式失败。
