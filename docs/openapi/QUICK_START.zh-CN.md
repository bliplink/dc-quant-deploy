# DC Open API v1 Quick Start

> 目标：用最少步骤完成 API Key 登录、查询行情、下单和查询账户。

## 1. 准备

你需要：

- API Key
- Secret Key
- location
- 可访问的 GW HTTP 地址

Trader Key 默认权限：

```text
MARKET_READ
ACCOUNT_READ
ORDER_READ
ORDER_WRITE
```

## 2. 生成签名

签名原文：

```text
raw_http_body + expiry
```

算法：

```text
HEX(HMAC-SHA256(secret_key, UTF8(raw_http_body + expiry)))
```

推荐：

```text
expiry = current_epoch_ms + 60000
```

### Python 示例

```python
import hashlib
import hmac
import json
import time

api_key = "YOUR_API_KEY"
secret = "YOUR_SECRET"
location = "ABC123"

body_obj = {
    "serverName": "LoginSvr",
    "method": "apiKeyLogin",
    "content": {
        "api_key": api_key,
        "location": location,
        "cid": "quickstart-auth-001",
    },
}

body = json.dumps(body_obj, separators=(",", ":"))
expiry = str(int(time.time() * 1000) + 60000)
signature = hmac.new(
    secret.encode("utf-8"),
    (body + expiry).encode("utf-8"),
    hashlib.sha256,
).hexdigest()

print(body)
print(expiry)
print(signature)
```

注意：签名必须使用**实际发送的原始 body 字符串**。如果签名后又重新格式化 JSON，签名会失效。

## 3. API Key Login

```http
POST /api
Content-Type: application/json
apikey: YOUR_API_KEY
expiry: 1790000000000
signature: YOUR_SIGNATURE
```

Body：

```json
{
  "serverName": "LoginSvr",
  "method": "apiKeyLogin",
  "content": {
    "api_key": "YOUR_API_KEY",
    "location": "ABC123",
    "cid": "quickstart-auth-001"
  }
}
```

成功后保存：

```text
data.user_id
data.location
data.sid / data.token
data.client_type
data.api_key_type
data.permissions
data.rate_limit_profile
```

## 4. 查询公开行情

```http
POST /httpapi/
Content-Type: application/json
sessionId: YOUR_SESSION_TOKEN
```

```json
{
  "serverName": "MDSvr",
  "method": "queryPublicMarket",
  "content": {
    "location": "ABC123",
    "securityID": "BTCUSDT"
  }
}
```

需要权限：

`MARKET_READ`

## 5. Place Order

```json
{
  "serverName": "OrderSvr",
  "method": "placeOrder",
  "content": {
    "SecurityID": "BTCUSDT",
    "MarketIndicator": "4",
    "Side": "BUY",
    "OCType": "OPEN",
    "OrdType": "Limit",
    "TimeInForce": "GTC",
    "OrderQty": "0.001",
    "Price": "60000",
    "ClOrdID": "quickstart-order-000001"
  }
}
```

需要权限：

`ORDER_WRITE`

`code=0` 只代表当前 API 请求成功受理。最终订单状态必须通过订单查询或 private stream 确认。

## 6. Query Open Orders

```json
{
  "serverName": "OrderSvr",
  "method": "queryOpenOrder",
  "content": {
    "securityid": "BTCUSDT",
    "marketIndicator": "4",
    "maxOrderCount": 100
  }
}
```

## 7. Query Balance

```json
{
  "serverName": "TradeSvr",
  "method": "queryAccountBalance",
  "content": {}
}
```

## 8. Query Position

```json
{
  "serverName": "TradeSvr",
  "method": "queryTradePosition",
  "content": {
    "securityid": "BTCUSDT"
  }
}
```

## 9. 接入 WebSocket

推荐顺序：

```text
signed apiKeyLogin
 -> sid/token
 -> connect GW realtime transport
 -> verify user_id/location/client_type
 -> subscribe public/private topics
```

完整 Topic 和恢复规则：

[WebSocket / Topic Reference](WEBSOCKET_TOPICS_V1.zh-CN.md)

## 10. 遇到限流

当前 Trader/Broker 默认：

```text
TRADER_STANDARD
100 req/s
burst 30
```

超限：

```json
{
  "code": 10003,
  "msg": "RATE_LIMIT_EXCEEDED"
}
```

不要立即无间隔重试。高频行情使用 WebSocket，不要用 HTTP 高频轮询替代实时流。

## 11. 下一步

- Trader: [Core Trading API Reference](CORE_TRADING_REFERENCE_V1.zh-CN.md)
- Broker: [Broker API Reference](BROKER_REFERENCE_V1.zh-CN.md)
- Tenant: [Tenant Management API Reference](TENANT_MANAGEMENT_REFERENCE_V1.zh-CN.md)
- Authentication: [Authentication Reference](AUTHENTICATION_REFERENCE_V1.zh-CN.md)
- Errors: [字段级调用参考](../DC_OPEN_API_V1_REFERENCE.zh-CN.md)
