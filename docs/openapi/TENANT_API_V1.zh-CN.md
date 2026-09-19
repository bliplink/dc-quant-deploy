# DC Crypto Tenant API v1

当前基线：2026-09-19。

本文只描述 **Tenant Management API**：租户自己的管理后台和自动化运维。管理型 Tenant Service API Key 的 Session 类型固定为 `TenantAPI`，但不能下单。

如果租户需要自己开发完整交易系统，并代表名下客户下单/撤单/查询账户/充值/提现，应使用 [Broker API v1](BROKER_API_V1.zh-CN.md)。

## 1. Tenant API 与 Trader API 的边界

Tenant API 是 Control Plane，不是交易账户。

```text
TenantAdmin / TenantAPI
        |
        v
     AdminSvr
 tenant users/symbols/robots/settings/trade query
```

Tenant Service Key 默认 scope：

```text
MARKET_READ,TENANT_READ,TENANT_WRITE
```

普通 Tenant Service Key **不拥有 ORDER_WRITE**。OrderSvr/TradeSvr 会拒绝管理型 TenantAPI；只有 `api_key_type=broker` 的 TenantAPI 才可以按 Broker 规则进入交易接口。

租户自研 Robot 应创建独立交易用户并给该用户创建 Trader API Key，而不是使用 Tenant Service Key 下单。

## 2. Tenant Service API Key 创建

Tenant Service Key 由交互式 `TenantAdmin` Session 通过 LoginSvr `tenantApiKeyAdmin` 创建。

示例：

```json
{
  "serverName": "LoginSvr",
  "method": "tenantApiKeyAdmin",
  "content": {
    "action": "CREATE",
    "label": "tenant-backoffice",
    "permissions": "TENANT_READ",
    "cid": "tenant-key-001"
  }
}
```

服务端固定：

```text
type=tenant
rate_limit_profile=TENANT_STANDARD
```

允许 scope 子集仅为：

```text
MARKET_READ
TENANT_READ
TENANT_WRITE
```

## 3. TenantAPI 登录

Tenant Service Key 与 Trader Key 使用同一 signed GW 入口：

```text
POST /api
serverName=LoginSvr
method=apiKeyLogin
```

成功后返回：

```text
client_type=TenantAPI
user_id=<tenant admin user>
location=<authoritative tenant>
api_key_type=tenant
permissions=...
rate_limit_profile=TENANT_STANDARD
sid/token=...
```

之后 HTTP 使用 `/httpapi/` + `sessionId`；TCP/WebSocket 使用该 Session 连接 GW。

## 4. Tenant Control Plane 方法

| Method | Action | Scope |
| --- | --- | --- |
| `tenantUserAdmin` | LIST | TENANT_READ |
| `tenantUserAdmin` | CREATE/ENABLE/DISABLE/RESET_PASSWORD | TENANT_WRITE |
| `tenantSymbolAdmin` | LIST | TENANT_READ |
| `tenantSymbolAdmin` | ENABLE/DISABLE | TENANT_WRITE |
| `tenantRobotAdmin` | LIST | TENANT_READ |
| `tenantRobotAdmin` | UPSERT/ENABLE/DISABLE | TENANT_WRITE |
| `tenantSettingsAdmin` | GET/AUDIT | TENANT_READ |
| `tenantSettingsAdmin` | UPDATE | TENANT_WRITE |
| `tenantTradeAdmin` | ORDERS/EXECUTIONS/POSITIONS/BALANCES/... | TENANT_READ |

AdminSvr 同时检查：

1. Session 类型必须为 `TenantAdmin` 或 `TenantAPI`；
2. TenantAPI 必须拥有对应 `TENANT_READ/TENANT_WRITE`；
3. 用户仍必须满足实际 TENANT_ADMIN 角色要求；
4. location 强制使用 Session 中的租户，body 不能切换租户。

## 5. Tenant Market Read

带 `MARKET_READ` 的 TenantAPI 可以读取自己租户允许的公共行情。

完整行情 Topic 见：

[WebSocket / Topic Reference v1](WEBSOCKET_TOPICS_V1.zh-CN.md)

TenantAPI 不允许订阅其他租户 location 的市场数据。

## 6. Tenant Trade Query

`tenantTradeAdmin` 是租户管理面的只读交易数据查询，目前 action 包括：

```text
ORDERS
EXECUTIONS
POSITIONS
BALANCES
POSTINGS
LIQUIDATIONS
ADL_EVENTS
ADL_LEDGER
```

这是 AdminSvr 的租户级查询能力，不等价于让 TenantAPI 直接访问 OrderSvr/TradeSvr Trader API。

## 7. Tenant Robot

`tenantRobotAdmin` 用于租户管理 Robot 定义，例如：

- robot_id / robot_name；
- security_id；
- api_user_id / api_key；
- quote_source；
- bid_levels / ask_levels；
- spread / step / order_qty / max_position；
- refresh / stale / deviation / circuit breaker；
- hedge 参数；
- strategy_config。

Robot 实际交易必须使用其绑定交易用户的 Trader API Key。

## 8. 安全、限流和错误

默认 Tenant profile：

```text
TENANT_STANDARD
refill = 20 req/s
burst  = 10
```

Tenant Service Key 同样支持 expiry、IP whitelist、last_used_time 和 GW 公共错误脱敏。

公共错误码见 [字段级调用参考](../DC_OPEN_API_V1_REFERENCE.zh-CN.md#121-open-api-v1-公共错误码白名单)。

## 9. Web 集成

未来 Tenant Web 的“API 文档”入口应链接本 Markdown 生成的静态页面，不复制本文内容到前端源码。这样 API 文档和 CI contract 保持同一份 Source of Truth。
