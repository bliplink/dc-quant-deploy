# Trader API

Trader Key 用于自己的交易账户、自建前端、量化策略 Robot 或风险监控；不需要 Broker 权限，也不能操作其他用户账户。

基本流程：创建最小权限 Trader Key → [签名登录](authentication.md) → 携带 Session 调用 GW → 消费订单状态事件并定期核对查询结果。常用方法包括 `OrderSvr/placeOrder`、`cancelOrder`、`queryOpenOrder`、`TradeSvr/queryAccountBalance`、`queryTradePosition`、`MDSvr/queryPublicMarket` 及 Projection 历史查询。完整 28 方法和权限见[方法目录](openapi/CATALOG_GENERATED.md)。

每个预期订单使用唯一 `ClOrdID`。HTTP 成功只代表请求受理，不能把它当作已成交；超时或断线时先按原订单标识查询再决定是否重试。不要把 Secret 放进浏览器，也不要给普通 Trader `TENANT_WRITE`。

详细字段、订单生命周期和验收要求见 [Trader 使用指南](api/TRADER_API_GUIDE.zh-CN.md)及[交易字段参考](openapi/CORE_TRADING_REFERENCE_V1.zh-CN.md)。
