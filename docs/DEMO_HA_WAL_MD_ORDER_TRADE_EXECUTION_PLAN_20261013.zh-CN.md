# OpenTradingCore Demo：MD 主切、WAL 归档安全删除、Order/Trade HA 执行目标

> 更新日期：2026-10-13。**本文件是后续执行唯一的验收任务总表**，每轮变更要更新完成状态、代码提交、镜像标识、故障证据和未通过原因。不是把待办事项写成已经上线。依据：`MAC_TRADE_COMMON_WAL_BATCH_LIVE_ROLLOUT_20261013.zh-CN.md`、`MD_HA_FAILOVER_GATES_20261010.zh-CN.md` 和 `MAC_COMMON_HA_WAL_ARCHIVE_RETENTION_GC_SAFE_20261012.zh-CN.md`。

## 总目标、约束与当前基线

**目标**：先在 Mac mini + Docker Compose Demo 上交付三个可验收机制：
1. **MD 主节点自动接管**，从 Order 权威订阅完整行情 Image + 连续 Delta 恢复；不增加 MD→MD WAL 副本路径。
2. **Order/Trade WAL 自动归档、Snapshot 和安全删除**，必须可重启恢复、48h 保留、低优先级/限速，拒绝未知文件、旧 epoch、Reader 未释放、缺 Seal/副本/Projection 水位及缺备份证明。
3. **Order + Trade 全链路 HA**，真实写入/撤单/撮合/持仓期间进程级故障注入，证明自动恢复与跨 DB/Projection 权威对账。

**优先性能**：避免高频全分区 ZK/磁盘扫描、锁住 Order/Trade 撮合热路径或制造同步 WAL/DB IO。Common 提供 RAFT 式 byte[] 状态机与可复用复制恢复/归档接口；Order、Trade 只负责自身业务 apply/snapshot/restore；MD 为 Order 派生行情。Gateway 只透传消息，不修改；Demo 不启用 TLS。

**当前本地运行基线（2026-10-13 实际核验）**：
- 24/24 容器 Running；Trade A/B 已冷切到本地 `dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261013-walbatch-08cc695`，双向自动温缓存、P222 A→B→A、P012 持 0.0001 BTC 的真实 SIGKILL 自动切主 Epoch5/被杀节点追平通过。
- Trade 256/256 分区 READY；11/11 租户 Robot 正常、每户 40 活动委托、盘口双边各 10 档；Projection 既有事件水位一致性只读核查通过。
- Order 三节点已有 256 Snapshot 一致与历史故障注入证据，但新一轮**带持续写入的跨服务权威逐笔**验收仍未执行。
- MD failover 只读 preflight `BLOCKED`，缺 Order 完整市场最新认证证明、控制器 CAS/fence 和旧 Primary publish fence；**绝不将 READY/日志当授权**。
- Common WAL 封存与隔离回收原语存在，真实 disposable GC canary 做到 1 安全删除+8 类不安全 HOLD；现网只读盘点 526 个归档、48h 到期 0、删除授权 0。**现网周期 Archive/退休闭环尚未通过**。
- 故障测试租户 QGM88N 仍有 `0.0001 BTC` 模拟多仓，恢复凭据受执行环境限制。必须走合法 Trader API 平仓，绝不直改 MySQL 或重复不确定成交。

## P0 — MD 自动主切（状态：BLOCKED / 未上线）

- [ ] MD C/A/B 的真实 ZK ephemeralOwner、assignment/epoch、实际行情订阅 Image 和完整市场清单逐分区只读建证；严禁凭容器 Up 或样例行情日志认为同步。
- [ ] Order 返回源 Primary Epoch/持久 commit HEAD、全市场 Image 摘要/水位与有界 Delta 连续性证明，MD 以签名 Source/新鲜度证明核验；不建立额外 MD→MD WAL 同步。
- [ ] 实现具有单控制器租约的 ZooKeeper `READY→RECOVERING(new epoch)→READY` versioned CAS，旧 Primary 分区级发布 fence、断联拒绝 publish，含失联恢复和并发主切单一性。
- [ ] 新 MD 仅在 `Order committed Image + contiguous Delta + current epoch + complete market set` 全满足后 READY，Robot/MDSvr 分离重新订阅及重建订单簿，不重复下单。
- [ ] 离线模拟断联、乱序、旧 epoch 和双主：先单分区，再 11 租户 Robot 真实行情下的 MD Primary SIGKILL、C 追平、role reversal。验收：**无双主/无旧行情、全租户盘口恢复、Order 权威订单与 MD 市场完全吻合**。一次失败即锁住自动主切。

