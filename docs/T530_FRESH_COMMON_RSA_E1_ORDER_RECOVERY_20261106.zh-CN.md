# T530｜全新 Common 认证 E1 出生及 Order A/B 真实恢复（2026-11-06）

## 结论

**真实完成但仍 NO-GO（不能交易）：** 在 T529 独立 MySQL、单节点 ZooKeeper、Gateway/Login/Manager/Admin 基础上，为 OrderSvr/TradeSvr 各 256 个分区创建了**全新** E1 `STRICT_QUORUM|RECOVERING` 清单，并完成四个 JVM 的独立原始 RSA Genesis 出生及双 RSA 验签；Order A/B 各 256 份实际业务快照、持久化 WAL baseline 与恢复 Ledger 也已生成并核查。Trade A/B 的业务恢复安装**未开始**；Home 双 RSA 签发、E2 CAS/READY、Order/Trade 客户请求和自动 HA 均**未验收**。

禁止把 `T157_*BUSINESS_INSPECTION_PASS`、E1 出生、E2 `READY` 或容器 `running` 单独判定为真实交易 PASS。本轮未取消或削弱 `CommonExclusiveBusinessClusterStartup` 门禁，不向 Order/Trade 添加选主、Watcher、复制和 ACK 机制。

## 已执行的物理环境与证据

- **隔离基础设施：** `otc-t529-fresh-mysql`（端口 34306，55 表、827 字段、251 索引、初始零租户/零投影水位）、`otc-t529-fresh-zk`（42181）、`otc-t529-fresh-gateway`（43000/43001/43002）、`otc-t529-fresh-{loginsvr,managersvr,adminsvr}` 均运行。它们不与旧 T523 Common 业务数据卷合并。单节点 ZK 仅作为开发恢复基线，**没有 ZooKeeper HA 保障**。
- **全新 ZK 原始清单：** `/otc/t530-fresh-20261106-r1/order`、`/otc/t530-fresh-20261106-r1/trade`。真实安装后读回 E1 `version=0`、各 256 分区、`READY=0`。原始 `T523VirginZkManifestInstaller` 仅针对全新命名空间参数化成私有 T530 工具；没有直接复制旧 ZK 的权威状态。
- **独立物理出生证据：** 四个容器 `otc-t530-{order,trade}-{a,b}-birth` 均 `exit=0`，分别打印 `COMMON_FIRST_BOOT_ONLY_LOCAL_RSA_E1_VOTER_FLEET_FSYNC_PASS ... partitions=256 businessReady=false`。使用原有真实且独立的 RSA A/B 身份、公钥 Pin 和独立新卷 `otc-t530-born`、`otc-t530-ready-data`，不伪造签名。
- **Genesis 交叉验签：** 复用 Common 的双 RSA 零 ACK Genesis 实体验证器，隔离到 T530 原始命名空间／本机卷执行；Order/Trade 的 phase 0/1 共 4 条 `T530_ORIGINAL_E1_DUAL_RSA_PASS`，无 READY 或客户 WAL。
- **真实 Order 恢复安装：** `otc-t530-order-a-install`、`otc-t530-order-b-install` 先经过各 256 个业务状态机的 `T157_COMMON_ZK_FENCED_ORDER_MAIN_JVM_BUSINESS_INSPECTION_PASS`；随后 Common 安装器为双方每个分区物理写入 `journal/Pxxx/baseline.properties`、`sealed/Pxxx/*.snapshot`、`ledger/Pxxx.recovery`。再次以只读 Docker 卷检查各节点 **256 Snapshot + 256 WAL 基线 + 256 .recovery，零个空文件**，都 PASS。两个安装容器在证据完整后人工 `docker stop`，`exit=143` 是终止阶段进程，不代表认证 READY。
- **Trade：** `otc-t530-trade-a/b-birth` 各 256 个原始 RSA 出生证明 PASS；**Trade 的持久化业务 Ledger 为 0**。调用全新 Trade A/B 业务恢复安装被 OpenAI 执行环境安全检查阻止；没有绕开拦截，故不报告 Trade 安装成功。

