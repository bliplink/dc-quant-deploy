# DC SaaS 加密货币永续合约系统开发交接

更新时间：2026-09-03  
源码根目录：`E:\sourcecode\stc-saas-crypto`  
目标分支：除 `gateway-api` 外统一使用 `saas-crypto`；`gateway-api` 使用 `3.0.0`。

> 本文供后续 ChatGPT/Codex 或工程师直接接手。文中不包含服务器私钥、私钥密码、平台账号密码、租户账号密码、币安 API Key 等敏感信息；需要时向项目所有者单独获取。

## 1. 产品目标与已确认边界

系统目标是建设一套按 `location` 隔离的 SaaS 加密货币永续合约交易系统，核心交易规则逐步对标 Binance/Bybit，同时保留现有 DC 服务化架构。

已确认的关键原则：

1. `location` 是租户隔离键。客户端传入的 location 不能作为最终权限依据，业务服务必须使用认证后得到的权威 location。
2. GW 保持通用、租户中立，只负责连接、认证消息转发、请求路由和订阅管理；租户数据授权由发布快照的业务服务完成。服务拒绝 snapshot 后，GW 不应把 topic 加入该连接的订阅集合。
3. MDSvr 行情不是全租户共享盘口。每个租户拥有独立 OrderBook、成交、K 线和行情 topic；APSSvr 的外部指数源可以共享输入，但 MDSvr 输出必须带租户维度。
4. AdminSvr 面向交易 Web；ManageSvr 面向平台运营后台和租户管理后台。
5. 普通交易用户、租户管理员、平台管理员是三个入口和权限体系。普通用户不能进入租户管理；租户管理员只能管理自己的 location；平台管理员管理申请、配额和全局运营。
6. RobotSvr 是交易系统之外的策略机器人，只允许访问 GW，不允许直接访问 MySQL、ClickHouse、LoginSvr、OrderSvr、TradeSvr、AdminSvr 等后端进程。
7. Robot 内部做市、扫用户挂单和模拟成交订单必须为 `isdemo=true`，只参与实时撮合和行情，不落订单/成交业务库；真实用户订单必须正常落库。外部 Binance 对冲单不是 demo 单。
8. Robot 内部计划维持 20 档报价；MDSvr/Web 当前按项目要求展示买卖各 10 档。
9. Web 未登录即可通过租户 URL 浏览该 location 的盘口、成交、K 线等公共行情；下单、资产、持仓和历史查询时才要求登录。注册自动继承 URL 中的 location，用户不能自行填写或篡改租户。

## 2. 当前架构与服务职责

| 服务/仓库 | 当前职责 | 后续重点 |
|---|---|---|
| GW / gateway / gateway-api | TCP/WebSocket/HTTP 连接、登录消息转发、请求和 topic 转发 | 保持租户中立；补齐 Robot API Key 登录协议、私有成交订阅一致性 |
| LoginSvr | 用户名密码、token/API Key 身份认证，返回权威用户与 location | 支持 Robot 通过 GW 完成 API Key 签名认证，禁止 Robot 直连 HTTP |
| OrderSvr | 下单校验、撮合、撤单、订单簿、执行回报 | 完整订单规则、序列号、恢复、分片和高并发 |
| TradeSvr | 资金、持仓、成交、保证金、资金费、账务查询 | 不可变账本、事务 outbox、对账、保证金模式完善 |
| LiqSvr | 风险检查、强平、保险基金、ADL | 生产级并发、幂等、故障恢复和极端行情验证 |
| MDSvr | 按 location 生成盘口、成交、ticker、K 线并经 GW 发布 | 租户隔离证明、snapshot+delta 序列、断档恢复 |
| APSSvr | 接收 Binance 等外部行情，计算指数输入；通过 GW 发布；执行外部对冲 | 多行情源指数、异常源剔除、真实对冲完整验收 |
| AdminSvr | 交易 Web 的注册、交易和查询接口 | 普通用户接口边界、权威 location、响应一致性 |
| ManageSvr | 平台审核、租户管理、配额、用户/品种/Robot 配置 | RBAC、2FA、配额硬限制、审计、计费 |
| RobotSvr | 通过 GW 订阅 APSSvr 行情，向 OrderSvr 报价；成交后经 GW 请求 APSSvr 对冲 | 完全外置、实时成交驱动对冲、本地幂等流水 |
| trade-web | 交易页、注册登录、租户后台、平台后台 | Bybit 风格完善、移动端、可用性和长稳测试 |
| dbscripts | MySQL/ClickHouse 表结构及升级脚本 | 账本/outbox、索引、迁移可回滚和升级验证 |
| deploy | 独立 Docker Compose、一键安装/卸载/更新/回滚、测试脚本和文档 | 最新全量重装、自动更新、回滚和生产证据 |

