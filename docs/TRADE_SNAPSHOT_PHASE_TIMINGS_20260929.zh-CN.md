# Trade 快照屏障：逐阶段耗时验证

日期：2026-09-29。源码 `3f0d027816872cdda82820fe1126efa127c493d7`，继承 `ce38b04` 固定 64 KiB 写缓冲。**本地候选与隔离历史副本验证；未部署、未启用周期快照、未故障注入或压测。**

## 1. 本轮交付

增加 manager 的 pre-scan、锁等待/持有、分项状态扫描/复制、save、释放耗时；增加 store 的核心状态/applied/terminal 编码及缓冲写入、排空、file sync、close、替换、目录同步/cache 等耗时。在固定缓冲下面计数实际文件 delegate write 次数、耗时和成功字节数，不在每个 JSON token 上加时钟。

这些都是诊断，不参与 READY、cash admission、committed prefix 或成功响应判定。Store 只保留一个有界摘要，按精确 snapshot ID 对应，遇并发覆盖可缺失而不能串到其他分区；输出不含 snapshot ID、用户/订单键、业务载荷和文件路径。日志/诊断 RuntimeException 不替换保存结果或跳过周期捕获的正常释放；不吞 JVM fatal error。

原格式、分区业务屏障、预验证和保存顺序保留：校验/manifest → tmp 编码写入 → 排空 64 KiB 缓冲 → file descriptor sync → close → 原替换/fallback → best-effort 目录 sync → cache 失效。目录同步仍不是断电持久性证明。没有改公式、Projection 协议、SQL writer、归属或复制。

## 2. 指标解释和一致性边界

- 编码阶段包含遍历、分配/GC、序列化与缓冲期间的文件写入，不是纯 CPU 时间。
- delegate-write 时间与编码/排空重叠；父阶段和子阶段不能相加。扣掉写入得到的也只是墙钟剩余，不是 CPU profiler 结果。
- manager saveCall 还包含 store monitor 等待和诊断；lockHeld 包含扫描、保存与释放。失败阶段可能只留下部分计时，不能把零值当没有执行。
- `AccountBalanceFacade.snapshotLocation`、`PositionFacade.snapshotLocation`、`OrderManager.snapshotLocation` 只收集**可变对象引用**；配置方法有复制，实时去重又需要相同分区屏障。现阶段直接释放屏障后编码会混合已提交坐标和后续业务效果。
- 将来锁外写必须先提供包含业务值、去重、配置与提交坐标的有界不可变冻结/COW 协议，同时证明 mutation、失败释放和资源上限。当前 100 MB 文件不能简单等同所需冻结堆，也不能用完整去重 DTO 复制掩盖内存放大。

## 3. 来源与测试

计数修正（后续编码验收时发现）：下段原 68 类 / 362 项的聚合包含已无当前源码的 `TradeRecoveryConfigurationCoverageTest` 旧报告 1 项，实际应为 **67 类 / 361 项**；镜像内 92 项和本页副本实测不变。结构化证据保留原聚合值与修正原因，不删除原报告。详见 [后续编码与 TCP 验收](TRADE_SCALAR_ENCODER_AND_TCP_QUALIFICATION_20260929.zh-CN.md)。

Java 8 缓存依赖、断网完整回归 **68 类 / 362 项**，零失败/错误/跳过。本轮新增 6 项诊断契约；原隔离实验测试进一步检查捕获/保存阶段存在、成功字节与快照长度一致。包括 retained/live 成功、不可变摘要/无载荷泄漏、精确 ID 与旧/其他分区拒配、流失败保留 latest/pinned、校验失败未安装、disabled 不伪造尝试/证明。没有用性能阈值写成单测。

候选镜像 `local/tradesvr:snapshot-stages-3f0d027`，Linux arm64，ID `sha256:6505d51b583e5027dfe2b0fa3704436704ebeca77f19875771ba7a5daf21bd9f`。全部 **311 文件（231 代码/资源、80 依赖）**与本地产物一致，`LC_ALL=C` 相对路径 sha256sum 清单摘要 `91d03ff070a303abd7415080e7db3af1870c8a0972ece5c401ab0f2080e0676e`。相比 `ce38b04`，仅 manager/store 相关 9 个 class 新增/改变，302 文件不变，80 依赖一致。独立依赖目录 `target/dependency-snapshot-stages-candidate`，缓存 base `sha256:b8039096ac6396135dc864690ae785a30e6ad6d7614c6cd1f1ba180c85a56845`；未下载依赖、推送或部署。

[固定构建定义](../tests/fixtures/trade-snapshot-stages-candidate/Dockerfile)不能在源码改变后沿用旧 revision。实验 helper/test classes 只读挂载，生产 classes/lib 来自固定镜像。实验输入仍为标记的 P204/P122 副本（约 3.3 GiB）；P122 先常驻，P204 checkpoint 813,788、末序号 815,788、delta 2,000 条。断网、1 CPU、1,024 MiB heap / 2,048 MiB 容器、180 秒时限，独立新输出目录。不挂原运行 journal，不追加/截断日志、不种快照到运行节点。控制器 10 项安全测试通过。

镜像内生产 classes/lib + 只读测试类执行 **6 类 / 92 项**关键回归通过，4.983 秒；包含整节点现金容量、现金执行器、混合状态覆盖、离线恢复、缓冲和阶段诊断。两轮大副本使用同一 helper 摘要 `d0cf9f995152e8db6fa9db6823153df72f01b473ea3d619d681e602ed556f729`，期间没有重新编译。不是 Spring/DAO/TCP/control plane/promotion 或完整节点验收。

## 4. 同镜像、同预算两轮实测

