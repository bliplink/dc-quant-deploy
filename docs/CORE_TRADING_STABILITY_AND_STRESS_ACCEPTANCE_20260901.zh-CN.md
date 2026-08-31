# DC SaaS 核心交易稳定性与压力验收报告

文档版本：V1.0

验收日期：2026-09-01

代码分支：`saas-crypto`

生产验证环境：`18.140.45.126`，Compose 项目 `dc-saas`，核心压力租户 `CORE_E2E`，持续行情租户 `WEB_E2E`

## 1. 最终结论

本轮完成核心下单、批量撤单、撮合、手续费、余额、保证金、持仓、执行记录、资金流水、服务重启恢复、只减仓平仓、Robot 10+10 档报价、Web 实时盘口和 APSSvr 断线恢复的严格验收。

最终 3000×32 压力轮次共执行 9,001 个 API 操作：3,000 个静态挂单、1 次全撤、3,000 个 maker 单和 3,000 个 taker 单。所有请求成功；撮合后 6,000 条双方执行记录和 6,000 条成交流水精确一致；无异步拒单、重复执行、重复资金流水、交叉盘口、负余额、负保证金、容器重启或 OOM。重启 OrderSvr/TradeSvr 后状态恢复一致，随后 ReduceOnly 平仓并释放保证金。

该结论表示“当前单机独立 SaaS 环境下，既定交易规则和本轮容量门禁通过”，不表示可以直接承载真实用户资金。真实钱包、不可变复式账本/事务 outbox、多源指数与标记价、外部对冲、高可用、灾备、安全合规仍是上线前置条件。

## 2. 本轮代码与部署基线

| 组件 | 修订/镜像 | 本轮作用 |
|---|---|---|
| GW | `6702148` / `ghcr.io/bliplink/gw:saas-crypto` | HTTP 回调线程组改为全连接共享，避免每个连接创建 8 个工作线程 |
| gateway-api | `abb5864` / Maven `3.0.2` | 无界 cached thread pool 改为固定工作线程、有界队列和调用方背压 |
| com.app.dc | `0597fe4` | 公共包固定依赖 `gateway-api:3.0.2` |
| TradeSvr | `e97b8cc` / `sha-e97b8cca1e2606e72e34042d7c38eb92e2d800ba` | 重新构建并只携带 `gateway-api-3.0.2.jar` |
| RobotSvr | `06d101d` / `sha-06d101d6aed3d4c9859fa77e725aa8102567d8b4` | APSSvr 重连、真实活动单健康和安全撤单后的最终版本 |
| 部署 | `e929526` | TradeSvr 设置 32 个 gateway-api worker、10,000 有界队列；GW 设置受控栈和直接内存 |

生产 TradeSvr JVM 参数包含 `-Dgateway.api.workerThreads=32 -Dgateway.api.workerQueueCapacity=10000`。SaaS Compose、数据目录和容器名与同机量化系统隔离，本轮没有操作量化容器。

## 3. 发现问题与修复闭环

### 3.1 GW 按连接创建回调线程

旧 `HttpServerHandler` 为每个 HTTP handler/连接创建一组 8 线程的 `AsynHttpMsg`。持续 Web/HTTP 会话下 GW 曾达到 1,162 个线程和约 329 MiB。修复为进程级共享回调组后，稳定窗口内 GW 保持约 107–114 个线程，内存约 208–252 MiB，重启数 0，`OOMKilled=false`。

### 3.2 TradeSvr 公共客户端使用无界线程池

`gateway-api` 3.0.1 的 `AbstractApiProxy` 使用 `Executors.newCachedThreadPool()`，每条服务入站消息均可创建工作线程。修复前 3000×32 轮次的 9,001 个操作和全部业务核对虽然通过，但撮合期间 TradeSvr 达到约 4,381 个线程、约 707 MiB，因此该轮资源门禁判定为失败。

`gateway-api` 3.0.2 改为固定线程池、10,000 有界队列和 `CallerRunsPolicy` 背压。相同 3000×32 复测时 TradeSvr 总 PID 保持 169–170，其中 `gateway-api-worker` 始终为 32；撮合阶段内存约 259–279 MiB。业务吞吐没有下降，maker/taker 反而达到 205.39/208.60 req/s。

### 3.3 压测基线被历史活动单污染

首次 1000×16 轮次发现两笔 taker 成交到了同租户历史 FOK maker 单，导致压力用户执行记录为 1,998/2,000。撮合结果本身正确，但该轮不能用于压力记账验收。脚本现于正式下单前检查压力租户所有活动单，只要存在非本轮活动单即输出样本并立即失败，禁止污染基线被误报成系统丢单。

## 4. 阶梯压力结果

| 轮次 | 并发 | 业务结果 | 资源结果 | 结论 |
|---|---:|---|---|---|
| 1000×16 首轮 | 16 | API 全成功；2 笔成交进入历史活动单 | 正常 | 基线污染，不计通过/失败 |
| 1000×16 干净重跑 | 16 | 3,001 个操作、2,000 条执行、2,000 条成交流水全部一致 | 0 重启、0 OOM | PASS |
| 3000×32 修复前 | 32 | 9,001 个操作、6,000 条执行、6,000 条成交流水全部一致 | TradeSvr 约 4,381 线程、707 MiB | 业务 PASS，资源 FAIL |
| 3000×32 修复后 | 32 | 全部业务断言、重启恢复、ReduceOnly 平仓通过 | TradeSvr 169–170 PID、32 worker、259–279 MiB | PASS |

