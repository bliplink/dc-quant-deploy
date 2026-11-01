# T398｜全新 Docker 原生卷 Order/Trade Common E2 READY 验收（2026-11-01）

## 用户指令与边界
旧 Demo 数据阻碍快速迭代时优先全新部署，不继续纠缠无法恢复的旧 E2 WAL；保留旧故障证据。所有代码归档 saas-crypto-latest，不使用 GitHub Actions；Common 负责全部 WAL/签名/ZK/切换，Order/Trade 只实现业务状态机。

## 失败原因与新环境
- T397 首次 E1 出生 Order A 在 P029 读取刚 fsync 写出的 Genesis 遇 `NoSuchFileException`；Mac 宿主目录随后能看到原 Genesis 文件，疑似 Docker Mac 共享目录一致性窗口，尚未严格证明。T397 的部分出生文件封存不再复用。
- T398 使用全新 `/otc/t398-fresh-20261101-r1/{order,trade}` 命名空间、私有配置根 `~/.opentradingcore/t398-fresh-20261101-r1`、Docker 管理卷 `otc-t398-born` 和 `otc-t398-data`，新独立 owner tokens。不复用 T364/T397 E1 原签名文件、E2 WAL、签名 READY 或旧业务数据。
- 通过 `tests/T398VirginZkManifestInstaller.java` 在真实三节点 ZooKeeper 上首次写入两服务 256/256 个 `STRICT_QUORUM|RECOVERING` E1 分区，A/B Home 各 128，初始 version 0、READY=0。
- 两份候选镜像 `local/otc-t396-ordersvr:t389-common-t395-business` 和 `local/otc-t396-tradesvr:t389-common` 使用同一 T389 Common JAR SHA-256 `6b4418f7b1373bb68a9fac4c79aa4406001e1699ec6d9dd080c83323110e2eae`。Order 镜像还包括 T395 Maker/Taker TransactTime 修复。

## 实际执行 PASS
1. 四个独立 Common RECOVERING 业务 JVM 依次启动，新 Node Geneses 落到 Docker 原生卷。`otc-t398-order-a-birth`、`-order-b-birth`、`-trade-a-birth`、`-trade-b-birth` 均输出 `COMMON_FIRST_BOOT_ONLY_LOCAL_RSA_E1_VOTER_FLEET_FSYNC_PASS partitions=256 businessReady=false` 且 exit 0。
2. 通过 `tests/T398OriginalE1DualPhysicalGenesisSeal.java` 检查每分区 A/B 原始本地快照字节一致、独立 RSA-2048 物理原回执及原零 ACK WAL，并调用 Common 原生 `sealAndVerify`，两服务原始签名 Quorum **512/512 PASS**（每分区 2 份 RSA 物理签名）。验证通过才写签名封存，不产生 READY。
3. 在 Docker T398 native data volume 创建四节点各 256 个空事务根（1024），按 A HOLD + B INSTALL → A INSTALL 的独立 ZK 原租约流程执行。实际查看 Docker Volume 中 `ledger/Pnnn.recovery` 字段 `phase=REPLAY_COMPLETE`，结果 Order A 256/256、Order B 256/256、Trade A 256/256、Trade B 256/256，总计 **1024/1024**。
4. Trade A 首次 INSTALL 曾被旧 A hold 的 ZK Ephemeral Session 正确拒绝，错误 `recovering node lease owned by another ZK session`，拒绝发生时 Trade A 0/256；旧 Session 自然过期后通过原有同一新命名空间重新启动，最终 Trade A 256/256，没有覆盖 Genesis。
5. 实际停止两个 A INSTALL 临时 Session，确认旧 Ephemeral Lease 消失，再使用新的 `signed-first-ready.properties` 原物理 A RSA 和 B 独立活 Session 执行 Common 原始 `E1→E2` 签名 CAS。两服务分别输出 `COMMON_ORIGINAL_FIRST_E2_READY_CAS_PASS service=... partitions=256 signedGenesis=true businessServing=false`，激活进程 exit 0。
6. 再使用 ZooKeeper `get -s /otc/t398-fresh-20261101-r1/{order,trade}/manifest` 独立读回：两服务均 **256 行 E2 STRICT_QUORUM READY、A/B 各 128 Home、version 1，PASS**。Order B 原 E1 Listener 因新 version 检测 Manifest 改变并拒绝续跑，属于旧 Epoch 隔离；不代表真正业务 B 已启动。

## 尚未完成 NO-GO
- 本轮完成的是控制面 E2 READY（真实原始签名与冷恢复），**不是正式 Order/Trade Spring 业务进程 READY**。旧运行镜像尚未替换；新的 T398 业务 DBPoolConfig、MySQL/ClickHouse 隔离和业务 WAL 根需要完整准备，不能误接入旧运行数据库。
- 新租户自动审批、两交易员入金、Robot Maker/Tape、真实成交与正确的 `MDEntryTime`、Projection 与资金/持仓回归，以及真实 A/B SIGKILL + 自动追平/Home 回切尚未验收。仍为业务 **NO-GO**。
- Common SHA 相同不代表业务服务已接入真正常驻自动 HA Watch。必须依照 P0 Common 自动切换、P1 业务启动相同 Common 语义的门禁核查，不允许在 Order/Trade 私自加 election/replication。

## 证据和源码
- 源码：`tests/T398VirginZkManifestInstaller.java`、`tests/T398OriginalE1DualPhysicalGenesisSeal.java`；E1 出生、B/A 安装和 first-ready 容器按 `otc-t398-*` 命名，ZooKeeper 三节点仍为既有真实 Docker 集群。
- 签名出生根 Docker Volume `otc-t398-born`，E1 事务和完整恢复 Ledger Docker Volume `otc-t398-data`；本机私有配置仅保存在 `~/.opentradingcore/t398-fresh-20261101-r1`，不入 Git。
- 旧失败环境 T364/T397 和当前运行的旧 Order/Trade 证据未删除或清理，GitHub Actions 未使用。