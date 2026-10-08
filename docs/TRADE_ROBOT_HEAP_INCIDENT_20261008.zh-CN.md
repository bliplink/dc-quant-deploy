# Trade HA / Robot 停报 incident — 2026-10-08（进行中）

> 环境：Mac mini / Colima Demo，全部为模拟资金。本文是可追溯的故障证据和发布门禁，不代表问题已经解决。禁止在未完成一致性核验前清空 Trade/Order journal、重置数据库或同时重启 Trade A/B。

## 现象与证据

- 原计划：50 个自动审批租户，每个 Maker Robot 20 买 + 20 卖，总计 40 单。新增 Binance aggTrade 驱动的 Tape IOC 尚未灰度；运行中 AdminSvr `TRIAL_LIQUIDITY_TAPE_ENABLED=false`。
- 13:38 报告 14 RUNNING / 36 ERROR。13:42 只读 MySQL 检查 0 RUNNING / 44 ERROR / 6 DEGRADED。13:58 短暂恢复为 15 RUNNING / 11 ERROR / 24 DEGRADED；14:07 为 4 RUNNING / 33 ERROR / 13 DEGRADED；14:11 为 9 RUNNING / 41 ERROR。50/50 从未再次证实。
- `dc_tenant_robot.last_error_code=RUNTIME_FAILURE`；绝大部分 `last_error_message=gateway rejected queryTradePosition: INTERNAL_ERROR`，部分直接为 `PARTITION_NOT_READY service=TradeSvrA/B partition=Pnnn` 或 `gateway TCP response is empty`。
- Trade A/B 日志均出现 `Terminating due to java.lang.OutOfMemoryError: Java heap space`。Docker 容器 `State.OOMKilled=false`；这里是 **JVM heap OOM**，不是 Docker cgroup OOMKill。
- 原环境运行参数：Trade A/B Docker 各 2 CPU、2048 MiB；JAVA_OPTS `-Xms64m -Xmx768m -Xmn192m`。部署 Compose 默认 `-Xmx1536m`，但私有环境明确覆盖成 768 MiB。Linux Docker VM 总内存约 16 GiB，诊断时 `MemAvailable≈2.4 GiB`，增加堆需先做整体预算。
- 14:11 Trade A 累计重启 7 次、Trade B 3 次（相对先前 4/1 增加）；RobotSvr 本身运行且零重启，不能把问题直接归因于 Robot 容器宕机。
- TradeA/TradeB 数据目录只读 `du` 各约 6.7 GB / 6.6 GB；恢复期间大量逐分区 `TRADE_PARTITION_READY`、`TRADE_PARTITION_UNCOMMITTED_TAIL_ARCHIVED`、`PARTITION_NOT_READY`。禁止以数据目录大为由删除日志或快照。

故障链当前证据：JVM heap OOM → Trade 退出/重启 → 分区恢复时交易查询被 readiness fence 拒绝 → Robot 持仓查询失败 → 连续 RUNTIME_FAILURE/ERROR → Robot 撤单、盘口停报。导致 heap OOM 的确切对象占用构成尚需实测验证。

## 代码修复（已入 Git，但线上未发布）