**阻塞条件**：现有 `check-md-failover-preflight.py` 返回 BLOCKED 时仅允许只读/隔离开发验证；不准 `--apply` 绕过已实现的人工 promotion fail-closed gate。

## P1 — WAL 定时归档 / Snapshot / 安全回收（状态：PARTIAL / 现网删除禁止）

- [ ] 盘点 Order/Trade/MD 的 Common 写入接口复用现状，确认 Trade 已有周期 Snapshot；确定真正独立的 **WAL 自动 Seal/分段调度** 是否实际运行，禁止将 Snapshot 重基线产生的 archive 目录冒充周期归档。
- [ ] 使用 Common `JournalArchiveRotationPolicy` / `JournalArchiveSealCoordinator` / `DurableJournalArchiveSealLedger`，由业务层注入物理 Primary/ZK epoch、已提交 durable HEAD、full Snapshot、所有 Replica durable ACK、Writer barrier，按分区稀疏轮询、单次有限 IO、可恢复 `PREPARED→WRITER_SWITCHED→ARCHIVE_SEALED`。
- [ ] 归档目录仅在落盘签名/哈希、Archive+Active 可读、Reader generation 退出且旧 epoch 无需追赶后成为删除候选；兼容旧主恢复跨 Archive/WAL。
- [ ] Common `JournalArchiveRetirementCoordinator` + `LocalArchiveQuarantineFileOps`：持久 `PREPARED→QUARANTINED→REMOVED`，48h（可配置但当前保持）并验证**每个消费组 Projection 持久水位**、Replica Snapshot/WAL、Reader fence、外部备份 SHA 恢复试验；锁内二次复核；失败 HOLD。
- [ ] 独立 canary 制造过期归档、故障中断/重启、备份损坏/水位落后、跨 epoch，验证仅安全对象真正 unlink。再做现场只读审计和最小分区灰度；没拿到全部持续运行证明 **physical GC.enabled=false**。
- [ ] 限速和资源基线：记录 TPS/P95/P99、CPU、GC、IOPS、WAL 磁盘真实 blocks；证明 Snapshot/封段/删除不造成明显吞吐下降或业务停顿。

**当前事实**：disposable 物理删除 canary PASS 不等于 live physical GC 已授权。无过期目录或缺少备份/签名消费者水位则在线必须 0 删除。

## P2 — Order + Trade 全链路 HA（状态：PARTIAL / 需逐笔权威证明）

- [ ] 固定当前本地 Common JAR、Order/Trade/Projection 镜像 hash、ZooKeeper 256 assignments、11 租户 Robot/业务基线；确认不同 Epoch 的 Snapshot 不可混淆、Replica durable ACK 满足门禁。
- [ ] 单分区/10→11 租户持续下单撤单撮合：SIGKILL 当前 Order Primary→ZK 新 epoch CAS→READY→恢复原节点 Learner 重基线并追平为 Replica→role reversal；先判定有无双主，不盲目杀第二个同步副本。
- [ ] 使用合法交易 API 保持真实模拟持仓，Trade Primary SIGKILL、自动晋升和恢复、双向角色反转、归档跨段落后副本追平。
- [ ] 每一故障前后对账：MySQL `orders/executions` 的稳定唯一 ID、`balances/positions/open orders`、Projection durable watermark + event tail、Trade 内存状态及 Order committed WAL/ACK；结果必须**不丢单、不重复成交、资金持仓总账最终一致**。`0 orphan` 的有界批次检查不能冒充全库事务证明。
- [ ] 记录 `kill→epoch change→READY→浏览器行情恢复` 时间、业务 TPS、P95/P99、CPU、GC、磁盘 IO、真实订单处理/撤单/成交数。验收失败优先修机制并回归，不修数据库伪造健康。

## P3 — 后续规模与发布（状态：DEFERRED）

- [ ] 11 租户负载长时 Soak，通过后 50→100→200 批次新建租户，自动审批、自动 Robot，记录每批订单 TPS 而不是点价数，按资源门禁动态停止。此阶段需等待 P0/P1/P2 安全门禁。
- [ ] **按用户要求暂缓正式发布链**：Common 3.0.18 Sonatype/Central、`com.app.dc` PR、Trade GHCR amd64+arm64 发布/全镜像替换，不作为 P0/P1/P2 的前提。保留当前本地镜像/源码/依赖的唯一 SHA 和原运行数据恢复点；Common 私有批量协议已有开发和本地验收记录，但正式版本是否 Central 可下载必须单独核验。
- [ ] 发布恢复时再进行中央仓库版本追踪、GitHub Actions 多架构编译、生产镜像 hash 和冷切换；不可将离线 local SNAPSHOT 声称为中央仓库版本。