核心数据流：

```text
Binance 行情 -> APSSvr -> GW topic -> RobotSvr
                              \-> 指数输入 -> MDSvr

Web/Robot -> GW -> OrderSvr -> 撮合/执行回报 -> TradeSvr -> 资金/持仓/账务
                         \-> MDSvr -> location 盘口/成交/K线 -> GW -> Web/Robot
                         \-> LiqSvr -> 强平/保险基金/ADL -> OrderSvr/TradeSvr

Robot 自有成交回报 -> GW 私有 topic -> Robot 暴露变化 -> GW -> APSSvr -> Binance 对冲
```

## 3. 已完成的开发基线

以下表示已有代码或已有阶段性测试，不代表已经满足真实资金生产标准：

1. 永续合约核心链路已有基线：下单、撤单、撮合、成交、资金、持仓、强平、保险基金和 ADL 基础流程。
2. 已实现精度、最小下单额、TIF、幂等、防自成交、行情保护、TP/SL/OCO 等一批核心规则；仍需按第 4 节补齐边界和生产验收。
3. WebSocket 登录、token 登录恢复基础能力已实现；公共行情未登录可见、租户 URL 自动注册已有基线。
4. MDSvr 主动推送实时 K 线，Web 不使用两秒轮询兜底；历史 K 线首屏、实时合并和 10+10 深度已有阶段性修复。
5. 多租户控制面已有基线：试用申请、平台审批、租户 URL、租户注册、租户用户/品种/API Key/Robot 配置/交易记录/设置/审计、暂停恢复。
6. Web 已有 Bybit 风格暗色布局、无显式编辑模式的拖动分隔、恢复布局、中英文切换和移动端基础适配。
7. 资金费重复计费的代码修复已在 TradeSvr 提交 `80a4cb4`：拒绝过期 Quartz 触发并按结算边界归一化。
8. Robot 做市和模拟成交基础链路此前已做过生产端到端验证；最新改造将内部订单统一设为 `Demo=1`。
9. Robot 最新提交 `655235b`：报价、扫单、模拟成交订单均通过 `markInternalDemo()` 设置 `Demo="1"`；外部 Binance 对冲请求仍为 `Demo="0"`。Robot 单元测试 38/38 通过（JDK 17）。
10. 部署仓库最新提交 `540058c`：持续观察脚本改为通过 GW 查询 Robot 活动委托，不再依赖订单库观察 Robot 内部挂单，并断言 Robot 活动订单不落库。
11. 独立 SaaS Docker Compose、公共 GHCR 镜像、一键安装/卸载、自动更新和回滚框架已经存在，可与量化系统使用不同 Compose project、端口和数据目录共存。
12. 已有一次压力测试基线：3000 请求、32 并发，约 208.6 req/s，p99 约 381 ms。该结果仅代表当时单机测试场景，不是交易所级容量结论。

## 4. 未完成事项（接手开发主清单）

### P0-A：先封闭当前 Robot Demo 改造

状态：代码已提交并推送，生产部署和证据尚未完成。

责任仓库：`robotsvr`、`deploy`、`ordersvr`、`mdsvr`、`trade-web`。

需要完成：

