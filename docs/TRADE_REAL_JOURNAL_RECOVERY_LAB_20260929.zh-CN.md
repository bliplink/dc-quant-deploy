# Trade 真实日志副本：恢复、容量与订单镜像验证

更新：2026-09-29。主线仍是集群底座、异常恢复、压测与稳定性。**本记录不代表完成自动切换、系统 TPS 或业务 RPO 验收。**

最新镜像复验：`a539940` 候选实际生产 classes/lib 已构建并逐项核对；镜像内 79 项关键回归通过。同一副本的 1 GiB 轮摘要一致，P204 full/delta（P122 常驻）为 42.061/5.440 秒，GC 后约 439 MiB、捕获屏障 5.106 秒；384 MiB 轮在 60 秒限额内未完成，非 OOM。环境共享资源、各预算单轮，不能把与下文旧数值的差异归因为代码回归；历史业务缺口未修复，完整节点/真实切换仍未验收。详见 [本轮不可变候选产物与恢复门禁](TRADE_RECOVERY_CANDIDATE_IMAGE_LAB_20260929.zh-CN.md)。

## 1. 结论和运行边界

- P204 的近尾增量不再从 journal 头部扫描：同一份复制日志，单分区快照增量恢复从约 8.34 秒降至 2.06 秒；完整状态摘要一致。
- P204 + 常驻 P122 的恢复状态，显式 GC 后仍占约 439–477 MiB 堆。B 当前的 384 MiB 堆不能据此被批准接管这两个分区；实验尚未覆盖完整节点的其他分区、启动缓存、线程、连接及直接内存。
- 双分区实验在 768 MiB 堆下增量恢复约 7.43 秒，其中 GC 约 5.64 秒；1 GiB 堆下约 2.45 秒，GC 约 0.53 秒。恢复耗时受内存余量影响，不只是磁盘/TCP。
- 快照捕获的分区屏障仍持有约 1.7–2.2 秒，必须带正常交易请求量测 p99，不能仅打开定时快照就宣布解决恢复问题。
- 发现订单镜像业务语义问题：成交片段缺失 `OrdStatus`、`OrderQty`、`Price`，却被保存为活动单。P204 完整副本中有 49,819 条这样的最终镜像，沿本地提交历史推导剩余量均为零。这个推导不是权威订单/资金对账，也不是清理授权。
- 已补新交易路径的订单镜像维护和回归测试；不重算资金，不改旧日志重放语义，不自动清除历史记录。另已禁止 authoritative 模式在 OrderSvr 重连时走锁外全局订单缓存清空/重载。

运行环境未切换：Trade A/B 仍为原镜像 `sha256:a74092669b0cee679c6be25ab8212d42497660e627b0c685d5c0750954571e51`。本阶段没有线上重启、故障注入、压力入场、assignment 修改或周期快照开启。也没有删除/截断真实 journal、snapshot 或 SQL 数据。

只读复核证据：`.tmp-trade-evidence/recovery-baseline-after-isolated-labs-20260929.json`。A/B 各 128/128 个本地主分区有当前进程 READY 日志证据，快照仍为 0；启动到最后 READY 仍是 A 128.802 秒、B 79.969 秒。日志 READY 不证明业务可写，启动时间不是异常切换 RTO。

## 2. 实验隔离与输入

实验仅在本地 Colima 的独立目录执行，容器断网、1 CPU，固定本地 image ID。源 journal 在复制时只读挂载，实验只打开副本；Chronicle 元数据可能更新，所以副本挂载可写。未把原服务数据挂入实验容器。

- 复制根目录：`/data/dc-saas-isolated-labs/trade-snapshot-P204.png2waHS`，带 `ISOLATED_LAB` 标记。
- P204 副本最后序号：815,788；快照 checkpoint commit：813,788；增量为 2,000 条 journal 记录，即 1,000 个 state batch。
- P122 副本最后序号：566,728，作为常驻分区与 P204 共享真实恢复状态表。
- P204 与 P122 分别复制，不是跨分区的原子业务切点。实验检查副本连续性及本地 clean committed tail，不证明网络复制的 ACK 或 RPO。
- 快照大小：100,473,484 bytes，约 95.8 MiB。每次使用新输出目录，不截断副本、不追加业务事件、不种入运行节点。