## 每轮进度记录规范

新增小节需含：时间、分支和提交 SHA、所用镜像完整 digest、实测命令/证据私有路径、PASS/BLOCKED/FAIL、复现范围与风险、下一步门禁。**未经测试的不标记完成。** 若测试安全机制阻断写操作，保留 BLO​CKED 和失败详情，严禁绕过 Gateway、Replica ACK、Epoch fencing 或高危文件安全策略。

## 2026-10-13 第一轮实机推进与证据（UTC 02:09–02:21）

以下为**这轮确实执行过的结果**，不替代上面的未完成清单。

### 任务 1：MD（只读安全基线 + 隔离单测）

- 通过 `scripts/check-md-failover-preflight.py` 锁定当前 3 个真实本地 MD 镜像，只读结果：`256/256 READY`，MDSvrA/B 各 128 Primary，3/3 物理 ZooKeeper ephemeral 结点存在，`canPromote=false`、`decision=BLOCKED`，仍缺 Order 当前认证全市场 Image、旧主 fencing、两阶段晋升 READY 证明、Robot reconciliation。
- 进一步完整扫描全部 256 个 ZK 分区：**MDSvrC 已被分配为 256/256 非投票 Learner**，此前旧文档“还未加入 C learner”是过时快照。无需再改写 ZK 注册。
- 用真实租户 Route→Partition→ZK Epoch/Role 对照完整容器日志：**MD A 11/11、MD B 11/11、MD C 11/11 `MD_MARKET_READY` 匹配**。这只是本地接收完整市场并启用内存 ready 的证据，**不是 Order durable committed HEAD 签名证明**。
- 本地 MD Java8 `MdImageRecoveryFailoverControllerTest`、`MdAutomaticFailoverServiceTest`、`MdZkDisconnectPublicationFenceTest`、`MdOrderSnapshotCheckpointContractTest`：**27/27 PASS**。独占租约和 CAS 两阶段控制器源代码已存在，但缺可独立认证的 `MdImageRecoveryFailoverController.Safety` 生产 Bean。**没有执行 MD SIGKILL、没有启用自动主切**。

### 任务 2：Snapshot 与 WAL 生命周期（安全 canary）

- 当前在线 `OrderSvrA/B/C` 和 `TradeSvrA/B` 实际配置 `*.snapshot.periodic.enabled=true`，**pollMillis=60000**；Order 每轮最多处理一个分区。实际 `ORDER_PERIODIC_SNAPSHOT_OK` 日志：Order A 2 条，Trade A `TRADE_SNAPSHOT_SAVED` 29 条、Trade B 6 条（窗口内；没有错误不代表永久无错误）。
- Order/Trade 源码下未发现直接接线 `JournalArchiveSealCoordinator`、`JournalArchiveRotationPolicy`、`JournalArchiveRetirementCoordinator` 的后台执行任务。观察到的 `.archive` 主要在 Snapshot Journal rebase/rollback 时由旧队列迁移生成；这**不是独立周期 WAL 归档机制已运行**的证明。
- 在线只读 `audit_saas_wal_archives_readonly.py`：总 **526 个 archive 目录**、活跃 WAL 实分配 `2,767,011,840 bytes`、归档实分配 `491,261,952 bytes`、超过 48h 的目录 **0**、`deletionAuthorized=0`、未知目录 0。
- 真实 disposable canary 再执行一次：**1 个安全 fixture WAL 真正 unlink、1 个不安全归档保留、8 类边界拒绝、备份恢复摘要吻合；没有碰在线 WAL**；Python `test_archive_retention_gc_canary.py` **6/6**、`test_audit_saas_wal_archives_readonly.py` **3/3** PASS。由于生产缺独立 Seal ledger/备份与 Reader/消费者 durable watermarks，**live physical GC 继续关闭**。

### 任务 3：Order / Trade HA（真实故障）

