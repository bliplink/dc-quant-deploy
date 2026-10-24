# Common HA T82 → T83 实际集群双 Custody 验收记录（2026-10-24）

## 环境、边界

- 本地 Mac mini Docker 8 vCPU / 约 15.58 GiB，T82、T83 是独立 Docker Compose Project；各有独立 3 ZooKeeper JVM、Common HA A/B JVM、WAL 持久卷与网络。同一 Mac / Docker VM **不是**独立物理失效域。
- T82 使用 `compose.v19-rf2-strict-cutover.yaml` + `compose.t82-custody-receipts.yaml`。
- T83 使用相同基础 Compose + `compose.t83-fast-cutover.yaml`，并从 `target-v19-t83-fast-cutover-compiled` 注入优化后的 `DemoV19Rf2AutoStage.class`，不覆盖 T82 或 Demo Order/Trade。
- **不能把隔离 Common HA / V19 Demo 成功等同 Order、Trade、MD、Projection 正式交易验收。** 所有 times 下文采用 Docker UTC 时间戳；“严格 2/2”与“单节点降级运行”严格区分。

## 本轮代码改动与验证

`common-ha-netty-v19-control-cache/src/main/java/com/opentradingcore/demo/DemoV19Rf2AutoStage.java` 的严格恢复状态机原采用 9 秒初始延迟、每 3 秒推进一个阶段；T83 改为控制器每 1 秒调度一次，在每一阶段校验成功后立即推进下一阶段，遇到失败、不满足前提或完成 READY 即退出循环。每个阶段的 ZK Lease、CAS、Epoch Fence、物理 WAL、RSA、Custody 检查逻辑均未删除。

已完成 Java 8 `javac -source 8 -target 8` 独立编译 PASS，真实 T83 三 ZK 与 A/B Netty JVM 启动 PASS。构建覆盖目录只保存于隔离工作区，不属于 Common 正式发布物。

## T82 基线

- Epoch 3（B Primary）、Epoch 5（B Primary）、Epoch 7（A Primary）先后有严格 `READY`、双 Custody 校验及继续 ACK 的日志。
- A/B `P000.wal` SHA-256 一致；三代 Epoch 3、5、7 `receipt-quorum.bin` 在两个独立容器间大小及哈希分别一致。
- B 严格 ACK 分阶段抽样 n=26：最终 ACK median 298.5 ms，p95 548.0 ms，p99 735.8 ms，max 793 ms。**这些只是阶段日志的抽样，不是正式客户端压测分布。**
- T82 三次 `FREEZE_STAGED → READY_ACTIVATED` 分别为 34.429 s、32.966 s、34.565 s。

## T83 故障与恢复时间线（真实容器）

| UTC | 事实 | 权限与数据结论 |
|---|---|---|
| 08:55:59 | 初次对空 P000 WAL 的 A 执行 SIGKILL | B 没有越过未认证的提交前缀自动 READY；测试条件不满足；随后恢复 A |
| 08:57–08:58 | 在 A 进行 8 次 Netty APPEND；返回 `code=0`，模式 `QUORUM_DURABLE_SINGLE_HOST_TEST`，两端 WAL 840 bytes、哈希相同 | 测试驱动选择 `local` 模式与实际返回模式不符，驱动报告 8 次**模式断言失败**；不能记为 strict 客户端 ACK PASS；仅作为建立源端已证实 WAL 前缀 |
| 08:58:13 | 真实 SIGKILL A | 故障注入成功 |
| 08:58:26.947 | B 自动 staged Epoch 2 `RECOVERING` | 写入仍拒绝 |
| 08:58:32.783 | B 自动降级 `READY` | `AUTO_DEGRADED_LOCAL_DURABLE`、`quorumDurable=false`；自 SIGKILL 约 19.8s；有单机永久故障 RPO 风险 |
| 08:59:16 | 启动 A JVM，作为 learner 追平 | 再入网无脚本人工授权 READY |
| 08:59:24.435 → 08:59:47.897 | B Epoch 3 严格冻结 → 双签 Genesis / 双物理 Custody 核验 → `READY` | **23.461s**，严格双节点 `QUORUM_DURABLE` |
| 09:00–09:01 | B 严格写入 12 次，全部 `QUORUM_DURABLE` ACK，seq 8→20 | 12/12 PASS、0 失败；p50 173.735ms、p95/p99 1086.794ms；3.739 ACK/s（单 worker） |
| 09:01:28 | 对 B 执行真实 SIGKILL | 从已证实严格提交 seq20 切换 |
| 09:01:43.788 | A 自动 staged Epoch 4 | 保留 `certifiedSeq=20` |
| 09:01:48.924 | A 自动降级 `READY` | `AUTO_DEGRADED_LOCAL_DURABLE`、`quorumDurable=false`；自 SIGKILL 约 20.9s |
| 09:02:01 | B JVM 重启追平 | 原 WAL 不清理 |
| 09:02:13.339 → 09:02:35.595 | A Epoch 5 严格冻结 → 双签 Genesis / 双物理 Custody 核验 → `READY` | **22.256s**，恢复严格 `QUORUM_DURABLE` |
| 随后 | A 严格写入 12 次，全部 `QUORUM_DURABLE` ACK，seq 20→32 | 12/12 PASS、0 失败；p50 293.314ms、p95/p99 614.561ms；2.841 ACK/s（单 worker） |

