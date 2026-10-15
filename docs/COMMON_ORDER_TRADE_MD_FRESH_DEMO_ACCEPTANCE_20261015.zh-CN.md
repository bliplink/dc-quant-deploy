# Common / Order / Trade / MD：全新 Demo 集群统一部署与验收｜2026-10-15

> 范围：Mac ARM64 单机 Demo。目标是**反复从零部署、发现机制问题、统一修复和验收**，而非恢复历史测试资金或 WAL。此文是本机实际验证记录，不是跨物理机 HA 证明。

## 一、发布形态

- 共 24 个 `dc-saas` Compose 服务。核心镜像均从已合入的 `saas-crypto` 源码构建，复用同一份 Common Jar SHA-256 `8898812068751cc3ab3916bb7b55fe535c10a413ffef7e9be20436d6ac8ff154`。
- 本机镜像：Order `dc-saas/ordersvr:merged-jdbc8-20261015`（3 台）；Trade `dc-saas/tradesvr:merged-snapshot-scope-20261015`（2 台）；MD `dc-saas/mdsvr:unified-freshboot-20261015`（3 台）；Gateway `dc-saas/gw:merged-jdbc8-20261015`。**这些是本地 ARM64 验收镜像，不是已发布 GHCR 正式镜像。**
- 此轮旧运行目录由 `scripts/mac-saas-reset.py --mode stage` 整体移至受控 quarantine，所有 MySQL、WAL、Snapshot 等旧数据均未删除。全新 MySQL 从零租户启动；没有把旧 P190/P220 的冲突 WAL 复制回来。
- 本地 Java 8 MD 全量 **139 tests / 0 failures**；Common/Order/Trade 的既有统一构建回归记录见本目录原统一验收文档，本轮未将其以前的测试成绩冒充再次执行。

## 二、冷启动发现的真实机制 / 发布问题与修复

