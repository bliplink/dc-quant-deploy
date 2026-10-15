# OpenTradingCore Mac Demo 统一镜像部署与交易验收｜2026-10-15

> **报告状态：核心服务启动、Order/Projection 初步一致性、真实交易功能通过；整体 11/11 租户健康及生产级 HA 主切未通过。** 该报告如实保留 NO-GO 结果，禁止被用作认证 WAL、资金权威总对账或 SIGKILL 的授权凭据。

## 版本与真实部署

- `saas-crypto` 合并完成：Common [PR #25](https://github.com/bliplink/com.app.common/pull/25) `43c770743ba4`、Common JDBC 8 [PR #26](https://github.com/bliplink/com.app.common/pull/26) `b1102e5e8274`、Order [PR #12](https://github.com/bliplink/com.app.dc.ordersvr/pull/12) `727e0abe64cd`、Trade [PR #31](https://github.com/bliplink/com.app.dc.tradesvr/pull/31) `ec3a0e8cc360`。
- 本地 Java 8 与离线统一依赖回归：Common 修复前 284 项、JDBC 8 修复后 **285 项**；Trade **286 项**；Order **373 项（0 失败、3 跳过）**；MD **136 项**；Gateway **16 项**。这是 Mac 本地验收，**没有 GitHub Actions 成功的凭据**；仓库 Actions 因账单／费用限制，用户明确要求不再处理。
- 已在 Mac Demo **直接整组替换** 9 个容器：Order A/B/C、Trade A/B、MD A/B/C、Gateway，未逐节点灰度；Robot 先暂停，再在冷启动确认后恢复。
- 镜像分别为 `dc-saas/{ordersvr,tradesvr,mdsvr,gw}:merged-jdbc8-20261015`（Mac **本地 ARM64 验证镜像**，非官方 GHCR release）。四类 Docker 容器经实际 `sha256sum` 核对同一 Common Jar：`8898812068751cc3ab3916bb7b55fe535c10a413ffef7e9be20436d6ac8ff154`，Maven 本地离线依赖名 `3.0.21-devcombined-20261015-SNAPSHOT`；**不是已发布到 Maven Central 的正式版本**。
- Common 两处遗留旧 JDBC 5.x 类 `com.mysql.jdbc.StringUtils` 的调用已移除，改为 Java 8 字符串操作；MySQL 服务保留 Connector/J 8.0.33，Gateway 没有新增数据库依赖。重启后 Gateway 未再记录该 NoClassDefFoundError。
- 既有全部 MySQL、Chronicle WAL、快照、隔离标记和旧运行根目录**完整保留**；原镜像、回滚 Compose env 另存本机 `~/.opentradingcore/otc-demo-direct-20261015/`（env 含敏感凭据，禁止提交）。当前部署数据根 `~/.opentradingcore/dc-saas-runtime-ordered-20261015`。

## 已通过的验收

1. Order 256/256 ZK assignment `READY`；A/B 各 128 primary，C 256 sync replica；256/256 节点快照一致，容器未报告新 OOM 或重启。冷启动一度发现 P077 A 快照落后 B/C，但稍后自动追平，重复全量检查通过。这只检查快照，不代表独立物理节点故障或完整 WAL ack 认证。
2. Projection 数据库尾部：当前 Order **11 行**、Trade **11 行** `PROJECTION_DB_TAIL_MATCH`。**不等于**对源端签名 WAL、资金、持仓、成交、委托、Projection 的最终权威对账。
3. 原有 10 个租户中 **8 个 Robot `RUNNING`**，各 **40 笔挂单**，公网交易 API 查询显示每个 **10 bid + 10 ask** 盘口。冷启动后 Robot 的行情缓存曾停在 `WAITING_MARKET_DATA`，随后由其订阅恢复机制自动回到 RUNNING；未绕过行情新鲜度校验。
4. 为验收实际 API，本轮**新注册独立测试租户** `YLCXP5`，不修改旧租户交易历史。该租户自动审批、Robot 自动启动且保持 40 笔挂单，新增交易员完成登录与 Demo 入金 1000、IOC 买入 **0.0001 BTC**，委托成交记录与持仓核对一致，再以 **reduce-only 卖出 0.0001 BTC**，最终持仓为 **0**、活动订单为 **0**；Robot 成功补回 20 bid + 20 ask。完整脚本 `tests/run-auto-tenant-trading-e2e.py` 本轮退出码 0，Mac 证据位于 `acceptance-evidence/unified-jdbc8-fresh-tenant-e2e-20261015.log`。未启用该脚本的 held-position SIGKILL 模式。
5. 因增加一个验收租户，Demo 当前共 **11 个租户，9 个 Robot `RUNNING` / 360 笔挂单，2 个 ERROR / 0 笔**，不能称“10/10 正常”。最新 Core/Robot 10 个容器运行，Order/Trade/MD/Gateway 新实例重启计数为 0；Gateway 无新的 MySQL 5.x 类加载错误。

## NO-GO 项：不可合并为一个虚假的“全通过”

- **Trade P190/P220 原始 WAL 冲突未恢复。** `LP3BG2`（P220）与 `PZGR4M`（P190）在旧运行时经历了同一 Epoch 未提交物理 WAL 重新使用 seq 引发 Replica 字节冲突。`TradeSvrA/replica-conflicts/P190.fenced` 和 `P220.fenced` 保留；不允许删标记、清理真实 WAL、跳过认证接收事务或强制 READY。Trade 正常 forward-only receiver 不支持 `snapshotSeq <= Replica localLastSeq` 的分叉处置，需新的完整认证事务、资金/持仓/委托/成交/Projection 外部权威检查。
- **Trade 活跃分区 HA Snapshot 前置检查 11/11 被阻止**，Replica Snapshot 身份不同／明显落后；新试验租户的 Snapshot 尚未完整生成。`authorizesPrimarySigkill=false`，原始 WAL committed HEAD 和独立签名接收端证明仍未验收。
- **MD 主切前置检查未通过。** `tests/check_order_md_market_snapshot_readonly.py` 对旧 10 租户的 Order 完整市场快照给出 30 项节点级 `ValueError`，其中源端部分 `snapshotSeq` 高于 `commitMarkerSeq`（例如 B75WXC 的 P106 在检查时为 50394 对 50391），不满足严格已提交 Snapshot 条件。MD 实际行情查询成功不等于完整 Snapshot/Diff、旧发布者隔离或权威状态重建已通过。
- Mac ZooKeeper 模式仍为 **`standalone`**，没有真正独立物理投票节点和 Quorum 证明。**没有执行 SIGKILL 或宣布 Order/Trade/MD 生产级 HA 通过。**
- 扩容门禁 `gate=NOT_READY`、`nextRampAuthorized=false`，明确原因 `ENABLED_ROBOTS_UNHEALTHY:2/11`。**未执行 50/200 租户稳态压测、故障注入或 2–3 倍 burst。**
- 所有旧 Robot 配置曾临时按负载调整为每 **30 秒报价刷新、5 秒 Tape**（功能均开启）；这不是原本 1 秒配置的吞吐承诺，不能拿它证明 200 租户容量。新租户沿用自动化默认模板，须单独观察差异。

## 下一轮只做验收阻塞收口

1. 实现并实测 P190/P220 在可信原始 WAL 归档＋独立物理节点签名＋接收端持久化事务下的认证分叉尾部处置，保留资金/持仓/委托/成交及 Projection 的权威对账；不得仅删除旧 WAL 以换取 11/11 RUNNING。
2. 修复活跃 Trade Replica Snapshot/Diff 追平和 MD 已提交全市场快照／旧 publisher fencing，并跑现有 failclosed 预检，先把需要的证明变成可检验的输出。
3. 在上述前提及独立 Quorum 成立后才执行 Order/Trade/MD SIGKILL 主切与 50→200 负载验收。正式发布须采用一致 Maven Central/Common 版本与 GitHub 构建的真实发布镜像，不能把 `-devcombined-...-SNAPSHOT` 的 Mac 本地验证镜像称为正式发布。

**备注：本次仅是已合并源码的 Mac Demo 联合验收，不在此报告中引入或合并新的恢复机制代码。**

## 10 月 15 日 18:07 更新｜Trade 定时快照分区级解耦已部署验收

此前统一验收过程中，进一步核实 Trade 的快照调度器 `TradeSnapshotScheduler.runOnce()` 先调用 `allLocalPrimariesReady()`，要求 **TradeSvrA 本地所有 128 个 Primary 都 READY**，随后才逐分区检查。现网 `P190`、`P220` 恰好属于 TradeSvrA Primary，受原始 WAL 冲突隔离，因此造成了**整个节点其他健康 Primary 定时快照停顿**。这个问题不是所有健康 Replica 的 WAL 都丢失；`TradeSnapshotScheduler` 原本只在 Primary 上定时产出快照，旧只读审计误将 Replica 初始零序号快照解释为 WAL 滞后，已在 [dc-quant-deploy PR #46](https://github.com/bliplink/dc-quant-deploy/pull/46) 校正分类，HA 主切门禁仍拒绝未验证的 WAL。

实际代码修复已合入 **[Trade PR #32](https://github.com/bliplink/com.app.dc.tradesvr/pull/32)**，`saas-crypto` 合并 SHA `96ef1fdfc80acd89211c1e38d5afbda67956e5de`。仅移除调度器的**跨分区全局 READY 否决**；仍使用每个分区的 `PartitionReadinessGuard` 与 Epoch 检查，且 `TradeSnapshotManager.captureLocked()` 再验证恢复隔离、WAL 提交边界和 writer lock。Trade Java 8 全量 **286/286 PASS**，新增回归覆盖有一个 Primary 隔离、另一个可正常参与快照候选；无 Common、Order、MD 或 Gateway 逻辑变更。

本机 ARM64 Trade 修复镜像 `dc-saas/tradesvr:merged-snapshot-scope-20261015` 基于此前已合并的 `merged-jdbc8-20261015` 候选，仅覆盖已测试的 `TradeSnapshotScheduler.class`；仍使用完全相同 Common Jar SHA-256 `8898812068751cc3ab3916bb7b55fe535c10a413ffef7e9be20436d6ac8ff154`。按 Demo 策略暂停 Robot、**同时重启 Trade A/B**、恢复 Robot，保留全部真实 WAL、Snapshot、MySQL 和旧版 env 回滚配置，无数据清理。

**真实本机复核**：TradeSvrA 的健康 `P026` Snapshot 从旧 13:27:36 更新到 **18:01:53**，健康 `P130` 从旧 13:20:37 更新到 **18:03:00**，日志 `TRADE_SNAPSHOT_SAVED` 带对应已提交序号；`P190/P220` Snapshot 保留 13:27 原状，原始冲突 `.fenced` 文件保留。Trade A/B 容器无重启/宿主 OOM；Robot 行情安全重订阅后再次达到 **11 个租户中 9 个 RUNNING，360 笔挂单**，其中健康九租户公开盘口均为 10 bid + 10 ask。订单 256 分区核查 PASS，Projection DB 尾部 Order/Trade **11/11 匹配**。本机证据包括 `acceptance-evidence/eleven-tenant-trade-scoped-snapshot-audit-20261015.json`；整体 11 租户审计依然 `FAIL`，因为两个租户 P190/P220 仍隔离，不存在虚假 11/11 全通过结论。

同时，使用最新已合并 `saas-crypto` 的 `check_order_md_market_snapshot_readonly.py` 重新检查旧 10 租户 Order 全市场 Snapshot，**10/10 三副本快照有效且一致，0 项格式错误**，脚本 9 项测试通过。之前使用旧工作树脚本得到 30 项 `ValueError` 的结论已被更正。**但 MD Promotion 仍未授权**：签名 WAL HEAD、完整 MD Snapshot/Diff、旧发布者隔离及独立 Quorum 未通过。本轮没有执行 SIGKILL 或 50/200 租户压测，ZooKeeper 仍为单机 `standalone`。

**余下 HA NO-GO**：Trade `P190/P220` 需经认证的分叉 WAL 尾部处置、外部资金/持仓/委托/成交/Projection 一致性认证和可信恢复事务；活动 Replica 的 WAL 真正提交头及重放一致性尚无有效独立物理 Quorum 证明。上述条件不足时，不能授权 Primary SIGKILL 或宣称 HA 验收通过。没有改动任何恢复门禁以强行开放 READY。
