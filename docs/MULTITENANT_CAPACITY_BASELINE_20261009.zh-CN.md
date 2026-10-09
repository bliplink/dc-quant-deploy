# Mac mini SaaS Demo：12 租户资源基线（2026-10-09）

## 采样环境

- 用户目前的 Mac mini / Colima VM，之前分配约 8 CPU、16 GiB VM 内存；当前资源基线未更改虚拟机资源、没有重启交易核心。
- 已实际核验 12 条租户流动性 Bootstrap 为 `COMPLETE/DONE`，12 个 RUNNING Robot 各 40 单；另外 1 条 QA Robot `STOPPED/0`。
- 仅从 Docker `stats --no-stream`、Linux `/proc/pressure/{cpu,memory,io}` 和 `MemAvailable` 读取资源，**不是实际交易 TPS 或 200 租户压力测试**。

## 结果

| 指标 | 样本（短时间观察，不等于压力测试结论） |
|---|---|
| CPU PSI some avg10 | 49.44%，随后 47.24% → 30.61%（约 10 秒差） |
| CPU PSI some avg60 | 约 49% → 44.78% |
| CPU PSI some avg300 | 约 39–40% |
| memory PSI some/full avg10 | 0.00% |
| I/O PSI some/full avg10 | 0.00% |
| MemAvailable | 约 4.0 GiB |
| RobotSvr CPU | 69.27% → 73.30%（Docker 相对单核百分比） |
| RobotSvr RSS/内存使用 | 约 371 MiB / 1 GiB |
| OrderSvr B | 约 2.22 GiB / 3 GiB，CPU 16.60% → 24.20% |
| OrderSvr A | 约 1.30 GiB / 3 GiB，CPU 16.72% → 7.96% |
| ZooKeeper | 约 108 MiB / 384 MiB，CPU 16–18% |
| MySQL | 约 1.22 GiB / 1.5 GiB，CPU 11.24% → 6.47% |
| ProjectionSvr | 约 357 MiB / 768 MiB，CPU 2–4% |

CPU PSI some 表示采样窗口存在至少一个可运行任务因 CPU 等待被延迟；它**不意味着整台虚拟机 49% 时间完全空转或饱和**。在 12 租户运行条件下观察到显著 CPU 调度竞争，而没有对应的内存 PSI / I/O PSI 尖峰；不支持将当前主要问题直接归因于写数据库或磁盘阻塞。

## 验证的正确性底线

- Order HA 节点/分区/快照与路由一致，无 OOM 或重启。
- Projection `orphan_mutations=0`、`trade_watermark_tail_mismatch=0`、`order_watermark_tail_mismatch=0`。
- Robot 12 RUNNING/40，隔离 QA Robot 停止/0；Tape 初始化失败 0。

## 下一步性能优化优先级

1. **RobotSvr CPU 分析**：按租户记录报价刷新次数、幂等撤单/重报次数、主动 Tape 成交频率、重试次数和单轮周期，结合线程栈/CPU profiler 找到热点；尽可能减少重复行情转换、订单差量计算及无效请求。
2. **Order 与 ZooKeeper 调度分离**：采集 1–5 分钟的 CPU PSI、JVM GC 停顿、线程阻塞、ZK session 心跳与 I/O PSI 对齐时间线。先证实共同停顿根因，不凭日志空档推断某个节点断网或 MySQL 写入。
3. **资源护栏**：保留同步副本及 fencing；不能因 `Demo=1` 就默认关闭 Order 复制或 WAL（涉及 HA 一致性语义，需要隔离故障验收）。
4. **循序扩容**：确认当前 12 租户持续报价/成交、管理 API 和前端响应正常后，20 → 50 → 100 → 200 分档，各档按真实业务 `Order` 请求与执行记录分别计量 TPS、P95/P99、CPU/内存/PSI、Robot 心跳、Projection watermark、故障恢复。出现重启、OOM、盘口空白或一致性差异立即停止。

本轮尚未对 JVM、Docker 资源分配、ZooKeeper 配置、Robot 配置或生产数据做任何变更。此文档是容量压测的**基线与优化计划**，不能视作系统已达到 50 或 200 租户能力。
