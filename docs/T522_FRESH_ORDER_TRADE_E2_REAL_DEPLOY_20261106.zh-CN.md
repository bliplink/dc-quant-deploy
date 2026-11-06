# T522｜全新 Order/Trade 双节点 E2 首次部署实证（2026-11-06）

## 判定

**首次认证 Genesis / E2 控制平面 READY / 四 JVM 启动：PASS。自动 HA、客户交易、资金一致性：NO-GO（尚无成功证据）。**

仅针对 Mac Demo 新隔离命名空间 `/otc/t522-fresh-20261106-r1`。旧 `otc-t488-order-a/b-ready`、`otc-t488-trade-a/b-ready` 原容器未被替换，原卷未清空。

## 一、全新原始 256 分区

- 从空 ZK 路径按 Common `NPC1|1` 规范建立 Order/Trade 各 256 分区，P000–P127 A Primary、P128–P255 B Primary，原状态 `STRICT_QUORUM|RECOVERING`；ZooKeeper 真实读回 dataVersion=0，READY=0。
- 四个实际 T521 ARM64 镜像进程在独立的 A/B 物理 RSA 签名身份下完成 256 分区原始 E1 Genesis、zero ACK WAL、fsync。四条 `COMMON_FIRST_BOOT_ONLY_LOCAL_RSA_E1_VOTER_FLEET_FSYNC_PASS` 均存在；无业务 READY。
- Common 统一 JAR SHA256 为 `3ea53430102f5d9111bc0da842bf4a95308d008a1bdf58f71f48fa1115efaf35`，与 T521 Order/Trade 镜像 Common JAR 一致。
- 离线用相同 Common 原始双签验收类核验 Order/Trade 256 个分区，A/B 两个独立 RSA 签名、原始 Image 和 zero ACK WAL：两个服务的 phase=0、phase=1 均 PASS，`READY=false`。

## 二、真实双 JVM 业务恢复事务与 E2 CAS

- 为每个服务的 A/B 独立创建 256 个物理恢复事务目录，四个 JVM 都真实执行 `T157_COMMON_ZK_FENCED_*_MAIN_JVM_BUSINESS_INSPECTION_PASS`，每个 node 256 分区。
- 原始业务 E1 恢复事务 `*.recovery` 逐步从少于 256 增长到四个节点均为 **256/256**，真实持久化 snapshot、journal、recovery ledger；不是回调假 PASS。
- Common A 节点对两个服务均产生 `COMMON_ORIGINAL_FIRST_E2_READY_CAS_PASS service=... partitions=256 signedGenesis=true businessServing=false`。
- 三节点 ZK 真实重新读取，两个服务均为 `NPC1|2`，P000/P255 为 Epoch 2、`STRICT_QUORUM|READY`，各 256 分区。旧 B `RECOVERING` 会话在 CAS 之后检测状态变更并 fail-closed 退出（exit=1），属于原恢复会话退出，不是新业务进程崩溃。

## 三、四个 E2 业务进程及通信

- 使用单独的 `otc-t522-ready-data` 卷和 `otc-t522-born` 原始证明卷，Order/Trade A/B 四个 E2 JVM 都实际记录 `Started OrderSvr` / `Started TradeSvr`，独立数据根目录分别有 256 个 `epoch-2/business.wal` 文件。
- 初次启动缺少真实 WAL 根目录及 `nodeRuntime.snapshotRoot`，经确认是隔离配置缺项，在新目录补齐；未放宽 Common 认证。
- 原 Bridge 网络容器无法连接 host-mode Login/Admin，业务节点彼此又绑定容器内 127.0.0.1。实测后仅为 T522 复制新的 `ATSConfig.ini`，采用 Host 网络及专用业务端口 34336/34341 (Order)、34337/34346 (Trade)，Common 物理复制端口 46322/46323 (Order)、46222/46223 (Trade)。保留原始配置和旧容器。
- Host 网络仍需访问 Bridge 上的 MySQL：通过已验证容器地址 192.168.128.3 绑定 T522 私有 `/etc/hosts` 别名，未更改数据库内容；ZK 三节点实际 IP 全部验证可达。
- 真实 socket 测试：上述 8 个新业务及 Common 复制端口，既有 Login 33034 与 Admin 33040，共 10/10 TCP CONNECTED。Order A 与 B 的日志均有 `TradeSvr partition primaries preconnected: 2/2`。
- T522 Host 网络 r2 四 JVM 持续运行，真实 Java Spring 启动已完成。需继续验证下单成交、资金变化和物理复制 ACK；容器 Up/端口 CONNECTED 均不能替代交易验收。

## 四、下一阻塞与不得越界事项

- **automaticRecovery=false** 是首次 E2 业务启动模式，尚未证明 SIGKILL 后的自动接管。不可将本轮 E2 首次 READY 等同 A→B→A 自动 HA。
- Common 生产执行器 `CommonCertifiedProductionPhysicalRecovery` 仍显式只有原始 E1→E2 的部分实现，跨 Epoch E2→E3、Snapshot/WAL 自动安装与 256 分区完整生产装配仍需 Common-only 验收。现有 T522 数据卷未找到独立双 RSA 原始 Home 收据，因此不允许后补假签名来绕过这一门禁。
- Cluster 选主/租约/ACK/Watch/复制/恢复只允许 Common 实现；Order/Trade 仅注入业务 byte[] snapshot/codec/state machine。真实客户业务闭环和 HA 未通过之前保持 NO-GO。

## 可核查证据位置

- Mac：`~/.opentradingcore/t522-fresh-20261106-r1/` 的 `*-birth.log`、`dual-rsa-genesis-seal.log`、`config-firstready/`、`config-hostready/`、`bridge-logs/`、`host-logs-r1/`。
- Docker：`otc-t522-{order,trade}-{a,b}-hostready-r2` 容器日志；本轮两个隔离数据卷 `otc-t522-born`、`otc-t522-ready-data`；原 T488 容器与卷未变。
- 新 RSA 私钥及现有真实认证材料没有提交 GitHub；未调用 GitHub Actions。