# Rate limits

The GW currently applies a token bucket **per API session (`sessionId`)** to business requests. It is not currently a separate bucket per IP, API key, user, Broker, or method. The profile is part of the authoritative session snapshot returned at login.

| Session | Profile | Refill | Burst |
| --- | --- | ---: | ---: |
| Trader key | `TRADER_STANDARD` | 100 requests/s | 30 |
| Broker key | `TRADER_STANDARD` | 100 requests/s | 30 |
| Tenant/service key | `TENANT_STANDARD` | 20 requests/s | 10 |

The current implementation charges one token for each limited business request; per-method weights and a dedicated Broker profile are not implemented. A rejected request returns `10003 RATE_LIMIT_EXCEEDED`. Back off instead of retrying immediately, and use the realtime stream for high-frequency market data rather than polling HTTP.

These values describe the current limiter, **not** a performance or availability SLA. The [complete Chinese rate-limit reference](/zh/api/RATE_LIMITS.zh-CN/) covers edge cases.
