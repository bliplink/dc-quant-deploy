# DC Tenant Management API Reference v1

> 面向租户后台、自动化运维和 Tenant Service API Key。  
> Tenant Management API 是 Control Plane，不是普通 Trader 交易接口。

---

# 1. Tenant Service Identity

Tenant Service API Key：

```text
api_key_type = tenant
client_type  = TenantAPI
```

默认权限域：

```text
MARKET_READ
TENANT_READ
TENANT_WRITE
```

普通 Tenant Service Key：

- 可以调用 AdminSvr Tenant Control Plane；
- 可以读取本租户公共行情；
- 不能作为 Trader 直接进入 OrderSvr / TradeSvr 交易接口；
- 如果租户需要代客交易，应使用 Broker API Key。

当前限流：

```text
rate_limit_profile = TENANT_STANDARD
20 req/s
burst 10
Token Bucket
scope = sessionId
```

---

# 2. Authentication

Tenant Service Key 使用统一 signed API login：

```http
POST /api
apikey: <TENANT_API_KEY>
expiry: <EPOCH_MS>
signature: <HMAC_SHA256>
```

Body：

```json
{
  "serverName": "LoginSvr",
  "method": "apiKeyLogin",
  "content": {
    "api_key": "TENANT_API_KEY",
    "location": "ABC123",
    "cid": "tenant-auth-001"
  }
}
```

成功后：

```text
client_type=TenantAPI
api_key_type=tenant
location=<authoritative tenant>
permissions=...
rate_limit_profile=TENANT_STANDARD
sid/token=...
```

后续：

```http
POST /httpapi/
sessionId: <token>
Content-Type: application/json
```

---

# 3. Tenant Control Plane Security

AdminSvr 每次请求都会检查：

1. Session 必须属于 `TenantAdmin` 或 `TenantAPI`；
2. TenantAPI 必须拥有所需 `TENANT_READ` / `TENANT_WRITE`；
3. 操作者必须实际拥有 TENANT_ADMIN 角色；
4. authoritative `location` 来自 Session；
5. body 中如果提交其它 location，会被拒绝。

因此：

> body 中的 `location` 不是提权字段。

---

# 4. List Tenant Users

## Permission

`TENANT_READ`

## Server / Method

```text
serverName = AdminSvr
method     = tenantUserAdmin
action     = LIST
```

## Request

```json
{
  "serverName": "AdminSvr",
  "method": "tenantUserAdmin",
  "content": {
    "action": "LIST",
    "cid": "users-list-001",
    "location": "ABC123",
    "page_num": 0,
    "page_size": 50
  }
}
```

## Parameters

| Field | Type | Required | Description |
|---|---|---:|---|
| action | enum | No | 默认 `LIST` |
| cid | string | No | 客户端请求 ID |
| location | string | No | 如提交必须等于 Session location |
| page_num | integer | No | 页号 |
| page_size | integer | No | 页大小 |

---

# 5. Create Tenant User

## Permission

`TENANT_WRITE`

## Request

```json
{
  "serverName": "AdminSvr",
  "method": "tenantUserAdmin",
  "content": {
    "action": "CREATE",
    "cid": "user-create-001",
    "request_id": "user-create-idem-001",
    "username": "trader01",
    "password": "strong-initial-password",
    "name": "Trader 01",
    "email": "trader01@example.invalid"
  }
}
```

## Current Fields

```text
cid
action
request_id
location
user_id
username
password
name
email
enable
page_num
page_size
```

---

# 6. Enable / Disable Tenant User

## Permission

`TENANT_WRITE`

支持：

```text
ENABLE
DISABLE
```

示例：

```json
{
  "serverName": "AdminSvr",
  "method": "tenantUserAdmin",
  "content": {
    "action": "DISABLE",
    "user_id": "customer-user-id",
    "request_id": "disable-user-001"
  }
}
```

服务端会根据 action 写入启停状态。

---

# 7. Reset Tenant User Password

## Permission

`TENANT_WRITE`

```json
{
  "serverName": "AdminSvr",
  "method": "tenantUserAdmin",
  "content": {
    "action": "RESET_PASSWORD",
    "user_id": "customer-user-id",
    "password": "new-strong-password",
    "request_id": "reset-pass-001"
  }
}
```

当前 `tenantUserAdmin` 支持 action：

```text
LIST
CREATE
ENABLE
DISABLE
RESET_PASSWORD
```