恢复比较覆盖内存中的余额、持仓、账户/品种配置、订单镜像、执行去重结果和终态键：实体数 + JSON 的 SHA-256 多重集合摘要。旧 journal 副本的两种恢复方式可以一致地恢复同一个语义错误，因此 `stateEquivalent=true` 不能代替业务正确性验证。

## 3. 实测结果

| 范围/候选 | 堆/容器 MiB | 全日志恢复 | 快照 + 增量 | 状态摘要 |
| --- | --- | --- | --- | --- |
| P204，流式快照 `083e1c8` | 768/1536 | 20.148 s | 8.336 s | 一致 |
| P204，流式快照 `083e1c8` | 384/896 | 20.790 s | 16.601 s | 一致；仅单分区 |
| P204，近尾 seek `33fbc70` | 768/1536 | 19.615 s | 2.061 s | 一致 |
| P204 + P122，seek + GC 观测 | 768/1536 | 22.443 s | 7.433 s | 一致 |
| P204 + P122，seek + GC 观测 | 1024/2048 | 22.041 s | 2.453 s | 一致 |
| P204 + P122，新订单镜像候选 `d16ee1c` 的旧副本兼容性 | 1024/2048 | 23.257 s | 2.791 s | 与旧候选摘要一致；不修复旧记录 |

双分区 GC 观测：

| 堆 MiB | 增量恢复期间 GC | 恢复后显式 GC 的堆占用 | 捕获屏障持有 |
| --- | --- | --- | --- |
| 768 | 26 次 / 5,641 ms | 490,543,912 bytes，约 467.8 MiB | 2,027 ms |
| 1024 | 12 次 / 527 ms | 499,858,184 bytes，约 476.7 MiB | 1,960 ms |

新订单镜像候选的兼容复测：增量恢复 GC 12 次 / 573 ms；显式 GC 后 460,480,176 bytes，约 439.1 MiB，捕获屏障持有 2,128 ms。采样值随 JVM/GC 状态有变化，不能当成精确对象容量；该轮仍明显超过 B 的 384 MiB 堆预算。

显式 GC 在计时的恢复阶段之外执行，报告分别记录其耗时。GC 后堆占用包括实验上下文，不等于精确业务对象占用，也不是完整服务容量；但已明显超出 384 MiB 的预算。阶段峰值是 20 ms 采样值，不保证抓到瞬时最大值。两轮资源对比为本地暖副本单次测量，未作统计显著性或生产容量结论。

双分区最终计数：执行去重 691,065，余额 131，持仓 72，订单镜像 60,390，终态键 284,471；摘要为 `d92971371930c9d0d67b01bc9c6caa3f7d6052b60de2bc10b35c8817b06a4c1c`。其中 60,208 条镜像缺少订单状态，182 条是 Suspended。

旧候选的 384 MiB 双分区实验在约 222 秒后人工停止，退出码 143、`OOMKilled=false`，未完成 P204 checkpoint 恢复。该结果是预算内未完成，**不是已经证实的 OOM 或内存泄漏**。新控制器自动按期限停止它自己创建的唯一实验容器，分别记录 TIMEOUT、CGROUP_OOM 和 FAILED；不触碰服务容器。

原始聚合证据保留在本地 `.tmp-trade-evidence/`，不提交原始业务载荷：

- `snapshot-lab-p204-768.json`、`snapshot-lab-p204-384.json`
- `snapshot-lab-p204-seek-768.json`
- `snapshot-lab-combined-seek-gc-768.json`、`snapshot-lab-combined-seek-gc-1024.json`
- `snapshot-lab-combined-order-image-gc-1024.json`
- `order-history-audit-p204.json`、`order-history-audit-p122.json`

