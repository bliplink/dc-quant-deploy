# T461｜Common 大 WAL 流式严格恢复认证与现网 P060 只读检查

**日期：2026-11-03**  
**状态：Common 候选修复与独立实测 PASS；真实 Order/Trade 256 分区业务 HA 仍 NO-GO。**

## 1. 根因：并非只有 Poison 自动 Stage 的问题

T460 已证明 A 节点仍在线时，可用真实旧主 RSA/会话认证让 B 自动将 P060 从旧 Epoch 转入新的 `RECOVERING`。本轮继续追查 `RECOVERING → 严格 READY` 的真实 Common 代码，确认另一项阻塞：

- `CommonCertifiedStrictCrashPrefix.inspectReadOnly` 依赖 `CommonFileBusinessWal.readHistoricalCommittedWindows`，将**全部已认证历史业务帧**保留在 Java 集合，并限制返回 payload 总量不超过 **64 MiB**，虽然 `maxWindowRecords<=4096` 是单次窗口，最终仍聚合整个历史。
- `CommonCertifiedStrictStagedReadyEvidence.Source` 直接限制 `maxBytes<=64 MiB`。
- 严格 READY 的两个独立路径 `CommonCertifiedStrictCrashReadyPublisher` 与 `CommonCertifiedStrictStagedReadyEvidence` 原来均调用 `Files.readAllBytes` 为旧主/旧副本整文件计算退休 SHA，内存峰值随历史 WAL 增长。
- 真实 Order P060 E2 原始 WAL：A **285,670,877 字节**，B **285,669,623 字节**，A 比 B 多 **1,254 字节**；B 原来最高已证实 CommitIndex/Custody 头为约 `seq=188530`。这个已保存的 A-only 物理尾部**没有成功双副本认证，不得视为客户已提交**。
- 源码旧限制与现网数据量矛盾，故单纯修复自动选主仍不能使 P060 通过签名 READY。这是 Common 通用容量问题，不属于 Order 特殊业务逻辑。

## 2. 最小修改：只变更原始 WAL 的验证方式

仅改 Common 三个生产类，没有创建第二套 HA、RPC、业务 WAL 格式或新 Epoch 协议：

1. `CommonCertifiedStrictCrashPrefix.inspectCertifiedHeadReadOnly`：新增**严格只读、认证元数据型 HEAD 验证**。打开两个不可伪装的物理 WAL，底层沿用 Common 原有完整帧顺序/CRC 检查；以副本真实持久化 CommitIndex、旧 EPOCH A/B 双 RSA Custody 回执选出已提交头；分别流式核验 A/B 的**已认证前缀 SHA**；返回旧 Epoch、认证 seq、A/B 原始物理 HEAD，不再返回所有历史 byte[]。单文件大小有可配置明确上限，最高 **8 GiB**（不等于内存申请）。
2. `sha256OriginalWalReadOnly`：针对双方已经独立退休的完整旧 WAL 使用 **32 KiB 缓冲区**计算 SHA-256；禁止路径符号链接，前后检查物理文件长度，并按配置大小限制；其 SHA 仍由旧 A/B **真实 RSA 退休回执**认证。
3. 原 `inspectReadOnly` 保留用于确实需要返回完整历史帧的小数据/显式 Replay 测试，**不改变其行为与边界**；真正的两处 Strict READY 核验器改用只返回 HEAD 的新 API，避免重放/验证重复物化几十万条命令。
4. 并未改变 `READY` 的其余强制门禁：旧主/副本各自真实 WAL 退休签名、原始双 Custody、双新 Epoch 恢复收据、封存业务 Image、精确 ZK CAS/租约。物理副本仍持有旧 WAL 文件锁时，验证照旧拒绝。**只校验证据，不恢复/裁剪/修改用户数据**。

## 3. 真实测试与明确边界

| 实测 | 结果 |
|---|---|
| 修改后的 Common 3 个主类独立 `javac -source 8 -target 8` 编译 | **PASS** |
| T461 独立 T293 **真实双 RSA** 数据：给复制后的旧主 A WAL 新增 68 条、总长度 **71,305,252 字节**，旧副本 B Custody 仍只认证 seq=2 | **PASS，认证 HEAD 严格保持 2，A 原始 WAL 不动** |
| 同一组真实签名物理数据，旧 A 退休 RSA 仍写 seq=3 时要求 Strict READY | **正确拒绝，CAS=0** |
| A 独立测试私钥对已关闭的 71 MB WAL 按实际 seq=71 补签退休回执，B 真实旧 Epoch RSA 退休、双方真实新 Epoch E5 RSA 恢复收据和封存 Image 均通过 | **Strict READY PASS；但 ZK CAS 是原有内存测试桩，非真实三 ZK** |
| 上述数据在 `-Xmx256m` 运行 T461 JUnit | **2/2 PASS** |
| 既有 4 类严格 READY / 物理回执 / Coordinator / Grant JUnit、实际 T293 签名文件 | **34/34 PASS** |
| **真实现网 Order P060 E2 A/B 285MB 原始文件**：Docker **`--network none --read-only`**，Docker named volume **`:ro`**，JVM `-Xmx192m`、Common 32KiB流式 SHA | **PASS**，无 OOM、无修改原始数据 |
| 当前现网 P060 原始 A/B WAL 的持锁物理完整 CRC 扫描 | **FAIL-CLOSED**；仍有实际持有者/未退休，不能强制解除或称已 READY |
| 精确 T461 JAR 三 ZK 真实 A/B RSA Poison P060 非 READY Stage（255 其他分区不变） | **PASS，退出码 0** |
| 精确 T461 JAR 三 ZK 256 Home/128 Watch 拒绝缺签名 WAL、原单分区 Stage 与新进程恢复 | **PASS，退出码 0；并非 256 全业务 READY** |
| 精确 T461 JAR 真实独立 A/B/C Demo JVM 的 A→B→A 两次 `SIGKILL`、新 Epoch 重加入与真实 TCP fsync | **PASS，退出码 0；不把 LOCAL ACK 冒充历史 2/2 Quorum** |
| 正式 Order/Trade 四容器同 SHA 重新编译、替换、全 256 E3 READY 与业务资金对账 | **尚未执行，NO-GO** |