1. [Trade commit 6441b0de](https://github.com/bliplink/com.app.dc.tradesvr/commit/6441b0de9e7d2137c463b013f4aaaaa253d6bb33)：`ExecutionDeduplicator.clearLocation` 改为直接迭代键视图、避免为每个恢复租户复制整张键表；同时清理该租户旧 insertion queue 记录，以免反复恢复造成队列累积。18 项相关测试 PASS；对应 [Actions](https://github.com/bliplink/com.app.dc.tradesvr/actions/runs/37735848479) 成功。
2. [Trade commit e5cebdd2](https://github.com/bliplink/com.app.dc.tradesvr/commit/e5cebdd2aa191e98a3128886634cd3b5eca6d3e6)：脏尾恢复 `captureRecoveryCheckpoint` 使用现有 `saveStreamingDedupe`，避免构造完整去重 Snapshot 副本；新增跨租户/终态订单回读测试，包含 20 项相关测试全部 PASS。对应 [Actions](https://github.com/bliplink/com.app.dc.tradesvr/actions/runs/37736264706) 在记录时仍构建中。
3. 两项修改均不降低 `trade.executionDedupe.maxEntries=1000000`，不更改交易幂等判定、不抹除账务或分区持久化状态。修复对象开销可下降，但不能据此推断生产环境已经恢复。

## 放行顺序与硬性门禁

1. **冻结新租户与 Tape**：保持 `TRIAL_LIQUIDITY_TAPE_ENABLED=false`，不触发 `tests/run-trial-tape-canary-host.sh`，不扩容到 200 租户。
2. **镜像门禁**：检查 `e5cebdd2` 的 Actions 成功、镜像确已推送 GHCR，核对 arm64/amd64 manifest、不可变 digest 与源码提交；禁止使用本机临时镜像替代。
3. **资源预算**：Trade A/B 旧堆 768 MiB 反复 OOM，拟试验在 2048 MiB 容器上将 `-Xmx` 提高至适度值（例如 1152 MiB），但必须同时核算 Docker VM 可用内存、其他 Order/ClickHouse 服务的 RSS、直接内存与 off-heap；不能单纯把堆调到 Docker 上限。先留存现行私有环境配置和容器镜像信息。
4. **受控滚动发布**：先做 ZooKeeper assignment 与分区角色快照，检查 A/B 不存在双主，记录 Order/Trade/Projection watermark；再选一个节点发布并等待分区恢复、复制追平与业务门禁通过；最后处理另一节点。禁止一条 `docker compose up -d` 同时重建 A/B。
5. **一致性**：对账 MySQL `orders/executions/balances/positions/open orders`、Trade 热状态、Projection watermark、Replica committed seq；未证明无双主、无丢单/重复成交前不宣称 HA 通过。
6. **Robot 恢复**：所有 enabled Robot 必须最近心跳为 RUNNING、错误码为空，且每租户真实活动委托为 20/20、公开盘口为 10/10；持续观测 p95/p99、CPU、内存、GC/OOM 和 Trade/GW 失败。单一时刻 50/50 不算长稳。
7. **Tape 门禁**：只有 50/50 Robot 长稳和账务一致后才执行 1 个 canary，核对真实 MySQL 执行与资金流水，然后按 1→5→10→50 的主动成交负载增量验证；200 租户压力测试需在此后单独排期。

## 只读诊断查询

```sql
SELECT runtime_status, COALESCE(last_error_code,'NONE') AS error_code,
  COUNT(*) AS robots, SUM(open_order_count) AS reported_open_orders,
  MIN(last_heartbeat_time) AS oldest_hb, MAX(last_heartbeat_time) AS latest_hb
FROM dc_tenant_robot WHERE enabled=1
GROUP BY runtime_status,last_error_code ORDER BY robots DESC;

SELECT LEFT(last_error_message,180) error_excerpt, COUNT(*) AS robots
FROM dc_tenant_robot WHERE enabled=1 AND runtime_status<>'RUNNING'
GROUP BY LEFT(last_error_message,180) ORDER BY robots DESC;
```

```bash
docker inspect --format '{{.Name}} running={{.State.Running}} restarts={{.RestartCount}} oom={{.State.OOMKilled}} image={{.Config.Image}}' dc-saas-tradesvr dc-saas-tradesvr-b dc-saas-robotsvr
docker logs --since 10m dc-saas-tradesvr 2>&1 | grep -aE 'OutOfMemoryError|TRADE_PARTITION_READY|PARTITION_NOT_READY' | tail -40
docker stats --no-stream dc-saas-tradesvr dc-saas-tradesvr-b dc-saas-robotsvr
```

避免将 DB 凭据、API Key、SessionID、用户个人数据、完整未清洗网关请求输出到公开仓库/Issue。

## 2026-10-08 15:18 滚动发布记录（持续观察中）

- GitHub Actions [37736264706](https://github.com/bliplink/com.app.dc.tradesvr/actions/runs/37736264706) 成功构建 TradeSvr `e5cebdd2`，GHCR 支持 `linux/arm64`、`linux/amd64`。
- Colima 直接 `docker pull` 因镜像层下载超时，改用 Mac 现有本机 HTTP 代理（端口 10808）运行 `crane pull --platform linux/arm64`，再用 `docker load` 导入官方镜像（约 211 MB，ARM64 镜像 ID `sha256:bf306c0fef77...`）。未使用本地自行构建镜像。
- 部署前核对 ZooKeeper 共 256 分区，主节点 A 146 / B 110，没有主副本重叠。先只重建 B，并将 B JVM `-Xmx768m -Xmn192m` 提升至 `-Xmx1152m -Xmn288m`，Docker 内存上限仍为 2 GiB。逐个 epoch 比对结果：当时 B 所属 110 个主分区全部有对应 `TRADE_PARTITION_READY`，0 新 OOM、0 重启。
- B 恢复完毕后再只重建 A。15:18 两个容器均确认为 GHCR `sha-e5cebdd2aa191e98a3128886634cd3b5eca6d3e6`，JVM `-Xmx1152m`，本轮重启计数均为 0。原 `c19d8d76` 镜像仍保留用于回滚。
- 15:21 A 仍在逐分区恢复，已记录至少 95 条 `TRADE_PARTITION_READY`；Robot 暂时为 33 RUNNING、17 ERROR，**未完成 50/50 稳定验收**。以上是时间点快照，不能以局部 READY 数推导整个 Trade HA 已恢复。
- 环境配置文件已在 Mac 主机单独备份；禁止把包含实际密码、API Key 等的私有 .env 上传 GitHub。Tape 开关仍为 false。没有清空 MySQL、Journal、snapshot 或更改租户 enabled 状态；200 租户压测尚未开始。
- 后续必须再次按 ZooKeeper 256 分区的实际 `(partitionId, epoch, primary)` 与 A/B READY 日志逐一对照，再验证 50/50 Robot、真实委托盘口、Trade/Order/Projection 对账，以及持续无 JVM OOM/重启；在完成这些步骤前**不要启动 Tape**。

## 2026-10-08 15:32 复制 ACK 阻断与全量盘口验证

- 15:28:06，Robot 曾短暂达到 `50 RUNNING / 0 ERROR / reported open orders 2000`。ZooKeeper 256 分区当前 assignment 与 A/B 启动以来的 `(partitionId,epoch)` READY 日志全部匹配（A 146/146，B 110/110）。但历史 READY 证据不能证明之后从未 revoke。
- 对 3 个 RUNNING 租户的真实 `MDSvr.queryPublicMarket` 只读抽查均为 10 bid + 10 ask。扩大到 50 租户时，首轮仅 36/50 达到 10+10；随后的关联验证显示 Robot 同时跌为 37 RUNNING / 13 ERROR，12 个缺档租户全部是 ERROR 且 reported open orders 为 0。因此**没有证据支持把缺档简单归因于 MDSvr 丢数据**，真正上游仍有 Trade 分区失效。
- 15:23:51 B→A 的 `P030` 复制出现 `TimeoutException: replication ack timeout requestId=7165`，随后写入和 `queryTradePosition` 被 `PARTITION_NOT_READY` 阻断。复制超时会撤销分区就绪状态，Robot 因持仓查询失败进入 `RUNTIME_FAILURE`；对应安全熔断正常但系统可用性下降。
- 约 15:31 的连续 3 分钟中，A/B 日志分别出现约 24/12 条 `replication ack timeout`、12/6 条 `trade replication failed endpoint`，以及 1835/693 条分区未就绪拒绝；同期 **0 新 OOM**，两个 Trade 容器本轮重启数持续为 0。复制 handler `TRADE_REPLICA_HANDLER_SLOW` 单次执行耗时最高约 224ms（A）/447ms（B），没有观察到单条 handler 执行超过 3 秒。待调查网络事件循环排队、Chronicle 日志同步写入、复制 ACK 等待和默认 `TRADE_CLUSTER_REPLICATION_REQUEST_TIMEOUT_MS=3000` 是否过紧。**不能仅靠上调超时就认定根因已经解决。**
- 15:32 的 Robot 状态仍为 42 RUNNING / 8 ERROR；最近一分钟 ACK 超时计数为 0，但仍持续有 `PARTITION_NOT_READY`；继续观察分区自恢复能力。**本次上线验证仍为 FAIL/PENDING，不开放 Tape，也不开始 200 租户测试。**
- 后续修复必须保证异步事件处理不会破坏按分区 journal 严格顺序、epoch fencing、持久化 ACK 以及幂等回放。在没有完整复制一致性与回归证据前禁止通过放宽就绪门禁伪造 50/50。

## 2026-10-08 16:14 Projection 持久化水位异常（P0，未修复）

- 50 个已启用 Robot 此时均 RUNNING，reported open orders=2000；但订单与历史投影一致性**不可据此视为通过**。
- 执行只读 `tests/check-projection-consistency-host.sh`，检查失败：`Found 1 orphan trade projection mutations`。定位为 Trade P232, epoch=1, journal_seq=7111, mutation_index=3，entity_type=`DEDUPE_RESULT`；缺少对应 `dc_trade_projection_event`。**不允许删除孤立 mutation 来让校验变绿。**
- P232 的 `dc_trade_projection_watermark` 为 epoch1/seq7025（最后更新时间 2026-10-08 09:18:55），但 Trade A `TRADE_PARTITION_READY` 后 committedStateSeq 已超过 56000。重启 ProjectionSvr 后明确报告 `PROJECTION_REBASE_REQUIRED partition:P232, watermark:1:7025, baselineSeq:56460, committedHigh:63373`。大量其他 Trade 分区存在同类 `PROJECTION_REBASE_REQUIRED`：**旧 watermark 已早于可直接 FETCH 的 journal 基线，不能只靠重启追平**。需要查归档链或完整、安全的快照/事件重建方案；不允许直接跳过序号。
- 2026-10-08 16:07：Trade Projection watermark 共 123 条，最新更新时间仅至 13:37:03，123/123 超过 2 小时；Order Projection watermark 共 125 条，多数也较旧（旧更新时间不必然代表错误，但结合下面 GAP 异常属高风险）。
- Order Projection P054 发生 `projection event exists ahead of watermark`，水位 epoch85/seq109061（12:48:09），已存事件 epoch85/seq109062，且 `Projection GAP retry` 持续出现。**禁止直接手动 UPDATE watermark**；应核对事件/关联物化变更的事务原子性和安全重放。
- ProjectionSvr 旧环境容器 512 MiB、`-Xmx192m`、CPU 0.2；历史日志明确有 Java heap OOM，队列反复 critical。16:10 单独把查询侧服务重建到容器 768 MiB、堆 320 MiB、CPU 1.0，并留存私有环境文件备份，Trade/Order/Robot 未重建。16:14 观察重启次数 0、内存约 497 MiB、没有新 OOM 或队列 critical，但仍有大量 REBASE_REQUIRED 和 GAP；仅资源瓶颈缓解。
- 部署 repo 的 `compose.yaml` 默认 ProjectionSvr 资源已同步到 768 MiB / CPU 1.0 / Xmx320m。不会改写 Trade/Order/MySQL 权威数据或已存在的 journal/snapshot。
- 基础账务表只读检查：订单 940、成交 582、持仓 560、余额 645；未发现负的订单 leaves/cum qty、成交数量/价格、余额、冻结/占用保证金。**另发现 1 条 BTCUSDT Cross 多头数量为 -0.0002**，需依据相关撮合/成交与 Trade 权威状态判定是否合法，不应臆断资金损失或直接改库。
- 解除 P0 的验收条件：定位归档/重建路径，P232 孤立变更归属得到解释且事件/变更一致，P054 watermark/事件物化严格原子，全部必要 Trade/Order watermark 与源头 committed seq、快照和历史订单/成交/资金/持仓一致；Trade 复制 ACK 与 50/50 Robot 继续长稳。未通过这些验收前，保持 `TRIAL_LIQUIDITY_TAPE_ENABLED=false`、禁止 200 租户负载测试与故障注入。

## 2026-10-08 16:17 归档恢复源码调查（待开发，不允许直接在线改水位）

- `bliplink/com.app.dc.tradesvr@saas-crypto` 的 `TradePartitionJournal` 已保留 Chronicle Queue `.archive` 历史分段，并提供 `replayConcurrentReadOnly` / `readTailRangeConcurrentReadOnly` 等归档只读读取能力。Mac Demo `TradeSvrA/journal/.archive` 中 P232 有多段旧归档，最早目录含原始未 rebase 队列，活动 baseline 为 56460（committedStateSeq=56459）。**潜在有源数据可用于补齐历史**，但尚未验证从 seq7025 起所有已提交事件是否完整连续。
- 当前 `TradeProjectionCommittedReader.read()` 在 `request.watermarkSeq < baseline.committedStateSeq` 时立即返回 `BASELINE_MOVED`；其 `readProjectionBatch` 对远距追赶采用的 `journal.readBatch` 仅遍历活动队列，不读归档。这解释了为什么仅扩大 Projection 堆和 CPU 不能消除 `PROJECTION_REBASE_REQUIRED`。
- **不能直接去掉 BASELINE_MOVED 检查**：归档段可能保留故障切换前未提交的 `STATE_BATCH` 尾部，单凭 seq <= 当前 committedHigh 无法保证该归档事件已提交。若误放行，会将旧主未提交状态作为真实交易流水。
- 修复应在独立代码分支设计“有界只读归档扫描 + STATE_BATCH/STATE_COMMIT 配对认证 + 断档 fail-closed + 跨 epoch/rollback 基线约束 + 响应字节数限制 + 测试原子一致性”，覆盖断档、脏尾、重复状态、回滚、巨大 journal、重新选主；**归档缺段一律拒绝，不自动跳水位**。
- P232 mutation seq7111 需要从归档中证明对应事件已提交、可安全重建；而 P054 的 Order Projection 109062 event/109061 watermark 必须证明事务与物化效果，不可单纯 `UPDATE watermark`。相关恢复应经隔离环境回归和正式 GHCR 镜像发布。
- 另已提交 `tests/run-trial-tape-canary-host.sh` 的只读 Projection 一致性硬门禁：`check-projection-consistency-host.sh` 不通过时，在任何 Tape canary 状态写入之前退出。当前灰度仍关闭。

## 2026-10-08 16:35–16:41 Trade ACK 请求超时覆盖值修复（滚动发布观察中）

- 发现线上 **A/B 两台** `/srv/dc/dc/TradeSvr/config/application.properties` 均设 `trade.cluster.replication.requestTimeoutMs=1000`；宿主机私有 `.env` 的 `TRADE_CLUSTER_REPLICATION_REQUEST_TIMEOUT_MS=1000` 覆盖了 `TradeReplicationManager` 源码默认 **3000ms**，也违反 `tests/test-trade-cluster-config.sh` 现有 3000ms 验收预期。
- 1 秒 deadline 在 Robot 持续更新与复制压力下导致 `TimeoutException: replication ack timeout`，最终分区 `PARTITION_NOT_READY`，连锁造成 Robot 错误/空盘口。**根因不仅可能是 deadline 过小**，还可能包含复制服务处理排队、日志同步/锁争用；必须继续测量长尾和真正的 ACK 链路。
- 已备份私有 env 和 A/B 生成配置，将 1000ms 恢复为 3000ms。保留原有 required durable ACK / epoch fencing / fail-closed；不涉及改动 Order 或交易数据。原本 3000ms 的部署配置测试通过。
- 滚动发布流程：16:35:04 只重建 B，随后使用 ZooKeeper 256 个分区 assignment 交叉验证当前 B 主分区 **110/110 分区 READY（同 epoch）**，拓扑无主副本重叠，0 新 OOM/重启；16:37:23 只重建 A，证实新配置值是 3000ms，B 未重启。截至 16:40:57 A 还在有序恢复重日志分区（20 条 READY），0 OOM/重启。**这时 Robot 暂时仅 14 RUNNING/36 ERROR，不能当成上线成功**；不得启动 Tape/增租户/故障注入，待 256 分区与 50/50 双边盘口恢复并稳定。
- 部署仓库 `generate-saas-configs.sh` 新增 Trade 集群超时上下限保护（3000–30000ms），`tests/test-trade-cluster-config.sh` 新增 1000ms 私有环境覆盖值的拒绝回归；避免下一次重部署退回 1 秒。提交 `78a1fff`、`d1cd57a`，须持续查看 Actions 结果。
- 不得为加速重启跳过原始 journal 检查点、删除 dirty tail/归档或手动将分区改为 READY。等 A 恢复完再收集超时前后定量指标；如仍有 ACK 超时，继续定位 DirectNetty 请求排队、接收侧 fsync、事件循环延迟，不要直接关掉持久化复制门禁。

## 2026-10-08 16:44 A 滚动恢复耗时与下一阶段门禁

- 将线上 ACK timeout 从 1000ms 调整到 3000ms 后，B 于 16:35 重建并通过 ZooKeeper **110/110 同 epoch 主分区**恢复验收。A 于 16:37:23 重建，两节点均实测 `trade.cluster.replication.requestTimeoutMs=3000`。直到 16:43 的日志窗口，未观察到新 ACK timeout、JVM OOM 或容器重启；但这段窗口仍处于 A 恢复且低于满载，**不能据此宣布故障已根治**。
- A 载有较大历史 Trade journal，当前 `TradePartitionLifecycleManager` 以 `Executors.newSingleThreadScheduledExecutor` 串行处理 146 个主分区；多个 dirty-tail 分区需要 30–40 秒分别执行 committed replay、snapshot checkpoint 和 journal rebase。16:44 时约 44 READY/146，Robot 暂时为约 22 RUNNING/28 ERROR。禁止把因滚动更新造成的长时间不可用解释为正式可用性通过。
- 后续要在测试环境设计有明确内存预算与并发上限的恢复调度/快照加速，并严格测试不同分区之间隔离、提交标记、epoch fencing、未提交尾部与重复投影；不要在线跳过检查点或强行开放 readyness。
- 恢复验收门槛：完成 A 146/B 110 对应当前 ZK epoch 的 READY、50/50 Robot 双边 MDSvr 盘口、5–10 分钟甚至更长的 0 新 ACK timeout/0 OOM/0 容器重启，再做 Order/Trade/Projection 权威一致性。Projection P232 rebase 与 P054 watermark GAP **仍另行阻断 Tape/200 租户测试**。

## 2026-10-08 16:56 3s ACK 灰度恢复快照（进行中，未通过）

- B 已在 16:35 以 3000ms ACK timeout 重新上线并通过 110/110 ZK 同 epoch READY 核对；A 自 16:37:23 开始独立恢复，在 16:56:20 只记录 116/146 READY，尚缺 30 个主分区。这证明当前单线程生命周期对大量历史日志的恢复时间过长，也是上线可用性 P0，不能视为正式 HA 演练通过。
- 50 个启用 Robot 约 44 RUNNING / 6 ERROR，reported open orders=1760；零新 JVM OOM、零恢复失败与 A/B 零次容器重启。此时**不能保证全部盘口可交易**，不运行 Tape 或 200 租户测试。
- 调整后 A/B 过去数分钟没有观察到 `replication ack timeout`。B 在 A 的复制端口停止时有 6 次 `Connection refused`，属于节点重建期间的预期连接失败，不能与在线 ACK 超时混为一谈；更不能以部分恢复期无 ACK timeout 证明满载稳定。
- 后续必须再次实测 ZooKeeper 256 分区 readiness、50/50 Robot、50 租户公开盘口与连续窗口复制尾延迟；并另行关闭 P232 Trade Projection 重建、P054 Order watermark GAP 的一致性阻断。

## 2026-10-08 17:16 WebCodex 复核：Trade 全部 READY，Order HA 仍抖动

- 通过 Mac mini WebCodex 只读连接确认 TradeSvr A/B、ProjectionSvr、RobotSvr 容器均 running，滚动升级后 restarts=0、OOMKilled=false，未再重建/清库。
- ZooKeeper 逐一读取 256 个 Trade assignment：A primary=146，B primary=110；与两个进程日志里当前 `partitionId+epoch` READY 一一核对 **256/256 MATCHED_READY**，无重复主副本。最近五分钟 Trade A/B 没有 `replication ack timeout`、`trade replication failed endpoint` 或 `PARTITION_NOT_READY`。
- 50 个现有租户的 `MDSvr.queryPublicMarket` 全量只读检查：**50/50 成功返回至少 10 档 bid + 10 档 ask**，但此结果只代表查询采样点，不能替代实时下单压测。
- Robot 并非持续 50/50：17:11 瞬间 50 RUNNING/2000 报价，17:12 先后波动至 41 RUNNING、再 26 RUNNING/24 DEGRADED，17:15–17:16 又回到 50 RUNNING/2000；不可以宣称已经长稳。
- DEGRADED 最近日志主因转向 OrderSvr，而非 TradeSvr：`gateway rejected queryOpenOrder: INTERNAL_ERROR`、`gateway TCP response is empty for placeOrder`、`queryOpenOrder: PARTITION_NOT_READY service=OrderSvrA`。Order A/B/C 容器未重启。
- 17:12 左右 Order 自动故障切换控制器在 C 上记录 **27 次 `ORDER_AUTO_FAILOVER_APPLIED`**（OrderSvrB → OrderSvrA），随后执行 **27 次 `ORDER_AUTO_REPLICA_REPAIRED`**；A 和 C 记录大量 `ORDER_LEARNER_REPLICATION_RETRY learner:OrderSvrB`。Order A/B CPU 采样约 140%/133%，容器内存约 2.59/2.57 GiB（每台限制 3 GiB），JVM 堆均 2048m；暂未观察到 Order OOM。
- 过去约 8 分钟 Order A 的 `ORDER_STATE_BATCH_SLOW` 记录 1498 条、B 为 3290 条；这些**慢日志子样本**的 totalMs 最大分别 5183/5080ms，慢日志内 p95 分别约 692/666ms（不是全量订单 TPS/延迟统计，不得误报）。大量慢调用涉及 stateReplicaMs、commitReplicaMs、journal 写入与 callback 队列；需要独立确定 Order B 在 failover 窗口被判不健康是心跳/GC/持久化延迟/连接事件哪一种，**不能凭现象直接关闭故障切换或放宽 ACK quorum**。
- Trade 投影仍有 P232 epoch1 seq7025 孤立事件/基线缺口，Order 投影 P054 epoch85 seq109061 落后 109062 事件；投影一致性未关闭。Tape 保持 false，暂不启动 200 租户测试、kill primary 或其他故障注入。
- 后续工作优先级：验证 Order failover 的原始存活判定与时间线、进程 GC 与 event loop 和同步 journal 延迟；优化 Order 状态批量持久化/投影日志读取上的热点并加回归测试；全链路 50/50 长稳及历史订单/成交/余额/持仓一致性通过后再启动单租户 Tape。

### 17:18 Robot 波动复核与复制模式（只读）

- 四个 7 秒间隔的 Robot 快照：17:18:05 `50 RUNNING/2000`、17:18:12 `48 RUNNING/2 DEGRADED/1920`、17:18:19 仍 48、17:18:27 `44 RUNNING/6 DEGRADED/1760`。**不可引用 50/50 的瞬间恢复宣告“持续正常”。**
- 三台现网 OrderSvr 的 `order.cluster.replication.consistencyMode=SYNC_PER_RECORD` 且 `order.cluster.replication.requestTimeoutMs=10000`，`replication.required=true`；源码支持 `SYNC_BATCHED` 通过 `OrderReplicationBatcher` 与累计 ACK，允许保留同步持久化语义并减少单条往返，但在这台高负载机器上尚未执行隔离回归/benchmark，**不得直接线上切换**。
- 下一步先补齐失去 OrderSvrB live 证明的事件时间线（ZooKeeper 会话、线程/GC、commit fsync、网络事件循环）；在隔离环境测试 `SYNC_BATCHED` 对混合订单/成交/撤单、failover+恢复、丢单/重复成交/双主的影响，再决定是否灰度上线。长期目标还需要记录全量 p95/p99，不能以 WARN-only 的样本分位替代全流量指标。

## 2026-10-08 17:31 Order ZooKeeper 6s 假离线与 Docker VM 压力（P0）

### 已核对的触发证据

- 17:12:18.707 ZooKeeper 服务端日志：`Expiring session ... timeout of 6000ms exceeded`，同一会话属于 OrderSvrB：17:12:18.629 B 的 ZkClient `Disconnected`，17:12:20.308 `Expired`，17:12:20.406 B 取得新 ZooKeeper 会话。随后的 Order HA 控制器发生 **27 次** `ORDER_AUTO_FAILOVER_APPLIED`（原主为 B）及相应 learner 副本修复。OrderSvrB 容器本身没有重启。
- 17:27:55.116 ZooKeeper 又过期一条 6000ms 会话，这次对应 OrderSvrA；17:27:55.764 A 报 `Expired`，Order 控制器随后将 P240/P242/P244 三个分区从 A 切到 B。证明 B 不是孤例，**6s session budget 对此环境过紧**。
- A/B/C 在 17:12:14–17:12:17 的日志都发生 4–5s 同步静默；B 还有更长日志间隔。此现象与 VM 资源争用/GC/调度暂停相符，尚不可据此断言具体停顿来源。
- 17:31 Colima/Docker VM 有 **8 vCPU、约 15.6GiB 内存**，load average 1m/5m/15m 分别为 17.21/15.99/15.67；`/proc/pressure/cpu` `some avg10=73.85 avg60=68.80 avg300=63.62`，`/proc/meminfo` MemAvailable ~1,073,020 KiB、SwapFree ~260 KiB；Order A/B 各耗 ~2.59/2.57 GiB（限制 3 GiB），容器 CPU 分别 ~126%/126%，均未 OOM。此为高资源争用与极低 swap 余量证据；不能基于慢日志子样本声称全流量延迟/TPS。
- 同期 Robot 的状态会在 `50 RUNNING/2000` 与 `DEGRADED` 间波动，Trade 的 256/256 ZK 主分区 READY 且 Trade ACK timeout 最近日志未复现；Order 高负载/会话过期是当前关键 P0。

### 已实施的部署代码改动（未上线到运行中 JVM）

- `.env.example`、`compose.yaml` 的 Order A/B/C ZK session timeout 默认从 6000 改为 **15000 ms**，连接超时仍为 5000ms，Trade 默认 **6000ms 未改**。
- `deploy-saas.sh` 全 HA 配置不再把 Order 强行回写为 6000ms，而使用 15000ms。
- `generate-saas-configs.sh` 在 Order cluster 开启时强制校验 **15000–40000ms**，`tests/test-order-cluster-c-config.sh` 反向验证 6000ms 会拒绝。GitHub Actions **37756851858** 完成 success。修复测试时发现 `.env.example` 注释换行错误（之前的 CI 失败），已修复并复验通过。
- Mac mini 私有部署 `.env` **已做备份并预置 15000ms**，实际 `docker compose ... config --format json` 验证三个 Order 节点期望环境均为 15000ms，Trade A/B 仍为 6000ms；**线上 A/B/C 的当前进程环境仍是 6000ms**，不重建便不会生效。
- 未改存储、未清空 journal、未动复制 quorum 或订单 epoch，未重启任何 Order 服务，Tape 继续关闭；200 租户压测仍禁止。
- **上线门禁**：在隔离/低风险场景验证三节点滚动更新时每个分区的同步副本/learner、journal/水位和回退策略，避免因为 session 调整而人为触发一轮重的 Order HA failover/长期报价中断；持续监控迁移前后 ZooKeeper Expired、批量复制 p95/p99、Robot 50/50、实盘盘口与 Projection 一致性。15s 增加真实故障检测/切换时延，是可用性取舍而非永久性能修复。
- 下一阶段同时需要处理资源压力：8 vCPU VM 的持续 load>15、CPU PSI>60% 和 swap 几乎耗尽。如果考虑增加 Colima vCPU/内存，必须计划停机维护，不能在交易持续运行时随意重启整个 VM。

## 2026-10-08 18:25–18:31 Order HA 滚动发布门禁执行结果：**NO-GO**

本轮没有在线滚动重启，亦没有开启 Tape/扩容或变更任何订单、持仓、资金/journal。安全门禁明确禁止在当前 Docker VM 资源过载时执行节点重建。

- Order A/B/C 容器均 running，restartCount=0、OOMKilled=false；Trade A/B、Robot、Projection 与 ZooKeeper 也仍在运行。18:24 单点 Robot 为 50/50 RUNNING、记录活动订单 2000，**仅单点观测，不代表长稳**。
- ZooKeeper 逐分区读取 `/dc/cluster/ordersvr/partitions/P000..P255`，**256/256** assignment `state=READY`，主节点分布 A=97、B=141、C=18；副本参与节点分布 A=141、B=115、C=238，部分分区的 A 为 learner。**C 仍拥有 18 个主分区，不是可直接摘除的空闲节点**。Assignment READY 也不能单独作为 committed watermark 的一致性证明。
- Colima/Docker Linux VM 8 vCPU、约 15.6 GiB。18:24 观测 1m load=22.48、`cpu.pressure some avg10=78.60%`、MemAvailable=1,121,576KiB、SwapFree=28KiB；同期 Order A/B 负载约 103%/108% CPU，各用约 2.6 GiB/3 GiB。
- 新增只读 `tests/order_ha_rollout_gate.py --target OrderSvrC`（支持 `--snapshot` 脱机验证）。**先看 CPU PSI avg60<=30%、MemAvailable>=2GiB、SwapFree>=256MiB、三个 Order 容器健康、50/50 Robot/2000 挂单，再读取 256 分区拓扑**。当计划移除节点仍承载主分区或同步 replica 时，一律 `NO-GO`，要求先完成受控 drain/quorum 评估。门禁 PASS **仅表示静态预检通过，不是最终发布授权**，还需权威副本同步和持久化证据。
- `tests/test_order_ha_rollout_gate.py` 覆盖 9 个正/负向情景，Mac mini 本地只读测试全部通过；部署 CI `Validate cluster deployment configuration` 已把它列入强制测试，Actions [37763654762](https://github.com/bliplink/dc-quant-deploy/actions/runs/37763654762) 成功。
- 现场执行 `--target OrderSvrC` 返回 **exit 2, NO-GO**：CPU PSI avg60=79.07%>30%；MemAvailable=1,088,992KiB<2,097,152；SwapFree=400KiB<262,144。工具未在不安全环境继续执行 256 次 ZK 查询。
- 现网私有 env 已备份预置 `ORDERSVR_ZOOKEEPER_SESSION_TIMEOUT_MS=15000`，Compose desired A/B/C 均是 15000，但运行中的三个 Order JVM 仍为 6000。**因此“代码/环境配置就绪”不是“现网运行参数已生效”。**
- 下次发布前必须降低 CPU/内存压力（停交易后的维护窗口可以重新评估 Colima 资源方案），并形成主分区迁移、同步副本证明、回滚时 epoch/journal 的验证脚本。不要直接执行 `docker compose up --force-recreate ordersvr*`，也不要以禁用自动切主或异步 ACK 回避风险。

## 2026-10-08 20:06–20:13 Order journal 高频日志诊断（源码优化、尚未上线）

- 20:06 50/50 Robot RUNNING / 活动报价 2000；Order/Trade/Projection/ZK 容器正常运行、0次重启；VM CPU PSI avg60 72.66%、MemAvailable 1,015,092 KiB、SwapFree 732 KiB。19:57:19 OrderSvrB 6 秒 ZK session 过期，控制器随后 7 次自动切主。因此 Order HA/Projection/200租户压测均未通过。
- 19:56:30–19:58:00 Order A/B/C 日志中 `ORDER_STATE_BATCH_SLOW` 样本数分别为 159/260/85，`ORDER_REPLICA_CATCHUP_OK` 也以高频 INFO 输出。之后 2min 抽样 Order A/B/C 合计日志约 3.7 MB、近 24,879 行，其中 slow 1006 条、catchup success 692 条。
- 最近 3min 的**只含 >=100ms WARN 的子样本**：Order A 慢日志样本 N=483，total avg 273ms、p95 570ms、p99 944ms；Order B N=664，avg 280ms、p95 677ms、p99 1018ms；Order C N=326，avg 259ms、p95 763ms、p99 1067ms。STATE/COMMIT 同步 replica 两阶段及 journal 写入都占明显耗时，publish 接近0。以上绝不代表全部订单的真实 p95/p99 或 TPS。
- 源码 `bliplink/com.app.dc.ordersvr` `saas-crypto` 提交至 `370a8f33a`，新增 `OrderSlowBatchLogLimiter`：100–999ms routine WARN 每秒最多 1 次、累计 suppressed 记录数随下次 WARN 一起输出；所有 >=1000ms slow 仍逐条 WARN；`ORDER_REPLICA_CATCHUP_OK` INFO 降为 DEBUG，**失败日志和复制/commit/epoch/quorum 逻辑没有修改**。4 项 JUnit 新测试，JDK8 helper 单独编译与行为 smoke 通过。完整 OrderSvr GitHub Actions [37774932516](https://github.com/bliplink/com.app.dc.ordersvr/actions/runs/37774932516) 已 **success**：Maven 全量测试及 Docker amd64+arm64 编译推送通过；已发布不可变标签 `ghcr.io/bliplink/ordersvr:sha-370a8f3`、manifest digest `sha256:191c05175ca0c61720018abf1a5b199c08b4e60f1edf429fe19f9c25861d40d9`。**此处只是镜像产物验收，绝不代表现网已部署。**
- 新源码**尚未上线**：现网镜像仍 `ghcr.io/bliplink/ordersvr:sha-26b01eb`，运行中 ZK 会话仍 6000ms。无安全 Order HA 滚动窗口前不可因源码构建成功而直接重建线上 A/B/C。
- Order journal 与日志位于 Mac mini 的 virtiofs 宿主机挂载；容器 overlay 是另一种文件系统。安全的 32×4KiB 同步写入探测（测试文件已删除）得到 `/tmp` 83–132ms、virtiofs 57–318ms，波动大，**不能下结论认为 virtiofs 是唯一根因**，更不允许迁移正在写入的 journal。
- `SYNC_BATCHED` 源码已存在，Batcher 设计要求累计 ACK 覆盖请求 seq 才返回；不能在未完成同步副本耐久、网络分区/GC/failover 回归和独立压测时把线上 `SYNC_PER_RECORD` 改成 `SYNC_BATCHED`，尤其禁止 `ASYNC_BATCHED` 伪装无丢单。

剩余优先级：GHCR 新镜像完整 CI 验收→生成安全滚动/回退方案→JVM GC/调度停顿证据采集→独立环境验证 SYNC_BATCHED 和 ZK 15s→Projection P232/P054 历史权威一致性→50租户长稳→200租户分批压测。
