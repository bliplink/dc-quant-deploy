# Trade 快照小写入优化：屏障停顿副本验证

日期：2026-09-29。Trade 源码提交 `ce38b04e805914f929a8694df6f67aec13c585ec`；**本地候选与隔离副本验证，未部署/启用运行快照或做故障切换。**

## 1. 改动及安全边界

原 `TradeSnapshotStore` 直接把每条 JSON、字段名和分隔符写入 `FileOutputStream`。实时去重流包含大量条目，产生很多小写入，且位于 snapshot manager 的分区业务屏障内。

本轮添加固定 **64 KiB** 写缓冲， retained / live-stream 两种保存统一到同一路径。不是整文档 JSON 缓存，不复制完整实时去重 DTO 表；大单条实体可直接穿过缓冲，现有实体限制不变。

保存顺序仍是：校验/manifest → 写 tmp → **排空缓冲** → file descriptor sync → 文件关闭 → 原有原子替换/fallback → best-effort 目录 sync → 清 metadata cache。写入/flush/序列化失败不替换 latest。原 fsync、格式、恢复预验证、dirty-tail 与覆盖门禁均未降低；不宣称 power-loss 或 RPO=0。

**没有把实时表遍历移到锁外。**在没有不可变时点镜像的条件下，锁外读会混合不同已提交坐标。业务对象、费用/PnL/保证金公式、现金 admission、SQL writer、归属和复制协议均未改变。剩余屏障停顿仍需专门设计有界冻结/捕获与业务负载验证，不能直接绕过锁。

## 2. 测试与产物来源

- Java 8、缓存依赖、断网全量：**67 类 / 356 项**通过，零失败/错误/跳过。本轮新增 7 项，包含 Unicode 字节等价、流式无 DTO 列表、固定缓冲、大实体 bypass、write/flush 失败与未关闭调用方 sink、部分 tmp 写入后保留旧 latest/cache/pinned descriptor、重试替换成功。
- 4,000 条合成 retained 图像：680,981 bytes，delegate write 从 **16,042 降至 11**；live stream：616,981 bytes，**32,038 降至 10**。这是确定性 sink 调用数，不是内核 syscall/TPS 或磁盘吞吐。
- 候选镜像 `local/tradesvr:snapshot-buffer-ce38b04`，Linux arm64，固定 ID `sha256:d6e7781eaf8368cccd34ea5935d30bbf129379a90663584ba51cc9e567d5babd`；revision label 与源码一致。使用独立新依赖目录和缓存 base，未推送。
- 全部 **307 文件（227 代码/资源＋80 依赖）**与本地产物摘要一致；标准 `LC_ALL=C` 相对路径清单 SHA 为 `2af50c729c7525b1453818c97dc30f88088d7a0db7abe1a920506d26366da645`。与上一镜像只有 Store 及其 3 个嵌套 class 变化（含行号元数据），其他 **303 文件一致**，80 个依赖无变化。
- 镜像生产 classes/lib＋只读挂载测试类，断网执行 **5 类 / 86 项**关键回归通过。本轮未重复执行 Projection 数据库实验；现金生产协议/消费者源码均未变化。
- [固定构建定义](../tests/fixtures/trade-snapshot-buffer-candidate/Dockerfile)，仅对应此提交与 `target/dependency-snapshot-buffer-candidate`；不能改源码后沿用旧 revision label。

## 3. 同一真实副本复验

沿用带 `ISOLATED_LAB` 标记的 P204/P122 既有副本，约 3.3 GiB。P204 末序号 815,788、checkpoint 813,788、增量 2,000 条 journal；P122 末序号 566,728，先恢复并常驻。实验独立新输出目录、断网、1 CPU、1,024 MiB heap / 2,048 MiB 容器、180 秒时限。原运行数据未挂入，不截断/追加日志、不种快照到节点。

| 阶段 | 上一轮未缓冲 `a539940` | 本轮缓冲 `ce38b04` |
| --- | --- | --- |
| 快照捕获总阶段 | 6.212 秒 | **3.039 秒** |
| 分区业务屏障持有 | 5.106 秒 | **2.067 秒** |
| P204 全日志恢复（P122 已常驻） | 42.061 秒 | 39.396 秒 |
| P204 快照＋增量（P122 已常驻） | 5.440 秒 | 5.052 秒 |
| delta 恢复后显式 GC 的堆 | 460,493,696 bytes | **460,795,432 bytes，约 439.4 MiB** |

本轮 PASS，完整实验 139.420 秒，exit=0、无 OOM/超时；包含多次恢复、快照、摘要与显式 GC，**不是故障 RTO**。快照 100,473,484 bytes。两种恢复摘要仍为 `d92971371930c9d0d67b01bc9c6caa3f7d6052b60de2bc10b35c8817b06a4c1c`，与上一轮相同。

屏障单轮观测降低约 59.5%；同机共享资源、每个候选各一轮，不是 p99 或统计性能结论，不能把其他恢复阶段差异全归因于缓冲。相同的 helper 摘要 `08f9107ac3182bd80b878858112841032a65bd1db1df48ba48c93f211cfead23`，输入/预算相同，不改变比较范围。

状态计数仍是执行去重 691,065、余额 131、持仓 72、订单镜像 60,390、终态键 284,471；60,208 条缺状态镜像未修复，历史用户配置未被证明。状态相同可以包含同样的旧业务问题，不是资金/订单正确性验收。实验仍用实际 planner/applier/manager 的兼容路径，不是完整节点现金 API、Spring 启动、TCP、control plane 或 replica promotion。

## 4. 证据与后续门禁

本地原报告：`.tmp-trade-evidence/snapshot-lab-combined-write-buffer-ce38b04-1024.json`，SHA `2a541e1c18afd48876374937c40827c37e8f854f65f731a282bfbd7649c073d0`；输出留在 `/data/dc-saas-isolated-labs/trade-snapshot-run.m9SSzCZJ`。临时实验容器已回收，输入/输出均保留。提交的 [结构化证据](evidence/trade-snapshot-write-buffer-20260929.json)记录新旧报告来源、镜像 diff、测试、指标与未验收项，不含原始业务载荷。

2026-09-29 **10:51:31 UTC** 只读核对 8 个 Order/Trade/MD/Projection 容器仍运行、restart=0、OOM=false，镜像未变；不证明业务可写。未修改其参数、assignment、SQL/历史、周期快照开关或进行压力/故障注入。

下一步：把剩余捕获阶段拆分测量，评估有界冻结/序列化/IO安排并带正常业务核对 p99；同时完成整节点（不是两大分区）接管资源预算与可信历史基线，再接入实际生命周期/受控切换。**2.067 秒屏障仍不能直接批准周期快照或 TPS 晋级。**B 的 384 MiB 接管预算没有通过；本轮未重测 384 MiB，不把旧镜像的 TIMEOUT 伪称新镜像测试，但约 439 MiB 保留状态仍不支持批准该预算。
