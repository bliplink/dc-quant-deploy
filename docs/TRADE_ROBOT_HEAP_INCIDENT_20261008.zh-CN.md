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
