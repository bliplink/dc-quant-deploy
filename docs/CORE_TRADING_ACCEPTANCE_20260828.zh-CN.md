# DC SaaS 永续合约核心交易验收报告（2026-08-28）

## 1. 验收结论

172.16.97.64 上的单 `location=CORE_E2E` 核心交易链路验收通过，最终自动化命令退出码为 `0`。

本次已从 Web、GW、OrderSvr、TradeSvr、MDSvr、LiqSvr 到 MySQL/ClickHouse 完成前后端闭环验证，覆盖登录、测试入金、挂单、撤单、撮合、最近成交、市价只减仓平仓、资金与持仓一致性、部分强平、保险亏空后的事务型 ADL、跨 location 隔离以及 JVM 内存限制。

该结论表示当前 P0 核心功能可用于继续进行产品验收，不表示已经达到真实资金生产交易所的安全、合规、高可用和完整 Binance/Bybit 兼容标准。

## 2. 环境与访问方式

- 主机：`172.16.97.64`
- Web：`http://172.16.97.64:18088/#/login?location=CORE_E2E`
- location：`CORE_E2E`
- 测试用户：`corebuyer`、`coreseller`
- 测试密码：`WebE2E!20260827`
- 默认交易品种：`BTCUSDT`
- 业务数据库：MySQL 8.0.36
- 行情与 K 线：ClickHouse 25.9.3.48
- 服务发现：ZooKeeper 3.8.4

页面目前使用 HTTP，因此浏览器显示“不安全”属于预期现象。测试环境的 Deposit 是内部记账，不是链上充值，不得接入真实资金。

## 3. 已部署版本

所有源码均位于独立的 `saas-crypto` 分支，未与量化系统 `latest` 分支混用。

| 模块 | Git 提交 | 64 环境镜像 |
|---|---|---|
| 部署仓库 | `1a900d84cfa77e1b88940575804ee103a6108a5e` | 一键部署、卸载、自动更新和验收脚本 |
| TradeSvr | `018a94b24a9e1a63cbda401b4c904ce25ad0d5ca` | `ghcr.io/bliplink/tradesvr:sha-018a94b24a9e1a63cbda401b4c904ce25ad0d5ca` |
| LiqSvr | `0c0aa56d3cf3c3a1b789afa4dfcbef54c4633880` | `ghcr.io/bliplink/liqsvr:sha-0c0aa56d3cf3c3a1b789afa4dfcbef54c4633880` |
| Trade Web | `719d0626d874435fd93d146ac15e9892ad5320d5` | `ghcr.io/bliplink/dc-saas-trade-web:source-719d0626d874435fd93d146ac15e9892ad5320d5` |
| OrderSvr | `1754c0e8f113b3780eb15bfc967ff44a88603380` | `ghcr.io/bliplink/ordersvr:saas-crypto` |

最终公开镜像摘要：

- TradeSvr：`sha256:cf44a09c711e8438d2cb1fe6f5a8ec567d86f636ecae5ca4b665e56a293e96fd`
- LiqSvr：`sha256:69b6e7e5bbfc74734624f904edcaa98ef6c8831f3673babd7b67fb873c9aeef9`
- Trade Web：`sha256:fe295432cd115f9d539b9d19a4f916c6f31da572dda4f59d9d77e653d467f518`

## 4. 核心验收结果

| 验收项 | 结果 | 关键断言 |
|---|---|---|
| 容器与基础设施 | PASS | 13 个 SaaS 容器运行，MySQL 34 张表，21 个表包含 location，Web 健康 |
| location 数据隔离 | PASS | MySQL 事务数据和 ClickHouse 同一 `BTCUSDT/1M` 键可按 location 独立存储 |
| 登录边界 | PASS | `CORE_E2E` 正常登录；伪造错误 location 被拒绝 |
| 测试入金 | PASS | 买卖双方入金及资金流水落库 |
| 限价挂单与撤单 | PASS | GTC 挂单、撤单状态、活动委托清理正确 |
| 撤单资金释放 | PASS | 撤单和平仓后 `used_margin/freezed_margin/freezed_commission` 全部为 0 |
| 撮合与成交 | PASS | `BTCUSDT` 价格 60000、数量 0.001 的双方订单均 Filled，成交回报落库 |
| 最近成交 | PASS | 页面显示当前 location 的价格、数量和成交时间 |
| 市价平仓 | PASS | Web 生成反向 `reduceOnly=true`、Market/IOC 平仓，不会反向开仓 |
| 最终持仓 | PASS | `corebuyer`、`coreseller` 多空仓位、锁仓和持仓保证金全部为 0 |
| 部分强平 | PASS | LiqSvr 发出 `reduceOnly`、Market/IOC 的 `liq_partial` 订单并真实撮合 |
| 强平资金 | PASS | 0.004 多仓减至 0.003；剩余保证金 1.90692，成交手续费 0.036 正确扣除 |
| ADL | PASS | 99.048 亏空全部分摊，状态 COMPLETED，remaining=0 |
| ADL 排序 | PASS | `adl_high` 排名 1、分摊 70；`adl_low` 排名 2、分摊 29.048 |
| 跨租户强平/ADL | PASS | `CORE_E2E_FOREIGN` 的对照持仓未被修改 |
| 最终健康检查 | PASS | 强平与 ADL 后再次检查，13 个容器和 Web 均正常 |