1. 构建并部署 RobotSvr `655235b` 对应公共镜像。
2. 更新仍依赖 `dc_orders` 查 Robot 挂单的一次性脚本 `run-robot-liquidity-e2e-host.sh`，统一改用 GW `queryOpenOrder` 观察活动挂单。
3. 验证 Robot 内部 20+20 活动报价持续存在，Web/MDSvr 稳定显示 10+10，不断档、不交叉、不出现异常远价。
4. 验证新增 Robot 报价、扫单和模拟成交不进入 `dc_orders`、`dc_orders_execorders`；真实用户订单、成交、资金和持仓仍正常落库。
5. 验证重启、断线重连、撤单重挂、行情停止/恢复期间没有残留重复挂单。

验收输出：GW 查询结果、Web 截图、MySQL 证据、Robot/Order/MD 日志和脚本结果。

### P0-B：Robot 完全外置，只访问 GW

状态：未完成；这是当前架构与目标边界之间最明确的缺口。

当前违规依赖：

- `RobotRepository.listRunnable/tryAcquire/heartbeat/release` 直接访问 Robot 配置/租约表。
- `RobotRepository.netPosition` 直接读取持仓。
- `RobotRepository.bestUserOrders` 直接读取用户委托。
- Robot 直接读写 `dc_robot_hedge_execution`。
- Robot 使用 `LOGIN_HTTP_URL` 直连 LoginSvr `/dc/user/getUserByApiKey`。

目标改造：

1. LoginSvr 支持经 GW TCP 登录消息进行 API Key 认证。建议扩展登录参数：`authType=API_KEY`、`apiKey`、时间戳、nonce、签名；GW 仅透传，LoginSvr 验签后返回权威 user/location/角色。
2. Robot 经 GW 拉取自己允许的策略配置、租约和心跳；由 AdminSvr/ManageSvr 提供受限运行时接口，不允许 Robot 自报 location 获得跨租户数据。
3. Robot 经 GW 查询自身活动订单；经 TradeSvr 查询资金/持仓快照，仅用于启动和周期对账。
4. 用户内盘挂单检测改为“该租户 MDSvr 聚合盘口 - Robot 自有活动订单数量”，禁止查询其他用户订单明细。
5. 移除 Robot 镜像中的 JDBC/MySQL 驱动、数据库环境变量和后端直连 URL；CI 加静态检查阻止回归。
6. Robot 本地仅保留加密配置和 append-only 运行日志/对冲幂等流水，不把策略状态写入交易系统数据库。

验收：断开 Robot 到数据库及全部服务端口，只保留到 GW 的网络访问后，报价、撤单、成交感知、重连恢复和对冲仍能运行。

### P0-C：Robot 实时成交驱动真实对冲

状态：未完成。

当前实现按报价周期轮询 MySQL 持仓，再与 `dc_robot_hedge_execution` 比较后对冲；这既违反 GW-only，也不能保证低延迟、幂等和重启恢复。

需要完成：

1. OrderSvr/TradeSvr 经 GW 发布 Robot 自有订单执行回报私有 topic，包含 location、账户、symbol、orderId、execId、side、lastQty、lastPx、cumQty、状态和服务端序列号。
2. Robot 对 `execId` 幂等处理，每笔成交立即更新净暴露并触发 Binance 反向对冲。
3. 本地 append-only hedge journal 原子记录 `execId -> hedge clientOrderId -> 请求/未知/成功/失败/补偿`，重启后先恢复再继续。
4. 超时不能直接重试下单，必须先按 clientOrderId 查询外部状态，防止双重对冲。
5. TradeSvr 持仓查询仅作启动/周期对账，不作为实时触发器。
6. 覆盖全成、部分成交、撤成、拒单、网络超时、返回未知、Binance 限流、Robot 重启、GW 重连和重复消息。

验收：用受限小额专用账户执行真实对冲；证明每个内部 `execId` 最多对应一次外部净对冲，最终暴露和外部仓位可对账。

### P0-D：真实资金账务正确性

状态：基础资金/持仓可用，生产级账本未完成。

责任仓库：`tradesvr`、`liqsvr`、`dbscripts`、`deploy`。

需要完成：

