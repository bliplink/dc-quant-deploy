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
