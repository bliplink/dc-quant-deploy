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

## 21:17 更新：Order/Trade 同步 WAL 本地回退风险修复并实际部署（HA 仍 NO-GO）

**新发现的共同机制风险**：`deploy-saas.sh --full-cluster` 意外把 Trade `rollbackUncommittedTail.enabled` 设置为 `true`，Order A/B/C 生成器也把相同开关固定为 `true`，同时两者都是 `replication.required=true`。这会允许旧 `RecoveryManager` 在新 Primary／同 Epoch 重启时，按单节点已提交水位对物理 Chronicle 原始 WAL 执行本地 archive/rebase；但另一个同步副本可能已经持久化相同 seq 的原始尾部，造成同 Epoch 物理 WAL 分叉。即使旧路径通过本机 snapshot/epoch 检查，也不足以证明 Common 独立物理 Quorum 的接收事务。

**已合入源码与部署配置：**

- [Trade PR #33](https://github.com/bliplink/com.app.dc.tradesvr/pull/33)，`f441cf7d89c59b5f2471689800daae4b373a9e87`：同步复制时禁止旧式本地 dirty-tail rollback/rebase。无论是在 `start()` 还是 `runOnce()`，配置非法即阻止服务取得 READY；之前已有 READY 标记也会撤销。无损保留原始 WAL，必须改走 Common 认证恢复。Trade Java 8 全量 **287/287 PASS**。
- [Order PR #13](https://github.com/bliplink/com.app.dc.ordersvr/pull/13)，`dba87a46fe9a519bdc4475012d3a9d89a6fb7519`：在 `OrderPartitionRecoveryManager` 的普通 Epoch 提升和 `rollbackSameEpochRestartTail()` 两条旧恢复入口检查 `order.cluster.replication.required`。有同步副本时拒绝本地 rebase，原始 WAL 不改写。Order Java 8 全量 **374 tests、0 failed、0 errors、3 skipped**。
- [dc-quant-deploy PR #55](https://github.com/bliplink/dc-quant-deploy/pull/55)：Trade full-cluster profile 默认 `rollback=false`，且配置生成器拒绝 `rollback=true` 与同步复制组合。
- [dc-quant-deploy PR #56](https://github.com/bliplink/dc-quant-deploy/pull/56)：Order A/B/C 和 Order dev HA 配置统一 `rollback=false`，Order/Trade 配置测试均 PASS。
- Common 本轮额外运行 `DurableReplicaAckGuardTest`、`RecoveryQuorumCommitAttestationTest` 和 `VerifiedRecoveryQuorumClientTest`，共 **12 tests PASS**（只证明 Common 单元契约，不是三台独立物理投票的在线证明）。

**Mac Demo 实际替换：** 保留既有数据、订单和 WAL，暂停 Robot，按业务组分别整组替换 Trade A/B 与 Order A/B/C，随后恢复 Robot。新本地 ARM64 镜像为 `dc-saas/tradesvr:merged-wal-fence-20261015`、`dc-saas/ordersvr:merged-wal-fence-20261015`。两种镜像仍引用和 MD A/B/C、Gateway **完全相同**的 Common Jar SHA-256 `8898812068751cc3ab3916bb7b55fe535c10a413ffef7e9be20436d6ac8ff154`。原本配置值在 Mac 运行目录改为 `false`，恢复配置备份只留在本机具私有权限的 `~/.opentradingcore/otc-demo-direct-20261015/acceptance-evidence/`（绝不提交凭据文件）。**这些镜像仍是 Mac 本地验收候选，不是官方 GHCR release。**

**上线后实测**（2026-10-15 21:17 CST）：Order 256/256 Snapshot、assignment 和路由只读检查 `PASS`，Order/Trade Projection DB 尾部 `5/5 MATCH`；新业务租户 `BS5GUJ` 在 Trade 修复后、新租户 `FHJ2E4` 在 Order+Trade 两组修复后均独立通过自动审批、40 笔 Robot 报价、10 bid/10 ask、模拟入金、真实 IOC 开仓成交、持仓核验、reduce-only 平仓后持仓归零和活动委托归零。最终 **5 个 Robot RUNNING，200 笔挂单**，各核心容器无新增重启／OOM。另一个早于集群初始化时产生的测试租户 `W4UB6K` 仍 `NEEDS_RECONCILIATION/FUND`，此轮未绕过财务门禁，故不能宣称所有 6 租户正常。

**未通过及下一步唯一需要收口的 HA 证明：**

1. 真正的 Common `Snapshot + 原始 WAL + diff`、源端 HEAD、持久 Replica ACK、独立节点签名／Quorum，以及接收端恢复事务与**资金／持仓／委托／成交／Projection**权威一致性证明未构成在线闭环。这一轮虽阻止了单节点错误 rebase，**仍不能授权 SIGKILL／自动主切／滚动 Order-C 同步副本停机**。
2. Order → MD 的*在线行情*正常，但 MD 的**完整已提交市场恢复 Image**尚未被证明可用：实际只读 `check_order_md_market_snapshot_readonly.audit` 对目前 5 个成功租户得到 `verifiedTriplicateSnapshots=4/5`。新租户 `FHJ2E4` 所属 `P064` 的 Order A/B/C 持久化 Snapshot 均为 `snapshotSeq=6, commitMarkerSeq=0, books=[]`，而它在实际交易 API 中有 10+10 档行情。这代表**在线 Order 盘口与过期磁盘 Image 之间有验收缺口**，不能拿实时盘口代替已提交原始 WAL 下的完整可恢复状态；修复须遵循 Order 当前权威 source、Snapshot/Diff 和旧 MD publisher Epoch 隔离，不能强行把未提交空快照标记为可信。
3. Mac 当前 ZooKeeper 仍在一个 Docker VM 中运行；缺乏独立物理 Quorum，未进行真实主切、持仓 failover／rejoin／角色反转、50/200 租户稳态或 burst 压测。以上须在恢复授权和在线证据充足后再测。

**结论：**本轮完成了 Order/Trade **共性不安全物理 WAL rebase** 的代码、测试和 Demo 统一部署修复；正常交易仍 PASS；**HA 认证恢复和 MD 自动主切仍明确 NO-GO**。不要清盘绕过不可用的证明链，也不需要再维护历史 P190/P220。

## 21:49 更新：Order → MD 新市场持久 Image 三副本恢复前置条件闭环

**发现：** 对已通过交易 E2E 的新租户 `FHJ2E4`，所在 `P064` 仍只有三份 `snapshotSeq=6, committedStateSeq=0, books=[]` 的旧快照，但实时盘口正常。Order Demo 定时快照每 60 秒扫描、20,000 已提交变更或 1 小时才更新、每轮最多 1 分区，因此一个低成交量新市场可能长期缺失恢复 Image。

**修复一：[Order PR #14](https://github.com/bliplink/com.app.dc.ordersvr/pull/14)**：当某分区原快照未包含任何已提交业务状态、首次出现真实已提交 mutation 时优先进行一次 `captureAndReplicateQuiescent`；后续保持原有节流。真正冷启动重建时还发现另一个边界：Robot 暂停期间，Order 会先持久化一份**有提交水位但 `books=[]`** 的快照（如 `P064 snapshotSeq=3205 committedStateSeq=3204`）；Robot 恢复后该新市场仍不满足首次提交判断，故不能靠 PR #14 单独解决。

**修复二：[Order PR #15](https://github.com/bliplink/com.app.dc.ordersvr/pull/15)**：`OrderSnapshotManager` 提供只读 O(1) 已登记市场 identity 数量；`OrderPeriodicSnapshotService` 对比当前 trackedBookCount 与上次**持久化 Snapshot 已覆盖的 Book 数量**。若出现新交易市场，且本分区已提交状态前进，优先捕获一次市场 Image，通过原有 Writer 隔离、commitMarker、Projection 水位、同步副本 snapshot transfer 和 `maxPartitionsPerRun=1` 预算；后续继续 20,000 mutation/1h 节流，不会按单笔委托反复截图。增加单测覆盖空业务、首次 commit、已有空快照的重启、Epoch 变化、新增第二市场和重复变更限流。

**真实零清盘 Demo 验收：** 两次补丁均合入 `saas-crypto`，Java 8 最终 Order 全量 **376 项测试，0 failures、0 errors、3 skipped**。Mac 本地 ARM64 镜像 `dc-saas/ordersvr:merged-market-identity-image-20261015` 已部署到 Order A/B/C，保持 `order.cluster.recovery.rollbackUncommittedTail.enabled=false`、Common 统一 SHA 和旧 WAL 完整保留。对最初问题租户 `FHJ2E4/P064`：三副本同步获得 `snapshotSeq=7762, committedStateSeq=7761, books=1`，不再是空 Image。

随后新注册租户 **H4676T**，自动审批、Robot 40 委托、买卖盘口 10+10、模拟资金、成交 0.0001 BTC、持仓核对、平仓归零 **全部 PASS**；其 `P228` 三副本 Snapshot 一致（`snapshotSeq=412, commitMarkerSeq=412, books=1, orders=39`）。最终 **6 个业务成功租户的 Order 全市场持久 Image 三副本核查 `6/6 PASS`、无问题**；Order 256 分区一致性 `PASS`，Projection 数据库尾部 `6/6 MATCH`。仍有早期启动失败的 `W4UB6K` 为 `NEEDS_RECONCILIATION`，未绕过财务门禁。

**重要边界：** 上述只证明恢复**源端持久 Image 的存在与三副本一致性**，并非 MD-C 自动接收并应用的 E2E 故障切换证明；Common 独立物理 quorum、源端已提交 WAL ACK、接收端 Ledger/READY、MD snapshot+diff、旧发布者隔离和 Order/Trade SIGKILL 仍明确 NO-GO。任何中间的 snapshotSeq 暂时偏差需最终达到三副本一致后才能通过。现有 Mac 单机 ZK 不可用来冒充跨物理节点 Quorum。

## 续验：MD 接收端 Image/Diff 应用证明与真实部署门禁（仍不授权 HA 主切）

**代码风险与修复**：原 `MdImageRecoveryFailoverController` 的两阶段 `RECOVERING → READY` 只调用 `Safety.requireAuthoritativeOrderImage` 与 `requireRecoveryEpochPublicationFence`。前者证明**源端** Order Image 的有效性，不能证明新当选 MD 已经实际应用全部市场 Snapshot 并连续回放 Diff。当前 MD 仍缺真实 `MdImageRecoveryFailoverController.Safety` 生产实现，自动 failover 关闭；但必须先消除接口层面“证明源端即允许 READY”的安全漏洞。

[MD PR #8](https://github.com/bliplink/com.app.dc.mdsvr/pull/8) 已合入 `saas-crypto`：在 READY 前增加独立的 `requireCandidateAppliedImageAndDiff(recovering)` 门禁，其默认实现 fail-closed；缺证明时返回 `RECOVERY_NOT_APPLIED`，保持当前分区 `RECOVERING`，不创建 READY ZK CAS、不授权 MD 行情读路由和发布。接收端收据未来必须绑定物理候选节点、partition、Epoch、源端已提交序列与完整市场库存，禁止跨 Epoch 或重放旧收据。源端 Order HEAD 认证、候选已应用数据及 Gateway/旧发布者隔离三项仍需分别验证，不能合成一个布尔值。

**本地 Java 8 回归**：`MdImageRecoveryFailoverControllerTest` 新增独立测试，证明仅有 signed source + publisher fence，而没有候选接收应用证明时仍不可 READY；补充应用证明后，仅在隔离 fake ZK 状态机测试中允许成功。MD 全量 **140 tests / 0 failures / 0 errors / 0 skipped**。

**Demo 同步验证**：基于前次 `dc-saas/mdsvr:unified-freshboot-20261015` 同一 Common Jar 构建 ARM64 本地镜像 `dc-saas/mdsvr:applied-image-ready-gate-20261015`，源码修订 `953af5cc7690b4650e8652c4bc14ee6ae18d3762`，`dc.release.authorized=false`（仅 Mac 候选，不是 GHCR 正式发布）。协调暂停 Robot/LiqSvr，重启 MD A/B/C，按顺序恢复 LiqSvr、RobotSvr，原始 Order/Trade、MySQL、Snapshot/WAL、ZK 分区均未修改。新 MD A/B 仍分别 128 个读分区，C 仍 0，未擅自提升为 Primary。重连期间 Robot 短暂 `WAITING_MARKET_DATA`，随后自动恢复 **6 RUNNING / 240 resting orders**，LiqSvr 六个租户的 mark 订阅均重新 READY。Order 256 分区快照/路由检查 PASS；6/6 Order 持久市场 Image 三副本齐全；Projection 数据库 tail 6/6 MATCH。新 MD 的 Common Jar SHA-256 `8898812068751cc3ab3916bb7b55fe535c10a413ffef7e9be20436d6ac8ff154`。

**操作型 HA 门禁改进**：[部署 PR #59](https://github.com/bliplink/dc-quant-deploy/pull/59) 允许对**完整 SHA-256 本地 Docker Image ID**进行严格匹配；拒绝不完整 SHA、不合法格式及可变的 `:latest`，仍保持所有 HA NO-GO 和只读接口不变，同时显式加上 `MD_CANDIDATE_APPLIED_IMAGE_DIFF_UNATTESTED` 阻塞。Python 隔离单测 **15/15 PASS**。对当前新版镜像执行 256 分区只读真实预检，确认 MD A/B 各 128 Primary；输出 **BLOCKED / canInjectMdPrimaryFault=false**。此前的持久快照存在与普通实时盘口通过并不能替代独立签名 Order Source HEAD、旧发布者/新 Epoch fence、候选节点应用 Snapshot/Diff 事务 Ledger、故障后的 Robot/Order 对账。Mac 单机 ZooKeeper 也不能证明物理独立 Quorum。**本轮未 SIGKILL、未做带故障压力、未向外宣称 HA 已验收**。

**后续唯一主线**：MD 接入可审计、不可跨 Epoch 复用的接收端恢复事务与真实应用回执，在 Common 的源端签名 HEAD/原始 WAL 范围/Replica ACK 和 Gateway 旧发布者隔离证明均就绪后，才尝试在受控故障注入中执行 `RECOVERING → READY`。Order/Trade 同样必须完成带资金、持仓、委托、成交、Projection 的权威一致性证明。GitHub Actions 费用限制不影响此轮 Mac 本地构建与单测。
