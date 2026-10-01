# Broker API

Broker 可以自己开发网站、App、客户中心和交易前端，通过统一 GW 接入交易核心，代理**自己 `location` 内获授权客户**的账户和交易操作。Broker 与其他租户/经纪商必须隔离。

Broker Key 同样执行 `LoginSvr/apiKeyLogin`；成功后 Session 为 `client_type=TenantAPI`、`api_key_type=broker`。Broker 仍以自身 actor 身份建立 Session，不能把客户的 `UserID` 当成权限。创建客户、记账入金/出金、代客下单、查询资产/持仓/历史时均需服务端校验 `location`、客户归属和权限。

当前涉及 `AdminSvr/tenantUserAdmin`、`TradeSvr/cashIn` / `cashOut`、`OrderSvr/placeOrder` / `cancelOrder`、账户与 Projection 历史等方法。完整目录见[方法目录](openapi/CATALOG_GENERATED.md)。资金操作的正式幂等和结果不明恢复尚未达到 External GA；Demo 中同样要先查明状态，再处理重试。

Broker 当前限流 profile 是 `TRADER_STANDARD`，不是单独的高 QPS 档位。完整接入流程见 [Broker 使用指南](api/BROKER_API_GUIDE.zh-CN.md)和[字段参考](openapi/BROKER_REFERENCE_V1.zh-CN.md)。
