# 2026-10-15 Mac mini 完整 WAL 区间认证候选：只读验收与发布 NO-GO

> 状态：**仅本地 ARM64 候选构建，正式集群部署 NO-GO**。无正式恢复接收端 READY 授权、无新版真实 SIGKILL 验收；未删除 WAL、清空数据或替换当前 `dc-saas` 生产容器。

## 原则与本次代码

- Gateway 仍是透传，不改业务；Common 统一 Snapshot/原始 WAL 持久化、完整范围摘要、独立节点签名 Quorum、认证与恢复事务；Trade/Order/MD 保留业务适配器。
- 已合并 [部署 PR #39](https://github.com/bliplink/dc-quant-deploy/pull/39)：Order HA 不再强制 50 个 Robot / 2,000 挂单；资源、同步副本、分区 READY、持久证明等安全门禁不删。
- Common 新候选：[PR #24](https://github.com/bliplink/com.app.common/pull/24) 的已认证完整 WAL 区间/可信恢复 Authority，加 [PR #25](https://github.com/bliplink/com.app.common/pull/25) 的 Netty I/O 线程卸载，集成源码 `8555166`。
- Trade 新候选：[PR #25](https://github.com/bliplink/com.app.dc.tradesvr/pull/25) 的 Chronicle 全范围持久认证和接收端恢复组装，加 [PR #26](https://github.com/bliplink/com.app.dc.tradesvr/pull/26) 的超时重复 ACK 原始字节核验，集成源码 `3ed6f41`。
- Order [PR #11](https://github.com/bliplink/com.app.dc.ordersvr/pull/11) 的物理 CQ committed prefix/durable ACK 和 JDBC 8.0.33，另修并发批量测试的 50ms 调度抖动，最新源码 `40b52d9`。
- MD `026306b`、Gateway `6a84739`、com.app.dc `3966437`。其余层叠 Draft PR 仍未按发布依赖次序全部合并。

## Mac mini Java 8 本地全量单测（集成后的最终源码）

| 模块 | 通过 | 失败 | 跳过 |
|---|---:|---:|---:|
| Common | 284 | 0 | 0 |
| Trade | 272 | 0 | 0 |
| Order | 369 | 0 | 3 |
| MD | 136 | 0 | 0 |
| Gateway | 16 | 0 | 0 |

Order 首次全量存在 `concurrentRecordsShareOneCumulativeAck` 依赖 50ms 调度的非确定性断言（一次拆成两批）。原测试独立复跑 4/4 PASS，单独调整该测试的并发批满窗口后全量再次 **372 tests，0 fail，3 skipped**。没有修改 Order 生产复制语义。

## 离线 ARM64 候选镜像（均未运行于 Demo）

| 服务 | 本地镜像标签 | Image ID 前缀 |
|---|---|---|
| Order | `dc-saas/ordersvr:certified-v2-local-20261015` | `a0501af27042` |
| Trade | `dc-saas/tradesvr:certified-v2-local-20261015` | `d5a578ce1fb5` |
| MD | `dc-saas/mdsvr:certified-v2-local-20261015` | `1e8ca54f44e6` |
| Gateway | `dc-saas/gw:certified-v2-local-20261015` | `e6f4fcbafa1e` |

四镜像都为 ARM64、Java 8，**同一个 Common JAR SHA-256**：
`af14b091151feba2caf384ae8652065fa1b12de8ef27af57b57fe955187d71de`；本地隔离 Common GAV 为 `3.0.21-devcombined-20261015-SNAPSHOT`（**未发 Maven Central**）。镜像明确 `otc.release.authorized=false`。构建为离线验证，基于本机已有旧服务 Java 运行时镜像而非重新拉取的干净正式基镜像，**不可直接当作 GHCR 生产发布镜像**。候选 image ID、源码锁和一致 SHA 的私有机器可读清单见 `~/.opentradingcore/otc-final-integrated-build-20261015/artifacts/candidate-images-20261015.json`，勿上传包含本机配置的其他私有 env。

## 当前真实 Demo 只读审计

- 24 个 `dc-saas` 容器运行，**11 个 TRIAL 租户**；其中 **10 Robot RUNNING、400 挂单，1 Robot DEGRADED/0 挂单**。不能写成 10/10 完全健康。之前观察到异常 `ZGH4H4` 的 `queryTradePosition` 被 `TradeSvrB/P077 PARTITION_NOT_READY` 拒绝。
- Order：`256/256 READY`，Epoch=1，三节点 `snapshot_sets_equal=256`，容器 0 OOM/重启；未有认证 HTTP Session，逐分区认证路由探针跳过，不能把此项称作完整写 API 验收。
- Projection 只读必要门禁：MySQL Order 11 / Trade 11 分区 `PROJECTION_DB_TAIL_MATCH`。它没有与 Order/Trade 权威 WAL committed HEAD、余额/持仓/订单/成交/流水做源端交叉证明。
- Trade 只读 Snapshot/角色门禁：`decision=BLOCKED`，因为租户审计未达到 11/11 完整健康状态；`authorizesPrimarySigkill=false`、`authorizesReplicaRestart=false`。
- ZooKeeper 实测 `Mode: standalone`；同一 Mac Docker VM 不能冒充跨物理故障域的真实投票多数派。
- Common/Trade 最新 CI 不运行：GitHub Checks 注释为近期账单付款失败或 spending limit；不是 Maven 编译失败。本机回归不等于 CI/现网高可用验收。

## 发布 NO-GO / 后续依赖顺序

1. 将 Common `CertifiedRecoverySourceAuthority` 与 Trade `TradeCertifiedRecoveryAssembly` 从候选手工组装真正接到受控被动接收节点恢复调度；从真实 ZK 读有效 Primary、Replica、Epoch/Version、投票集合与独立节点信任配置，并证明完整 Snapshot + **所有物理 WAL 区间 SHA** 的多数签名。任何截断、快照落后、成员变化、未获授权的写/重放必须失败关闭。
2. 所有恢复阶段保留 Common durable ledger，`REPLAY_COMPLETE` **不等于 READY**；必须增加由权威 Trade/Order WAL 与 MySQL balances/positions/orders/executions/open orders/Projection/MD 全量跨域对账并检验旧 Primary fencing 的独立外部门禁。
3. 修复实时异常租户和 Trade 分区反复 NOT_READY，保持现有十个正常 Robot 真实业务长稳。新候选镜像须通过干净正式构建/指纹锁及隔离接收者安全验收后，才能按依赖顺序合并发布 Common → com.app.dc → Order/Trade/MD/GW，后续执行真实 SIGKILL/角色反转。
4. WAL 过期物理删除与 MD 自动主切仍保持关闭；50/200 租户性能测试延后独立进行，不应再成为 Order HA 的固定 50 Robot 门禁。

本报告明确区分本机单测/候选镜像与正式部署。**本轮未执行生产集群替换或故障注入；没有实际新协议 HA failover PASS。**