1. 建立不可变双重记账总账，所有余额变化必须有业务单号、借贷分录、币种、location、账户和幂等键。
2. 将关键资金/持仓更新与 outbox 事件放在同一数据库事务，替换关键路径的纯内存异步队列。
3. 建立余额、持仓、成交、资金费、强平、保险基金、ADL 的持续对账与差异告警。
4. 完成失败恢复、消息重复、乱序、服务重启、数据库短暂不可用时的一致性测试。
5. 真实充值/提现、钱包、KMS/HSM、地址风控、审批、KYC/AML 尚未实现；当前“添加资金”只能视为测试/运营入金。

### P0-E：多源指数价格与标记价格

状态：当前主要验证了单一 Binance Futures 行情输入，未达到生产抗操纵要求。

责任仓库：`apssvr`、`mdsvr`、`liqsvr`、`tradesvr`。

需要完成：多交易所行情源、加权中位数或稳健聚合、异常/过期源剔除、源不足降级、偏离保护、指数/标记价格质量状态，并把可信标记价格完整贯穿盈亏、保证金、强平、资金费和 Web 展示。

### P0-F：租户隔离的完整证明

状态：登录、管理和主要接口已有权威 location 基线，但全链路攻击矩阵未完成。

责任仓库：除 Robot 外几乎全部服务。

需要验证并修复：

1. OrderSvr、TradeSvr、MDSvr、LiqSvr 的 DAO 条件、缓存 key、锁 key、topic、snapshot、增量消息全部带 location。
2. 用户修改 URL、请求体、WebSocket payload、topic、token/API Key、重放旧消息时不能访问其他租户数据。
3. 同名账户、同 symbol、同 orderId/clientOrderId 在不同 location 下不能碰撞。
4. MDSvr 对 snapshot 做授权；GW 只根据结果决定是否加入订阅，不在 GW 内硬编码 SaaS 规则。
5. 建立自动化双租户/三角色越权测试矩阵，并覆盖暂停租户、禁用品种、超配额状态。

### P0-G：行情和私有流的一致性协议

状态：实时推送可用，交易所级断档恢复未完成。

责任仓库：`mdsvr`、`ordersvr`、`tradesvr`、`gateway`、`trade-web`、`robotsvr`。

需要完成：服务端单调序列号、snapshot 起始序列、delta 前后序列、客户端 gap 检测、自动重订阅、重复/乱序过滤、断线补偿；盘口、成交、K 线和私有订单/成交/资金流都要覆盖。

### P0-H：高可用、灾备和安全

状态：单机 Docker 部署可用，生产高可用和完整安全体系未完成。

需要完成：

- MySQL、ClickHouse、ZooKeeper 的高可用与备份/PITR；定期恢复演练并定义 RPO/RTO。
- OrderSvr 撮合分区单写、热备/故障转移、订单簿重建和事件回放。
- TLS/域名证书、Secret 管理、2FA、平台/租户 RBAC、API 限流、防刷/WAF、审计、镜像与依赖漏洞扫描。
- SaaS 与量化系统的端口、网络、Compose project、数据卷、自动更新和卸载边界证明。

### P1-A：完整交易规则和账户模式

状态：已有核心基线，以下仍需补齐或做系统性验收。

责任仓库：`ordersvr`、`tradesvr`、`liqsvr`、`adminsvr`、`trade-web`。

1. 完整单向/双向持仓模式。
2. 全仓/逐仓保证金以及模式切换限制和资金划转。
3. Unified Account 或明确不支持时的产品边界。
4. 追踪止损：激活价、回调率、触发源、下单失败补偿。
5. Close on Trigger、完整 SMP 分组与模式、每用户/品种活动委托上限。
6. 维护保证金阶梯、风险限额、最大杠杆和强平价展示在所有边界条件下一致。
7. 市价保护、PostOnly、IOC/FOK/GTC、ReduceOnly、TP/SL/OCO、幂等、防自成交继续做交叉组合和异常恢复测试。

### P1-B：性能与容量

状态：只有单机阶段性压测结果。

需要完成：symbol/location 分片、撮合单写分区、队列和背压、慢消费者隔离、批量持久化、容量模型、SLO/告警；分别测试下单、撤单、撮合、行情 fan-out、资金结算、强平风暴和多租户噪声邻居。目标值必须由产品明确，不能把现有 208.6 req/s 当生产目标。