---

# 8. List Tenant Symbols

## Permission

`TENANT_READ`

## Server / Method

```text
serverName = AdminSvr
method     = tenantSymbolAdmin
action     = LIST
```

## Request

```json
{
  "serverName": "AdminSvr",
  "method": "tenantSymbolAdmin",
  "content": {
    "action": "LIST",
    "cid": "symbol-list-001",
    "location": "ABC123"
  }
}
```

---

# 9. Enable / Disable Tenant Symbol

## Permission

`TENANT_WRITE`

支持：

```text
ENABLE
DISABLE
```

## Request

```json
{
  "serverName": "AdminSvr",
  "method": "tenantSymbolAdmin",
  "content": {
    "action": "ENABLE",
    "cid": "symbol-enable-001",
    "request_id": "symbol-enable-idem-001",
    "location": "ABC123",
    "security_id": "BTCUSDT"
  }
}
```

当前请求 DTO 还包含：

```text
market_indicator
enabled
tick_size
qty_tick_size
min_order_qty
max_order_qty
min_notional
market_take_bound
max_price
maker_commission
taker_commission
funding_interval
risk_tiers
```

但当前公开 Tenant action 只允许：

```text
LIST
ENABLE
DISABLE
```

因此不要把 DTO 中存在的风险/费率字段误解成租户可以自由修改。

---

# 10. List Tenant Robots

## Permission

`TENANT_READ`

## Server / Method

```text
serverName = AdminSvr
method     = tenantRobotAdmin
action     = LIST
```

```json
{
  "serverName": "AdminSvr",
  "method": "tenantRobotAdmin",
  "content": {
    "action": "LIST",
    "cid": "robot-list-001"
  }
}
```

---

# 11. Upsert Tenant Robot

## Permission

`TENANT_WRITE`

## Action

`UPSERT`

## Current Request Fields

```text
robot_id
robot_name
security_id
api_user_id
api_key
quote_source
enabled
bid_levels
ask_levels
level_spread_bps
level_step_bps
order_qty
max_position_qty
refresh_interval_ms
stale_price_ms
max_deviation_bps
circuit_breaker_seconds
hedge_enabled
hedge_venue
hedge_account_ref
hedge_api_key
hedge_api_secret
strategy_config
```

示例：

```json
{
  "serverName": "AdminSvr",
  "method": "tenantRobotAdmin",
  "content": {
    "action": "UPSERT",
    "request_id": "robot-upsert-001",
    "robot_id": "MM-BTCUSDT-01",
    "robot_name": "BTCUSDT Market Maker",
    "security_id": "BTCUSDT",
    "api_user_id": "robot-trader-user",
    "api_key": "robot-trader-key",
    "quote_source": "BINANCE",
    "enabled": true,
    "bid_levels": 10,
    "ask_levels": 10,
    "level_spread_bps": "2",
    "level_step_bps": "1",
    "order_qty": "0.01",
    "max_position_qty": "1",
    "refresh_interval_ms": 500,
    "stale_price_ms": 3000,
    "max_deviation_bps": "20",
    "circuit_breaker_seconds": 30,
    "hedge_enabled": false,
    "strategy_config": "{}"
  }
}
```

### Secret Boundary

`hedge_api_secret` 等敏感字段不能在普通 GET/LIST 响应和日志中明文泄露。

Robot 实际交易必须使用绑定交易用户的 Trader API Key，不使用 Tenant Service Key 直接下单。

---

# 12. Enable / Disable Tenant Robot

## Permission

`TENANT_WRITE`

支持：

```text
ENABLE
DISABLE
```

示例：

```json
{
  "serverName": "AdminSvr",
  "method": "tenantRobotAdmin",
  "content": {
    "action": "DISABLE",
    "robot_id": "MM-BTCUSDT-01",
    "request_id": "robot-disable-001"
  }
}
```

---

# 13. Get Tenant Settings

## Permission

`TENANT_READ`

## Server / Method

```text
serverName = AdminSvr
method     = tenantSettingsAdmin
action     = GET
```

```json
{
  "serverName": "AdminSvr",
  "method": "tenantSettingsAdmin",
  "content": {
    "action": "GET",
    "cid": "settings-get-001"
  }
}
```

当前 Settings DTO：

```text
registration_enabled
trade_enabled
default_locale
branding
```

---

# 14. Update Tenant Settings

