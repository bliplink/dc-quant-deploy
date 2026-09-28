# DC Authentication API Reference v1

> API Key、签名、Session 和安全策略参考。  
> 当前 v1 使用 GW Native HTTP Transport。

---

# 1. API Key Login

把 API Key 交换为短生命周期 Session。

## Endpoint

```http
POST /api
Content-Type: application/json
apikey: <API_KEY>
expiry: <EPOCH_MILLISECONDS>
signature: <HEX_HMAC_SHA256>
cid: optional-client-request-id
```

## Authentication

Signed API Key。

签名原文：

```text
raw_http_body + expiry
```

算法：

```text
HEX(
  HMAC-SHA256(
    secret_key,
    UTF8(raw_http_body + expiry)
  )
)
```

建议：

```text
expiry = now + 60000ms
```

## Request

```json
{
  "serverName": "LoginSvr",
  "method": "apiKeyLogin",
  "content": {
    "api_key": "0123456789abcdef",
    "location": "ABC123",
    "cid": "auth-000001"
  }
}
```

## Trader Success

```json
{
  "code": 0,
  "msg": "NO_ERROR",
  "data": {
    "client_type": "API",
    "user_id": "500020",
    "location": "ABC123",
    "token": "opaque-session-token",
    "sid": "opaque-session-token",
    "api_key_type": "trade",
    "permissions": "MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE",
    "rate_limit_profile": "TRADER_STANDARD"
  }
}
```

## Broker Success

Broker API Key 当前使用 TenantAPI client type：

```json
{
  "code": 0,
  "msg": "NO_ERROR",
  "data": {
    "client_type": "TenantAPI",
    "user_id": "tenant-admin-user",
    "location": "ABC123",
    "token": "opaque-session-token",
    "sid": "opaque-session-token",
    "api_key_type": "broker",
    "permissions": "MARKET_READ,ACCOUNT_READ,ORDER_READ,ORDER_WRITE,TENANT_READ,TENANT_WRITE,CUSTOMER_CASH",
    "rate_limit_profile": "TRADER_STANDARD"
  }
}
```

## Tenant Service Success

```json
{
  "code": 0,
  "msg": "NO_ERROR",
  "data": {
    "client_type": "TenantAPI",
    "user_id": "tenant-admin-user",
    "location": "ABC123",
    "token": "opaque-session-token",
    "sid": "opaque-session-token",
    "api_key_type": "tenant",
    "permissions": "MARKET_READ,TENANT_READ,TENANT_WRITE",
    "rate_limit_profile": "TENANT_STANDARD"
  }
}
```

## Session Usage

成功登录后：

```http
POST /httpapi/
sessionId: <token>
Content-Type: application/json
```

## Security Rules

- Session 的 `user_id` / `location` 是权威身份；
- 请求 body 不能扩大 identity；
- Session 的 `api_key_type`、`permissions`、`rate_limit_profile` 在登录时生成快照；
- refresh / resume 不能扩大权限；
- 缺失权限快照的旧 API session fail-closed；
- Trader 不能把自己提升为 TenantAPI；
- Broker 不能跨 location。

## IP Whitelist

API Key 支持 IP whitelist。

当前 signed `/api` 入口强制验证：

- IPv4
- IPv6
- 单 IP
- CIDR

当前直连部署使用 socket peer，不信任客户端自行提供的代理 header。

## Common Errors

| Code | Msg |
|---:|---|
| 7001 | API_REQ_HAS_EXPIRE |
| 7002 | API_SIGN_ERROR |
| 7003 | API_IP_NOT_ALLOWED |
| 7004 | API_KEY_POLICY_NOT_READY |
| 9005 | AUTHENTICATION_FAILED |
| 9008 | SIGNATURE_VERIFY_FAIL |
| 9018 | API_KEY_LIMIT_REACHED |
| 9019 | NOT_API_USER |
| 9000 | INTERNAL_ERROR |

---

# 2. Session Expiry / Reconnect

遇到：

`9002 USER_SESSION_NOTEXIST`

客户端应：

1. 停止使用旧 session；
2. 重新 signed API Key Login；
3. 获取新 token；
4. 重建 HTTP / WebSocket 身份；
5. 重新订阅 public/private streams；
6. 查询 Open Orders / Balance / Position 重建本地状态。

不要继续无限重试已经失效的 session。

---

# 3. API Key Types

## Trader Key

```text
type = trade
client_type = API
```

常用权限：

- MARKET_READ
- ACCOUNT_READ
- ORDER_READ
- ORDER_WRITE

## Broker Key

```text
type = broker
client_type = TenantAPI
```

Broker 可以同时拥有：

- MARKET_READ
- ACCOUNT_READ
- ORDER_READ
- ORDER_WRITE
- TENANT_READ
- TENANT_WRITE
- CUSTOMER_CASH

## Tenant Service Key

```text
type = tenant/service
client_type = TenantAPI
```

用于管理面，不允许冒充 Trader 调用普通交易接口。

---

# 4. Rate Limit

登录交换完成后，业务 session 使用 GW Token Bucket。

详见：

`docs/api/RATE_LIMITS.zh-CN.md`

当前默认：

```text
TRADER_STANDARD = 100 req/s, burst 30
TENANT_STANDARD = 20 req/s, burst 10
```