这里的主切是 **集群控制器自动执行**，外部操作仅注入 SIGKILL / 启动失效容器。拒写、数据水位、双 Custody 校验必须保留。由于单 worker、每段只有 12 次请求，p95/p99 只作为该样本的描述，不能作为生产 SLA。

### 持久化最终一致性

- T83 Epoch 5 恢复并完成全部 24 次严格 ACK 后，A/B `P000.wal` 均 **3388 bytes**，SHA256 均为 `b0693434d8db185c3f9e81b52f9d2ccf0e1f4faf2ec571dd5e80313c4457ea38`，已提交末端为 seq 32。
- Epoch 3 `receipt-quorum.bin` A/B 一致：`cae990f0c331568ab82c5e95acabd78e3cc9dad76598ff8603848d5bf68b470c`。
- Epoch 5 `receipt-quorum.bin` A/B 一致：`a7ffd0b0d92d53b778b491ad41e9627f261289b74d4468f6dd5c12e6e30e50fa`。
- 最终 ZK `P000`: Epoch 5、Primary=A、Replica=B、state=READY、`QUORUM_DURABLE`、`quorumDurable=true`。
- T83 测试保留自身 Docker evidence volumes；生产 Demo Order / Trade / MySQL / MD 未作更改。

## 性能目标差距（NO-GO）

| 项目 | 目标 | 当前可审计结论 |
|---|---|---|
| 单条本地 WAL / 网络严格 ACK | 端到端 < 5–10ms | **未达标**；T83 严格客户端 ACK p50 174–293ms，p95 615–1087ms。纯 WAL fsync 与严格 ACK 不应混同，纯 WAL 单测指标还缺 |
| 批量分摊 | <1ms/条 | 本轮未完成可靠的 8/32 批次客户端分摊统计 |
| SIGKILL → 可写故障切换 | <1s | **未达标**，约 20s 才得到风险标记正确的单节点 `READY` |
| 严格 2/2 恢复冻结→READY | 越短越好 | T82 约 33–35s，T83 22.256s / 23.461s；条件不完全相同，不能当严格对照实验 |
| 单分区 1–2k msg/s、256 分区线性扩展 | 目标 | 单 worker 严格写仅 2.84–3.74 ACK/s；未做全并发、256 分区合规压测 |
| 10 / 50 / 200 租户、2–3x burst | 稳态/突发 | 本轮未开始 |
| Order/Trade/MD 真实资金/持仓/委托/成交/Projection 账本对账 | 严格一致 | 本轮未开始 |

## 交付阻塞（必须收口）

1. 在实际工作树中，T82 运行使用的 Common 新类 `DurableWalCustodyReceiptLedger` / `DurableWalCustodyReceiptControlHandler` **仅见隔离 `target-v19-strict-cutover-compiled` 的编译 .class**；`common-upstream-review-20261022/target/com.app.common-3.0.22-SNAPSHOT.jar` 未打包这两类，搜索到的本机 Common 源码目录也未找到对应 Java 源文件。必须找回可审计源码、完善测试并重新构建正式 Common JAR；不能以隔离 class 覆盖代替生产代码交付。
2. 最大延迟仍在持久证书生成、双物理 Custody 回执归档、验证 / 控制平面与 fsync 组合。进一步拆解阶段 p50/p95/p99，优化严格 ACK 热路径网络请求、磁盘组提交和恢复状态机，绝不省略真实多数/旧主撤权。
3. 新建隔离测试循环完成 SIGKILL→AUTO_STAGE→DEGRADED_READY→追平→严格双回执→严格 READY→重启重复，并注入单回执、签名篡改、陈旧 Epoch、ZK quorum 损失等拒绝测试；当前 T82/T83 中已验证的是正常双回执及双向故障流程，不能声称全部负面测试通过。
4. Common 正式化后，再统一 Order/Trade/MD 接入、Demo 发布、非零余额/持仓真实交易中双向自动主切与权威对账。用户要求优先完成机制，不扩新功能；本地 Maven/Docker，不使用 GitHub Actions。

**总状态：隔离 Common RF2 双向自动主切及双 Custody 机制局部 PASS；整体 HA 与性能目标 NO-GO。**