最终核心验收日志：`/root/core-acceptance-final-018a94b.log`。

浏览器截图、网络和页面结果保存在 64 环境：`/opt/dc-saas-runtime/e2e-artifacts`。

## 5. 本轮发现并关闭的问题

### 5.1 LiqSvr 强平订单有效期错误

旧实现发送 Market/FOK，OrderSvr 按交易规则拒绝市场 FOK，自动强平链路不能实际成交。

修复后 LiqSvr 发送 `Market + IOC + ClOSE + ReduceOnly + PositionSide`，并分别使用 `liq_partial` 和 `liq` 标记部分/最终强平。真实撮合和数据库验收均已通过。

### 5.2 撤单回报乱序导致冻结资金残留

实际浏览器验收发现，OrderSvr 的 `Trade_Cancel` 偶尔先于原始 `Newing` 到达 TradeSvr。旧实现会先从零执行解冻，随后处理迟到的新单并再次冻结，造成订单已取消但账户仍残留冻结保证金和手续费。

修复内容：

- 同一 `location + orderId` 的生命周期事件使用同一串行锁；
- 订单进入终态后，迟到的 `Newing` 被识别为陈旧事件并忽略；
- 解冻数量下限固定为 0；
- Web E2E 增加资金门槛，撤单和平仓后任何冻结或占用金额不为 0 都会失败。

修复后权威 MySQL 结果：

```text
corebuyer  balance=99999.952  used_margin=0  freezed_margin=0  freezed_commission=0
coreseller balance=99999.952  used_margin=0  freezed_margin=0  freezed_commission=0
live_orders=0
```

## 6. 自动化测试

- TradeSvr：47 个测试，0 失败、0 错误；新增取消先于 Newing 的乱序回归测试。
- OrderSvr：43 个测试，0 失败、0 错误。
- LiqSvr：10 个测试，0 失败、0 错误；镜像发布流程不再跳过测试。
- 合计：100 个服务级测试全部通过。
- 主机级整套验收：退出码 `0`。

主机验收不是只查接口返回，还会复核 MySQL 中的订单、成交、持仓、余额、冻结资金、资金流水、ADL 事件和 ADL 流水。

## 7. JVM 与容器内存

| 服务 | JVM Xmx | 容器限制 |
|---|---:|---:|
| GW、LoginSvr、LiqSvr、ManagerSvr、AdminSvr | 512 MiB | 768 MiB |
| MDSvr、APSSvr、OrderSvr | 768 MiB | 1 GiB |
| TradeSvr | 640 MiB | 896 MiB |
| MySQL | - | 2 GiB |
| ClickHouse | - | 3 GiB |
| ZooKeeper | - | 512 MiB |
| Trade Web | - | 512 MiB |

验收时 Java 服务实际使用约 198–294 MiB，Trade Web 约 6 MiB，MySQL 约 469 MiB，ClickHouse 约 1.4 GiB，均低于容器限制。

## 8. 自动更新与回滚

- root cron 每 5 分钟执行 `/root/dc-saas-deploy/auto-update-saas.sh`。
- 只检查并拉取公开 GHCR 应用镜像，MySQL、ClickHouse、ZooKeeper 不自动滚动更新。
- 所有服务摘要稳定 300 秒后才作为一个 SaaS 发布处理。
- 串行拉取镜像，部署失败时恢复上一组运行镜像。
- GitHub 瞬断增加 3 次限时重试；连续失败进入指数退避，不会中断当前运行服务。
- 2026-08-28 22:46 的镜像复检成功，发布指纹为 `18feb1e933b7ff229dd6a82fa45826eb1a9d71f8ee4722bd95d1dd08e105a299`，运行 TradeSvr 与公开最新镜像 ID 一致，无需重启。

## 9. 用户手工验收建议

1. 打开 `http://172.16.97.64:18088/#/login?location=CORE_E2E`。
2. 使用 `corebuyer / WebE2E!20260827` 登录。
3. 在 Account Info 中执行测试 Deposit，并在 Funds 中查看流水。
4. 使用 BTCUSDT 挂一个远离盘口的限价单，确认 Open Orders 出现后撤单。
5. 确认撤单消失，Available 恢复，Order History 为 Cancelled。
6. 如需手工对敲，可分别用 `corebuyer` 和 `coreseller` 开两个浏览器会话，以 60000、0.001 提交相反方向限价单。
7. 在 Trade History、Recent Trades 和 Positions 中检查成交；使用 Close 验证只减仓市价平仓。

## 10. 下一阶段边界

建议保持既定顺序：继续完成永续合约交易规则，再进入租户申请/审批和租户管理产品化。

仍需完成的交易所级能力主要包括：生产级指数价/标记价来源与异常剔除、资金费率生产结算、全仓/逐仓与风险限额完整模型、双向持仓、完整 TP/SL/追踪止损/OCO、保险基金全链路、不可变复式账本与持续对账、压力/混沌/恢复测试、私有流顺序与补发、限流、API 签名、安全合规和高可用。

多租户阶段再实现：租户试用申请、平台审批、独立 URL、租户内注册、租户管理员 RBAC、用户/品种/费率/风控/Robot 配置、交易和资金审计，以及所有查询、订阅、缓存、锁和持久化键的强制 location 边界。
