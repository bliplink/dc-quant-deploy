# 生产对账、验收与会话交接

本文是量化系统生产运维的长期交接入口。换机器或换会话后，先拉取本仓库，再从本文确认最近一次生产基线、尚未完成的事项和安全操作顺序。

本文不得记录 SSH 私钥口令、API Key、机器人 Token、数据库密码、真实用户标识或完整成交明细。环境相关值只能在运行时通过环境变量或安全配置取得。

## 1. 服务和数据权威边界

- APSSvr 的执行账本是订单与成交事实的权威来源。
- ClickHouse 的 `dc.quant_order`、`dc.quant_trade`、`dc.quant_position` 和账户快照是查询、报表与复盘投影。
- QuantSvr 负责信号消费、风险控制、报单及把执行回报投影到 ClickHouse。
- INDSvr 负责场景识别、候选策略和实盘选择。
- SIMSvr 负责带交易成本的回测、优化及自动发布。
- BatchSvr 负责运行报告、日报和系统巡检任务。

当 APSSvr 与 ClickHouse 不一致时，不能只按行数或账户余额判断，必须按 `executionID` 做集合差异。

## 2. 最近一次生产基线（2026-10-03）

本节只保留可公开的聚合证据，不保存账户标识。

- 核心容器均在运行，ClickHouse 和 Web 健康检查正常。
- BatchSvr 于 2026-09-27 恢复运行；30146 和 18080 端口正常，ClickHouse、APSSvr、MDSvr、INDSvr 连接正常。
- BatchSvr 已成功生成 2026-09-27 日报，运行报告和实时监控任务持续执行。
- 10 个交易品种的场景选择在 2026-09-28 00:05 UTC 左右全部刷新。
- `strategy_live_registry` 当时有 100 个 `ACTIVE`、9 个 `OFFLINE` 策略。
- DOGE 新候选 `research_r39_doge_stable_rsi_wick_range_reentry_short@v1` 已通过正式回测并自动发布。
- 最近一轮 SOL 平仓的 ClickHouse 投影净收益约为 `+4.62104544 USDT`；单笔新交易不能代表账户整体收益。
- 2026-10-03 已完成 2026-09-20、2026-09-21 磁盘写满窗口的显式投影修复。修复前权威执行账本有 267 个唯一 executionID，ClickHouse 有 257 个，缺失 10 个；缺失部分的已实现毛收益为 `-84.47097`、手续费为 `6.24594818`、净影响为 `-90.71691818 USDT`。
- 修复后 APSSvr 与 ClickHouse 均为 267 个唯一 executionID，双向差集为 0；逐 executionID 的已实现收益和手续费不一致数为 0，双方汇总毛收益、手续费和净收益完全相等。
- QuantSvr `f8e5212` 修复了历史投影中演示标记同时存在 `true` 与 `1` 时，显式修复 CLI 误查真实账本的问题；成交去重查询不再按演示标记拆分，与既有交易唯一键保持一致。全量 43 个测试通过，生产容器已自动部署该 revision。
- 两个日期首次修复分别新增 2 笔和 8 笔；随后重复执行分别得到 `insertCount=0, skipCount=15` 与 `insertCount=0, skipCount=8`，幂等验收通过。
- QuantSvr `04a8be8` 已包含“同一策略两个不同亏损订单后暂停”的运行时保护。
- SIMSvr 已使用费用后目标选择参数，并隔离重叠的 walk-forward 证据；相关基线提交为 `dc1343b`、`4e68601`、`5a4d996`、`db03895`、`ae27d12`。
- 根分区在清理后曾降至约 24%，到本次验收已回升到约 54%。主要增长源仍是 APSSvr 和 MDSvr 高频日志；日志轮转是 P0，不能仅清理业务日志后视为解决。
- APSSvr `4faf492` 已将逐 tick 原始 Binance JSON 降到 DEBUG，并把高频 `GwServerResource` 发布日志限制为 WARN；MDSvr `255109c` 已将逐 K 线持久化日志从 WARN 降到 DEBUG。
- 部署仓库已为全部长期运行容器设置 Docker `json-file` 默认滚动：单文件 100MB、保留 3 份；可用 `DOCKER_LOG_MAX_SIZE` 和 `DOCKER_LOG_MAX_FILE` 覆盖。

