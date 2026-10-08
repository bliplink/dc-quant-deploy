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