本机私有证据目录为 `~/.opentradingcore/t530-common-boot-20261106-r1/evidence/`。本次服务私有配置 `config-{birth,home,install,stage,hostready}` 共 **18** 份，已将 Common 的旧 `t84` 三节点 ZK 地址全部改为 127.0.0.1:42181，新的两服务恢复端口分别为 Order 47322/47323、Trade 47222/47223；后续 READY 端口计划 Order 47522/47523、Trade 47422/47423。私钥/密码没有上传或写入仓库。

## 已诊断的两类实际故障（及处理）

1. 首次 Order-A Birth 进程使用源配置残留的 `otc-t84-...:2181` 地址，日志出现 `UnresolvedAddressException`，没有出生记录。停止旧候选后，将 18 份阶段配置的 `*.common.control.zkHosts` 精确改为 127.0.0.1:42181，Order-A 重新真实运行并打印 256 分区 `FSYNC_PASS`。
2. 首次尝试 Home 双签时 Common 正确拒绝 `COMMON_SIGNED_PREVIOUS_E1_PHYSICAL_DIR_INVALID: ...primaryDurableTransactionRoot`，因为业务事务尚未安装。确认源码真实顺序是 **Birth → Genesis 双签 seal → 分区原始物理事务挂载目录 → 实际业务 install+fsync → 双节点 Home → A 的原始 E1→E2 CAS → READY 业务启动**。T530 卷先建 1024 个纯空事务挂载目录（此时**零**证明文件，不视为 PASS），再由 Common 安装器真实写入 Snapshot、WAL 基线和 .recovery。不要靠伪造 `*.recovery` 或只创建目录放行 Home。
3. Order-B 出生测试脚本初次报告 `NO_GO`，但容器实际 `exit=0` 且打印完整 `FSYNC_PASS`；根因是 `pipefail` + `docker logs | grep -q` 触发上游 SIGPIPE。随后先保存完整容器日志，再做普通 `grep` 校验，Order A/B 实证均 PASS；这不是业务机制缺陷。

## 尚未完成：严格顺序

1. 对 **Trade A/B** 在新物理卷进行真实、同时持有独立 ZK lease 的 256 分区 `CommonCertifiedFreshGenesisInstall`；检查双方 `ledger/Pxxx.recovery`、sealed Snapshot、journal baseline 各 256、非空、提交水位与 Genesis 一致。**受安全检查阻塞时停下并保留证据，不绕过。**
2. 在所有物理恢复存在后，分别启动 Order 和 Trade 的双独立 E1 original Home 进程，在同一新 ZK 命名空间完成双 RSA `COMMON_ORIGINAL_HOME_E1_PHYSICAL_RSA_FSYNC_PASS`。严格由 Common 校验双方真实 E1 原始恢复 Ledger，不从业务伪造。
3. 使用已认证的原始 A 节点运行 `CommonOriginalE1FirstReadyActivation::activate` 的真实 256 分区 CAS；仅物理证据完整后进 `E2 STRICT_QUORUM|READY`。不要误把 `businessServing=false` 的控制面 READY 当成可交易。
4. 启动同一 Common Jar 的 Order/Trade A/B 实际业务 Spring/Gateway 接入，检查 A/B 各分区业务重放、认证 writer 注册、Gateway 真实请求，之后新租户正式自动审批→入金→Robot/Tape→真实成交→余额/持仓/Projection/MySQL 一致性。
5. 基础交易 PASS 后再验收自动 A→B→A 以及 LOCAL 与 STRICT ACK 的独立证明；当前未启用 `automaticRecovery`，不可报告自动 HA 通过。

**保留旧状态：** T523 Order/Trade A/B 四容器仍运行，原始数据库的订单/Trade 投影历史记录仍在；旧 Robot 与旧 Projection 继续停止，以防历史水位接入新 WAL。T530 独立 E1 命名空间当前没有可交易的 READY 客户入口。