1. **MD 在全新 ZooKeeper / Order 尚未在线时同步订阅导致 Spring `CommandLineRunner` 崩溃。** [MD PR #7](https://github.com/bliplink/com.app.dc.mdsvr/pull/7) 合入 `saas-crypto`：异步重试上游 Order 全量 Image/成交/Depth Diff 与指数/标记价订阅，成功的订阅不重复注册；Common 的分区、Epoch 和旧发布者隔离不放宽。
2. **裸 `docker compose up` 绕过正式发布的 MySQL 全量 migration。** [deploy PR #48](https://github.com/bliplink/dc-quant-deploy/pull/48) 补齐 trial liquidity + Tape 初始 SQL；[PR #49](https://github.com/bliplink/dc-quant-deploy/pull/49) 在 initdb 阶段执行全套版本化迁移；[PR #50](https://github.com/bliplink/dc-quant-deploy/pull/50) 修正只读 mount 子目录冲突；[PR #51](https://github.com/bliplink/dc-quant-deploy/pull/51) 修复初始 tenant ID/序列重复 DDL；[PR #52](https://github.com/bliplink/dc-quant-deploy/pull/52) 淘汰重复且不可安全重放的旧 numeric-ID migration。实际空库重建后全部迁移执行成功，MySQL 日志明确显示 `schema bootstrap complete` / `MySQL init process done`，表 `dc_fresh_schema_install_status` 的 `all-migrations-done=1`。
3. **数据库部分初始化失败但 MySQL 端口健康会误报 READY。** [deploy PR #53](https://github.com/bliplink/dc-quant-deploy/pull/53)：全新数据库从 initdb 早期写 `ready=0`，全部迁移完成后才写 `ready=1`；健康检查要求完成标记和关键业务表。保留旧数据库无此标记时的兼容检查。两项新增离线测试覆盖初始化中断、缺表与兼容性。**该安全门禁已合入源码，未为改变正在运行的 Demo 容器而再次清盘。**
4. **直接 Compose 启动没有执行 `deploy-saas.sh` 的 ZK 分区初始化。** 真实检查时三个分区根目录均不存在；按正式脚本规定创建后验证：Order `256/256`（A/B 交替 Primary，C 同步副本）；Trade `256/256`（A/B 互为副本）；MD `256/256`（A/B 交替 Primary，C Learner）。随后重启 A/B/C 装载分配，重新验收。MD-A/B 各出现 `MD_READ_ROUTES_READY partitions:128`，MD-C `partitions:0`，符合 Learner 不参与 Primary 发布的隔离。
5. **直接 Compose 启动未初始化专用 Robot Runtime 身份。** Robot 登录报 `USER_ACCOUNT_OR_PWD_ERROR`。调用正式部署脚本已有的 `provision_platform_admin()` 和 `provision_robot_runtime_identity()`，按真实 API Key 更新 LoginSvr 内存，再重启 Robot；无需放宽鉴权或修改 Common/Gateway。
6. **LiqSvr 与 MD 冷启动顺序竞争。** 直接 Compose 首次启动 LiqSvr 时上游尚未就绪，`CommandLineRunner` 报错；上游 MD 完整启动后，重新启动 LiqSvr，实测 `LIQ_MD_SUBSCRIBE_READY location:QXFUMM securityID:BTCUSDT markReady:true`。正式部署脚本必须将 **先配置 → ZK 分区 → 业务节点 READY → 依赖服务就绪** 作为固定顺序；不要将一次 `docker compose up` 当成一键部署验收。
7. **自动审批是异步事务。** [deploy PR #49](https://github.com/bliplink/dc-quant-deploy/pull/49) 修正 E2E：提交后轮询 `APPROVED`，仅真正审批成功才允许继续后续入金、下单；即时 `PENDING` 不是永久失败。

## 三、真实业务 E2E（最终核对 20:13 CST）

| 租户 | 审批 / Robot | 撮合、持仓和资金 | 状态 |
|---|---|---|---|
| QXFUMM | 自动 `TRIAL`，`RUNNING`，40 笔委托；公开盘口 10 bid + 10 ask | 模拟入金，买入 0.0001 BTC，成交 + 多头一致，卖出平仓，持仓 0，活动委托 0 | **PASS** |
| HKRIJ1 | 自动 `TRIAL`，`RUNNING`，40 笔委托；公开盘口 10 bid + 10 ask | 独立交易员模拟入金、开仓 0.0001 BTC、成交核对、平仓、持仓 0 | **PASS** |
| Z541W7 | 自动 `TRIAL`，`RUNNING`，40 笔委托；公开盘口 10 bid + 10 ask | 独立交易员模拟入金、开仓 0.0001 BTC、成交核对、平仓、持仓 0 | **PASS** |
| W4UB6K | 分区初始化前产生的测试租户，无 Robot | `NEEDS_RECONCILIATION/FUND`，自动流程 fail-closed；禁止通过重复入金清除此状态 | **预期隔离 / 不计 PASS** |

- 已完整成功的**三个不同租户**共持有 120 笔 Robot 委托，非虚构 10/10。订单分区/快照与路由的现网只读核查 **PASS**。Projection MySQL 尾部事件 Order/Trade **3/3 匹配**（仅数据库 tail，不代表各 Replica 持久 WAL 与独立投票证明）。
- 当前 24 服务进程保持运行。服务器存储剩余约 98 GiB；macOS 单 Docker VM 的 ZooKeeper 为 `standalone`，无法用此环境证明多物理节点独立证书 Quorum。

## 四、后续统一 HA 门禁（NO-GO，不能虚报）

- Order-C `tests/order_ha_rollout_gate.py --target OrderSvrC` 真实只读结果 **NO-GO**：C 持有 256 个同步副本角色；未确认剩余副本同步 WAL ACK 和可验证持久化 Quorum 之前，不能 SIGKILL 或滚动停它。
- Trade A/B 的认证 WAL HEAD + Replica ACK / Epoch 与源端财务权威对账、真实持仓故障主切及恢复节点追平仍需完整验收。不能把一份 Snapshot 或 Projection tail 等价为 Trade 自动主切授权。
- MD 的完整 Order 市场 Image/Diff、旧主发布者隔离、可信 HA Quorum 与故障后恢复仍待验收；Learner MD-C 不应自行成为有发布权限的 Primary。
- 50/200 租户持续负载、2–3x burst 尚未执行；当前三个成功租户不能证明生产容量。Common 统一接口不应被为了 Demo 测试绕过：必须保持 WAL 证据、Epoch fencing、持久化 Ledger 和 Replica READY 防线。

**运行指引：** 重新部署必须走 `deploy-saas-macos.sh --full-cluster` / `deploy-saas.sh` 正式分阶段入口，或者在有明确验证证据时逐项执行同样的 MySQL migration、服务身份创建、ZK assignment、Order/Trade/MD READY 步骤；不能仅按 Compose 容器 Up 数量宣布通过。代码通过已合入 `saas-crypto` 的 GitHub PR 发布，**GitHub Actions 费用限制不在本次任务范围内**。