最终 3000×32 精确性能：

| 阶段 | 成功/总数 | 吞吐 | p50 | p95 | p99 | 最大 |
|---|---:|---:|---:|---:|---:|---:|
| 静态挂单 | 3000/3000 | 135.76 req/s | 201.62 ms | 485.85 ms | 692.06 ms | 1456.28 ms |
| 全撤 | 1/1 | - | 3097.97 ms | 3097.97 ms | 3097.97 ms | 3097.97 ms |
| maker 下单 | 3000/3000 | 205.39 req/s | 169.09 ms | 274.67 ms | 300.59 ms | 473.00 ms |
| taker 撮合 | 3000/3000 | 208.60 req/s | 125.87 ms | 277.14 ms | 380.82 ms | 587.04 ms |

原始结果：`docs/evidence/stress-bounded-3000x32-20260901.json`。服务器完整产物：`/data/dc-saas-runtime/e2e-artifacts/stress-bounded-3000x32-20260901`。

## 5. Robot、行情和 Web 稳定窗口

GW 线程修复后的连续 305.3 秒干净窗口：

- 模拟用户请求：接受 416，拒绝 0，认证刷新 0。
- 数据库盘口缺档：0。
- 真实 Chromium：1,188 个新增采样，买卖盘最小/最大均严格为 10/10，缺档 0，页面错误 0。
- GW：重启增量 0，`OOMKilled=false`。

原始结果：`docs/evidence/robot-steady-final-20260901.json`。

![Robot 持续报价、Web 10+10 档与实时行情](evidence/web-market-live-20260901.png)

## 6. APSSvr 故障注入与自动恢复

| UTC 时间 | 状态 | 断言 |
|---|---|---|
| 21:32:43 | 停止 `dc-saas-apssvr` | 故障前 Robot `RUNNING/20`、数据库 10+10 |
| 21:32:47 | Robot `STALE/0` | 4 秒内完成失败安全撤单，故障期不保留陈旧报价 |
| 21:33:08 | 启动 APSSvr | 不重启 GW 和 RobotSvr |
| 21:33:53 | 首个 ask 恢复 | 后端发现和订阅自动重建开始生效 |
| 21:33:55 | Robot `RUNNING/20` | 数据库恢复 10 bid + 10 ask，总恢复约 47 秒 |

故障恢复后又运行 141.0 秒干净窗口：接受 156、拒绝 0、数据库缺档 0；真实浏览器新增 544 个样本，严格 10+10、缺档 0、页面错误 0；APSSvr、GW、OrderSvr、TradeSvr、MDSvr、RobotSvr、LiqSvr 全部重启增量 0、`OOMKilled=false`。

原始结果：`docs/evidence/robot-post-fault-final-20260901.json`。

## 7. 数据库与容器证据

最终证据由生产 MySQL、ClickHouse 和 Docker inspect 重新采集。MySQL 显示压力账户各 3,001 条资金流水、余额与持仓归零结果；强平、保险基金与 ADL 事务流水仍完整；ClickHouse `kline` 表包含 `location` 并展示各租户数据分布；核心容器均为当前公开镜像且运行正常。

![最终 MySQL、ClickHouse、强平 ADL 和运行镜像证据](evidence/database-evidence.png)

证据 SHA-256：

- `database-evidence.html`：`73d2753f17d034b071727ad332fad4edf1a557bcbdd61a515aea8afcdac70f5d`
- `database-evidence.png`：`5d186655940bd68709d761f0f63395e35aa1004fd2eee782782057277938e5dd`
- `web-market-live-20260901.png`：`2b6dd4add6a3963494ce8c132ed4b24a73e566da797d613f3d6e08237e89ba61`

## 8. 当前运行状态与剩余门禁

截至最终采样，GW、OrderSvr、TradeSvr、MDSvr、APSSvr、RobotSvr 和 LiqSvr 均为 `running`，RestartCount=0，`OOMKilled=false`。Robot 常驻任务继续在 `WEB_E2E` 运行并产生混合下单、点价、撤单和 10+10 报价，用于继续观察长期行为。

尚未完成、不得误报为通过的项目：

- 真实 Binance 反向对冲：当前 `hedge_enabled=0`，没有专用外部账户凭据。
- 天级稳定性、容量极限和拐点：本轮确认 3000×32 门禁，不等于最大容量。
- 真实钱包、KYC/AML、提现审批、KMS/HSM、安全加固和互联网暴露。
- MySQL/ClickHouse/ZooKeeper 高可用、撮合热备、PITR 和灾备演练。
- 事务 outbox、不可变复式账本、持续对账、多源指数与极端行情回放。

因此下一阶段应先运行 24 小时稳定性与故障矩阵，再做更高阶容量剖析；同时推进生产账本、指数/标记价和全量跨租户攻击测试。外部对冲必须使用专用 Binance 测试或小额账户单独验收。
