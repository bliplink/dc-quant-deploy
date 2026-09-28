# DC Developers

DC Developers 是 DC Core Architecture 对外开发者文档入口。

当前 Open API v1 面向三类集成方：

- **Trader**：普通交易用户、量化程序和自动化策略，只操作自己的交易账户。
- **Broker**：自建网站、App、CRM 或 Broker 后台，管理自己 location 下的客户并代理客户交易。
- **Tenant Service**：租户管理后台和自动化运维，用于 User、Symbol、Robot、Settings 和管理侧交易查询。

## 快速入口

### Trader

如果你是普通 API Trader：

1. 阅读 [Authentication](openapi/AUTHENTICATION_REFERENCE_V1.zh-CN.md)
2. 创建并登录 Trader API Key
3. 阅读 [Core Trading API Reference](openapi/CORE_TRADING_REFERENCE_V1.zh-CN.md)
4. 阅读 [Market Data Reference](openapi/MARKET_DATA_REFERENCE_V1.zh-CN.md)
5. 阅读 [WebSocket Topic / Recovery Contract](openapi/WEBSOCKET_TOPICS_V1.zh-CN.md)

### Broker

如果你要把 DC 作为 Broker 交易核心：

1. 阅读 [Broker API Overview](openapi/BROKER_API_V1.zh-CN.md)
2. 阅读 [Broker API Reference](openapi/BROKER_REFERENCE_V1.zh-CN.md)
3. 完成 Customer / Deposit / Trading / Position / History 接入
4. 必须验证 location/customer 隔离
5. 使用 private streams 跟踪客户实时订单与成交

### Tenant Service

如果你在开发租户自己的管理后台：

1. 阅读 [Tenant API Overview](openapi/TENANT_API_V1.zh-CN.md)
2. 阅读 [Tenant Management Reference](openapi/TENANT_MANAGEMENT_REFERENCE_V1.zh-CN.md)
3. 使用 Tenant Service API Key 调用 AdminSvr Tenant Control Plane

## 当前真实 HTTP 入口

Open API v1 当前继续复用 GW 原生传输：

```text
POST /api
POST /httpapi/
```

请求使用统一 envelope：

```json
{
  "serverName": "OrderSvr",
  "method": "placeOrder",
  "content": {}
}
```

我们不会为了让文档看起来像其它交易所而虚构尚未实现的 `/v1/order` 等 REST URL。

未来可以增加 REST-friendly façade，但它只做协议映射，不重新实现撮合、风险、账户、持仓或租户权限。

## Rate Limits

当前 GW 已实现 Token Bucket：

| Key Type | Profile | QPS | Burst |
|---|---|---:|---:|
| Trader | TRADER_STANDARD | 100 | 30 |
| Broker | TRADER_STANDARD | 100 | 30 |
| Tenant / Service | TENANT_STANDARD | 20 | 10 |

当前每个 session business request 统一消耗 1 token。

详见 [Rate Limits](api/RATE_LIMITS.zh-CN.md)。

## WebSocket

实时行情与私有交易状态通过 GW WebSocket / Topic 提供。

文档已经定义：

- Public market topics
- Order / execution private topics
- Account / position private topics
- Broker customer topics
- Depth snapshot + diff
- Gap recovery
- Session reconnect
- Private state rebuild

详见 [WebSocket Topic / Recovery Contract](openapi/WEBSOCKET_TOPICS_V1.zh-CN.md)。

## Source of Truth

机器可读规范：

`docs/openapi/crypto-openapi-v1.yaml`

文档原则：

```text
implementation
 -> tests
 -> OpenAPI schema/catalog
 -> Markdown reference
 -> static Developer Portal
```

生成后的 HTML 不是 Source of Truth。

## External GA 状态

当前接口已经覆盖 Trader、Broker、Tenant Service 的核心合同和真实 E2E，但 External GA 前仍需要继续完成：

- Java SDK
- Python SDK
- OpenAPI method-specific machine schemas
- Broker cash/customer 幂等合同进一步锁定
- WebSocket SDK 自动重连与 Gap recovery
- static Developer Portal CI 验证
- sandbox / demo credentials strategy
- versioned changelog
