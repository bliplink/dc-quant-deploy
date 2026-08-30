# RobotSvr 租户流动性与币安对冲专项验收

文档版本：V0.9（生产部署前）

日期：2026-08-31

分支：`saas-crypto`

## 1. 当前结论

RobotSvr 的单 location 流动性代码、APSSvr Binance Futures 10 档接入、租户管理配置、数据库迁移、Docker 编排、自动更新和主机级 E2E 脚本已经完成。RobotSvr 最新源码基线为 `70e1a75f53dfeb1f49e9581c34e5c105a783a3f3`，公开工作流构建成功，18 项单元/风险不变量测试全部通过。

当前不能声明生产验收通过：`ghcr.io/bliplink/robotsvr:saas-crypto` 的 GitHub Package visibility 仍为 Private，生产服务器匿名拉取返回 `unauthorized`。按照“生产服务器不登录镜像仓库、全部应用镜像必须公开”的发布规则，本次没有绕过门禁部署。Package 切换为 Public 后，执行本文第 7 节的一键增量部署和第 8 节的真实 E2E。

真实币安反向对冲还需要专用 Binance Futures 测试或小额账户凭据。凭据不进入 Git、MySQL、Web 或报告，只按运行时 `hedge_account_ref` 映射注入。

## 2. 业务目标

一个 Robot 配置绑定一个 `location + robot_id + symbol + tenant API key`，实现：

1. 从 APSSvr 接收 Binance Futures 10 档深度。
2. 在该 location 的 OrderSvr 订单簿维持上下各 10 档流动性。
3. 用户直接成交 Robot 报价后，恢复被部分成交的档位，并按 Robot 内部净持仓在币安执行反向对冲。
4. 用户限价单进入 Binance 外部买一/卖一之间时，Robot 以 IOC 主动吃掉，避免租户盘口长时间停留在偏离外部市场的价格。
5. 行情异常、风险越限、对冲不确定、配置停用和服务退出时停止报价并撤单。

## 3. 行情与报价规则

- APSSvr 使用 Binance Futures partial-depth 10 档、100 ms 流，发布 Topic `dc.aps.depth.BNFutures.<symbol>`。
- RobotSvr 通过 GW 订阅 APSSvr Topic，不直接建立第二套外部行情连接。
- `quote_source=APSSVR_BINANCE_DEPTH` 时，Robot 价格逐档镜像外部买卖盘；默认 bid 10 档、ask 10 档。
- 档位价格按租户 `tick_size` 对齐；数量按 `qty_tick_size` 向下取整，并校验最小/最大数量、最小名义金额、单档上限和最大库存。
- 数量模式：`FIXED` 使用租户固定 `order_qty`；`SCALED` 使用外部档位数量乘配置系数，再受单档上限约束。
- 常规报价 TIF 为 PostOnly，避免 Robot 主动成为 taker。
- 对账使用活动单的 `leaves_qty`。发生部分成交后，旧档撤销并补充为完整目标数量，避免原始 `order_qty` 相同但剩余深度不足。

## 4. 用户挂单扫单规则

- 用户 Sell 价格严格低于 Binance 外部卖一时，Robot 可发 Buy IOC。
- 用户 Buy 价格严格高于 Binance 外部买一时，Robot 可发 Sell IOC。
- 外部卖一/买一同价边界不扫。该价格可能已有 Robot 同方向镜像单，边界 IOC 可能先触发自成交保护或打到自身订单。
- 每次只选择对 Robot 最有利的候选订单，数量不超过用户剩余量、`sweep_max_qty` 和剩余库存容量。
- 允许的最差价格由 `sweep_max_loss_bps` 控制；超出损失上限不扫。
- 查询条件固定包含 location、symbol，排除 Robot 自己和所有 `algo_name LIKE 'robot%'` 的订单。

## 5. 外部反向对冲规则

- 目标外部仓位 = 租户内 Robot 净持仓的相反数。
- 每轮只对冲“目标外部仓位 - 已确认外部对冲仓位”的差额，不重复提交全仓。
- 对冲单在调用 APSSvr/Binance 之前，先事务写入 `dc_robot_hedge_execution` 的 PENDING 流水。
- clientOrderId 可确定重用。调用超时或响应不完整时记录 UNKNOWN、撤销租户报价并停止继续报单。
- RobotSvr 使用同一 clientOrderId 经 APSSvr 查询 Binance：完全成交记 FILLED；终态部分成交记 PARTIAL 并继续补差；零成交终态记 FAILED；仍未知则持续阻断。
- 外部账户只配置别名。`ROBOT_HEDGE_ACCOUNTS_JSON` 在容器运行时把别名映射为 API Key/Secret，Web 和数据库只保存 `hedge_account_ref`。

