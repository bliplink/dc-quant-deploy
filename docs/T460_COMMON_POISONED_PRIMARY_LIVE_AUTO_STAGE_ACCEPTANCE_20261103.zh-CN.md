# T460｜Common 单分区 Poison 自动非 READY 切换：正式证据审计

日期：2026-11-03

## 结论

**T460 Common 源码与 Demo 隔离验证 PASS；正式 Order/Trade 256 分区业务 HA 仍 NO-GO。**

已解决 Common 自动故障控制面缺口：旧主 A 的 JVM 和 ZooKeeper 节点租约仍然存活，但某一分区（如 Order P060）已经永久 Poison，旧的普通故障 Watch 等待整节点旧 Lease 消失，因此无法自行接管。新增**Common 内部**的旧主分区级 RSA Poison 通知，让 B 通过现有 Common Watch 启动**原有协作签名 Stage**，仅将 P060 从 Epoch 2 READY 转成 Epoch 3 RECOVERING；并不授权新主立即写客户业务，更不允许复制未认证的旧 WAL 尾部。**未在 Order/Trade 增加选主或 WAL 引擎。**

## 生产 P060 事实与保护边界

- Order A 在 E2 P060 `seq=188531` 写入 WAL 后，从 B 端 `127.0.0.1:45323` 收到 `Connection refused`；`COMMON_COMMIT_PHASE=INDEPENDENT_WAL_FSYNC_RECEIPTS walWriteStarted=true`，触发 Common 的不可逆 `fencePoisonedPrimary`。
- 实际 Order P060 E2 WAL：A `285670877` 字节，B `285669623` 字节，B 的整个前缀与 A 字节一致，A 多出的 **1254 字节不具备成功 Quorum/CommitIndex 证明**；`commit-00000000000000188530.bin` 是可见已认证前一个提交。
- 现场 ZooKeeper 仍有 `P060|2|OrderSvrA|OrderSvrB|STRICT_QUORUM|READY`，但 A 本地严格拒绝该 poisoned Epoch 的后续 ACK。**ZK READY 不能代表业务物理 READY。**
- A 继续服务其余健康分区，整节点 lease 不能因为 P060 出错被人为删除；只允许 P060 进入认证的新 Epoch 恢复流程。现网原始 P060 的旧数据、未确认尾部与 ZooKeeper 本轮均未改动。

## Common-only 最小实现

1. `CommonCertifiedPoisonedPrimaryNotice`：A 的真实 Common grant 在 WAL 写入后 Poison，**只在 Common 后台控制线程**通过当前原有 ZooKeeper 会话发布 ephemeral marker；marker 内容由旧 A 自己的 RSA 私钥签名、用已钉住的 A 公钥自证，绑定 service、Pxxx、旧 Epoch、A、B、精确 manifest 版本与 SHA-256。marker 的 ZK ephemeralOwner 必须等于 A 真实 node Lease 的 sessionId。
2. B 只有同时满足自己是现行严格 RF2 READY Replica、A 原会话在线、marker 会话同源、标记版本/消息无篡改、A RSA 验签通过，才在 `CommonCertifiedFailoverWatch` 使用 `stageSignedPoisonedPrimary` 调用**已有** `stageCooperativeRecovering`。拒绝伪造通知、错误签名、旧会话、改变的 manifest、错误 Epoch、错误 Replica。
3. 既有 `CommonDurableFailoverStageLedger` 签名 Stage/ZK CAS 把单个分区改为新 Epoch **RECOVERING、routable=false**；其余 255 分区不变；旧主 A 其他业务继续持租约。旧 Epoch WAL 退休签名、CommitIndex/双 Custody、业务 Snapshot/WAL Apply、双方新 Epoch 恢复收据及签名 READY **仍需额外满足**，通知本身不替代这些认证证据。
4. `NodeClusterControlManager` 保持业务 WAL/ACK 热路径零 ZK/RSA；Poison callback 仅登记待发送事件并异步调度现有控制执行器，单次最多处理一个分区，失败保留并按后续续租重试，避免 256 个失败分区占满控制线程。短暂 manifest Watch revoke 不会擦除已永久 Poison 的意图，撤权期间旧业务 grant 仍拒写。
5. `CommonCertifiedNodeBootstrap` / `AutomaticReplicaRecoveryPlan` 采用**可选钉住的旧主 RSA 公钥**启用该功能；没提供证据则保持原有普通 crash/home Watch 行为，不引入 Order/Trade 专用状态机。

## 源码与二进制

Common 源码与两项测试正式合入 `bliplink/com.app.common` 的 `saas-crypto-latest`，经过独立 `codex/t460-live-poisoned-primary-auto-stage` 分支逐文件本地/远端 Git Blob SHA 校验（10/10 一致）后，使用 GitHub 原子 fast-forward ref 更新；**没有覆盖其他 Common 代码、没有启用 GitHub Actions**。

本次仅针对受影响 Common Java 主类以 `javac -source 8 -target 8` 编译并叠加到 T459 候选 JAR；不是全量 Maven clean package，不得据此认为正式镜像构建已完成。

最终候选：
- `dc-quant-deploy/.work/t449-common-gw-rejoin/target/t460-common-live-poison-v2.jar`
- SHA-256 **`951971b7b4001de0cada8b0d1d3c1afdebbcda8830210e86ffd78aa941a0da03`**

## 本轮实测

