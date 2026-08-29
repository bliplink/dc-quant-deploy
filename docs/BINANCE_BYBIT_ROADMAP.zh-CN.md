# 对标 Binance / Bybit 的产品化路线图

基线日期：2026-08-29。目标是把已经完成核心永续合约闭环的独立 SaaS 系统发展为能够承载真实资金的中心化加密货币交易系统，而不是复制量化系统。

官方能力基线：

- [Binance U 本位合约公共定义与交易过滤器](https://developers.binance.com/zh-CN/docs/products/derivatives-trading-usds-futures/common-definition)
- [Binance API 安全与权限模型](https://developers.binance.com/en/docs/products/spot/rest-api)
- [Binance User Data Stream](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/ws-api/user-data-stream)
- [Bybit V5 创建订单](https://bybit-exchange.github.io/docs/v5/order/create-order)
- [Bybit Self Match Prevention](https://bybit-exchange.github.io/docs/v5/smp)
- [Bybit 私有订单流](https://bybit-exchange.github.io/docs/v5/websocket/private/order)
- [Bybit 私有成交流](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)
- [Bybit API 限流](https://bybit-exchange.github.io/docs/v5/rate-limit)

## 1. 当前基线

已经具备：

- 独立 `saas-crypto` 分支、公开镜像和一键部署/卸载。
- Web、GW、LoginSvr、MDSvr、APSSvr、OrderSvr、TradeSvr、LiqSvr、ManagerSvr、AdminSvr。
- MySQL 业务数据、ClickHouse 行情/K 线、ZooKeeper 服务发现。
- `location` 租户字段和双租户数据库隔离冒烟测试。
- 登录、测试入金、限价/市价/条件单、撤单/改单/批量撤单、订单/成交/持仓/资金页面。
- GTC/IOC/FOK/Post Only、tick/step/minNotional、市价保护、ClOrdID 幂等、价格时间优先和 STP 核心规则。
- 保证金、杠杆与风险档位、maker/taker 费用、资金费、reduce-only、TP/SL/OCO、部分/最终强平、保险基金和事务型 ADL。
- 97.64 已通过双浏览器闭环、140 个源码测试和 17,100 个压力订单请求；订单、执行、余额、持仓和 11,400 条成交资金流水精确一致。

尚不能承载真实资金的核心原因：

- 租户隔离仍主要依赖调用方传入 `location`，未完成所有 DAO、会话和唯一键的强制约束。
- 资金变化缺少统一的不可变复式账本、幂等键和全链路对账。
- 已实现的订单、仓位、费用、资金费和强平规则仍需历史极端行情回放、属性测试、生产账本和更大容量验证。
- API、WebSocket、账户安全、限流、高可用和灾备尚未产品化。
- 当前环境的 Binance 出站网络不可用。
- 64 环境外部 Binance 行情不可达，核心验收使用受控标记价；可靠的多源指数、标记价和异常剔除仍是生产硬门槛。

## 2. P0：真实资金前置硬门槛

建议周期：4–6 周。未全部验收前禁止真实充值和提现。

### 2.1 强制多租户边界

- 登录后由 LoginSvr 的服务端会话绑定权威 `location`，业务接口不再信任浏览器自行传入的租户值。
- GW 保持租户中立，兼容多租户和非多租户部署，不负责重写 `location`；OrderSvr、TradeSvr、MDSvr、资金和查询服务校验会话上下文与请求中的租户是否一致，冲突时拒绝并审计。
- Topic 权限由目标服务负责：GW 转发订阅请求并获取 Snapshot，只有服务校验 `location` 成功且返回 Snapshot 成功时才把 Topic 加入客户端订阅列表。
- 逐个审计 MySQL DAO、RocksDB key、Topic、锁、缓存、报表和管理查询。
- 用户、订单、成交、持仓、余额、API key 的唯一键和索引改为包含 `location` 的组合键。
- 加入跨租户读、写、撮合、订阅和管理越权的自动化攻击测试。

验收：任意用户不能通过改 URL、请求体、Topic、订单号或用户 ID 访问另一 `location` 的任何数据。

### 2.2 金融级账本与对账

- 建立不可变复式账本：资产、负债、手续费、已实现盈亏、资金费、充值和提现均以分录表达。
- 每次资金变化具备业务幂等键、来源事件、前后余额、币种、`location`、用户和审计时间。
- 余额表变为账本投影；禁止业务代码直接覆盖余额。
- 建立订单、成交、持仓、余额、总账和外部钱包的持续对账任务。
- 金额全部使用明确精度的十进制定点数，禁止浮点数参与金融计算。

验收：重复请求、服务重启、消息重放和部分失败均不会重复扣款；每个币种、每个租户借贷恒等。

### 2.3 确定性订单状态机和撮合

- 固化价格优先、同价时间优先及 maker/taker 判定。
- 支持且严格测试 `GTC`、`IOC`、`FOK`、Post Only。
- 实现 tick size、step size、最小/最大数量、最小名义金额、价格振幅和最大挂单数过滤器。
- 增加客户端订单号幂等、改单、批量下撤单和断线全撤。
- 处理成交与撤单竞态、部分成交、重复消息和顺序错乱。
- 实现 STP：Cancel Maker、Cancel Taker、Cancel Both；支持租户内 SMP group。
- 撮合事件可追加、可重放，重建后的订单簿和最终状态必须完全一致。

验收：状态机模型测试、属性测试、百万级随机指令重放和故障注入结果一致，资金与持仓无差异。

### 2.4 自动化质量门禁

- 把登录、入金、下单、撤单、部分成交、完全成交、最近成交和租户隔离加入浏览器 E2E。
- 服务级契约测试覆盖 GW/FIX 消息字段、错误码和 Topic。
- 每个镜像使用不可变 `sha-*` 版本；CI 生成 SBOM、漏洞扫描和签名。
- 数据库变更必须版本化、可回滚，并在全新安装和存量升级两条路径验证。

## 3. P1：永续合约核心（核心闭环已完成，继续生产化）

建议周期：6–10 周。

- 已完成：long/short 持仓字段、基础 Cross 模式、初始/维持保证金、杠杆档位和风险上限；待补全单向/双向模式以及逐仓的产品级接口和迁移。
- 已完成：`reduceOnly` 校验、Web 市价平仓和强平自动缩量；待补 Close on Trigger 的完整组合行为。
- 已完成：订单市价保护；待补生产多源指数、标记价格、合理价格、异常源剔除和断流降级。
- 已完成：基础 Maker/Taker 费率；待补 VIP 等级、返佣和多手续费币种。
- 已完成：资金费周期结算、幂等和事务流水；待补生产费率计算、封顶/封底和历史回放。
- 已完成：TP/SL、条件市价/限价和 OCO 核心语义；待补追踪止损、触发价来源和全部组合验收。
- 已完成：强平价、破产价、25% 部分强平、最终强平、保险基金和事务型 ADL；待补极端行情、并发和恢复场景的长期验证。

验收：用历史行情和极端跳价场景验证无负余额穿透；强平、资金费和手续费均可由账本独立复算。

## 4. P2：交易所兼容 API 和行情体验

建议周期：4–8 周，可与 P1 后半段并行。

- 提供版本化 REST 和 WebSocket API，字段/错误码风格分别映射 Binance/Bybit 兼容层。
- API key 分权：只读、交易、提现；支持 IP 白名单、过期时间、轮换和撤销。
- HMAC SHA-256，并评估 RSA/Ed25519；签名、时间戳和 `recvWindow` 防重放。
- 用户私有流：订单、成交、持仓、余额和钱包；保证序列号、断线续传和快照恢复。
- 公共流：ticker、trade、book ticker、depth snapshot/delta、mark/index price、funding、K 线。
- 按 IP、用户、API key、`location` 和接口权重做分层限流，响应中返回剩余额度。
- 批量下单、改单、撤单、查询活动单/历史单/成交和账户余额。
- Web 补齐输入校验、明确错误提示、网络重连、订单确认和移动端适配。

验收：官方风格 SDK 可以通过兼容层完成登录签名、下单、撤单和私有流回报；深度流按序列规则可无损重建订单簿。

## 5. P3：SaaS、账户安全和资金托管

建议周期：6–12 周。

- 租户控制台：品牌、域名、交易对、费率、风险参数、配额和功能开关。
- 平台管理员、租户管理员、客服、风控、财务和审计员 RBAC。
- 密码使用 Argon2id/bcrypt，支持 2FA、设备管理、登录风控、会话撤销和反钓鱼码。
- KYC/KYB、AML、制裁名单、可疑交易和 Travel Rule 根据运营司法辖区接入。
- 子账户、统一账户、内部划转和主子账户权限。
- API secret、钱包密钥和数据库密钥接入 KMS/HSM；配置与日志脱敏。
- 真实充值提现：地址生成、区块确认、充值归集、热/温/冷钱包、提现审批、额度和风控。
- 所有管理和资金操作写入不可篡改审计日志。

## 6. P4：高可用、容量和运营

建议周期：持续建设，在真实资金灰度前完成首轮验收。

- 撮合按 `location + symbol` 分片，单分片单写，提供热备和确定性故障切换。
- MySQL 高可用与时间点恢复；ClickHouse 复制；ZooKeeper 奇数节点集群。
- 消息持久化、消费位点、死信、回放和跨服务幂等。
- 多可用区入口、健康摘除、限流降级和无损滚动升级。
- 指标覆盖订单延迟、撮合延迟、拒单、账本不平、行情滞后、强平和租户资源。
- 建立 SLO、告警、值班手册、容量压测、混沌测试、备份恢复和灾难演练。
- 生产发布使用 staging、金丝雀、不可变镜像和一键回滚。

建议首个容量目标：单交易对持续 5,000 orders/s、峰值 10,000 orders/s，P99 下单确认低于 50 ms；最终目标应由业务规模和成本预算重新确认。

## 7. P5：扩展产品

在永续合约和账本稳定后再建设：

- 现货、杠杆、反向合约、交割合约和期权。
- 跟单、网格、定投和策略市场。
- 机构子账户、做市商计划、批量和低延迟通道。
- 法币入金、支付渠道、Earn 等非核心产品。

## 8. 推荐实施顺序

1. 保持现有核心闭环为发布门禁，先实现事务 outbox/不可变复式账本、持续对账和生产多源指数/标记价。
2. 完成服务端权威 location 和所有请求、订阅、缓存、锁、Topic、DAO 的跨租户攻击测试。
3. 实现租户申请/审批、独立 URL、租户管理员、用户/品种/费率/风控/Robot 和审计。
4. 补齐追踪止损、完整账户模式、兼容 API、私有流、签名和限流。
5. 完成账户安全、托管、合规、高可用与灾备后，小额度内部灰度。
6. 通过连续对账、渗透测试、恢复演练和容量验收后再扩大资金与用户规模。