## 4. 订单镜像问题与已补代码

来源链路：Order 的 `TradeExecOrder.Trade` 使用 `Utils.createExecutionReport(ExecOrder)` 构建成交片段；此时订单终态通常尚未设置，原始总数量/委托价也没有进入该 DTO。Trade 原先直接把片段存入 OrderManager，并把同样片段写入 `OPEN_ORDER UPSERT`。缺失状态既不会删除活动单，也不会建立 Filled 的终态去重键。

另一条风险是 `OrderManager.init` 的连接回调：它异步全局 `clear()` 后查询所有 Order primaries，不经过分区屏障和 journal，可覆盖已经恢复或正在交易的缓存。authoritative 模式已停用这条回调，保留 OrderSvr client 供正常业务请求；非 authoritative 模式保留旧行为。

新交易路径按以下契约维护镜像：

1. 在现有分区/订单生命周期屏障内，先查执行幂等结果，再准备订单镜像。重试先返回原结果，不再次累加成交量。
2. 只在同 location/user/order/security、可靠原始总量/累计量/委托价及有效执行 ID 存在时推导新累计量和剩余量；保留入场元数据，覆盖本次提供的成交字段。
3. 资金检查/处理仍接收**原始成交片段**；镜像只在处理成功后安装。失败不推进订单量、不标记成功、不写成功 journal。
4. 部分成交记录完整镜像，全部成交记录 `OPEN_ORDER REMOVE` 和 Filled 终态去重。原状态格式版本不升级，recovery applier 不对旧记录重新推导。
5. `trade.orderImage.requireBaseline=false` 是兼容默认值：缺基线、不合法数量或超量时保留旧路径并计数/限频告警，不猜测终态。设置为 `true` 后，在资金处理前拒绝这些无法解释的缺状态片段。**尚未在运行节点开启；开启前必须完成历史权威对账与迁移门禁。** 已带明确状态的回报沿用原路径，此开关不是所有订单生命周期不变量的总验证器。

离线历史审计仅按 Newing 基线和后续 Trade 数量分类：P204 的 49,819 条缺状态 Trade 镜像均归为 `INFERRED_ZERO_REMAINDER`。不会导出订单/账户键，也不会据此写 REMOVE、Filled 或资金记录。需要核对权威 Order committed 状态、活动单/成交/撤单链路与资金效果；不能用 SQL 投影中“没有活动单”替代提交证明。

P122 副本审计补充：最后序号 566,728，最终订单 mutation 键 10,425，其中缺状态 Trade 10,389 条，全部归为 `INFERRED_ZERO_REMAINDER`。两分区合计 60,208 条，与恢复摘要中缺状态镜像总数一致；仍只是本地提交历史的数量推导。该审计使用新候选 image，启动时实验类摘要为 `08f9107ac3182bd80b878858112841032a65bd1db1df48ba48c93f211cfead23`。

## 5. 代码、镜像与复现

Trade 本地提交：

- `33fbc70`：近尾 journal seek、tailer 关闭与隔离实验。
- `b51abc5`：GC/回收后堆观测、dirty tail 拒绝回归。
- `c2328e5`：authoritative 订单缓存不再随连接全局重载。
- `b52829c`：缺状态镜像和提交历史只读审计。
- `d16ee1c5fd0d704614b7311dc610194492351bcd`：新交易完整订单镜像、严格基线可选门禁、真实 CQ 恢复回归。

本节实测使用 `local/tradesvr:recovery-seek-33fbc70`，image ID `sha256:eec28625c141df44752f2b81ce63e5e8b1f432da2bcf1c898eb34a38e2b1dc4f`。生产 classes 截止 `33fbc70`，只读挂载较新的离线测试类；因此**该镜像不包含后续缓存重连/订单镜像修复**。桥接 DC Common JAR 与原 Trade 依赖一致，SHA-256 为 `8a22afe1bd404ca5a2613a189df9133025ebc77cca990f9a202cfcaccc899329`；未发布或部署公共恢复新版本。