## Permission

`TENANT_WRITE`

## Action

`UPDATE`

```json
{
  "serverName": "AdminSvr",
  "method": "tenantSettingsAdmin",
  "content": {
    "action": "UPDATE",
    "request_id": "settings-update-001",
    "registration_enabled": true,
    "trade_enabled": true,
    "default_locale": "zh-CN",
    "branding": "{}"
  }
}
```

---

# 15. Tenant Audit

## Permission

`TENANT_READ`

## Action

`AUDIT`

```json
{
  "serverName": "AdminSvr",
  "method": "tenantSettingsAdmin",
  "content": {
    "action": "AUDIT",
    "page_num": 0,
    "page_size": 50
  }
}
```

---

# 16. Tenant Trade Query

## Permission

`TENANT_READ`

## Server / Method

```text
serverName = AdminSvr
method     = tenantTradeAdmin
```

当前 action：

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

示例：

```json
{
  "serverName": "AdminSvr",
  "method": "tenantTradeAdmin",
  "content": {
    "action": "ORDERS",
    "cid": "tenant-orders-001",
    "user_id": "customer-user-id",
    "security_id": "BTCUSDT",
    "page_num": 0,
    "page_size": 50
  }
}
```

## Query Parameters

| Field | Type | Required | Description |
|---|---|---:|---|
| action | enum | No | 默认 ORDERS |
| user_id | string | No | customer filter |
| security_id | string | No | symbol filter |
| page_num | integer | No | 页号 |
| page_size | integer | No | 页大小，服务端最大 200 |

服务端始终附加：

```text
WHERE location = authoritative session location
```

因此 Tenant 不能查询其它租户交易数据。

---

# 17. Tenant Trade Query Semantics

当前各 action 对应持久化数据域：

| Action | Data |
|---|---|
| ORDERS | durable orders |
| EXECUTIONS | executions |
| POSITIONS | positions |
| BALANCES | balances |
| POSTINGS | cash/account postings |
| LIQUIDATIONS | liquidation deficit records |
| ADL_EVENTS | ADL events |
| ADL_LEDGER | ADL ledger |

Tenant Management API 这里提供的是管理侧只读查询。

它不等于把 Tenant Service Session 直接放进 OrderSvr / TradeSvr Trader API。

---

# 18. Rate Limit

当前 Tenant Service：

```text
TENANT_STANDARD
20 req/s
burst 10
weight = 1/request
scope = sessionId
```

超限：

```json
{
  "code": 10003,
  "msg": "RATE_LIMIT_EXCEEDED"
}
```

详见：

`docs/api/RATE_LIMITS.zh-CN.md`

---

# 19. Common Errors

| Code | Msg | Meaning |
|---:|---|---|
| 9002 | USER_SESSION_NOTEXIST | Session 不存在 |
| 9004 | PARAMETER_ERROR | 参数或 location 冲突 |
| 9007 | CLIENT_TYPE_NOT_SUPPORTED | client type / tenant permission 不允许 |
| 10003 | RATE_LIMIT_EXCEEDED | 超限 |
| 10004 | ACCESS_DENIED | 访问拒绝 |
| 9000 | INTERNAL_ERROR | 脱敏内部错误 |

---

# 20. Current E2E Coverage

当前租户生命周期 E2E 已真实验证：

- TenantAdmin login
- Tenant Service API Key create
- signed TenantAPI login
- TenantAPI 调 AdminSvr user list 成功
- TenantAPI 直接进入 OrderSvr 被拒绝
- TenantAPI 直接进入 TradeSvr 被拒绝
- cross-location tenant request 被拒绝
- symbol LIST / DISABLE / ENABLE
- tenant trade ORDERS query
- tenant settings GET
- tenant suspend / reactivate
- quota enforcement
- two-tenant identity isolation
- database tenant/account/symbol/audit persistence

部署侧入口：

`tests/run-tenant-lifecycle-e2e-host.sh`

---

# 21. External GA Notes

对外发布前还需要继续锁定：

1. 每个 Admin action 的 response schema；
2. Robot secret write-only / mask contract；
3. branding / strategy_config 的 JSON schema；
4. pagination response metadata；
5. request_id 幂等规则；
6. OpenAPI machine schema 中为各 action 建立正式 oneOf schema；
7. Java / Python SDK。

当前 Markdown 只把已经真实存在的 request contract 和安全边界先固定下来。