## 6. 已完成自动化测试

| 测试组 | 数量 | 结果 | 覆盖重点 |
|---|---:|---|---|
| GatewayMarketDataClientTest | 2 | PASS | APSSvr 深度解析、乱序输入排序、空订阅快照 |
| QuoteEngineTest | 6 | PASS | 价格/数量对齐、10+10 档、库存边界、数量缩放、熔断、部分成交补档 |
| LiquiditySweepEngineTest | 4 | PASS | 买卖双向扫单、损失上限、数量上限、库存上限 |
| HedgeResultTest | 3 | PASS | 完全成交、终态失败、工作中/部分成交状态 |
| RobotRiskInvariantTest | 3 | PASS | 1 万轮盘口变化、10 档单调唯一、数量约束、双向库存与自成交边界 |
| 合计 | 18 | PASS | 0 failure、0 error、0 skipped |

APSSvr 21 项测试、AdminSvr 相关 6 项测试和 Trade Web `npm run build-prod` 也已通过。RobotSvr、APSSvr、AdminSvr、Trade Web 镜像工作流均成功。

## 7. 生产增量部署步骤（Package Public 后执行）

```bash
cd /home/ec2-user/dc-saas-deploy
sudo docker pull ghcr.io/bliplink/robotsvr:saas-crypto
sudo ./auto-update-saas.sh --force
sudo ./validate.sh
```

部署前后必须记录 `docker compose ls`、量化项目 11 个容器的 ID/状态、SaaS 项目容器 ID/状态。只允许 `dc-saas` 从 13 个核心容器增加到 14 个；`dc-quant-deploy` 的容器、端口、数据目录和 RestartCount 不得变化。

RobotSvr JVM 为 `-Xms32m -Xmx256m`，容器内存上限 384 MiB。MySQL 迁移应确认 Robot 运行租约字段、`dc_robot_hedge_execution` 和扫单查询索引存在。

## 8. 单 location 生产 E2E（待执行）

```bash
cd /home/ec2-user/dc-saas-deploy
sudo ./tests/run-robot-liquidity-e2e-host.sh
```

脚本创建隔离 `ROBOT_E2E_<timestamp>` location 并保留证据，必须全部满足：

1. Robot runtime_status 进入 RUNNING，活动报价恰好 10 bid + 10 ask。
2. 连续比对实时 Binance REST 深度，双方至少 8/10 价格重合；差异只允许来自抓取时间差。
3. 用户 IOC 直接吃 Robot ask，用户单成交，Robot maker 累计成交增加。
4. 部分成交档位被撤旧补新，20 个活动单的 leaves_qty 全部恢复为目标 order_qty。
5. 用户 Sell 挂入外部价差后，Robot Buy IOC 将其吃掉；双方订单、execution、持仓和资金落库。
6. 禁用 Robot 后 runtime_status=STOPPED，所有 Robot 活动报价清零。
7. 该次 ClOrdID 在其它 location 中计数为 0。
8. Robot/APSSvr/OrderSvr/TradeSvr 无未处理异常，容器 RestartCount=0、OOMKilled=false。

## 9. 真实币安对冲验收（待专用凭据）

生产前必须额外完成：

- 用户分别吃 Robot bid 和 ask，核对内部净持仓与币安外部相反仓位数量一致。
- 市价单完全成交、部分成交后取消、交易所拒单、请求超时但交易所已接单四类结果。
- APSSvr 重启、RobotSvr 重启、网络断开/恢复；同一 clientOrderId 不得产生重复外部订单。
- UNKNOWN 期间租户活动报价为 0；完成查询对账后才恢复。
- 交易手续费、滑点、外部 PnL 和内部 Robot PnL 可对账，密钥不出现在日志、数据库和 API 响应。
- Binance 限频、时间偏移、最小数量/名义金额和价格保护拒绝均有明确告警与安全停报。

完成第 8、9 节并补充 Web 盘口、MySQL Robot 配置/订单/对冲流水、容器镜像三类截图后，本报告版本才能升级为 V1.0 生产验收。