### P1-C：SaaS 商业化控制面

责任仓库：`managersvr`、`adminsvr`、`loginsvr`、`trade-web`、`dbscripts`。

需要完成：自定义域名/TLS、套餐和计费、用户数/品种数/API Key 数/下单速率/存储配额硬限制、2FA、细粒度 RBAC、敏感导出审批、平台管理员职责分离、跨租户健康/容量视图和灰度发布。

### P1-D：Web 生产化

责任仓库：`trade-web`、`mdsvr`、`adminsvr`。

需要完成：

1. 继续按 Bybit 的信息密度和交互体验优化，但不能复制受版权保护的素材或品牌。
2. 桌面/平板/手机完整响应式操作；触摸拖动、下单、撤单、历史查询和键盘无障碍。
3. 盘口进度条、买卖盘固定布局、K 线涨跌色、首屏居中、实时跳动、历史加载和 resize 稳定性回归。
4. 统一 loading/error/empty/reconnect 状态，避免空白界面和静默失败。
5. 长时间 WebSocket 运行的内存、CPU、重连和序列恢复测试。
6. 普通交易登录/注册、租户登录、平台登录必须继续保持独立入口；登录后提供明确登出。

### P1-E：最终全量验收和文档

状态：现有 Word/Markdown 报告早于最新 Robot 改造，不能作为最终交付。

需要完成：

1. 最终版本部署后执行功能、规则、并发、压力、24/72 小时长稳、断网/重启/数据库故障/消息重复乱序等测试。
2. 至少覆盖两个 location、普通用户/租户管理员/平台管理员、Robot、强平、ADL、资金费、订阅越权。
3. 完成最新 Web 桌面和手机截图、数据库/ClickHouse 证据、日志证据和测试原始结果。
4. 输出最新版产品业务规则、全链路数据流、运维手册、用户手册、测试报告和 Word 交付文档。
5. 资金费修复需要观察至少一个完整结算周期没有新增非边界重复记录；历史重复资金流水如何处理必须由项目所有者授权，禁止开发者自行冲正。

## 5. 推荐接手顺序

1. **封闭 Robot Demo 变更**：部署 `655235b`，改完一次性测试脚本，收集 GW/Web/MySQL 证据。
2. **Robot GW-only**：先做 API Key 经 GW 登录，再做配置/租约、活动订单、持仓快照全部经 GW，最后删除 JDBC 和直连 URL。
3. **实时成交对冲**：私有 execution topic、本地幂等 journal、真实小额 Binance 对冲全场景。
4. **账务与行情生产化**：不可变账本/outbox/对账，多源指数与标记价格。
5. **租户隔离和消息一致性**：自动攻击矩阵、序列号、snapshot+delta 恢复。
6. **规则、性能、HA、安全**：完成 P1 规则、容量、灾备和安全基线。
7. **Web 与 SaaS 控制面**：完成生产化交互、移动端、配额/RBAC/计费。
8. **最终统一部署验收**：干净安装、升级、回滚、卸载、长稳、报告与 Word 文档。

每一步都应做到：代码与测试一起提交；提交后推送目标分支；镜像使用不可变 digest/tag；测试报告记录 Git SHA、镜像 digest、配置摘要和时间范围。

## 6. GitHub 仓库、当前分支与精确版本

以下信息于 2026-09-03 从本机 Git 元数据重新核对。

