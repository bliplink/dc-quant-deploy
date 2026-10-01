# Authentication and identity

Open API v1 uses the GW native request envelope. `LoginSvr/apiKeyLogin` exchanges a signed API key for a short-lived session. Subsequent business calls use the returned session token; there is no separate REST endpoint for each method.

## Signed login

```http
POST {GW_BASE_URL}/api
Content-Type: application/json
apikey: <API_KEY>
expiry: <EPOCH_MILLISECONDS>
signature: <HEX_HMAC_SHA256>
```

Sign `raw_http_body + expiry` with HMAC-SHA256 using the API secret. The `expiry` is in epoch milliseconds. The [quick start](quick-start.md) contains a Python example and the exact login envelope.

```json
{"serverName":"LoginSvr","method":"apiKeyLogin","content":{"api_key":"YOUR_API_KEY","location":"ABC123","cid":"auth-001"}}
```

A successful response has `code: 0` and `data` containing `sid` / `token`, authoritative `user_id` and `location`, `client_type`, `api_key_type`, `permissions`, and `rate_limit_profile`. Keep the token private.

## Session request

```http
POST {GW_BASE_URL}/httpapi/
Content-Type: application/json
sessionId: <TOKEN>
```

The session's `user_id` and `location` are authoritative. Caller-supplied identity fields cannot widen them. Permissions and the rate-limit profile are snapshotted at login. A stale API session lacking a permission snapshot fails closed and must log in again.

| Key type | `client_type` | Typical scope |
| --- | --- | --- |
| Trader | `API` | Own market, account, order and trading operations |
| Broker | `TenantAPI` with `api_key_type=broker` | Authorized customers in the Broker's own `location` |
| Tenant service | `TenantAPI` | Tenant management within its own `location` |

Broker requests must pass server-side customer ownership checks. A `UserID` in the body is not an authorization grant. API keys may also be restricted to an IPv4/IPv6 address or CIDR range.

## Expiry and reconnect

On `9002 USER_SESSION_NOTEXIST`, stop using the old session, perform a new signed login, reconnect HTTP/realtime clients, resubscribe, and query open orders, balance and positions to rebuild state. Do not blindly replay writes whose result is unknown.

Common errors include `7001 API_REQ_HAS_EXPIRE`, `7002 API_SIGN_ERROR`, `7003 API_IP_NOT_ALLOWED`, `9005 AUTHENTICATION_FAILED`, and `10003 RATE_LIMIT_EXCEEDED`. See the [full Chinese authentication reference](/zh/openapi/AUTHENTICATION_REFERENCE_V1.zh-CN/) and [public errors](/zh/DC_OPEN_API_V1_REFERENCE.zh-CN/) for field-level details.
