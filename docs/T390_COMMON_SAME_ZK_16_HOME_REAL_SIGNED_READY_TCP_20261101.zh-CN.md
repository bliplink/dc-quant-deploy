# T390｜Demo+Common 同一真实 ZooKeeper 集群连续 16 Home 物理回切 PASS

日期：2026-11-01（Mac 本地 CST）。本轮**只使用隔离 Demo+Common**；线上 Order/Trade、Gateway、Projection、Robot 不重启、不更新、不中断、不清理数据。

## 一、与以往单分区测试的实质区别

- 基准：原业务 Common T143 源码；新增的真实冷控制优化候选 JAR `.work/t374-demo-common-ha/target/t389-common-cold-watch-proof-first.jar`，SHA-256 `6b4418f7b1373bb68a9fac4c79aa4406001e1699ec6d9dd080c83323110e2eae`。**尚未部署到 Order/Trade。**
- 本次 **只创建一次** 3 节点独立 ZooKeeper Compose、一个固定 256 分区 manifest、一个 A Docker JVM、一个 B Docker JVM。通过 `OTC_T390_HOME_PARTITIONS` 在两个进程内部保持同一 ZooKeeper 连接/EPHEMERAL lease，顺序遍历 P000–P015，而不是每切一个分区就关机重建 ZK 或重新发布一份初始 manifest。
- **所有 WAL、Custody、退休 RSA、签名 Stage、E3 Image、REPLAY_COMPLETE、双恢复 RSA、E3 TCP WAL** 都落在每个 `Pxxx` 自己的 `a/shards/Pxxx` 和 `b/shards/Pxxx` 物理目录。即便第二次及之后的恢复发生在同一 JVM，也不能覆盖上一分区证明。
- A/B 在下一分区开始前，从**同一真实 ZK manifest** 核验所有已回切分区仍为 `A E3 STRICT READY`；其余待回切原始 A Home 仍 `B E2 READY`、B 原始 Home 仍 `B E1 READY`。任何已成功分区角色回退/状态变化、无凭据就绪、多个同时 RECOVERING 都失败。
- 每一步仍运行 128 个 Common Home Watch，127 个无当前物理签名证明，必须 fail closed；唯有目标分区可通过原来的物理 2/2 CommitIndex/Custody、旧 Epoch 双退休、E3 双签 Image、StateMachine REPLAY_COMPLETE 和恢复双 RSA，并自动发布独立的严格 READY CAS。
- 同一固定 B 会话持续服务旧所有权的控制面；A 同一固定会话连续恢复后续分区。每个目标分区用 Common 正式 TCP/Netty 写入与 2/2 `QUORUM_DURABLE` ACK。A/B 两个 JVM 退出后，第三独立 JVM 仅使用公钥和原始磁盘数据，按 Pxxx 各自验证新的 E3 双份 WAL、CommitIndex/Custody 和真实 ACK 内容。
- 辅助测试跨 JVM 签名文件通过**fsync 后原子发布**，新增「双签 Image 已完整落盘且再次 reopen」标记，防止另一个 JVM 读到仅创建了 Snapshot 但尚未写完 `genesis-e3.quorum` 的半证据。该辅助标记并不绕过正式 Common 原始 RSA/Quorum 验证。

## 二、当前真实验收证据

运行入口：

```bash
python3 tests/run-t376-isolated-common-zk-stage.py \
  --mode home256-signedwatch \
  --home-partitions P000,P001,P002,P003,P004,P005,P006,P007,P008,P009,P010,P011,P012,P013,P014,P015 \
  --all-home-watch-pressure \
  --candidate-jar-name t389-common-cold-watch-proof-first.jar \
  --worktree .work/t374-demo-common-ha \
  --base /Users/kong/.opentradingcore/t177-common-saas-crypto-integration-20261027 \
  --expected-sha256 6b4418f7b1373bb68a9fac4c79aa4406001e1699ec6d9dd080c83323110e2eae
```

原始证据：`.work/t374-demo-common-ha/target/t376-isolated-zk/t378-signed-auto-home-8a0b4f96.log`。
之前同集群 8 分区证据：`t378-signed-auto-home-9cd21840.log`。
之前同集群 4 分区证据：`t378-signed-auto-home-1196dc4b.log`。
之前同集群 2 分区证据：`t378-signed-auto-home-48d00bf6.log`。

