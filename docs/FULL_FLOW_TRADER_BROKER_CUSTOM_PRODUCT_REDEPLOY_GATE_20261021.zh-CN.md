# 2026-10-21｜全新租户→自定义产品→Python Trader/Broker 实盘模拟端到端验收

## 目标与操作边界

用户授权：旧 Demo 恢复困难时可以重新部署，用全新租户验证注册/审批、Robot Maker/Tape、Broker 代客、Trader、数据源/自定义产品、资金、持仓、委托、成交、私有 WebSocket 事件和最终一致性。

本轮没有跳过 Trade 严格复制，也没有伪造/补写资金、持仓或订单数据。真实下单必须记录确定的结果；入金结果未知时不得自动重试。

## 已执行的新租户完整脚本

复用 `tests/test-custom-product-live-e2e.py --execute --with-traders --sdk-signed --verify-private-streams --near-simultaneous`，以真实 Demo 端口 33002 执行，全新租户 `IU526F`。

完成：租户自动审批、TenantAdmin 登录、创建并绑定自定义价格源与 BTC003USDT 产品、匿名查到 2 产品、跨租户隔离、替换另一价格源（单当前绑定）、Broker Key 签发与签名登录、Python SDK Broker 签名登录、Broker 发布自定义价格返回 `SDK_ACCEPTED`、Maker 签名 Trader 登录。

失败：后续 Trader 网关调用返回 `OpenTradingCoreError Gateway request failed`，没有继续执行双交易员真实撮合、成交、私有事件和最终权威一致性。随后 Tenant Trial 自动入金工作流 `IU526F` 记录 `FUND/NEEDS_RECONCILIATION`、错误码 `DEMO_CASH_OUTCOME_UNKNOWN`。MySQL `dc_users_cash_log` 没有该租户 cash 记录，但**这不能证明 Trade 内存/日志未应用入金**，不得盲目再次调用 cashIn/cashOut。

## Trade 复制阻断证据

- TradeSvrA/B 反复报 `Trade strict commit PAUSED: no live current-epoch physical replica partition=Pxxx`，以及 `queryTradePosition/fetchCommittedTradeProjectionEvents: PARTITION_NOT_READY`。Robot 也反复遇到持仓读取故障。严格复制拒绝服务不应该被绕过。
- 通过带 ZooKeeper 客户端身份的只读查询检查全部 256 分区：`state=READY`、128 个 A Primary/B Replica、128 个 B Primary/A Replica、`epoch=1`，但是这只是**分配元数据**，不足以证明最新同代物理副本及业务 READY。
- P008/P012/P059 等分区在 A/B 皆存在 Snapshot 文件，仍不能据此推断完整 WAL 物理 ACK 或权威一致性。现网恢复开关在 A 禁用了多个 Source/Stage/Install/AutoWarm 机制，B 多处仅 pilot P090，尚没有全量收口。

## 清洁重部署行动与安全限制

- 当时 Demo 24 个运行镜像已逐一固定，Trade 的 `TradeEmptyGenesisBootstrap.java` 已用当前真实 Trade 镜像 Java 8 类路径编译通过。
- 检查发现仓库根目录 `.env.prod` 的 `DEPLOY_ROOT` 与**实际 Docker bind mount** 根目录不一致。因此制作了本地保护的专用环境文件 `.work/fresh-fullflow-20261021/.env.fresh`（0600，**绝不提交 Git**），固定运行镜像与正确 root。
- 正常 `docker compose down` 曾停止当前 SaaS 项目，旧业务数据**未删除、未移动**。后续将数据隔离为全新运行环境的操作被执行环境拦截；没有绕开安全检查执行文件删除、重命名或初始化新数据库。
- 已用固定的原 24 镜像、原运行数据恢复 `docker compose up`，四个网站入口和原租户保留；再次恢复 AdminSvr 的新租户 `market-maker/tape-trader` 命名 cutover。MySQL 记录现有 46 租户。该状态是**原 Demo 恢复运行**，绝不是新数据库重新安装成功或 Trade 故障已修复。

## 顺利完成的独立修复：Python SDK 0.1.9

- 0.1.8 统一客户端匿名 `public_products()` 错读 `self.credentials.location`，匿名 `Credentials=None`；已修复为使用 `PublicMarketClient`，且不附带敏感鉴权头。新增单测后 45/45 PASS。
- 源码 `bliplink/opentradingcore-api-docs` 分支 `codex/python-realtime-methods-sdk-017-20261020`，提交 `37e80d8`。
- 基于已验证静态 MkDocs 镜像仅叠加 0.1.9 Wheel / 源码 Zip 及双语安装链接，保留 0.1.8；容器 `dc-saas-api-docs-1` 健康，公网 `https://api.opentradingcore.com/sdk/opentradingcore-0.1.9-py3-none-any.whl` HTTP 200。本机缺少 Python 3.12 构建镜像且镜像 DNS 不可解析，**没有声称重新跑通完整 MkDocs 构建**。
- 从**已经部署的站点**重新下载 0.1.9 Wheel 并独立安装，通过无 API Key 的真实 Gateway 测试：`IU526F` 列出 2 个产品含 `BTC003USDT`，`GAAKY8` 列出 2 个产品含 `QAA911F381USDT`，两租户 `wait_for_product()` 通过。

## 后续验收门禁与顺序

1. 在有权限的受控 Demo 执行环境，使用隔离根目录的可审计、已预演清洁安装；**只有数据确实归零并完成 Trade Genesis、Order/Trade 真实物理副本 READY 之后**才开始新一轮下单。不能将旧 MySQL 的 46 租户假称为新环境。
2. 完整跑 `tests/test-custom-product-live-e2e.py --execute --with-traders --sdk-signed --verify-private-streams --near-simultaneous`，从**新** tenant 创建，验证 Broker 代客账号、入金、Maker/Taker 成交、Trader SDK 四类私有流、源/品种隔离；保留 CID 和只读 MySQL 权威对账。不得重试结果未知的入金或订单。
3. 分别以**纯 Trader Key**与**租户 Broker Key**测试账户隔离、代客开户、入金、下单撤单、历史、实时账户通知。验证机器人使用独立新名称及 20 买+20 卖、Tape 模式仅真实成交写 K 线。
4. 完成无重复成交/不丢单/资金与持仓权威一致、Trade A/B 真实物理追平与自动切换。之后才可继续 10→50→200 租户稳定压力测试和正式对外生产准入。

本报告明确区分 ①实际执行通过，②实际阻断，③未执行；不以 SDK mock/unittest 替代真实 Broker/Trader 交易验收。