| 本地目录 | GitHub 仓库 | 当前开发分支 | 当前 HEAD |
|---|---|---|---|
| `adminsvr` | https://github.com/bliplink/com.app.dc.adminsvr | `saas-crypto` | `9b397d4b857d5ddcb1efc67d7f644a8b88f371b4` |
| `apssvr` | https://github.com/bliplink/com.app.dc.apssvr | `saas-crypto` | `23c31e22da1f805154f7e87175a7d6b0047a4a40` |
| `com.app.dc` | https://github.com/bliplink/com.app.dc | `saas-crypto` | `0597fe4502610534047d6d0913100b5be12a839a` |
| `dbscripts` | https://github.com/bliplink/dbscripts | `saas-crypto` | `f35d859ba399f9688c5c781624cff01c6f8abf6f` |
| `deploy` | https://github.com/bliplink/dc-quant-deploy.git | `saas-crypto` | `540058cb51cc6529113efb06af8570e69ca5ec5c` |
| `gateway` | https://github.com/bliplink/gateway | `saas-crypto` | `6702148f925ccfbb0284ee693c0e384a0375ea61` |
| `gateway-api` | https://github.com/bliplink/gateway-api.git | `3.0.0` | `abb5864ac515a7edea7d4443863fa2c03c7fe7b9` |
| `gw-image` | https://github.com/bliplink/gw.git | `saas-crypto` | `7d201def9b2787c5dccb8e6971a560c2503f0b52` |
| `liqsvr` | https://github.com/bliplink/com.app.dc.liqsvr | `saas-crypto` | `0c0aa56d3cf3c3a1b789afa4dfcbef54c4633880` |
| `loginsvr` | https://github.com/bliplink/com.app.dc.loginsvr | `saas-crypto` | `6a031c17ec2734190a762a35f9312376bd106cd3` |
| `managersvr` | https://github.com/bliplink/com.app.dc.managersvr | `saas-crypto` | `1adf3565a1721abdb570c6d0dc802799aba7fffa` |
| `mdsvr` | https://github.com/bliplink/com.app.dc.mdsvr | `saas-crypto` | `7c98e5fdc5f3a8b8f533832a1e05370de17ca4ab` |
| `ordersvr` | https://github.com/bliplink/com.app.dc.ordersvr | `saas-crypto` | `fe6960a41bbd5c8cf352918b9309ecdb78c9a5bf` |
| `robotsvr` | https://github.com/bliplink/com.app.dc.robotsvr.git | `saas-crypto` | `655235b551220db7a7225344e95207dc4b77ef0e` |
| `trade-web` | https://github.com/SKT-Walter/dc-trade-web.git | `saas-crypto` | `079e1ef87492e4535bbd33824364983496c5d5ef` |
| `tradesvr` | https://github.com/bliplink/com.app.dc.tradesvr | `saas-crypto` | `80a4cb4ee4813471d82e0e2d7f1fb4b6dc785355` |

### 远端可见分支

| 仓库 | 远端分支 |
|---|---|
| adminsvr | `main`, `saas-crypto` |
| apssvr | `feat/ghcr-publish-apssvr`, `fix/salt-formula-config`, `latest`, `main`, `new_0.0.1`, `new_0.0.2`, `saas-crypto` |
| com.app.dc | `0.0.3`, `fix/signal-order-fields`, `main`, `saas-crypto` |
| dbscripts | `main`, `saas-crypto` |
| deploy | `latest`, `main`, `saas-crypto` |
| gateway | `3.0.0`, `feat/ghcr-publish-gw`, `fix/salt-formula-config`, `latest`, `master`, `saas-crypto` |
| gateway-api | `3.0.0` |
| gw-image | `latest`, `main`, `saas-crypto` |
| liqsvr | `main`, `saas-crypto` |
| loginsvr | `latest`, `main`, `saas-crypto` |
| managersvr | `main`, `saas-crypto` |
| mdsvr | `codex/task-title`, `feat/ghcr-publish-mdsvr`, `fix/salt-formula-config`, `latest`, `main`, `saas-crypto` |
| ordersvr | `feature/orderbook-depthdiff-optimization`, `main`, `saas-crypto` |
| robotsvr | `main`, `saas-crypto` |
| trade-web | `main`, `saas-crypto` |
| tradesvr | `main`, `saas-crypto` |

不要继续在 `latest` 上开发 SaaS；它是既有量化系统历史主线。SaaS 代码只合入 `saas-crypto`，除非项目所有者另行决定。

## 7. Git 和工作区注意事项

