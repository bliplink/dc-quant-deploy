# 最新 Trade 候选镜像：真实大分区副本恢复与预算门禁

日期：2026-09-29。本轮从代码测试推进到**不可变候选镜像中的真实日志副本恢复**；不是现有服务升级或实际 TCP 集群切换。新镜像没有推送或替换当前运行节点。

## 1. 候选产物与来源

- Trade 源码：`a539940d4b83a1010096b8efae68adce56917b8c`，工作树无源码未提交改动。
- 本地镜像：`local/tradesvr:node-recovery-a539940`，Linux arm64。
- 固定 image ID：`sha256:834ebf7ae2eac0a44eb3e88cedd45a39d44d5adfd900c067be329856048ce0dd`，revision label 与源码提交一致。
- 构建只使用缓存 Maven/Java 8 与已有 JRE base，无依赖下载；重新生成独立 `target/dependency-node-recovery-a539940`，不混入旧依赖目录。base image ID 为 `sha256:b8039096ac6396135dc864690ae785a30e6ad6d7614c6cd1f1ba180c85a56845`。
- 镜像全部 **307 文件（227 代码/资源＋80 依赖）**与本地产物逐项 SHA-256 一致。对相对路径使用 `LC_ALL=C` 排序的 `sha256sum` 清单摘要为 `f34d2af159a1f58909256fee9de365098f1d7a76458bf5a0717c28ca567e1c0b`；不能混用不同 locale 的排序摘要。
- Common 3.0.14 / bridge JAR 摘要分别为 `542d25a3c7345c2d25806fc7c975465e96ff21ac5151dd8c35f13520c006396c` / `8a22afe1bd404ca5a2613a189df9133025ebc77cca990f9a202cfcaccc899329`。新公共恢复执行器仍未因此接入服务。
- [构建定义](../tests/fixtures/trade-node-recovery-candidate/Dockerfile)与本轮实际定义一致，固定这次提交/依赖目录；不能修改源码后继续沿用旧 revision label 伪称同一候选。

生产 classes/lib 固定在镜像内。实验 helper/test classes 只读挂载，启动 helper 摘要为 `08f9107ac3182bd80b878858112841032a65bd1db1df48ba48c93f211cfead23`；实验期间没有重新编译。镜像内断网执行现金执行器、混合覆盖、整节点门禁和副本实验四类 **79 项**关键回归通过；使用实际镜像生产 classes/lib，不是仅重跑源码 Maven。源码 **349 项×2 轮**属于上一候选验收，本轮未把它重复计作镜像内成绩。

## 2. 真数据输入与隔离范围

复用有 `ISOLATED_LAB` 标记的既有副本 `/data/dc-saas-isolated-labs/trade-snapshot-P204.png2waHS/journal`：P204 约 2.0 GiB，末序号 815,788；P122 约 1.3 GiB，末序号 566,728。只打开副本，原运行目录没有挂入实验。Chronicle 可更新副本元数据，但不追加、删除或截断业务 journal。

每轮使用新输出目录；断网、1 CPU、明确 heap/container/时限。先恢复并常驻 P122，再对 P204 做 checkpoint 恢复、快照捕获、独立全日志恢复和 snapshot＋delta 恢复。P204 checkpoint=813,788，delta=2,000 条 journal（1,000 批状态）；各分区不是同一原子业务切点。

实验执行实际 `TradeRecoveryPlanner/Applier/SnapshotManager` 的既有兼容恢复路径，不启动 Spring 服务、不连接 DAO、控制面或复制 TCP。**不是对完整 256 分区、新整节点现金 API 接线、authoritative 历史基线或真实 promotion 的验收。**实验生成的 snapshot 只留在实验目录，不种入运行节点。

## 3. 本轮实测