## 3. executionID 对账流程

### 3.1 只读基线

先取 ClickHouse 投影中的唯一 executionID：

```sql
SELECT DISTINCT execID
FROM dc.quant_trade
WHERE quantID = '<quant-id>';
```

再通过 APSSvr 的只读 `queryExecOrder` 查询同一账户、交易模式和时间范围。对两个集合计算：

```text
missing_in_clickhouse = aps_execution_ids - clickhouse_execution_ids
extra_in_clickhouse   = clickhouse_execution_ids - aps_execution_ids
```

只有明确得到缺失 ID、日期和聚合金额后，才允许进入修复步骤。不要通过账户余额倒推并手工伪造成交。

### 3.2 显式修复入口

QuantSvr 提供仅供运维 CLI 使用的显式修复开关。普通定时任务、启动同步和日常复盘仍受自动回填禁用开关保护。

容器升级到包含显式修复能力的版本后，对每个确认缺失的交易日执行：

```bash
docker exec dc-quantsvr sh -lc '
  cd /srv/dc/dc/QuantSvr &&
  java -Dlog4j.configuration=file:./config/log4j.ini \
    -cp "classes:config:lib/*:/srv/dc/tpc/tpc/*" SyncDayReviewCli \
    "<quant-id>" "2026-09-20" --repair-backfill --sync-only
'
```

CLI 还需要通过进程环境提供 `APS_ADMIN_PASSWORD`；只允许从安全配置或当前运维会话注入，不得写入脚本、文档、命令输出或仓库。

历史数据可能同时使用 `demo=true` 和 `demo=1`。维护入口必须用 `DemoModeUtils.isDemo(...)` 识别兼容值，不能把存量字符串与单一常量做严格相等判断；成交去重必须与唯一键一致，不能再额外按 `demo` 拆分，否则会出现误查真实账本或重复回填。

对 2026-09-21 重复一次。`--sync-only` 保证只修复订单/成交投影，不重新触发 AI 日报或策略演进。

修复逻辑使用 QuantSvr 原有映射、上下文补全和交易键去重：

- 查询 APSSvr 当日订单及成交；
- 从订单、信号和同族订单恢复策略元数据；
- 用 `quantID + venue + symbol + orderID + execID` 判断已有成交；
- 仅以 `download_trade` 来源写入真正缺失的成交。

### 3.3 修复验收

修复后必须完成四项检查：

1. APSSvr 与 ClickHouse 唯一 executionID 数相等，两个方向差集均为零。
2. 第二次执行同一日期修复时 `insertCount=0`，证明幂等。
3. 缺失成交的毛收益、手续费及净收益与修复前差集完全一致。
4. 账户余额、累计已实现盈亏、手续费、持仓和成交汇总能够形成解释一致的等式。

禁止删除旧行、修改 APSSvr RocksDB 或以 ClickHouse 行数相等代替 ID 级验收。

## 4. 生产闭环验收

每次交易核心变更后按以下顺序验证：

```text
INDSvr 场景/信号
  -> QuantSvr 收到并匹配运行策略
  -> 风控允许或写入明确阻断原因
  -> APSSvr/交易适配器接受订单
  -> executionID 成交事实
  -> QuantSvr ClickHouse 投影
  -> 持仓与账户快照
  -> BatchSvr 运行报告和日报
```

推荐查询：

