# Quick start

This guide uses a Trader API key to log in, read a market, place one demo order, and reconcile its state. Use a disposable demo account. `api.opentradingcore.com` serves **documentation only**; send API requests to the GW HTTP base URL assigned to your environment. A public production API base URL has not yet been frozen.

## 1. Prepare credentials

You need an API key, its secret, the tenant `location`, and a reachable GW HTTP base URL. A typical Trader key has `MARKET_READ`, `ACCOUNT_READ`, `ORDER_READ`, and `ORDER_WRITE` permissions. Keep the secret on your backend, never in browser code or logs.

## 2. Sign the exact login body

The signature is `HEX(HMAC-SHA256(secret_key, UTF8(raw_http_body + expiry)))`. `expiry` is an epoch-millisecond timestamp; `now + 60000` is the documented example. Sign the exact bytes you will send. Reformatting JSON after signing invalidates the signature.

```python
import hashlib
import hmac
import json
import time

api_key = "YOUR_API_KEY"
secret = "YOUR_SECRET"
location = "ABC123"

body = json.dumps({
    "serverName": "LoginSvr",
    "method": "apiKeyLogin",
    "content": {"api_key": api_key, "location": location, "cid": "auth-001"},
}, separators=(",", ":"))
expiry = str(int(time.time() * 1000) + 60000)
signature = hmac.new(
    secret.encode("utf-8"), (body + expiry).encode("utf-8"), hashlib.sha256
).hexdigest()
```

Send that `body` to `POST {GW_BASE_URL}/api` with `Content-Type: application/json`, `apikey`, `expiry`, and `signature` headers. Save the returned `data.sid` / `data.token`, `data.user_id`, `data.location`, `data.client_type`, `data.api_key_type`, `data.permissions`, and `data.rate_limit_profile`.

## 3. Make authenticated calls

Use `POST {GW_BASE_URL}/httpapi/`, `Content-Type: application/json`, and `sessionId: <token>` for the following envelopes.

Public market query (`MARKET_READ`):

```json
{"serverName":"MDSvr","method":"queryPublicMarket","content":{"location":"ABC123","securityID":"BTCUSDT"}}
```

Limit order (`ORDER_WRITE`):

```json
{"serverName":"OrderSvr","method":"placeOrder","content":{"SecurityID":"BTCUSDT","MarketIndicator":"4","Side":"BUY","OCType":"OPEN","OrdType":"Limit","TimeInForce":"GTC","OrderQty":"0.001","Price":"60000","ClOrdID":"quickstart-order-000001"}}
```

Open orders (`ORDER_READ`):

```json
{"serverName":"OrderSvr","method":"queryOpenOrder","content":{"securityid":"BTCUSDT","marketIndicator":"4","maxOrderCount":100}}
```

Account balance (`ACCOUNT_READ`):

```json
{"serverName":"TradeSvr","method":"queryAccountBalance","content":{}}
```

`code=0` means the request was accepted; it does **not** prove that the order was filled. Confirm its final state through order queries or the private stream. If a write times out, query by the original `ClOrdID` before retrying; never blindly replay an ambiguous order or cash operation.

## Next steps

Read [authentication](authentication.md), the [Trader guide](trader.md), and the [YAML-derived method catalog](openapi/CATALOG_GENERATED.md). The [full Chinese quick start](/zh/openapi/QUICK_START.zh-CN/) includes additional position and WebSocket examples.