| 预算/阶段 | 结果 |
| --- | --- |
| 1,024 MiB heap / 2,048 MiB 容器 | PASS，实验整体 149.954 秒（含多次恢复、捕获、摘要和显式 GC，不是 RTO） |
| P122 常驻恢复 | 30.474 秒 |
| P204 完整日志恢复，P122 已常驻 | 42.061 秒；阶段 GC 4.264 秒 / 217 次 |
| P204 snapshot＋delta，P122 已常驻 | 5.440 秒；阶段 GC 1.190 秒 / 12 次 |
| 快照捕获 / 业务屏障持有 | 6.212 秒 / **5.106 秒** |
| full / delta 后显式 GC 的堆占用 | 501,641,312 / 460,493,696 bytes（约 478.4 / **439.2 MiB**） |
| full / delta 阶段 20 ms 采样堆峰值 | 949,158,120 / 964,271,200 bytes（不是瞬时最大值或精确对象预算） |
| B 同等预算：384 MiB heap / 896 MiB 容器，60 秒时限 | **TIMEOUT**，含停止耗时 62.128 秒，exit=143、OOMKilled=false |

两种恢复摘要相同：`d92971371930c9d0d67b01bc9c6caa3f7d6052b60de2bc10b35c8817b06a4c1c`。计数为执行去重 691,065、余额 131、持仓 72、订单镜像 60,390、终态键 284,471；仍有 60,208 条缺状态镜像和 182 条 Suspended，未自动修复。配置记录未出现在计数中，不能据此批准历史默认值或财务/业务正确性。

384 MiB 轮在常驻分区恢复后进入 checkpoint 阶段，未在时限内完成；控制器仅停止/移除它自己创建的实验容器。不能把该结果说成已证实 OOM、泄漏或生产 RTO>60 秒。但它没有通过预算内完成门禁；1 GiB 轮 GC 后保留状态也超过 B 当前 384 MiB。两轮输入、输出与聚合证据均保留。

本机 VM 同时运行其他服务；两种预算各一轮，不是性能分布或回归归因分析。新 5.44 秒与旧 2.79 秒不具备受控重复条件，不能直接宣布代码变慢/变快。需要独立资源环境、重复阶段测量和带正常业务负载的 p99 才能评估部署影响。

## 4. 证据与可重跑入口

原始聚合报告（无账户/订单键与载荷）：本地 `.tmp-trade-evidence/snapshot-lab-combined-node-recovery-a539940-{1024,384}.json`。输出目录分别为 `/data/dc-saas-isolated-labs/trade-snapshot-run.vAxxvVCP` / `trade-snapshot-run.4TO4i95m`，没有自动删除。提交的 [结构化证据](evidence/trade-recovery-candidate-image-lab-20260929.json)包含原报告 SHA、生产产物摘要、指标和未覆盖项。

复验仍使用 `tests/run_trade_snapshot_offline_lab_host.py`，指定上述完整 image ID、副本根与当前已编译 helper；`--partition P204 --resident P122 --heap-mib 1024 --memory-mib 2048 --timeout-seconds 180 --output <全新证据路径>`。改为 384/896/60 可复验小预算门禁。控制器 **10 项安全测试**本轮通过。不得传原运行 journal 路径，不能覆盖旧报告。

2026-09-29 **10:35:40 UTC** 只读核对：Order A/B、Trade A/B、MD A/B/C、Projection 均运行、restart=0、OOM=false、仍为原镜像。实验容器已回收；没有重启服务、修改 assignment/参数、启用快照、写 SQL/历史或压测。该进程状态不证明业务可写。

## 5. 实际晋级前必须解决

1. **接管预算：**完整节点含全部 resident 分区、连接/缓存与直接内存；不能把 1 GiB 两大分区通过直接改成线上配置，也不能批准 B 的 384 MiB 接管。
2. **快照停顿：**5.1 秒屏障不能直接带正常交易量启用；先验证有界捕获/资源安排、业务 p99 与提交一致性，不取消预验证/屏障来缩短数字。
3. **可信基线与业务状态：**历史用户配置与缺状态订单仍有未证明内容；先核对来源和制定明确可审计迁移，不自动从 SQL Projection 补核心恢复，也不给旧分区造伪空快照。
4. **实际生命周期与协议：**Order/Trade/MD adapter、有界调度、replica catch-up/提交证明、旧主 fence、投递 GAP 和所有真实业务后态须完整接线；旧 SQL-first 资金路径尚未退场。

这些通过后才单节点候选晋级→小分区受控故障→大分区故障→300/16 与逐级业务 TPS。目前得到的是可核对候选产物和真实规模恢复前置证据，不是系统 HA/RTO/RPO/TPS 成绩。