```sql
-- 最近成交及策略上下文
SELECT eventTime, securityID, side, lastQty, lastPx,
       realizedPnl, fee, scene, strategyName, strategyVersion, execID
FROM dc.quant_trade
ORDER BY updateTime DESC
LIMIT 50;

-- 非零持仓
SELECT *
FROM dc.quant_position_latest_view
WHERE ifNull(longPosition, 0) != 0
   OR ifNull(shortPosition, 0) != 0;

-- 信号阻断原因
SELECT rejectStage, count()
FROM dc.quant_signal_block_event
WHERE tradeDate >= today() - 1
GROUP BY rejectStage
ORDER BY count() DESC;

-- Batch 最新状态
SELECT job_name,
       argMax(status, update_time) AS status,
       max(update_time) AS latest,
       argMax(failure_reason, update_time) AS failure
FROM dc.strategy_batch_job_run
GROUP BY job_name
ORDER BY job_name;
```

验收不能只看容器为 `Up`。至少要求：容器无重启/OOM、端口归属正确、服务依赖连接成功、数据库有预期事实、报告任务到达终态。

## 5. 连续亏损风控验收

当前规则：同一策略版本的两个不同平仓订单连续产生负已实现收益时，对对应品种停止新开仓；重复的最终回报不得重复计数，盈利平仓会清零计数，不同策略版本之间不串计数。

安全验收分两层：

1. 自动测试验证两次亏损、重复回报、盈利复位和跨版本隔离。
2. 生产只做被动证据检查，不为了测试故意制造真实亏损。

生产检查项：

- 镜像 revision 至少包含 `04a8be8`。
- 容器内存在 `StrategyLossStreak.class`。
- 风控参数 `maxConsecutiveLoss` 的有效上限为 2。
- 新的亏损平仓后，状态和日志出现明确暂停原因；暂停期间新开仓被拒绝，但平仓与保护单仍允许执行。
- 服务重启、跨日自动恢复及手动恢复后，计数和展示不能形成“运行中但显示超限”的长期矛盾。

## 6. BatchSvr 恢复后的注意事项

- 容器恢复只会继续未来 cron，不会自动补跑停机期间错过的每一天。
- 是否补历史日报必须由业务决定；补跑时按日期显式执行，并确保不会触发策略发布、退役或通知副作用。
- `strategy_batch_job_run` 中短暂的 `RUNNING` 是正常的，但同一任务长期不进入 `SUCCESS/FAILED` 才是故障。
- 启动时可降级的外部客户端告警必须与后续持续错误区分；端口、ClickHouse 和关键依赖连接成功后仍要观察一个任务周期。

## 7. 日志与磁盘 P0

已知高增长源是 APSSvr、MDSvr 应用日志和 Docker `json-file` 日志。当前已落地高频源码降级和 Docker 硬性滚动，仍需持续实施：

- Docker Compose 为所有长期运行服务保留 `max-size` 和 `max-file`，部署后用 `docker inspect` 验证实际生效；
- Log4j/Logback 设置按日和按总量保留；
- 将逐 tick、完整请求响应和大 JSON 从 INFO 降为 DEBUG 或改成采样；
- 每日监控根分区、Docker 数据目录和应用日志目录增长；
- 设预警阈值，并在达到阈值前停止新增任务，而不是等 ClickHouse 拒绝写入。

清理 `${DEPLOY_ROOT}/log` 不会清理 `/var/lib/docker/containers` 下的 Docker 日志。释放磁盘后，发生过 RocksDB 后台写入错误的服务还需要重建容器并验证数据文件继续增长。

## 8. 当前后续优先级

1. 复核连续亏损状态跨重启/跨日恢复的一致性，不主动制造生产亏损。
2. 验证 APSSvr/MDSvr 新镜像和 Docker 日志滚动已部署，观察至少 24 小时增长率；应用日志再补总量保留策略。
3. 对 ACTIVE 策略按 24 小时、3 天、7 天观察费用后净收益、手续费占比、最大回撤和实盘/回测偏差。
4. 持续观察新启用的 BTC 场景策略自然触发；没有信号时不得为了验收强制制造生产成交。
5. 需要时显式补算 BatchSvr 停机期间日报；默认不自动回补。

每次完成一项后，更新本文的“最近一次生产基线”和本节，不要把仅存在于聊天记录中的结论当成长期交接材料。
