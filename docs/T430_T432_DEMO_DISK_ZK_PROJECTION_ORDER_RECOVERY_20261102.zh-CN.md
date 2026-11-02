# T430–T432｜2026-11-02 Demo 容量事故、认证恢复与 HA NO-GO

## 真实验收与边界

- 首个新租户 `JRHHXA` 与后续 `KCV203` 均通过正式 Gateway 申请、自动审批、Maker/Tape 独立入金、Robot 自动启用，曾达到 `RUNNING`、40 条活动报价。ClickHouse 在 13:21 查询的累计成交数分别为 152 和 19，均为 12:31 之前；**不等于故障恢复后继续成交**。
- `Order P193` / `Trade P240` 的 A/B 原始 WAL 曾核验 SHA-256 完全相同。仅代表当时被采样的分区物理一致，不代表全局 256 分区或故障期间交易端到端一致。
- 12:31:49 对 Trade B 执行物理 `SIGKILL` 后，等待超过 40 秒，`/dc/cluster/tradesvr-t398/partitions/P240` 仍为 Epoch2、Primary TradeSvrB、READY，**没有自动切向 A**。故障期间 Robot 后续 ERROR，自动 HA **FAIL/NO-GO**。
- 根因：旧版 `trade.cluster.failover.enabled=false` 是 Common-only 架构的正确配置，不可打开旧业务选主；Common 已提供 `armAllAutomaticReplicaRecoveryWatches` / `armAutomaticPhysicalRecoveryWatch` 等 API，但当前 Order/Trade 的 Common 启动 wiring 仅调用 `openAndStartWithZkFencingAndReplay`，未将可信恢复所需的 coordinator、catchup、signed publisher、physical/domain installer 组装并安装。**不能只加空心 watch 或手工 CAS READY**。

## Trade P240 原始尾部证据

- 旧主重启因 `custody/head.pending` 拒绝。Trade A/B 原始 WAL 到 seq102，但双方已发布的 `head.bin` 与独立 receipt ledger 均为 seq101。Trade B 的 `head.pending` 为 seq102（没有已发布对应 ledger）。
- 只读探针验证签名水位、物理前缀哈希、两端文件大小与提交边界后，将 A/B 原始完整 WAL、custody101、双 ledger101、B pending102、B commit-index102 共八件原件副本写入 `.work/t428-trade-p240-recovery/evidence/`，再只对 P240 做认证前缀恢复到 seq101。没有将 pending102 冒充 ACK。
- Trade A/B 其后均成功启动，Common 256 分区认证路由检查通过；但自动 HA 仍未修复。

## Docker 磁盘 100% 事故根因

- 13:27 时，Colima 容器内 `/dev/vdb1` 147G 用尽，MySQL InnoDB redo 日志反复报 `Cannot resize redo log file`，SQL 无法连接；Mac 宿主机仍有约 40GiB 可用。
- 精确定位单个容器 `/otc-t399-projection-host` 的 `json-file` 日志 **78,994,585,603 字节**（约 79GB）。日志主要是 `OrderProjectionBinaryConsumer` 针对 256 分区反复 GAP 请求时打印 `SERVER.OrderSvr is not Online` 完整异常堆栈，重试没有按分区限制错误栈输出。
- 保留最后 1200 行异常日志于 `.work/t430-projection-log-recovery/projection-error-tail-20261102.log`（SHA-256 `3f5e3c43e29fb80bb36f66b4decd8dedabf43b41f871cdccf67c7eaaf4dc96e1`），停旧 Projection 后定点截断该容器 Docker JSON 日志。此操作没有动 WAL、MySQL 数据卷、custody 或快照。
- Docker 可用空间恢复约 74 GiB，使用率由 100% 降至约 48%；MySQL 重启并通过真实 `SELECT 1`。
- ZK1/ZK3 也曾在容量故障期间以 code10 退出，导致 ZooKeeper 丧失多数派；已重启原 ZK1/2/3，保留原 IP `.5/.8/.6`，重新读取到既有认证分区记录，未清空 ZooKeeper。

## T430 投影防洪泛及部署

- `bliplink/com.app.dc.projectionsvr` `saas-crypto-latest`，Git commit `5a481d7`：对 OrderProjection GAP 失败按分区 1s→2s→4s→8s→16s→30s 有界指数退避；重试期限由 `requestGap` 同时约束，防止 safety poll 绕过；同分区最多 60 秒报告一次短错误，而非每次打印完整堆栈；收到有效 OK 响应重置重试计数。
- Java 本地离线编译、JUnit 定向回归 **7/7 PASS**；候选镜像 `local/otc-t430-projectionsvr:bounded-gap-log`，新容器 `otc-t430-projection-safe-logs` 使用 Docker `json-file` 日志轮转 `max-size=10m,max-file=3`。旧 `otc-t399-projection-host` 已停止保留。
- 13:38 重新启动后，Projection Spring 已启动、OrderProjectionBinaryConsumer 已开始运行；`TradeProjectionBinaryConsumer` 仍持续报 `ERROR: control snapshot not READY`，**Trade 投影 catch-up 没有通过验收**，需要另行根因定位，不能因容器 `Up` 而宣布 Projection PASS。