- Trade 的 P012 持模拟仓位 Primary SIGKILL Epoch5 与被杀节点恢复，以及 P222 A→B→A / Epoch3 双端 Snapshot 一致，证据详见链接的上轮报告。本轮**没有重复 SIGKILL Trade**，不重复开仓或访问私人恢复凭据。
- 本轮新的受控 Order 验收：先核对 `EPO2RU` BTCUSDT 路由为 **P156**，原 `OrderSvrA Primary, OrderSvrB+OrderSvrC Replica`，三份 Snapshot `Epoch1 seq30500` SHA256 相等。然后执行现有 fail-closed 脚本 `tests/run-mac-demo-order-sigkill.py` **真实 SIGKILL Order A**。
- 实际 `OrderSvrB` 自动接管 P156 `Epoch 1→2`、新 Primary READY 且盘口恢复；被杀 Order A 自动重启、`unless-stopped` 策略恢复，脚本 `PASS_AUTO_TAKEOVER_AND_MARKET_READS`。**故障证据（Mac 私有目录）**：
  `~/.opentradingcore/epochwarm-walbatch-cold-cutover-20261013/evidence/order-p156-sigkill-20261013T021153Z.json`。
- 恢复过程最初出现 Order A **74 Learner**，随后全部自动追平恢复为 Replica。再查 **256/256 READY、0 Learner、256 组 Snapshot 相等**，全部 Primary 转至 Order B，Order A/C 均有 256 个副本；11/11 Robot 40 活动委托/双边盘口继续 PASS，Order 容器无 OOM。
- 纠正故障工具写死 `P238` 的误导性错误及日志提示，改为显示真实选择的 `PARTITION`，部署仓库提交 [`1838b98`](https://github.com/bliplink/dc-quant-deploy/commit/1838b9819f61dbc280615be2a426b2e4c9eecbcb)；**仅修日志，没有修改故障注入/恢复机制**。
- Java8 Order 周期快照、自动故障接管、跨 Epoch rebase、安全晋升专项测试 **27/27 PASS**。
- **Projection 一致性验收的限制**：短查询窗口曾触发 MySQL `MAX_EXECUTION_TIME`；随后有界孤儿审计 **约 448,000 Mutation、孤儿 0、92s**，但是**未扫描完整上界**，状态 `PARTIAL_NOT_ATTESTED`；`check-projection-consistency-host.sh` 正确返回非零，**不能报告全量跨 WAL/Projection 事务一致性 PASS**。应采用低 IO 的只读主键范围审计/离线快照审计，避免在线反复扫数十万行。

### 下一轮阻塞与安全规定

1. **MD**：实现真实 Order persisted full-market Image 签名 Source HEAD + source epoch、精确市场 Inventory/Delta 连续性证明、旧 publish 源隔离 proof 及控制器 READY 原子发布，先 1 分区隔离测试再实机灰度；仅有 11 租户 `MD_MARKET_READY` 不够。
2. **WAL**：为 Order/Trade 实现生产 adapter，采集 durable Seal + Replica ACK + 全消费组 Projection + 备份恢复 + Reader generation，先完成有界后台自动 Seal，再授权每段回收；没证明不删活 WAL/Archive。
3. **HA**：现在不再对 Order A/B/C 连续 SIGKILL，先建立 committed WAL HEAD/ACK、账户资金/成交完整逐笔权威审计与 Projection 低开销全部覆盖；以后带持续业务写入的故障验收须有显式准入。
4. 继续**暂缓 Common 3.0.18 Central 和正式 GHCR 双架构发布链**，目前 Demo 维持已锁定本地镜像。

## 2026-10-13 第二轮继续执行记录（MD/归档/权威对账）

**不得把本轮的辅助审计当作用户要求的 3 个功能已全部完成。**

### MD 完整 Order 市场清单三节点交叉验证（已开发、实机 PASS；promotion 仍 BLOCKED）

- 新增 `tests/check_order_md_market_snapshot_readonly.py` 及
  `tests/test_check_order_md_market_snapshot_readonly.py`（源码
  `810e15e` / `91c1447`，负例测试提交 `cc554f4` / `63fb8ef`）。
- 严格校验 11 租户的 `location␟4␟BTCUSDT` Order 路由，
  在 A/B/C 的 `snapshot/Pxxx/snapshot.json` 中寻找**完整且无重复/越分区的市场清单**，
  检查 committed Epoch/marker、marketUpdateId 和三份完整文件 SHA256，
  不需要交易员账号或更新在线分区。
- 实机命令：
  `python3 tests/check_order_md_market_snapshot_readonly.py --data-root ~/.opentradingcore/dc-saas-runtime-epochwarm20261013/data --tenant-audit ~/.opentradingcore/local-ha-clean-20261012-v1/tenants-after-walbatch-sigkill-20261013.json --output ~/.opentradingcore/epochwarm-walbatch-cold-cutover-20261013/evidence/order-md-snapshot-crosscheck-strict-20261013.json`
- 结果：`checkedTenants=11`、`verifiedTriplicateSnapshots=11`、`snapshotIssues=[]`，Python 负例 **7/7 PASS**。
- 显式 `promotionAuthorized=false`、`decision=BLOCKED`、
  `orderDurableSignedHeadAndAckProof=NOT_CHECKED`、
  `mdOldPublisherFenceProof=NOT_CHECKED`、
  `mdFullMarketImageAndDeltaProof=NOT_CHECKED`。
  **这是盘上三副本 Snapshot 内容一致性，不是新鲜认证 HEAD/持续增量/旧主发布隔离。**
- 源码还有 `OrderMdCheckpointHeadGate`、`OrderMdMarketManifest`、
  `MdDepthReplayWitness`、`MdImageRecoveryFailoverController`，
  但没有把独立可信的 `Safety` Bean 接入线上两阶段晋升。
  因此 **MD 自动主切未开放，不执行 MD SIGKILL**。

### WAL 生命周期（安全上限仍阻塞自动删除）

- 已确认 `JournalArchiveSealCoordinator` 明确要求业务 Adapter 在独占
  Writer/Recovery Barrier 内检查 **durable committed HEAD、所有必需 Replica ACK、
  当前物理 Primary 租约、Reader generation、完整 Snapshot 和重新打开的 Archive**。
  而 `DurableJournalArchiveSealLedger` 明确对未完成的 PREPARED/WRITER_SWITCHED
  要求重启后外部对账，不可将它当成可直接安全删除证明。
- 现有 Order/Trade rebase 产出旧 CQ Archive，不具备上述独立周期可恢复封段
  + 全消费组 Projection/外部备份证明，**不能为了完成任务而直接启用真实 WAL 删除**。
- 本轮仅复核 Common API 及既有 GC canary 验收；未修改现网归档目录、Reader、ZooKeeper 或 WAL。

### Order/Trade 权威数据对账（仅部分证明；全量仍缺）

- 上轮真实 Order P156 SIGKILL 与 Trade P012 带仓位 SIGKILL、
  Epoch 接管、归队与 11 租户业务已通过；本轮未重做危险故障注入。
- Projection 既有审计曾在带时间上限的 92 秒内扫描约 448k
  Mutation，返回 0 孤儿，但**`PARTIAL_NOT_ATTESTED`**。
  尚无 WAL committed HEAD/所有 Replica durable ACK 的跨业务分区权威对账证明。
- 定向 MySQL schema 调查确认 scoped 订单、成交可按 `location,user_id,create_time`
  索引有界读取，`orders` PK=(order_id,user_id)，`execorders`
  PK=(exec_id,user_id)，持仓 PK=(location,user_id,security_id)；
  其中 EPO2RU 定向只读检查订单=2、成交=2、持仓记录=3，
  成交对订单引用或位置不匹配=0、负持仓=0。
  **这些只是局部抽样，不是全部 11 租户在同一提交时点的资金总账审计。**
- 更深的数据库查询请求被执行环境安全检查拦截；
  没有绕过限制访问凭据、没有直接修改 SQL 数据、没有伪造完整对账 PASS。

### 本轮结论和下个工程门禁

任务①需要实现可独立认证的 Order 完整 Image + committed HEAD、
真实多市场连续 Delta 和 MD 共享发布隔离，以 `Safety`
集成测试和线上 SIGKILL 为最终条件；尚未完成。

任务②需要真正可靠的 Writer/Reader/Replica/Projection/Backup
Adapter 与可崩溃恢复持久 Seal 流程；**现网自动删除未完成且维持禁止**。

任务③继续实行已跑通的 Order/Trade 故障接管，但还缺有界完整
按主键/事务快照的订单、成交、资金、持仓和 WAL ACK 联合证明；
**最终权威对账未完成**。

用户暂缓 Common 3.0.18/GHCR 正式发布的要求维持不变。

## 2026-10-13 第三轮：Order MD 源端提交门禁与 WAL 崩溃恢复启动隔离

本轮实际代码和测试（**并非三大项已完成的声明**）：

- Order 项目 [PR #7](https://github.com/bliplink/com.app.dc.ordersvr/pull/7)
  已合并至 `saas-crypto`，merge SHA
  `1c818972bda18033f1ded139abd2f00c98e4fe25`。
- 新增 `OrderMdCommittedPrefixBoundary`：
  从**相同分区**的完整 Snapshot 基线、累计 `STATE_COMMIT`
  水位、当前 writer Epoch 和 WAL HEAD 生成 Common `RecoverySourceAttestation.SourceHead`
  所需的内部源事实。
  严格拒绝未提交 STATE 尾部、Snapshot 越过 committed HEAD、
  错配 Epoch、回退提交水位、缺市场 Image、虚假 SHA 等。
  **它不是 HMAC 签名，不包含独立验证的 Replica durable ACK，
  也不授予 MD 晋升许可**；
  后续需以 Order source authority + challenge/physical-node HMAC
  及 MD verifier 串接生产路径。
- 新增 `OrderWalArchiveStartupFence`，并在
  `OrderPartitionRuntime.init()` 打开 Chronicle Journal 前接入
  可选配置：`order.cluster.wal.archive.startupFence.enabled=false`
  （默认关闭）、`order.cluster.wal.archive.sealLedgerDir`。
  显式打开时要求可信已存在目录，对全部分区读取
  Common `DurableJournalArchiveSealLedger`，
  `PREPARED`、`WRITER_SWITCHED` 的未完成归档会**拒绝启动**；
  仅 `ARCHIVE_SEALED` 通过，目录丢失/符号链接均拒绝。
  只在启动时执行，没有委托匹配/复制热路径和在线 WAL 文件改写。
  **不等于已实现物理归档/删除，不允许独立打开此开关替代 GC 证明。**
- 本地 Java 8 专项：Order MD Manifest/HEAD **22/22 PASS**，
  Order Prefix+Archive 重启安全 **7/7 PASS**。
  生产适配代码进入独立分支后，全量 Order Java 8
  **330 项测试、0 failures、0 errors、1 skipped**，
  `mvn -o test -q` exit code 0；唯一 skip 为仓库既有的测试跳过。
  现网 Order A/B/C 仍运行原先的本地镜像，
  **没有将这个新源码私自替换现网**。
- MD 基线额外已在 `dc-quant-deploy/saas-crypto` 提交完整市场
  三节点 Snapshot 交叉审计和 7 项反例测试：
  `checkedTenants=11`、`verifiedTriplicateSnapshots=11`、
  `snapshotIssues=[]`；这个检查仍
  `promotionAuthorized=false`，`decision=BLOCKED`。
- 下一阶段仍缺：
  **(1) Order 经物理 Primary 身份和精确 ZK version 的当前已提交 HEAD 签名，
  全市场 Image + 连续 Delta 的真实 MD 验证以及旧发布者隔离**；
  **(2) Order/Trade Writer-Reader-Projection-Replica-Backup 独立有效证明，
  可恢复封段和真实定时 Archive/GC Adapter**；
  **(3) 稳定时点的 11 租户订单/成交/资金/持仓 + Projection
  + WAL durable ACK 权威一致性。**
  在这三类门禁都满足前不得把对应任务标记成 PASS。

### 本轮最后一次现网只读核验

- Order A/B/C、MD A/B/C、Trade A/B、Robot 运行均 `Running=true`，
  `OOMKilled=false`；没有为验证新代码重启服务。
- Order `P156` 三端 Snapshot Epoch2、Seq44902，SHA256 完全一致；
  Trade `P012` 双端 Snapshot Epoch5、Seq43434，SHA256 完全一致。
  上述为**持久快照内容等价**，不可替代权威最新 WAL HEAD/ACK 对账。
- 11 租户严格 Order 完整 Snapshot 审计仍通过
  `checkedTenants=11 verifiedTriplicateSnapshots=11 snapshotIssues=[]`，
  MD promotion 依然 `BLOCKED`。
- 最新只读 WAL 审计 `tests/audit_saas_wal_archives_readonly.py`：
  **782** 个历史 archive 目录，活跃 WAL 实分配
  **3,570,253,824 bytes**，archive 实分配
  **1,095,634,944 bytes**，48h 到期 0、授权删除 0、
  未知目录 0。与先前 526 个目录的盘点相比数量增加，
  但包含故障后的 Snapshot/rebase 归档；**不代表生产
  自动 Seal/GC 已运行**，需观察增长趋势与磁盘空间。