| 测试 | 结果 | 证据与边界 |
|---|---|---|
| Java 8 Common 编译与 Poison/自动 Watch/安全回归 JUnit | **52/52 PASS** | 包括 3ZK 所需候选进程 Class 编译、伪造 RSA、篡改、旧会话、非 Poison 拒绝、单分区 255 不变、Watch 不伪造 READY、暂时 grant revoke |
| 独立三 ZooKeeper + A/B 两 JVM + 不同真实 RSA 测试身份 + 256 ZK 分区 | **PASS，退出码 0** | A 保持独立 EPHEMERAL lease，旧 A 签 Poision 通知，B 自动 Watch 只 Stage P060 E2→E3 RECOVERING；255 其他分区 READY 保持不变，**customerReady=false** |
| 最终 JAR 对既有 A→B→A 两次真实 SIGKILL | **PASS，退出码 0** | A Kill→B 自动 E2 业务 WAL 恢复、C 独立 RSA 见证、A E2 追平；B Kill→A 自动 E3 恢复、B E3 重返 |
| A→B E3 真实 TCP WAL 新写入与 B 独立 fsync | **PASS** | E3 WAL A/B 全字节 `cmp` 相同、两个独立路径各 178 字节，均 SHA-256 `0935a4241ce2a5d1ab17137d29d2d8e5cec8c000e30346c69dbc0094a62ce689`，B 进程自己的日志含 `T272_B_E3_COMMON_TCP_NEW_WAL_FSYNCED_PASS seq=3 total=85 requests=7` |
| 新 JAR，真实三 ZK、256 Home 控制面及 128 Watch 拒绝冒进 | **PASS，退出码 0** | 缺旧 WAL 时 128 Watch 一致拒绝，旧 B lease 仍 LIVE，实际控制线程 2，`autoEpochCas=0`；认证 P000 单 Stage + 新 A 会话恢复前序可复核，255 READY 仍不变 |
| **全 256 分区实际业务、资金与成交一致性，全部自动签名 READY** | **NO-GO，未执行** | 不允许拿控制面或者 Demo 单分区 PASS 替代正式 Order/Trade 验收 |

**原始证据目录：**

- 最终三 ZK 分区 Poison：`/Users/kong/dc-quant-deploy/.work/t460-live-poison-evidence/cc947831`，含 `old-a.log`、`candidate-b.log`、`bootstrap.log`。
- 最终双 SIGKILL + B TCP fsync：`/Users/kong/.opentradingcore/t124-live-kill-runs/20261103191325`，包含两端真实业务 WAL、`t456-returned-a.log`、`t456-returned-b.log`、独立见证记录和固定 `common-tested-pin.jar`。
- 最终 128 Home Watch 控制面：`/Users/kong/dc-quant-deploy/.work/t460-real-256-home/target/t376-isolated-zk/t377-home-control-721ea524.log`。

三 ZK P060 现场关键标记：

```
T460_REAL_3ZK_256_ORIGINAL_READY_BOOTSTRAPPED_PASS
T460_OLD_A_LIVE_RSA_SIGNED_POISON_EPHEMERAL_PASS partition=P060 epoch=2 other255Unchanged=true
T460_REAL_3ZK_LIVE_POISON_SIGNED_AUTO_WATCH_STAGE_PASS partition=P060 oldEpoch=2 nextEpoch=3 unchanged=255 oldALease=LIVE signedA_RSA=true customerReady=false
T460_ISOLATED_3ZK_CLEANUP=True
```

**严格测试限制：** 三 ZK Poison 控制面正向实测使用独立 JVM、真实 RSA/ephemeral session/Watch/ZK CAS，但测试源端的 `NodePartitionGrantTable` 是隔离构造的 Common grant 模拟，主动模拟了一次 WAL Poison；没有真实 Order 业务写入、也没有从正式 Spring `NodeClusterControlManager` 自动生产真实物理 Poison 的全链路。不能因此声称该测试证明了 Order 的真实 P060 已自动恢复。此测试验证的“255 不变”指 ZooKeeper 分区控制面，**并非真实 255 个业务分区都有持续客户 ACK**。

## 下一步唯一业务 GO 门槛

1. 在 Common 继续复用已有物理签名 WAL/双 Custody/旧主退休/新 Epoch 恢复 READY 代码，把 Poison 自动 Stage 之后的恢复、业务重放、双方签名 READY **真正跑通**；一旦原业务 WAL 有不确定尾部，必须由认证 CommitIndex 断言决定已提交范围，不得直接复制未确认尾部。
2. T458 Order/Trade Spring 候选源码仍缺 128 个本地 Replica 的完整 `AutomaticReplicaRecoveryPlan`、物理 source handlers、跨 E2/E3 的真实 Snapshot/WAL 业务 Apply。因此不把尚不能启动的候选合进 Order/Trade 正式分支，不覆盖 Demo 四个运行容器。
3. 对 **四节点完全相同 SHA** 的 Common 重新统一编译/打包镜像、验证真实 256 分区自动 A/B 故障切换、Home 128:128 回归、Snapshot/WAL 原始字节、余额持仓订单成交 Projection 一致性，再跑新租户自动审批、Robot、Tape 与 MD QuerySymbol+APS 标记价格全流程。

本轮隔离测试容器正常清理；真实 Order A/B、Trade A/B 与 P060 原始数据未改变。**最终生产/业务状态为 NO-GO**。
