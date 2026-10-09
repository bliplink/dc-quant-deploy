# SaaS 12 租户盘口与成交持久化持续巡检（2026-10-09）

## 目标与边界

本轮仅对既有的 12 个试用租户进行**只读、匿名交易 Web Chromium 巡检**，不注册新租户、不开仓、不审批、不入金、不调整 Robot、不做租户路由变更/回滚或 Placement 发布。与生产真实下单 TPS、200 租户容量或真实 HA 故障注入不同。

工具：`tests/market-readonly-tenant-survey.js`。默认租户 ID 为此次运行时所见的 12 个租户；其他环境必须通过 `E2E_TENANTS` 显式覆盖，**不要将默认列表当成动态租户发现服务**。浏览器只检查当前租户 `location` 的 10 买/10 卖 DOM 档位、最后成交价、最近成交列表、实时 K 线页面状态和 pageerror。记录每一租户的单独 JSON，失败时截图。

注意：短暂的 `KLINE_PUSH_NOT_YET_OBSERVED` 只是打开页面后短时观察窗口未见更新，**不等于订阅失败**。需另跑更长时间的实时 K 线专项 E2E。真正的故障是盘口持续空白/脚本错误/最新价长期不初始化等。

## 已取得证据

首次运行：11/12 租户买卖各 10 档、最近成交均加载 200 行；`BIHZYE` 在 11 秒内未出现双边盘口。对其单独将超时改为 25 秒重测 **PASS**，盘口双边各 10 档和 200 行最近成交。

第二次全 12 租户运行：**5 PASS、7 WARN、0 FAIL**；12/12 盘口均可加载买卖各 10 档且最近成交窗口约 200 行；警告为短窗口 K 线尚未收到更新，以及 5 个交易页中央最新成交价初始化显示 `--` 的问题。不同租户警告会随刷新时序变化，不能把短窗口无 K 线事件误认为行情中断。

针对该明确 UI 逻辑：`dc-trade-web` 的 Order Book 在 `onTradeHistory` 收到缓存历史时，如盘口 tab 仍显示，会提前返回，导致已有成交历史也不能初始化中央 `execPrice`。现已改成按最新缓存成交填入初始价，不覆盖更新过的实时价，并在切换交易对时重置旧价。源码提交 `bliplink/dc-trade-web@030df71`；需正式镜像发布/完整 CI 与线上 12 租户回归后，才能称为已部署且通过。

本轮资源单次快照：Colima CPU PSI `some avg10=55.88%`，I/O PSI `some avg10=0.19%`，RobotSvr `75.07%`（Docker 单核百分比），Order B 内存 `2.461GiB/3GiB`。因此暂无足够证据扩容到 50/200 租户，主要需排查 CPU 调度与 Robot 任务执行和行情刷新。

ClickHouse `dc.market_trade` 行情成交仍持续新增；同期 5413 条覆盖 12 租户，最新落库 2 秒，最近 90 秒 `BatchClickHouseTask:market_trade` 错误 0；另一次只读检测中 5585 条的 `(location,securityID,execID)` 组合全部唯一，空 execID 0。**样本唯一不代表未来所有数据都有强幂等保证。** ClickHouse `market_trade` 目前仍为 `MergeTree`，客户端重试超时写入可能重复。

## 可复跑操作（只读）

```bash
docker cp tests/market-readonly-tenant-survey.js \
  dc-saas-web-e2e-runner:/runner/market-readonly-tenant-survey.js
docker exec -e E2E_ARTIFACT_DIR=/artifacts/market-readonly-survey \
  -e E2E_TENANT_TIMEOUT_MS=15000 dc-saas-web-e2e-runner \
  bash -lc 'NODE_PATH=/runner/node_modules node /runner/market-readonly-tenant-survey.js'

MARKET_TRADE_MIN_TENANTS=12 bash tests/check-clickhouse-market-trade-host.sh
ENV_FILE=/Users/kong/.opentradingcore/dc-saas-fresh2-20261005.env \
  bash tests/check-projection-consistency-host.sh
bash tests/verify-order-cluster-state-host.sh
```

`survey-report.json` 保留 `PASS`、`WARN`、`FAIL` 不同状态；`WARN` 含初始价尚未可见、短时 K 线尚未更新、首次盘口加载超时但二次等待恢复。千万不要把 `WARN` 统计成完全通过。生产 Mac mini 现有结果保存在 E2E 容器的 `/artifacts/market-survey-20261009-1300` 和 `/artifacts/market-survey-20261009-1310`。

对于 `dc-trade-web@030df71` **部署后**验收，可以加 `E2E_REQUIRE_LAST_PRICE=1`，将历史成交已载入但最新价仍然 `--` 升级为真正的 FAIL；首次运行旧镜像时不能打开此新版本专用门槛。

## 续验补充：首帧盘口与初始最新价

