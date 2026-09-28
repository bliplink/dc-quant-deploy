# DC Developer Portal Structure v1

> 本文定义 DC Open API 静态开发者文档站的导航与页面规范。  
> Markdown / OpenAPI 是 Source of Truth，生成后的 HTML 不是。

## 1. Top-level Navigation

```text
DC Developers
│
├── Getting Started
│   ├── Overview
│   ├── Quick Start
│   ├── Authentication
│   ├── API Key Types
│   ├── Permissions
│   ├── IP Whitelist
│   ├── Rate Limits
│   └── Error Codes
│
├── Market Data
│   ├── Public Market
│   ├── Kline
│   ├── Order Book
│   ├── BookTicker
│   ├── Trades
│   └── WebSocket Market Streams
│
├── Trading
│   ├── Place Order
│   ├── Cancel Order
│   ├── Batch Cancel
│   ├── Query Order
│   ├── Open Orders
│   ├── Executions
│   ├── Leverage
│   └── Position Mode
│
├── Account
│   ├── Balance
│   ├── Position
│   ├── Account Configuration
│   └── Private WebSocket Streams
│
├── History
│   ├── Order History
│   └── Execution History
│
├── Broker
│   ├── Broker Overview
│   ├── Create Customer
│   ├── List / Manage Customers
│   ├── Deposit
│   ├── Withdraw
│   ├── Place Order for Customer
│   ├── Cancel Customer Order
│   ├── Customer Open Orders
│   ├── Customer Balance
│   ├── Customer Position
│   ├── Customer History
│   └── Customer Private Streams
│
├── Tenant Management
│   ├── Tenant Service API Key
│   ├── Users
│   ├── Symbols
│   ├── Robots
│   ├── Settings
│   ├── Audit
│   └── Tenant Trade Query
│
├── WebSocket
│   ├── Connection
│   ├── Authentication
│   ├── Public Topics
│   ├── Private Topics
│   ├── Snapshot / Delta
│   ├── Gap Recovery
│   └── Reconnect
│
└── SDK
    ├── Java
    ├── Python
    ├── JavaScript / TypeScript
    └── Go
```

## 2. Current Source Files

### Getting Started / Security

- `AUTHENTICATION_REFERENCE_V1.zh-CN.md`
- `../api/RATE_LIMITS.zh-CN.md`
- `../DC_OPEN_API_V1_REFERENCE.zh-CN.md`

### Trading / Account

- `CORE_TRADING_REFERENCE_V1.zh-CN.md`
- `TRADING_OPERATIONS_REFERENCE_V1.zh-CN.md`
- `TRADING_API_V1.zh-CN.md`

### Market Data

- `MARKET_DATA_REFERENCE_V1.zh-CN.md`

### Broker

- `BROKER_API_V1.zh-CN.md`
- `BROKER_REFERENCE_V1.zh-CN.md`

### Tenant Management

- `TENANT_API_V1.zh-CN.md`
- `TENANT_MANAGEMENT_REFERENCE_V1.zh-CN.md`

### WebSocket

- `WEBSOCKET_TOPICS_V1.zh-CN.md`

### Machine-readable

- `crypto-openapi-v1.yaml`

## 3. Interface Page Template

每个正式接口页固定使用以下结构：

```text
Title
Summary
Permission
Endpoint / Server / Method
Authentication
Rate Limit
Request
Request Parameters
Identity / Scope Rules
Response
Response Parameters
Async Semantics
WebSocket Relationship
Common Errors
Examples
Client Guidance
```

不能每个接口使用不同结构。

## 4. Rate Limit Display

当前每个接口页统一展示：

```text
Weight: 1
Scope: session
Profile: session rate_limit_profile
```

并链接到统一：

`docs/api/RATE_LIMITS.zh-CN.md`

在 per-method weight 尚未实现前，不允许自行填写不同 weight。

## 5. Identity Display

Trader 页面必须明确：

```text
Session user == account owner
```

Broker 页面必须明确：

```text
Session user == broker actor
Target UserID == authorized customer
Location == broker authoritative location
```

Tenant Management 页面必须明确：

```text
Session location is authoritative
Body location cannot widen scope
```

## 6. Internal Fields

外部 Developer Portal 不应鼓励客户依赖内部实现字段。

例如：

- Demo
- Isdemo
- Terminal
- AlgoName
- internal partition ID
- physical service instance
- journal / snapshot internals

如果当前 runtime contract 仍依赖内部字段：

1. 在技术 Reference 中明确标记为 internal；
2. SDK / façade 负责填充；
3. External GA 前从客户接口中隐藏。

## 7. Friendly REST Façade

当前 v1 真实入口仍是：

```text
POST /api
POST /httpapi/
serverName
method
content
```

未来可以增加：

```text
POST /v1/order
DELETE /v1/order
GET /v1/open-orders
GET /v1/account
...
```

但 REST-friendly façade 只能做协议映射。

禁止在 façade 里重新实现：

- matching
- risk
- balance
- position
- tenant authorization
- order state machine

## 8. Static Site Generation

推荐任一静态工具：

- VitePress
- MkDocs
- Docusaurus

原则：

```text
Markdown + OpenAPI
        |
        v
CI build
        |
        v
static HTML/assets
        |
        v
Developer Portal
```

Web 只链接静态站点：

- Trade Web -> API Docs
- Tenant Web -> Developer / Broker API
- Platform Web -> API / Operations Docs

## 9. Versioning

当前：

`v1`

未来 API breaking change：

```text
v1 remains stable
v2 gets new namespace/docs
```

不要在不改变版本的情况下悄悄改变：

- field meaning
- permission
- identity scope
- order semantics
- error code meaning
- WebSocket recovery contract

## 10. External GA Checklist

External GA 前至少满足：

- OpenAPI schema 与 runtime 一致；
- Trader E2E；
- Broker E2E；
- Tenant Service E2E；
- WebSocket reconnect E2E；
- rate limit E2E；
- public error whitelist；
- customer / tenant isolation；
- Java SDK；
- Python SDK；
- static Developer Portal；
- example credentials / sandbox strategy；
- versioned changelog。
