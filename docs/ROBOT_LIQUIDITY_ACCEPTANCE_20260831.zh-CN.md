# RobotSvr 租户流动性专项验收报告

文档版本：V1.0

日期：2026-08-31

分支：`saas-crypto`

环境：`18.140.45.126`，隔离租户 `ROBOT_E2E_20260831100417`

## 1. 验收结论

RobotSvr 的租户内部流动性闭环通过生产环境 E2E。APSSvr 接收 Binance Futures 实时 ticker/bookTicker，经 GW 发布给 RobotSvr；RobotSvr 按租户和品种合成 10 档买价与 10 档卖价，经租户 API 身份向 OrderSvr 报单。用户成交 Robot 报价后，Robot 会撤销过期档并补齐 10+10 档；用户订单进入外部参考价差后，Robot 使用 IOC 主动成交，避免租户盘口长期停滞；配置停用、租约续期失败或行情失效时安全撤销报价并停止。

本结论覆盖内部报价、撮合、补档、主动成交、资金/持仓/执行落库、租户隔离和停止撤单，不代表真实 Binance 反向对冲已经验收。当前隔离租户 `hedge_enabled=0`，未向源码、Git、MySQL 或报告写入外部交易所凭据。

## 2. 发布基线

| 组件 | 基线/镜像 | 状态 |
|---|---|---|
| RobotSvr | `62718fd7faa6905a79aeaa4ddbc0397e280e4e51` / `ghcr.io/bliplink/robotsvr:sha-62718fd7faa6905a79aeaa4ddbc0397e280e4e51` | 已公开、已部署 |
| APSSvr | `87113eab` / `ghcr.io/bliplink/apssvr:sha-87113ea` | 已公开、已部署 |
| GW | `ghcr.io/bliplink/gw:saas-crypto` | 已部署，转发 `dc.bookticker.**` |
| OrderSvr/TradeSvr | `saas-crypto` | 已部署并参与真实撮合与结算 |

RobotSvr JVM 为 `-Xms32m -Xmx256m`，容器内存上限 384 MiB。生产 SaaS 共 14 个容器，与同机量化系统使用独立 compose、容器名、端口、目录和数据卷。

## 3. 业务规则

### 3.1 租户与行情

- 一个 Robot 配置唯一绑定 `location + robot_id + security_id + api_user_id`。
- `quote_source=APSSVR_BINANCE_TICKER`。APSSvr 维护 Binance Futures 参考行情，RobotSvr 不重复建立外部行情连接。
- 行情、订单查询、活动委托、成交、持仓和租约条件全部包含 `location`，本次对照查询确认其它 location 中没有测试订单。
- 行情超过 `stale_price_ms`、偏离超过 `max_deviation_bps` 或处于熔断期时停止新增报价。

### 3.2 10+10 档报价

- 使用外部买一/卖一和配置的首档价差、档间距合成逐级价格。
- 买价严格递减且唯一，卖价严格递增且唯一；价格、数量按租户品种的 tick、qty tick、最小/最大数量和最小名义金额对齐。
- 每档使用 PostOnly，避免常规补档成为 taker；库存达到 `max_position_qty` 时停止扩大相应方向风险。
- 每轮采用有界对账：批量撤销不再需要或数量不足的旧档，再补充目标档；循环中持续检查停止信号，避免停用与补档并发产生残留订单。

### 3.3 用户订单主动成交

- 用户 Sell 价格进入外部参考价差时，Robot 可发 Buy IOC；用户 Buy 价格进入价差时，Robot 可发 Sell IOC。
- 候选查询固定包含租户和品种，排除 Robot 自身及其他 Robot 算法订单。
- 主动数量不超过用户剩余量、`sweep_max_qty` 与 Robot 剩余库存容量，价格损失受 `sweep_max_loss_bps` 限制。
- 成交必须同时产生双方订单状态、execution、持仓和资金流水，不能只改变盘口显示。

