# Trade 快照恢复 F1 验证记录

日期：2026-09-29。范围：降低快照恢复额外内存、补齐低频分区首快照候选门槛。未做新的业务压测、故障注入或现有节点重启，未清理真实 journal、数据库或快照。

后续真实 journal 副本实验、近尾 seek、双分区容量与订单镜像业务门禁见 [真实日志副本验证](TRADE_REAL_JOURNAL_RECOVERY_LAB_20260929.zh-CN.md)。下面保留 `083e1c8` 阶段的版本和测试基线，不把后续结果混入旧候选镜像。

源码提交：Trade `083e1c8832e8cf6287065f3767d66edffe190359`（本地提交，未推送）。

本地候选镜像：`local/tradesvr:recovery-stream-083e1c8`，Linux arm64，image ID `sha256:9781936cd58e71d20e3dfe74a3e3a060c37d4b67ffa6b81dac5eb7564b0b06de`。**尚未部署、未发布到镜像仓库**。内置 DC Common 依赖与现有 Trade 运行依赖一致，JAR SHA-256 为 `8a22afe1bd404ca5a2613a189df9133025ebc77cca990f9a202cfcaccc899329`；未混入尚未适配服务的新公共恢复原语。

## 已实现

1. `TradeSnapshotStore.openRecovery` 打开并固定快照文件描述符，解析元数据与非去重业务状态；执行去重/终态订单逐条扫描。文件原子替换后，原恢复计划继续使用原文件，避免验证与安装读到不同快照。
2. Applier 在修改运行状态前验证全部去重记录的类型、location/分区归属及快照 location 索引，并预验证 committed delta；随后在业务分区屏障内安装快照和重放增量，复核 assignment/epoch。文件句柄在成功、失败和未进入安装的旧计划路径关闭。
3. 清理单 location 的旧去重状态不再复制全局键列表，并移除该 location 的旧淘汰队列记录，防止同名恢复值被旧队列项提前淘汰。其他租户保持原状态。
4. 首次观察到无快照但有已提交变更的分区后启动年龄计时；提交数量或 `maxAgeMillis` 任一门槛满足时可成为快照候选。失败保留计时，成功/无待处理变更/角色丢失清除计时。原有全本地主 READY 门禁、单候选执行和数量优先策略保留。

## 隔离测试结果

运行环境：缓存 Java 8/Maven 容器，容器限制 1 CPU/1 GiB。测试数据全为临时目录中的合成数据，无集群连接。

| 项目 | 结果 |
| --- | --- |
| Trade 全量单元测试 | 49 个测试类，191 个用例，0 failure / 0 error / 0 skipped |
| 候选镜像内关键回归 | 使用镜像内生产 classes/lib 与只读挂载测试类/JUnit，断网运行 27 个用例，全部通过；不是服务启动或连接集群验收 |
| 合成快照 | 83,219,194 bytes（约 79.4 MiB）；10,000 条去重结果，每条消息 8,192 字符 |
| 子进程堆限制 | `-Xms16m -Xmx64m`；实际报告最大堆 64,880,640 bytes |
| 原 `load` 整份读取 | 可复现 Java heap OOM；属于测试预期，不是服务 OOM |
| 新恢复读取 | 成功读出紧凑核心状态，再完整扫描去重记录两遍；计数均为 10,000 |
| 新方式合成读取耗时 | 约 1.8–1.9 秒；不含业务状态安装、journal 重放、网络、初始化或切主，不是 RTO/TPS |

新增回归覆盖：UTF-8/转义字符、旧字段顺序与空集合、文件原子替换、重复/缺失元数据、格式损坏、超大单记录、非法跨 location 记录不修改运行状态、恢复去重/终态订单拦截、保留其他租户、首快照年龄/失败重试/角色丢失、拒绝未来 epoch 后关闭文件句柄、旧淘汰队列不淘汰恢复同名键。

复现命令（Trade 源码目录，Java 8）：

```sh
mvn -q test
mvn -q -Dtest=TradeSnapshotRecoveryTest,TradeSnapshotRecoveryMemoryTest,TradeRecoveryApplierTest,TradeRecoveryPlannerTest,TradeSnapshotSchedulerTest,ExecutionDeduplicatorTest test
```

## 限制与晋级门禁

- 只减少去重解析/中间 DTO 的额外内存，**不保证完整服务能使用 64 MiB 堆**。核心业务状态暂时仍保留列表，安装后的去重运行表必须计入堆预算。
- `trade.cluster.snapshot.recovery.maxEntityBytes` 默认 4,194,304 bytes，限制单条业务实体/去重记录解析大小；超限时拒绝恢复，不截断或跳过记录。字段名/元数据及核心状态总量不由此限制；需按实际状态容量配置和验证。
- 文件固定依赖已有快照写入的临时文件加 rename 协议；禁止外部原地修改恢复中的文件。新 snapshot/journal 格式未升级，旧整份 `load` 仅保留兼容入口，实际恢复 planner 不再使用它。
- 首快照达到年龄只表示进入候选；其他恢复未就绪、繁忙候选或捕获失败仍可能推迟执行。公平调度/内存与 IO 预算是后续工作，不能宣布所有分区有硬时限。
- 当前 Trade A/B 的周期快照仍关闭。本轮只读核查均 running、0 restart、`OOMKilled=false`，仍是原进程。A 当前 768 MiB 堆不证明 B 的 384 MiB 堆能接管其大分区。
- Order/Trade 的确认与降级提交语义未改变；未证明 RPO=0、自动异常接管、业务可写或 MD 序列连续性。公共恢复原语仍未集成服务，MD 继续列在首批适配范围。

本轮只读证据：本地 `.tmp-trade-evidence/recovery-baseline-stream-code-20260929.json`，采样时间 2026-09-29 08:58:05（+08:00）。256 个 assignment 为 READY，观察前后归属未变化；A/B 各 128 个本地主分区有当前 epoch 的进程 READY 日志证据，均 0 个快照。A/B 仍为原运行版本 `sha256:a74092669b0cee679c6be25ab8212d42497660e627b0c685d5c0750954571e51`。日志 READY 不是经认证的业务可写验证。

下一步：使用已固定的候选镜像/依赖和隔离目录验证真实规模快照捕获的峰值内存/屏障耗时，以及加载、安装、去重容量和增量恢复；通过后再单服务晋级并低频启用 Trade 周期快照。之后才做小分区异常演练、大分区接管及分级 TPS 测试。
