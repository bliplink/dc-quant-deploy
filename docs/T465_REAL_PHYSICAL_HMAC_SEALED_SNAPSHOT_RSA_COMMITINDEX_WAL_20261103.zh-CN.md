# T465｜真实物理恢复源：持久化独立 HMAC、双 RSA CommitIndex 原始 WAL、磁盘 SHA 封存 Snapshot

日期：2026-11-03。严格目标：不修旧 Demo P060 数据，仅修代码。正式 Order/Trade 全业务 HA **仍 NO-GO**。

## 根因（相对 T464 的真实缺口）

T464 Common 已完成 256 分区自动恢复源和 Replica Plan 的通用装配；Order/Trade 也有相应 Spring Bean 名称，但真实物理提供者缺失。仅提供 Map 或伪造 SourceHead/READY 绝不合法。本轮先接通已经存在的 Common RSA 签名 CommitIndex、Netty WAL、DurableRecoverySnapshotSeal 与真实磁盘 HMAC 文件，复用原 Common 协议，**不新增选主、复制、HTTP 或业务服务的 HA 代码**。

## 真实源码修改

Common（`bliplink/com.app.common`, `saas-crypto-latest`）：

1. 新增 `CommonPinnedRecoveryHmacKeyRing.java`：严格从显式配置的绝对路径加载**各物理 RSA 成员独立的 32 字节随机 HMAC**，只接受 owner-only 目录/文件权限、非软链接、64 字节小写 hex（可加单个换行），拒绝缺失、共享默认密钥、非法编码和不属于已 pin RSA 的节点。一次启动后固定到内存，每个 RPC 克隆返回，不在下单热路径做 ZK/磁盘读取。
2. `CommonCertifiedPartitionRuntime.java` 新增 `requireAuthenticatedOriginalSourceWal`：只有当前仍被 Common 认证授权的实际 Primary，且实际物理 WAL fsync 头与**已存盘 A/B 双 RSA CommitIndex**最高认证头完全相同，才可按已有 Common `readCertifiedWindow` 从原本物理 WAL 读取连续 opaque byte[]。任何未认证尾部、错误分区、错误 Epoch、虚报提交序号、错误身份、超过 8 条 batch 等一律拒绝；不签新 ACK、不授予 READY、不开第二套 WAL。单次 recovery batch 限制 16 MiB。
3. 新增 `CommonCertifiedSealedSourceData.java`：作为原有最终 `RecoverySourceDataControlHandler.SourceData` 的**真实后端**，要求已有 `DurableRecoverySnapshotSeal` 通过全文件 Snapshot SHA 和提交边界元数据验证，按实际磁盘 offset 读取最多 64 KiB 块，检查文件身份/长度/修改时间及当前 Common Primary；WAL 直接调用上述当前 RSA CommitIndex 受控读取。错误 HEAD、错误分区和封存后变动拒绝。后续由原 FINAL ControlHandler 独立校验 HMAC、时间窗及 source role 并签帧，不生成任何新签名协议。
4. 测试：`CommonPinnedRecoveryHmacKeyRingTest.java` 与修改 `CommonCertifiedPartitionRuntimeTest.java`。

Order/Trade 候选分支：
- 新增 `OrderCommonRecoveryPhysicalKeysWiring.java`、`TradeCommonRecoveryPhysicalKeysWiring.java`，用各自已存在的 `ExistingDemoRsaNodeIdentity` 限定物理成员；从显式配置 `*.common.nodeRuntime.signedSourceHmacDir` 和 `*.common.nodeRuntime.authorizedReaderHmacDir` 加载 **两套不同**磁盘 keyring；除了目录必须不同，还检查对应物理节点的 reader/source key **实际内容不同**。缺配置直接启动拒绝，不会为开发环境编造默认密钥。
- 两服务各自 `CommonAutomaticBootstrapGateTest` 增加真实物理密钥接线拒绝测试，默认自动 HA 和显式手动 E1 行为不变。
- 代码仍在独立候选，**未合入 Order/Trade 正式 `saas-crypto-latest`**，因为真实 SourceEvidence、签名初始 Home 和 E(n+1) 双 RSA 物理业务恢复尚未全接通。

部署仓新增 `tests/provision-t465-recovery-physical-hmac.sh`：只在**全新 Demo 命名空间**生成并安全保存 Order/Trade 的 A/B signer 与 reader 共 4 个独立 256 位密钥；目录 `700`、文件 `600`、umask `077`、有同名已有配置立即拒绝覆盖、不打印密钥。真实执行并在独立 `.work/t465-physical-hmac-smoke-20261103` 测试了 Order 和 Trade；仅隔离测试数据。**随机密钥不上传 GitHub，不复制到现网容器。**

## 实测与限制