1. `gateway/saas-crypto` 当前本地 HEAD 与 `origin/saas-crypto` 一致，但 upstream 错误指向 `origin/latest`，所以 `git status` 可能显示 ahead 12。这是跟踪配置问题，不是 12 个未推送提交。接手者可在确认后执行：

   ```powershell
   git -C E:\sourcecode\stc-saas-crypto\gateway branch --set-upstream-to=origin/saas-crypto saas-crypto
   ```

2. `mdsvr/.../Consts.java` 曾因文件时间/换行状态显示修改，但 blob hash 和 `git diff` 没有内容差异。先执行 `git update-index --refresh` 并检查，不要直接 reset。
3. 当前工作区存在构建、崩溃和测试证据文件，例如各服务 `target/`、`hs_err_pid*.log`、`replay_pid*.log`、Web `build/`、`web-build.log`，以及 deploy 下部分失败截图。这些不是已确认源代码变更；不要批量删除、提交或覆盖，先逐个检查。
4. `deploy/docs/evidence` 下有若干未跟踪失败截图，应由接手者判断是纳入测试报告还是保留在本地，不要把失败证据当成功证据。
5. Gateway 公共库修改的发布顺序必须是：`gateway-api/com.app.dc/gateway` Maven 构件发布成功 -> 依赖服务升级版本 -> GW/服务镜像发布。不要只推源码后直接假设镜像含新协议。

## 8. 部署现状和限制

1. 生产 SaaS 部署目录为 `/home/ec2-user/dc-saas-deploy`；量化部署目录为 `/home/ec2-user/dc-quant-deploy`，二者不能混用。
2. SaaS 使用独立 Compose project/container 前缀 `dc-saas`。正式改动前必须核对端口、volume、network、容器名和数据目录，不得影响量化系统。
3. 最新 Robot `655235b` 在本次交接前尚未完成生产部署验收；不要宣称“Demo 不落库已在生产验证”。
4. 生产 Robot 真实 Binance 对冲此前未验证，配置曾为 `hedge_enabled=0`；启用前必须使用专用小额账户、限额、熔断和人工监控。
5. 所有 GHCR 镜像目标是 public，无需 `docker login`。仍需做一次最新全量干净安装、自动更新、回滚和不影响量化的一键卸载证明。
6. 不要把服务器地址、SSH 私钥路径、私钥口令、Web 用户密码、数据库密码和 Binance Key 写入 Git、镜像或测试报告。

## 9. 接手者开始工作前的核对命令

```powershell
$root = 'E:\sourcecode\stc-saas-crypto'
Get-ChildItem $root -Directory | ForEach-Object {
  if (Test-Path (Join-Path $_.FullName '.git')) {
    git -C $_.FullName status --short --branch
    git -C $_.FullName remote -v
  }
}
```

对每个仓库先 fetch，再确认目标分支和 HEAD；不得使用 `git reset --hard` 或覆盖用户未提交文件。修改应按单一职责拆分提交，并在提交信息中包含服务和业务目的。

推荐首先阅读：

- `deploy/docs/ROBOT_EXTERNAL_STRATEGY_ARCHITECTURE_20260902.zh-CN.md`
- `deploy/docs/BINANCE_BYBIT_ROADMAP.zh-CN.md`
- `deploy/docs/CORE_TRADING_ACCEPTANCE_20260828.zh-CN.md`
- `deploy/docs/USER_GUIDE.zh-CN.md`
- MDSvr/GW 行情链路改造和稳定性说明文档

## 10. “完成”的统一判定

任何事项只有同时满足以下条件才算完成：

1. 代码和自动化测试已提交并推送到正确 GitHub 分支。
2. 对应公共镜像已构建，可由部署脚本匿名拉取，镜像 digest 有记录。
3. 在目标环境按一键脚本部署，并通过正常、边界、异常、重启和回归测试。
4. Web、GW/服务日志、MySQL/ClickHouse 数据和测试脚本证据互相一致。
5. 不引入跨租户访问、Robot 直连数据库、真实资金异步丢失、重复对冲或影响量化系统等回归。
6. 文档明确记录 Git SHA、配置、测试时间、已知限制和未覆盖风险；不能用“代码已写”代替“生产已验收”。
