# 方向时钟：零执行队列交接与受限本地并行

2026-11-11 03:04，北京时间。此项只是让尚未执行的研究队列提前计算，不是策略通过或发布；100条独立生产策略的目标仍未完成。仅用已有OHLCV，不改服务架构、不调用DeepSeek、不降低任何金融门槛。

## 已完成的交接

旧时钟队列原本等待OHLCV批次全部200项完成。迁移前两次确认旧PID `27328` / create_time `1794333235.826844` / module `recovery.run_directional_clock_batch` / 原output精确一致，状态为 `WAITING_FOR_BOUND_PROFILE_BATCH`、0/100，没有候选、源码、编译目录、STARTED标记、金融输出或计算子进程；绑定的OHLCV父进程也仍在运行且远未完成。没有终止任何Java/Javac或真实回测。

预检逐字节验证旧工具及新目录实际导入副本、全部Native源码和工程类、9例实际FIT oracle、12例锁参oracle、16项数学/64条独立路径fixture、139项Java回归、行情/训练READY和数据；重建原完整100作用域队列必须完全一致。原研究协议与10品种×5场景×2方向全部保留；两个方向仍只有一个保守机制组，不是100条独立策略。

新工具专测10项、完整Python回归202项通过。直接运行第二次完整回归得到 `REGRESSION_PROCESS_EXIT=0`，不是将PowerShell的stderr包装当作测试失败/成功。只在此后终止经复核的空闲等待父进程，并写入原目录 `ORCHESTRATION_HANDOFF.json`；不改旧manifest/status，也不伪造COMPLETE或FAILED。

03:02:03新进程启动：

- PID `23812`，create_time `1794337323.3252933`，module `recovery.run_directional_clock_parallel`。
- 工作目录 `_work/dc-quant-deploy-directional-clock-parallel-20261111`，调度代码提交 `918f3b9364f41d5f23067140e4afbde57bf7c56e`。
- 原计划 `_work/strategy-directional-clock-formal-20261111` 只用于保存冻结计划与交接证明；**不要根据其旧WAITING状态重启27328**。
- 新金融目录 `_work/strategy-directional-clock-parallel-formal-20261111`；实时读取小 `status.json`、不可变候选checkpoint，而不是并发读取大results账本。
- 日志 `_work/strategy-directional-clock-parallel-launch-20261111/{stdout,stderr}.log`。
- 新控制器同时持有旧根和新根的真实OS排他锁，防止旧命令误启；锁文件存在本身不是进程存活证明。

资源守卫在每个新作用域之前检查：沿用原8GiB磁盘/1.5GiB内存底线，额外要求可用内存至少3072MiB、至少4逻辑核。只新增1个串行槽位，内存不足等资源，不杀其它计算任务。启动时一度等内存，随后可用3147MiB真实放行；资源等待不是失败，不应降低阈值或重启。

原完整目录控制器24052（最多2 worker）、OHLCV20660保持原进程/源码/数据运行，未合并或覆盖它们的工具树；4332早已自然完成400，不重启。新控制器继续调用原 `run_case`、原源码工厂、原实际主期执行器、上传前严格贡献裁决、独立62天留出。仅主期全过才运行留出；局部尝试一律保留并拒绝盲目重放。

## 首条真实工作证据

首项 `catalog_adausdt_trend_392d9515f27e` 已完成原源码校验、独立编译、2023全年35040根训练信号对照：154个信号、0差异，已有真实 `PRIMARY_STARTED.json` 和实际主期Java计算进程。此时不能称为金融通过。

- 固定源码：`3acfbc68bd67a13d5f8dbc7e97d150c75564e8a19b7f44776cc082939be1dab8`。
- 编译JAR：`300c4218d768cc090de71036ddbc4fb1d9715be56d4f188a1c102e91ea06b4dd`。
- seed：`81e6f9cae100a73511e25a7a0db295686313cd23db1c41471045ffdb4b62ae36`。

03:05补充终态：这条原主期已完成，17笔/PF0.287003/扣费验证-963.961326/扣费前向-131.719138/OOS0，真实拒绝 `oos_not_passed`，未开始留出或上传。经原 `completed_case` 校验检查点、金融哈希与来源合同，没有重算；完整摘要见 `recovery/snapshots/directional-clock-zero-finance-handoff-20261111.json`。队列已真实推进第二条；本地独立性与工程正确不代表能赚钱。

关键SHA-256：

| 证据 | SHA-256 |
| --- | --- |
| 原100作用域manifest | `a7b7a09c2b995ce660d1deefae84bddecf67c07f03fe61ecb9c528abcce03852` |
| 原目录交接证明 | `b0f0098e37e7670f6c247025b1e372be64237ea35f1cfce790eca34a0edb4337` |
| 新金融manifest | `f2a7ee61d8ca590bd596cc89ef163c6af1487147a9ed6a25d16b3942ef373f16` |
| 预检完成marker | `dfb8dcc021b959484ab00992fc49e648ba0ce6d7e084888dafe3db7b0e11e592` |
| 新控制器源码 | `1e3c0dc9ec7b51cc829d5b21af61256c9e21a723cfe6ce22fe7d39595cff0770` |
| 空闲进程退休工具源码 | `0000b07fc538ead5915d5ed176addd8a544745093ad8d3b0080913c4b7eb1d9c` |
| 10项交接回归源码 | `09ddb0410abe6b922f6c5f4c142682ab7e30b05b9430901064f8337669bd9d8e` |

## 下一会话接续与发布边界

先核对23812的PID/创建时间/完整命令/output及实际子进程，再读新status和完成checkpoint。若出现FAILED或半完成目录，先保留并诊断；观察超时不能据此另起相同金融任务。新/旧计划SHA、源码、helper或数据不符都要拒绝接续，不能更新预期SHA来接受不同输入。

仅新的本地严格主期及分离留出均通过，才做当前生产同单元源码独立性审核，并把固定源码上传126走正常编译、最近完整365日回测、场景/基线/发布器。此前服务器失败的ADX UNI、平衡LINK/UNI、完整目录ADA及较早ETH全部不重导入；贡献0.163532的LINK原raw通过也不能上传。本地4条近期严格通过全部服务器失败，新增实盘仍0。最近生产库存核验仍为01:31:21北京时间的4 ACTIVE/运行资格，其中只有2另过贡献，不能当4条完整新发布合格。

固定策略合法空参数 `{}` 被原发布器误判的问题仍等待用户明确批准单独修复；本次只改本地排队，不是该修复授权，也不加无用参数绕过。生产镜像/配置/风险/持仓/订单均未修改。