新本地候选：`local/tradesvr:recovery-order-image-d16ee1c`，Linux arm64，image ID `sha256:b22b83a163a8e08c36ddfeab90bcccd74923012670dbc2e33efd855ee03afa53`，revision label 为完整 `d16ee1c` 提交。包含缓存重连与新交易镜像修复；使用同一 bridge JAR。没有推送或部署。源码全量 54 个测试类 / 212 个用例通过，0 failure/error/skipped；隔离控制器 10 个用例、原只读基线 6 个用例通过。镜像内生产 classes/lib 与只读测试类断网运行 37 个关键用例通过；不是 Spring 服务启动或连接集群验收。

执行器入口 `tests/run_trade_snapshot_offline_lab_host.py`：只接受固定 image ID、P000–P255、有标记且 canonical 路径不逃逸的隔离副本、有限内存/CPU/时间和新证据文件。输出目录及副本保留用于追溯，不自动删除。

新报告记录启动时主实验类及其嵌套类的 SHA-256 摘要，区分生产 image 与挂载实验代码；不伪造补写旧报告的启动摘要。实验期间不要重新编译挂载目录，当前记录是启动观测而不是挂载文件的原子冻结协议。

复现示例（已准备复制数据和对应编译测试类；输出文件必须是新路径）：

```sh
python3 tests/run_trade_snapshot_offline_lab_host.py \
  --image sha256:eec28625c141df44752f2b81ce63e5e8b1f432da2bcf1c898eb34a38e2b1dc4f \
  --journal-copy-root /data/dc-saas-isolated-labs/trade-snapshot-P204.png2waHS/journal \
  --test-classes /Users/kong/Documents/Codex/.webcodex-managed-worktrees/tradesvr-rebuild-common314/target/test-classes \
  --partition P204 --resident P122 --heap-mib 1024 --memory-mib 2048 \
  --timeout-seconds 180 --output .tmp-trade-evidence/new-combined-recovery.json
```

提交历史审计用 `--mode order-history-audit`，不传 `--resident`。审计的 PASS 仅表示扫描和报告完成，不表示所发现的业务状态通过验收。

测试包含：近尾恢复有界读取/顺序/GAP、dirty tail 不截断、隔离根/镜像/预算/超时控制、审计不泄露键、authoritative 重连保护、部分/全部成交、拒绝/重试/迟到 Newing、跨租户/品种、非法数量/缺执行 ID、真实 CQ recorder→planner→applier 的完整镜像/余额后状态/去重恢复。真实 CQ 回归的资金处理为合成桩，不是手续费/PnL 公式验收。

## 6. 后续顺序与晋级门禁

1. 固定新订单镜像修复的提交及不可变候选；先做镜像内回归与旧副本兼容恢复。原节点保持不变。
2. 把历史异常订单镜像与权威 Order 提交状态核对，形成可审计、可回滚的补偿方案；禁止删除日志或直接改 SQL“重置”。只读推导不自动生成线上终态。先验证订单镜像及冻结量/资金计算业务正常，再批准数据迁移或开启严格基线门禁。
3. 对完整节点容量和快照屏障评估，规划 B 接管大分区所需资源；不要把 1 GiB 两分区实验直接变成线上 heap 配置。
4. 完成以上门禁后，才单服务晋级、低频快照和 300/16 基线；然后小分区异常→大分区异常→负载下切换。每阶段核对 ACK、epoch、订单/资金和 MD 序列。
5. 公共恢复执行器继续补有界调度/资源预算/取消退避，再按 Order、Trade、MD 三种适配交付；MD C 的 learner/catch-up/接管仍在计划中。三服务均须经过异常而不只是正常 role reversal 验收。

系统 TPS、故障 RTO/RPO、跨故障域 HA 和 24/72 小时长稳仍未测得，不从本实验推导。