### 原始文件的实际流式 SHA-256

在带有原始 Docker volume 的真实只读容器中完成，不查看或读取任何私钥：

- A `285670877` 字节：`d2a9477de11703624f7c4a61ee0c8aad63e489c4b0929a7e3cab01e90f27e67a`
- B `285669623` 字节：`3aebad74f356cb527ef3553f15adb636c33cbd854939b84df42bf396d4702373`
- 测试内 Java 堆 `194641920` 字节；脚本报告 `originalMountedReadOnly=true`、退出码 0。
- 单纯计算原始 SHA **不是**认证客户已提交前缀，不能代替旧 A/B 的完整签名 Custody + CommitIndex。

### 固定构建与证据

- 最终 Common 候选路径：`dc-quant-deploy/.work/t449-common-gw-rejoin/target/t461-common-streaming-strict-ready.jar`
- **SHA-256：`6abfb7dbf8fa962c18059b2cac1c2acb44eb6d623d8b84faa553b51b944a23a6`**
- 构建方式：从经过双向认证的 T460 候选以 Java 8 单独编译并替换 **3 个 Common 正式 Class 的产物**；不是正式 `mvn clean package`，不得直接视为 Order/Trade 的已批准部署镜像。
- 完整真实双 SIGKILL A/B/C 原始日志与双方 E3 WAL：`/Users/kong/.opentradingcore/t124-live-kill-runs/20261103195012`。A/B 各自 E3 WAL **178 字节**，按原始全文件 `cmp` 一致，SHA-256 都为 `0935a4241ce2a5d1ab17137d29d2d8e5cec8c000e30346c69dbc0094a62ce689`；独立 B 日志验证 `T272_B_E3_COMMON_TCP_NEW_WAL_FSYNCED_PASS seq=3 total=85 requests=7`。
- 新 JAR、真实 3ZK Poison Stage：`/Users/kong/dc-quant-deploy/.work/t460-live-poison-evidence/9f68a65d`
- 新 JAR、真实 3ZK Home Stage：`/Users/kong/dc-quant-deploy/.work/t461-real-256-home/target/t376-isolated-zk/t377-home-control-0ec29020.log`
- 实测关键程序类：`examples/common-only-demo/src/test/java/com/app/common/replication/CommonT461ReadOnlyActualP060AuditProcess.java`。本地 `CommonT461LargeStrictWalStreamingTest` 通过独立固定 T293 测试用 RSA 数据验证，原始签名源无改动。

## 4. 接下来的正式业务门槛

**先恢复真实 P060，不绕过认证：**
1. 在真实 Order/Trade 使用与 Demo 相同的 Common 代码和独立持久化的 `AutomaticReplicaRecoveryPlan`。旧 A P060 签名 Poison 仅能产生 E3 非 READY Stage；其它 255 分区仍可交易。
2. 在确认 ZK 非 READY 且旧 Epoch 不可能再获客户 ACK 之后，**仅关闭 P060 旧 A/B 的物理 WAL 锁**，分别用现有 Common 退休 API 签发真实 RSA 退休回执；必须保留 A 多出的 1254 字节作为不可回写的证据，不得直接使用未经 Quorum 认证的尾部。
3. 根据真实 B 的独立双 Custody/CommitIndex 确定 E2 认证头，通过已有 Snapshot+WAL 流式重放恢复**同一份客户业务状态**，两物理节点在 E3 安装一致、分别签发恢复 RSA，再由 Common 验证并 CAS `READY`。失败保持 `RECOVERING`，不能强制开闸。
4. 再完成 256 分区真实双向 SIGKILL、A/B 每侧 128 Home 自动归还，订单/成交/资金/持仓/Projection 一致性、Robot/Tape 与 MD QuerySymbol/APS 业务 E2E。不能拿单分区 Demo 和只读 SHA 作为正式业务 HA 的 GO 证据。

**在全部门槛未完成前，真实 Order P060 仍为 `P060|2|OrderSvrA|OrderSvrB|STRICT_QUORUM|READY`，A/B 本地不确定写入仍保持隔离。Order A/B、Trade A/B 4 个现网容器本轮未重启。**
