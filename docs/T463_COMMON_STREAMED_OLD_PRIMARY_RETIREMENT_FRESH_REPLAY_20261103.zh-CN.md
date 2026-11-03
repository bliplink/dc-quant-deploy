# T463｜只修真实代码，旧 P060 数据直接放弃：Common 流式旧主退休及 Order/Trade 新 E1 引导

日期：2026-11-03  
正式结论：**Common T463 代码与隔离 HA 回归 PASS；Order/Trade 全新 Demo 重建和业务 256-shard HA 仍 NO-GO**。不再修补历史 P060 WAL/旧 Snapshot。

## 1. 根因证据及本轮 Common 修复

T461 已将 STRICT READY 审计改为常量内存流式 WAL 前缀验证，但继续源代码检查发现 **CommonCertifiedPartitionRuntime.retireCooperativeAtSignedStage()** 仍然在旧主 WAL 停止/关闭后执行：

```java
SnapshotTransferIntegrity.sha256(Files.readAllBytes(physicalWalPath));
```

这会在旧主 A 仍在线、仅 P060 出错时，把该分区整个原始 WAL（现网约 285MB，未来更大）一次性放入 JVM 堆。即便全新部署，交易一段时间后依旧会复现内存峰值。因此这是必须修的**通用 Common 代码问题**，不是老数据问题。

现已改为 `CommonCertifiedStrictCrashPrefix.sha256OriginalWalReadOnly(physicalWalPath,8GiB)`：必须先完成签名 Stage 核验并 `close()` 释放旧 WAL 文件锁，再以 32KiB 缓冲区只读流式计算**原始 WAL 完整字节**的 SHA-256，前后检查物理大小及软链接，保留原始 WAL 所有未确认尾部证据。旧主的 RSA 回执仍绑定原始文件 SHA、真实物理 EOF seq 和原 Stage/ZK，会在签发过程中再次校验最新 Stage。不能将整个物理 WAL 的末尾误算作已证实 CommitIndex/Custody 客户 ACK。

变更类：
- `src/main/java/com/app/common/replication/CommonCertifiedPartitionRuntime.java`
- `src/test/java/com/app/common/replication/CommonCertifiedPartitionRuntimeTest.java`

Common 代码已合并 GitHub `bliplink/com.app.common` 的 `saas-crypto-latest`，commit `de6ae70c01f16d62ca1dad3e0a6455711e1a6234`，两份源码与本地测试版本 Git Blob 完全一致。

## 2. 真实实测证据

| 验证 | 结果 |
|---|---|
| Java 8 源码编译，原物理 Common + RSA + Netty 回归 | **PASS，7/7 JUnit** |
| 额外真实两个 Common 物理节点 Netty 写 68×1MiB、A/B 独立 fsync/证书，合计 P090 WAL **71,305,110 字节**；旧主 A 先确认分区 Stage 再释放文件锁、原始 RSA 签名退休 | **PASS，7/7，JVM -Xmx192m**，物理 HEAD=69；P128 继续提交到 seq=2；A 节点租约保持 LIVE |
| 同一最终 Common JAR，三 ZooKeeper + 独立旧 A/B RSA + 256 完整 Home，A LIVE 的 P060 Poison | **PASS，退出码 0**，P060 E2→E3 RECOVERING，255 分区 READY 不变，未伪造 READY |
| 最终 Common JAR，独立 A/B/C 物理进程真实两次 SIGKILL、双向接管、原始 WAL 恢复、重新加入、B TCP fsync | **PASS，退出码 0**，但明确 RPO/LOCAL ACK 限制，不等于真实 Order/Trade quorum |
| 独立 E3 A/B 最后真实 WAL 整文件 `cmp` | **PASS**，各 178 字节，SHA-256 `0935a4241ce2a5d1ab17137d29d2d8e5cec8c000e30346c69dbc0094a62ce689` |

最终候选 JAR：`dc-quant-deploy/.work/t449-common-gw-rejoin/target/t463-common-streamed-retirement.jar`，SHA-256 **`f3ff15872b819024bb7d2f13c086fa1403800ccaf82cd2128aaffe3fa302f0f1`**。使用已有 T462 JAR + 单独 Java8 编译后的新 Common 主类构建，**不是 Maven 全量 clean package，也未生成正式 Order/Trade 镜像**，不得声称已经正式业务部署。