本轮：
- 真正 ZooKeeper manifest：256 个分区，单一连续 Cluster/Namespace。
- 连续 **P000→P001→...→P015 = 16/16** 物理签名自动 Home STRICT READY PASS。
- 连续 **16/16** 新 E3 TCP `QUORUM_DURABLE` ACK PASS。
- **16/16** 不同的 2/2 RSA 旧 CommitIndex/Custody、两份旧物理退休、双新 E3 Image、StateMachine REPLAY_COMPLETE/签名恢复收据。
- **16/16** 完全独立的第三 JVM 原始磁盘 WAL/Custody 审计 PASS。
- 每个目标回切都运行 128 个 Home Watch，其他分区无证据拒绝，2 条共享冷控制线程。
- A 的 ZooKeeper Session ID 在 16 个分区全部相同；B 的 ZooKeeper Session ID 在 16 个分区全部相同；旧 B 持续维持控制会话、没有切换成虚构新主。
- 整轮 A JVM 实际执行时长：`204983ms`（约 205 秒），B JVM：`209042ms`（约 209 秒）。**含**逐分区 WAL/Custody 签名、ZK CAS、恢复、TCP ACK、额外的测试等待；不等于真实集群切换过程的最大客户停顿时间。
- 单分区自动 READY 耗时最小 `2469ms`，中位数 `3550.5ms`，最大 `4166ms`；此处仅 16 分区，**不是 128 分区 P99**。真实第三 JVM 磁盘审计发生在这两段 JVM 执行结束之后。
- 所有隔离 ZK 容器、旧 B 测试容器在运行结束后停止；原始证据目录保留，现有业务 Common JAR 不变。

首次八分区曾在 P006 被挡在 Snapshot 双签封存读取阶段：B 在 `genesis-e3.snapshot` 出现时过早 `reopen`，而 Quorum 文件尚未完整发布。修复**测试辅助证据交接顺序**后整轮八分区重跑 8/8 PASS，再扩大为本次 16/16 PASS。此前 P001 单次 Custody 文件时序也已采用原子辅助交接；没有减少 Common 的真实签名/持久化认证步骤。

## 三、限制：整体现网 HA 仍 NO-GO

当前**绝不能将 16/16 宣称 128/128 完整验收，更不能立即部署 Order/Trade**：

1. 剩余 P016–P127 共 **112 个 Home 分区**尚未在同一进程/同一 ZooKeeper 中完成这套真实物理严格回切；必须测出全部 128 分区的真实时间/P95/P99、256 个分区准确一致性，以及从发生故障到恢复业务可用的全链路延迟。
2. **真正持续服务仍未证明**：此多分区隔离夹具在每个分区新 E3 客户 ACK 之后，会关闭该分区临时 `CommonCertifiedPartitionRuntime`/Netty 实例，虽然 ZK manifest 保持已切回的 READY，但没有证明 P000 在 P001→P015 迁移期间仍能持续接受真实客户端写入。下一门禁必须让已回切分区的业务状态机/Certified Runtime **一直存活并保持可写**，同时迁移其余分区，并提供旧 B 其他原始 Home 在期间仍可写的证据。
3. 真实 A 故障→B 自动接管→A 追平回 Home，再反向 B 故障→A 自动接管→B 追平回 Home的**完整双向循环、旧主物理隔离、256 分区持续有并发客户写入**仍缺；不能仅用活主协作交接代替真正 SIGKILL 主故障验收。
4. 测试是**同一台 Mac 内独立 JVM、独立卷与不同 ZooKeeper 会话**，并非多台真实独立故障域主机。需诚实标记测试隔离边界；严格 2/2 保证的是实际签名和 FileChannel fsync，不暗示跨实体机器容灾。
5. 只有 Demo+Common 全量真实门禁 PASS，才将同一版 Common 集成到 `saas-crypto` 的 Order/Trade（业务仅提供状态机），本地编译镜像、替换 Demo，验证自动审批、新租户、Robot Maker/Tape、订单/成交/资金/Projection 和真实双向 HA。不得扩新功能或把 HA 复制回业务服务。

**结论：T390 同一真实三 ZooKeeper + 同一 A/B JVM 长会话连续 16 分区独立物理签名 READY+TCP 2/2 ACK+第三 JVM 审计 PASS。整体 HA 未完成 128/128 与持续可写/反向故障门禁，暂不部署 Order/Trade。**