| 验证 | 结果 |
|---|---|
| Common 三个生产 Java 8 类、真实测试编译 | PASS |
| 真实文件 256 位独立 HMAC、RSA 成员 pin、权限、软链接、重复 key、Hot Path 不反复读盘、实际新随机目录 reopen | **5/5 PASS** |
| Order/Trade Spring 物理密钥 + T464 Strict HA/Fresh E1 gate 源码 Java8 编译及 JUnit | **Order 6/6、Trade 6/6 PASS** |
| **实际两个 Common 物理实例**：A/B Netty fsync + RSA 双 Custody/CommitIndex；读取 A 的 P090 原 WAL，拒绝 B Replica 冒充、拒绝虚报 CommitIndex HEAD | **PASS** |
| 实际磁盘提交的 Snapshot：SHA+边界封存后按 64KiB Chunk 读取、精确相符原 WAL；Snapshot 损坏后拒绝 | **PASS**。测试中 Snapshot 是隔离生成的真实文件，不是生产资金/持仓 Image |
| Common 合并 JUnit：原物理签名/恢复门禁、全 256 源与当前 129:127 Replica 计划、磁盘 HMAC、封存 Snapshot/WAL | **34/34 PASS**，完整使用既有 RSA fixture，没有把 `Assume` 跳过计作通过 |
| 最终 JAR **真实三 ZooKeeper** + 完整原 Home，A LIVE 同 Session RSA Poison P060 E2→E3 RECOVERING，其他 255 不变 | **PASS，退出码 0；不伪造 READY** |
| 最终 JAR **A→B→A 双真实 SIGKILL**、独立证书/恢复与 E3 B 复制 TCP fsync | **PASS，退出码 0**，但 E2/E3 是 LOCAL ACK，不能冒充未来正式严格 2/2 ACK |
| 双独立 E3 A/B WAL 原始文件 `cmp` | **PASS**，各 178 B，SHA `0935a4241ce2a5d1ab17137d29d2d8e5cec8c000e30346c69dbc0094a62ce689` |
| 正式 Order/Trade 四镜像/真 E3 物理安装/新租户、Robot、交易结算、资金、持仓与 256 HA | **未执行，NO-GO** |

Common 最终候选：
`dc-quant-deploy/.work/t449-common-gw-rejoin/target/t465-common-real-physical-sources.jar`

SHA-256：**`a0de1fb65d29e6ec6d2a9741c8b621c959c5bc3c63b1c7fcd5266c415fdc7c19`**。从已验证 T464 JAR 增量替换 Java 8 编译后的三个 Common 正式类；Zip 检验通过，没有打包测试 Class。此 JAR 不是一次正式 Maven full clean package，也不是最新业务镜像。

证据：
- 3 ZK 256 Home RSA Poison：`/Users/kong/dc-quant-deploy/.work/t460-live-poison-evidence/657b0a92`
- A/B/C Demo 物理 SIGKILL 和最后 TCP fsync：`/Users/kong/.opentradingcore/t124-live-kill-runs/20261103224051`，`common-tested-pin.jar` 与上述 SHA 一致。
- 新隔离物理 key 目录：`dc-quant-deploy/.work/t465-physical-hmac-smoke-20261103`。不得将内容作为文件上传或复制到源码仓库。
- 单测标记：`T465_REAL_DISK_SEALED_SNAPSHOT_PLUS_QUORUM_WAL_READ_PASS`、`T465_OPEN_REAL_FRESH_RANDOM_ORDER_TRADE_HMAC_DISK_PASS`、`T465_REAL_NETTY_TWO_RSA_COMMITINDEX_SOURCE_WAL_BYTES_PASS`。

## 没有完成的真正代码事项

当前两服务 Spring 自动模式依赖的 **`orderCommonPersistedSignedSourceEvidence`、`tradeCommonPersistedSignedSourceEvidence`** 仍缺实际业务生产持久化 SourceHead/封存 Snapshot Provider；已有 Common `CommonCertifiedSealedSourceData` 可以作为真正后端，但必须由经过源端业务 CommitMarker/状态和当前 RSA ZK Grant 验证的运行时绑定后才能用于正式源 HMAC。

同样未完成真实认证原始 256 Home 的持久证据提供者，以及 `orderCommonCertifiedPhysicalRecovery` / `tradeCommonCertifiedPhysicalRecovery` 的旧 Epoch 退休、独立 Replica Catchup、双方 RSA READY 回执和 E+1 业务 Snapshot/WAL Apply。**不能以新 HMAC 和源读成功代替这些必需证据**，也不得合并不完整的自动 HA 候选直接重装现网。

用户规则仍是：旧 P060 数据不修补，代码通过完整真实业务启动/恢复门禁后，统一构建四镜像同一 Common SHA；采用**全新 Namespace/空业务卷**部署，重新注册租户、自动审批、Robot/Tape 报价/点价、真实下单成交、订单/资金/持仓/Projection 一致性和双向自动 A/B 回 Home 全链路验收。当前四个 Demo Order/Trade 容器保持 Up、未修改。