原始证据：
- T463 真实 3ZK Poison：`/Users/kong/dc-quant-deploy/.work/t460-live-poison-evidence/10a44cec`。
- T463 双向 A→B→A SIGKILL、物理 WAL、B fsync：`/Users/kong/.opentradingcore/t124-live-kill-runs/20261103205218`，其中 `common-tested-pin.jar` SHA 与 T463 候选一致。
- T463 68MiB Netty + RSA/文件锁退休：`CommonCertifiedPartitionRuntimeTest` 测试标记 `T463_REAL_68M_NETTY_WAL_RETIRED_RSA_STREAMING_PASS bytes=71305110 physicalHead=69 otherShardP128Ack=2 oldALease=LIVE`；是隔离临时测试卷，运行后已释放。

## 3. Order/Trade 代码阶段（未合入正式分支）

经实查，**正式** Order/Trade `saas-crypto-latest` 目前仍使用经过此前交易部署的 `CommonCertifiedNodeBootstrap.openAndStartWithZkFencingAndReplay` Common 源码入口，没有切入 T458 尚未完成的自动 Watch Bean。这意味着**干净 E1 Replay 引导本身可沿用正式源码**，而不能将 T458 缺 Bean 的候选误报为当前已部署生产分支。

T458 候选下的 `OrderCommonNodeRuntimeWiring`、`TradeCommonNodeRuntimeWiring` 目前缺少实际 Spring Bean：
- `orderCommonSignedRecoverySources` / `tradeCommonSignedRecoverySources`；
- `orderCommonAutomaticReplicaPlans` / `tradeCommonAutomaticReplicaPlans`，每节点精确 128 本地 Replica，须包含真实 Catch-up、旧 Epoch WAL/Custody、业务 Apply、E(n+1) READY、固定 256 Home。

本轮对两服务的 **独立候选**增强为显式生命周期选择：
- `*.common.nodeRuntime.automaticRecovery=true`（**默认 true**）必须走 Common 已存在的严格自动 HA 启动 API，缺少任何真实源/恢复计划即启动拒绝。
- 仅显式配置 `automaticRecovery=false` 时，走**同一 Common** 的已存在 E1 认证 Replay 启动入口，没有额外 Order/Trade WAL/选主。它只适用于**全新 Genesis 引导阶段**，不会自动 A/B 切换，严禁宣称 HA GO；历史 P060 不能走这条路洗白。
- 保留真实 RSA 身份、ZooKeeper 认证 census、业务 Replay、Netty 物理 WAL/ACK，任何无 signed-ready 的写入仍拒绝。

本轮最新 T463 Common JAR 下，Order/Trade 各自 Java 8 编译通过，各 **4/4 JUnit PASS**：验证默认不会悄悄降级、手动引导必须显式开关、原来空 signedSources/空计划仍拒绝。只是源码和编译级门禁，**并非已经真实 Spring 启动或 E2/E3 完成**。

候选独立 GitHub 分支：
- Order：`bliplink/com.app.dc.ordersvr` / `codex/t463-order-auto-and-fresh-bootstrap-candidate`，HEAD `f398c11d0612dfd2d886f59bc3498695d281f630`。
- Trade：`bliplink/com.app.dc.tradesvr` / `codex/t463-trade-auto-and-fresh-bootstrap-candidate`，HEAD `a3134567f27b5253ede155e5afa97214212fefb0`。
- 两服务合计 4 份变更源码/测试与本地 Git Blob 匹配。
- **未合并到正式 Order/Trade `saas-crypto-latest`，未修改现网配置或容器。** 两服务正式分支中的既有手动 E1 Common Replay 逻辑不受影响。

## 4. 从此只修代码后全新部署

不再花时间修复现网旧 P060 的 1254 字节未确认尾部、恢复旧 Epoch、迁移旧租户数据。它们只保留为历史诊断证据。

接下来的代码门槛：
1. 为正式自动 HA 补齐 **Common 统一实现**的物理签名源、128 Replica 自动恢复 Plan、旧主自动退休、认证 Snapshot/WAL Apply 与两物理节点 E+1 RSA READY。Order/Trade 不增加独立集群逻辑；只做 byte[] 业务状态机/快照/Apply。
2. 统一 Common 真实全量构建、生成 ARM64 Order/Trade **4 节点同 SHA** 的新镜像，本地编译和真实启动验证，暂不用 GitHub Actions。
3. 使用**全新独立 ZooKeeper namespace、全新空业务卷、同一固定 256 Home 128:128**部署，正式签名 E1 Genesis。禁止复用 t398 旧 P060 E2 的 WAL/Custody/恢复签名。
4. 新租户 → 自动审批 → Robot 开启/Tape 点价 → 持续盘口与真实委托成交 → 订单/成交/余额/持仓/Projection 认证一致性 → A 停 B 接 → A 追平回 Home → B 停 A 接 → B 追平回 Home，才算最终 GO。

**现网四个 Order/Trade 容器未动、旧数据未改；Common T463 PASS，正式业务 256 HA 仍 NO-GO。**
