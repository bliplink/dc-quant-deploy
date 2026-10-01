# 限流

GW 当前对 Open API 业务请求按 **Session (`sessionId`)** 使用令牌桶；不是按 IP、Key、用户或方法分别计数。限流 profile 由 LoginSvr 在登录时写入 Session 快照。

| Key 类型 | Profile | 补充速率 | 突发容量 |
| --- | --- | ---: | ---: |
| Trader | `TRADER_STANDARD` | 100 请求/秒 | 30 |
| Broker | `TRADER_STANDARD` | 100 请求/秒 | 30 |
| Tenant 服务 | `TENANT_STANDARD` | 20 请求/秒 | 10 |

当前受限业务请求统一消耗 1 token，尚无 per-method weight 或独立 Broker profile。超限返回 `10003 RATE_LIMIT_EXCEEDED`；应退避重试，实时行情不要依靠 HTTP 高频轮询。上述数值是当前限流实现，**不是吞吐或可用性 SLA**。细节见[完整限流参考](api/RATE_LIMITS.zh-CN.md)。