| 阶段 | 第 1 轮 | 第 2 轮 |
| --- | --- | --- |
| 捕获总阶段 | 1.892 秒 | 2.352 秒 |
| 锁外 pre-scan | 0.543 秒 | 0.796 秒 |
| 锁等待 | 2.749 ms | 4.554 ms |
| **分区业务屏障持有** | **1.343 秒** | **1.550 秒** |
| open-order 扫描 | 46.733 ms | 45.059 ms |
| 编码＋缓冲写入总计 | 1,134.451 ms | 1,449.273 ms |
| ↳ 核心状态编码＋写入 | 335.838 ms | 338.235 ms |
| ↳ applied 去重结果编码＋写入 | **727.353 ms** | **1,018.432 ms** |
| ↳ terminal 键编码＋写入 | 71.197 ms | 92.366 ms |
| 实际 delegate write（与上述重叠） | 163.556 ms | 253.302 ms |
| 最后排空缓冲 | 0.167 ms | 0.073 ms |
| file descriptor sync | 120.685 ms | 42.720 ms |
| 文件替换 | 17.089 ms | 2.892 ms |
| P204 全日志恢复，P122 已常驻 | 30.061 秒 | 25.348 秒 |
| P204 快照＋增量，P122 已常驻 | 3.565 秒 | 2.978 秒 |
| delta 恢复后显式 GC 的堆 | 500,507,256 bytes / 477.3 MiB | 460,491,704 bytes / 439.2 MiB |

两轮 PASS，完整实验分别 104.276 / 114.810 秒，exit=0、OOM=false、无超时。完整实验含多次恢复/摘要/GC，**不是故障 RTO**。每轮快照仍为 **100,473,484 bytes**，实际 delegate write **1,535 次**，成功字节与文件长度一致；大单条可 bypass，不能按固定块数推导内核 syscall。

**定位结论：**编码＋缓冲写入占锁持有约 **84.4% / 93.5%**，applied 去重结果是最大子阶段。文件写入占锁持有约 12.2% / 16.3%，file sync 约 9.0% / 2.8%；文件写入已经包含在编码/排空里，不能重复加总。两轮编码减 delegate write 的墙钟剩余约 0.971 / 1.196 秒，含遍历/分配/GC，不是测得的 CPU 时间，但足以说明“全部时间都在刷文件”不符合这两轮数据。没有 SQL 参与该实验，不能由此宣称整个运行系统旧 SQL writer 已退场。

这一提交增加的是诊断，不是新的性能优化。与上一候选单轮 2.067 秒屏障的差异没有受控归因；共享 VM、JIT/GC/文件缓存与其他服务负载均可影响观测。两轮不能给出 p99、确定 CPU 瓶颈或“计时让性能提升”的结论。保留堆也在 439–477 MiB 间变化，原因未用对象级实验确认，不直接判为泄漏或计时对象保留；两个观测都高于 B 的 384 MiB，仍不批准大分区接管。

完整恢复与快照＋delta 的状态摘要，两轮均为 `d92971371930c9d0d67b01bc9c6caa3f7d6052b60de2bc10b35c8817b06a4c1c`，与上一候选相同。计数仍是 applied 691,065、余额 131、持仓 72、订单镜像 60,390、terminal 284,471；仍有 60,208 条缺状态镜像、182 条 Suspended，历史配置未被证明。相同摘要不等于资金/订单业务正确性，不自动修复或种历史快照。

## 5. 证据、复验与下一步

提交的 [结构化证据](evidence/trade-snapshot-phase-timings-20260929.json)含固定镜像、本地产物核对、测试、两轮完整聚合报告和解释边界；不含账户/订单键与业务载荷。

- 第 1 轮本地原报告 `.tmp-trade-evidence/snapshot-lab-combined-stages-3f0d027-1024.json`，SHA `f34e75b108cc1ec9f62b9002db19ce5b18b2ad678a1f2f2cc1c401d2051bab45`，输出 `/data/dc-saas-isolated-labs/trade-snapshot-run.QDRrX6qt`。
- 第 2 轮原报告 `.tmp-trade-evidence/snapshot-lab-combined-stages-3f0d027-1024-r2.json`，SHA `5f042fced016856a0d1f3cb6d73afeddec5b22c6be4a10dfa575c32ca42fcc8a`，输出 `/data/dc-saas-isolated-labs/trade-snapshot-run.wMneQrE4`。
- 临时实验容器已回收；复制输入与两轮输出保留。复验沿用 `tests/run_trade_snapshot_offline_lab_host.py`，指定本节固定镜像、副本和已编译 helper，P204/P122、1024/2048/180 预算，必须给全新报告路径，不覆盖本轮证据。
- 2026-09-29 **11:40:04 UTC** 只读核对 8 个 Order/Trade/MD/Projection 容器仍运行、restart=0、OOM=false，镜像未变；没有改 assignment、参数、SQL、历史、周期快照开关、压力或故障。进程健康不证明业务可写。

下一切片先针对 **applied-result 序列化减分配/复用**做有界隔离验证：保持 JSON 字节、失败顺序、保留窗口、原结果和恢复摘要一致；需实测再决定是否采用。若仍要锁外落盘，另交付不可变冻结/COW 与完整预算，不能直接释放现有屏障。

实际晋级仍依次受完整节点资源/直接内存、可信历史与业务计算基线、Order/Trade/MD 有界生命周期接线、replica 提交证明/旧主 fence、业务重试与 p99 门禁约束，随后才做受控异常和 300/16 逐级业务 TPS。当前得到的是瓶颈定位证据，不是自动故障切换、RPO=0、稳定 TPS 或长稳成绩。
