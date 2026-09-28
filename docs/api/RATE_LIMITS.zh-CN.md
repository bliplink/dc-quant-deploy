# DC Open API Rate Limits

> 本文描述 **当前已经实现并生效的 GW OpenAPI 限流行为**。  
> 规划中的接口权重、Broker 独立 profile 等能力会明确标记为“规划”，不能当作当前生产能力。

## 1. 当前实现概览

GW 已经接入：

`OpenApiRateLimitSecurityCheck`

并且已经加入 GW 的 `securityChecks` 链。

当前算法：

> **Token Bucket（令牌桶）**

当前限流维度：

> **按 API Session（sessionId）建立独立 bucket**

也就是说，同一个 API session 的业务请求共享同一个 bucket。

当前不是按 IP、API Key、UserID、Broker、method 分别计数。

## 2. 当前 Profile

### TRADER_STANDARD

适用于：

`client_type = API`

默认参数：

| Parameter | Value |
|---|---:|
| Refill rate | 100 requests / second |
| Burst capacity | 30 |
| Scope | sessionId |

语义：

- bucket 初始最多 30 个 token；
- 每成功处理一个受限请求消耗 1 个 token；
- 按 100 token / second 的速度补充；
- token 不足时请求被拒绝。

### TENANT_STANDARD

适用于：

`client_type = TenantAPI`

默认参数：

| Parameter | Value |
|---|---:|
| Refill rate | 20 requests / second |
| Burst capacity | 10 |
| Scope | sessionId |

## 3. WEB Session

普通：

`client_type = WEB`

**不进入当前 OpenAPI rate limiter。**

原因：

- Web 产品自己的交互不应和 API Trader 共用同一个 API bucket；
- OpenAPI limiter 只负责开放 API session。

这不代表 WEB 永远没有其它保护机制，只表示它不受 `OpenApiRateLimitSecurityCheck` 这一层约束。

## 4. Signed Login 与业务请求

签名入口：

`POST /api`

当前用途主要是 API Key 登录交换。

Signed `/api` 本身不会消耗业务 session bucket。

成功登录后，客户端获得 session token。

后续业务请求：

`POST /httpapi/`

Header：

`sessionId: <token>`

真正的 OpenAPI rate limit 在这些 session business requests 上执行。

## 5. Profile 来源

LoginSvr 是 session policy 的权威来源。

登录成功后，session policy 包括：

- `client_type`
- `rate_limit_profile`

GW 会缓存：

`sid -> client_type / rate_limit_profile`

如果 GW 重启或登录事件存在 race，GW 可以回查用户 session 信息重新解析 policy。

## 6. 超限错误

### Rate Limit Exceeded

```json
{
  "code": 10003,
  "msg": "RATE_LIMIT_EXCEEDED"
}
```

### Invalid Profile

```json
{
  "code": 10005,
  "msg": "RATE_LIMIT_PROFILE_INVALID"
}
```

客户端遇到 `RATE_LIMIT_EXCEEDED` 时应：

- 降低请求速率；
- 做指数退避或固定短退避；
- 不要立即无间隔重试；
- 对行情查询优先使用 WebSocket，避免 HTTP 轮询。

## 7. 当前每个请求的 Weight

当前 OpenAPI limiter：

> **每个业务请求统一消耗 1 token。**

当前还没有实现 Binance / Bybit 风格的 per-method weight。

因此当前不能在正式客户文档中声明类似：

```text
Place Order       weight = 1
Open Orders       weight = 2
Order History     weight = 5
Kline 1000 bars   weight = 10
```

这些属于后续演进方向，不是当前实现。

## 8. 当前还没有独立 BROKER_STANDARD

当前已实现 profile：

- `TRADER_STANDARD`
- `TENANT_STANDARD`

目前没有独立：

`BROKER_STANDARD`

因此正式 Broker API 上线前，需要根据真实 Broker 压测结果决定：

- 是否增加独立 Broker profile；
- Broker 持续 QPS；
- Broker burst；
- 是否按 customer / API key / broker location 做二级 bucket。

在这些数值正式压测确定前，不应拍脑袋写死。

## 9. 后续规划

参考成熟交易所 API 文档方式，后续可以演进为：

```text
API Key / Session Global Bucket
        +
Per-method Weight
        +
Broker / Customer Scope
        +
Market Data Independent Bucket
```

可能的 profile：

- `TRADER_STANDARD`
- `BROKER_STANDARD`
- `TENANT_STANDARD`
- `MARKET_DATA_STANDARD`

但这些必须先完成：

1. OrderSvr 单热点性能优化；
2. GW / Order / Trade 压测；
3. Broker 真实并发模型压测；
4. 查询类接口成本统计；
5. 下单 / 撤单 / 历史 / Kline 分接口成本评估。

然后再决定正式 weight 与 QPS。

## 10. 客户端建议

Trader：

- 下单和撤单走 HTTP / request-response；
- 高频行情走 WebSocket；
- 遇到 10003 做退避；
- 不要用高频 HTTP 轮询替代 private/public streams。

Broker：

- 多客户并发需要客户端自身做请求队列和速率整形；
- 不要让单个 customer 的突发流量占满整个 Broker session；
- 后续如果引入 BROKER_STANDARD，需要根据 Broker 的客户规模决定 profile。

Tenant：

- 管理类接口和交易类接口建议分 API Key / session；
- 大规模批处理应避免瞬时打满 burst。

## 11. 当前实现来源

GW 当前限流实现：

`com.app.gw.security.OpenApiRateLimitSecurityCheck`

当前 GW Spring 配置中：

- `openApiIngressSecurityCheck`
- `openApiRateLimitSecurityCheck`
- `sqlInjSecurityCheck`

已经共同接入 `securityChecks`。

另有旧的 `LimitSecurityCheck` bean 定义，但当前并未加入实际 `securityChecks` 链，因此 OpenAPI 对外文档应以 `OpenApiRateLimitSecurityCheck` 的行为为准。