### 3.4 停止与租约

- 配置 `enabled=0`、租约续期失败、行情失效或服务退出时执行同一套完整停止流程。
- 停止顺序为：设置停止信号、阻止后续补档、撤销当前租户与 Robot 的全部活动报价、释放租约、写入终态。
- 修复前租约失败会提前把 `running=false`，Supervisor 随后因 CAS 直接返回而跳过撤单。`62718fd` 将租约失败直接路由到完整 `stop(...)`，并由并发契约测试和生产 E2E 共同验证。

## 4. 自动化测试

| 测试域 | 结果 | 覆盖重点 |
|---|---|---|
| RobotSvr 单元测试 | 25/25 PASS | 档位单调唯一、数量约束、库存、扫单、行情失效、租约、停止/补档并发 |
| APSSvr 单元测试 | 22/22 PASS | Binance bookTicker 解析、快照发布、重复 Bean 防护 |
| Robot 生命周期专项 | PASS | 启用后 20 笔活动报价；停用后 `STOPPED` 且活动报价为 0 |
| SaaS 部署校验 | PASS | 14/14 容器、MySQL 41 张表、27 张表含 location、Web/ClickHouse 健康 |

## 5. 生产 E2E 结果

执行脚本：`tests/run-robot-liquidity-e2e-host.sh`

| 场景 | 结果 | 生产硬断言 |
|---|---|---|
| 实时参考行情 | PASS | APSSvr 可见 BTCUSDT/ETHUSDT Binance ticker |
| 初始报价 | PASS | 10 个不同买价 + 10 个不同卖价，方向有序，均位于实时中间价 30 bps 范围内 |
| 用户成交 Robot 卖价 | PASS | 用户与 Robot 双方 execution 落库，随后恢复完整 10+10 档 |
| 用户订单进入价差 | PASS | Robot IOC 主动成交，订单、execution、资金和持仓均落库 |
| 租户隔离 | PASS | 测试 ClOrdID 在其它 location 的订单数为 0 |
| 停用 Robot | PASS | `enabled=0` 后进入 `STOPPED`，活动报价为 0 |
| 清理 | PASS | 所有 `ROBOT_E2E_%` 配置均禁用/停止，活动测试委托总数为 0 |

脚本汇总：`quotes=80, sweeps=1, fills=1, executions=4, foreign_location_orders=0`。`quotes=80` 是整个启用、成交、补档、主动成交和停止周期内观察到的报价事件累计，不是同时活动委托数；正常稳定盘口为 20 笔活动报价。

## 6. 数据流

```text
Binance Futures ticker/bookTicker
  -> APSSvr（解析、快照、Topic）
  -> GW（dc.bookticker.**）
  -> RobotSvr（location + symbol 策略、10+10 档、风险与租约）
  -> GW / OrderSvr（租户 API 身份报单、撤单、IOC）
  -> TradeSvr（成交、手续费、余额、持仓、流水）
  -> MDSvr（该 location 的订单簿、最近成交、K 线）
  -> GW / dc-trade-web（租户行情与账户展示）
```

## 7. 未完成边界：真实外部对冲

外部反向对冲需要专用 Binance Futures 测试账户或经过限额保护的小额账户，验收前不能启用。后续必须覆盖：

- 用户分别成交 Robot bid/ask 后，内部净持仓与外部相反仓位数量一致。
- 完全成交、部分成交、拒单、超时但交易所已接单四类确定性对账。
- APSSvr/RobotSvr 重启和网络中断恢复后，同一 clientOrderId 不产生重复外部订单。
- UNKNOWN 状态期间租户报价为 0，对账确认后才恢复。
- 交易手续费、滑点、外部 PnL、内部 Robot PnL 可核对，密钥不出现在日志、数据库和 API 响应。

在上述场景完成前，产品页面应明确区分“内部流动性正常”和“外部对冲已启用/健康”，不能用前者替代后者。