- `dc-trade-web@030df71` 正式镜像通过发布/视觉/功能/压力四条 CI 并部署；首次启用严格 `E2E_REQUIRE_LAST_PRICE=1` 的 12 户验收得到 **5 PASS、5 WARN、2 FAIL**，FAIL 为 `UJ2WZD`、`QS12O4` 的 `LAST_PRICE_UNINITIALIZED`。
- 对两户追加逐 2 秒采样：`UJ2WZD` 在约 4 秒之后出现双边 10/10 和最新价，`QS12O4` 在约 4 秒看到最新价，但该次采样直到 12 秒时盘口仍为 0/0；浏览器没有 pageerror。说明初始最新价和盘口首帧是可分离的时序问题。
- 另对 `QS12O4` 使用只读 `MDSvr.queryPublicMarket`（带原有格式的分区键 `location + U+001F + 4 + U+001F + BTCUSDT`）发现服务端快照是 **10 买、10 卖、最近成交 200**，与 `DPGR6B` 一致；缺少该请求键的请求返回 `code=9000`。故此证据指向浏览器初次 WebSocket 快照/订阅时序问题，**不是此时服务端真的 0 挂单**，也没有发现对应页面 JS 异常。
- 为避免把首次几秒初始化当成长期故障，验收脚本新增最多 8 秒价格宽限时间和 WARN 状态 `LAST_PRICE_RECOVERED_AFTER_GRACE`；两户再测 **2 WARN、0 FAIL**，分别是 `QUOTE_RECOVERED_AFTER_TIMEOUT` 与价格宽限内恢复。
- 新增 `a31c3a4` 交易 Web 修复（尚待最终 CI/部署）：WebSocket 完整盘口持续缺失 8 秒时，最多一次读取当前租户公开盘口快照；正常情况下继续纯 WS，不循环轮询；仅传递现有分区路由键，不改变服务端租户路由或 Placement。必须 CI 与真实浏览器一起通过后才能声明修复完成。
- 验收脚本对持续失败项会额外读取一次服务器公开行情快照（仍为只读），对比服务端是否有 10/10 档位，从而区分服务端空盘口与浏览器订阅缺帧；故障报告保留相应结构化诊断。

## MDSvr 失败批处理保护：实现前必须满足的门槛

从 `com.app.dc.mdsvr` 和 `com.app.dc` 检查确认：
1. `CommonDataManager` 使用 `cacheMarketTrade.drainTo(...)` **先清空内存待写列表**，再把整批交给 `AsyncSeqThreadGroup`。
2. `CommonDataUtils.BatchClickHouseTask` 中 `ClickHouseDBUtils.insertList(...)` 抛异常后直接记录日志，**失败批次未回队列、未落磁盘**。
3. `AsyncSeqThreadGroup` 每条线程使用接近无限容量的 `LinkedBlockingQueue`，数据库异常或重试阻塞时可能导致堆积与 OOM。
4. 当前 ClickHouse `market_trade` `MergeTree` 不是有持久化唯一约束的 outbox。即使已有 5585 条 unique event ID，遇到服务端插入成功但客户端超时的 **UNKNOWN_COMMIT**，直接重试也可能把数据写两次。

因此不要以简单的 `for (i=0;i<3;i++) sleep(); insertList();` 上线冒充可靠。正确的改造应拆为：
- 业务唯一事件键先规范 `(location,securityID,execID)`，明确是否跨 epoch/回放重用 ID；对空 ID 报告错误，不凭价格/数量组合推断唯一性。
- 在单节点稳定路径上将待写事件持久化到有容量上限的 WAL/outbox（包括每个 MDSvr 副本自己的**稳定节点 ID**），先完成持久化提交，再认为队列已接收；容器重建后仍可恢复。有限内存预算，磁盘超过高水位时显式报严重告警，不能静默丢弃。
- 数据库写入结果区分 `ACKED` / `DEFINITELY_NOT_WRITTEN` / `UNKNOWN_COMMIT`。后者**先检查服务端 event key 状态**，再做幂等补偿或重放，不直接盲目重试。确认 ClickHouse 的幂等设计、相关索引及并发竞争后再启用。
- 故障注入门槛：ClickHouse 暂停/恢复、网络超时但数据已插入、批次部分写入、MDSvr SIGKILL/容器重建、磁盘满、异步积压、MDSvr 多副本重试。验收必须保证无 silent drop、无多副本重复计数、内存有界、恢复能继续推进，并记录实际 p95/p99。
- 旧失败批次不能由新队列自动恢复，若权威 Execution/Projection 中还有事件，应另做安全、可审计的历史回填流程。

本轮**尚未修改或部署 MDSvr 重试代码**；已找到具体风险位置和必要条件，先保持旧服务运行。上述门槛通过之前，不将 `market_trade` 统计当作权威撮合一致性或 200 租户压测合格证明。