## Order B/A 当前恢复计划

- 之前 P060 A/B 原始 WAL 已约 182MB，超过旧 Common 128MiB 冷恢复上限。Common 在 `bliplink/com.app.common` 的 `saas-crypto-latest` 提交 `dbc425013bf06035a1eea9166afd2b6fae10bb52` 使用严格有界 256MiB 认证回放；不会放宽物理签名/ACK/授权。
- `otc-t431-order-b-restored` 使用上述 Common 候选、原数据卷和配置，启用 50MB × 3 Docker JSON 日志轮转。13:46:49 已真实启动，Common 256 分区检查通过，明确记录 Trade A/B physical client connected，`partition primaries preconnected:2/2`。此操作仅证明 B 的交易端连接已恢复。
- `otc-t432-order-a-restored` 13:52:40 通过 Spring 启动、Common 256 分区认证路由，13:52:45 通过 Trade A/B 2/2 客户端连接；首次认证冷启动 291.005 秒。
- Robot `otc-t420-robotsvr` 暂停，避免 Order/Trade 未恢复时生成大量不可成交的新单。不能以历史成交当作故障恢复后的成交。

## 尚未通过的最终验收（不可省略）

1. Order A 完成冷恢复，通过真实 Common/Gateway 认证与 Trade A/B 2/2 连接；ZK 三节点保持多数派。
2. 重启 Robot，确认新租户 Maker 20×20 持续两侧挂单、Tape 真实成交、Order/Trade 资金持仓及 Projection 正式链路；监测磁盘不会继续爆满。
3. Common 内统一装配真正的自动接管 plan：现存独立实体签名、ZK 旧 Epoch 撤权、恢复 snapshot+WAL、两个原始物理节点的真实 custody 与业务 apply，最后才发布 READY；不要旧 Order/Trade 选主、不绕过 2/2、多分区不能半切漏切。
4. 再次 **SIGKILL B → A 自动接管 → B 原样追平 → A 作为原 Home 平稳复位**，并做反向物理故障切换、256 分区/Order/Trade/MD/Projection 一致性与无重复成交验证。未完成之前始终 HA NO-GO。

执行原则：**先查实机原因与原始证据，再定点修复；开发 Demo 可重部署，但认证日志、客户资金状态与证据不能当作无条件可删。** 本轮没有启用 GitHub Actions。

## 14:19–14:31 实机继续复核

- 13:27 后 ZooKeeper1/3 容量故障及会话丢失导致 Trade A/B 进程中的 Common `NodeClusterControlManager` 认证租约过期/撤权。真实接口返回 `TRADE_COMMON_CERTIFIED_CENSUS_UNAVAILABLE (1003)`；Common `ZkNodeScopedControlPlane.reauthorizeAfterLoss` 明确要求新 Manifest generation、新 Epoch 与认证旧主撤权，不能只读旧的 `READY` 就重新允许写入。
- 14:21 Trade P240 A/B 数据卷只读检查：WAL 均为 536727B，SHA-256 均为 `b72ea275e84f38dec95387638cbc2c5f4f49797aec8ab9f6b37c542583e3e727`，两个已发布 custody head / receipt-quorum ledger 均为 1010B；未发现任何 `head.pending`。
- 保留现有数据，按次序平滑重启 Trade B（14:22:55，Spring 47.977s，256/256 Common 认证 PASS）、Trade A（14:23:59，Spring 19.522s，256/256 Common 认证 PASS）。没有开旧版业务选主、没有篡改 Epoch、没有修改账户余额。
- Robot 在新 Trade 上运行时 Gateway/Order 的旧 Netty 路由仍出现 `queryTradePosition INTERNAL_ERROR` 或 Order `9000` / `SERVER.TradeSvr is not Online`。Gateway 重启后查询恢复，但 Order 老 TCP 连接无自动自愈，属另外一个控制面连接恢复缺口。
- 14:27 停止 Robot 以避免重复拒单；同一认证数据卷没有发现 Order `head.pending`。Order B 14:29:16 再次完成 256 分区认证启动（110.984s），14:29:18 Trade A/B 物理客户端在线 **2/2**；Order A 在 14:30:04 依次重启，14:31:40 时仍在安全 WAL 回放，尚未宣布新一轮 READY。Robot 暂停，新成交尚未验证。
- 14:28 检查到 Trade A/B 既有容器各有约 2.3GB Docker JSON 日志且未设置轮转。必须在下一次镜像替换时启用 max-size/max-file，不能对已经运行的金融业务容器随意停机或清空诊断证据。

重要：**当前 Trade 主备自动切换仍 FAIL**；原先出单+Tape 成交 PASS 只覆盖故障前，故障后未取得完整新成交与资金持仓验收。
