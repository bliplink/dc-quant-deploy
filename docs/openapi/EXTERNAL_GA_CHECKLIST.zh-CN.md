# DC Open API v1 External GA Checklist

> External GA = 可以把 API 正式提供给外部 Trader / Broker / Tenant 客户。文档完成不等于 GA 完成。

## 1. 当前结论

当前状态：

`NOT YET EXTERNAL GA`

原因不是基础接口缺失，而是仍有若干对外发布门槛需要完成。

## 2. 已完成

### Architecture / Identity

- [x] Trader / Broker / Tenant 角色边界
- [x] location 多租户隔离原则
- [x] Broker actor vs customer owner 模型
- [x] Session authoritative identity
- [x] permission scope
- [x] API Key type separation

### Authentication / Security

- [x] HMAC-SHA256 signed login
- [x] expiry
- [x] IP whitelist
- [x] API Key permission snapshot
- [x] public error whitelist
- [x] internal error sanitization

### Rate Limits

- [x] GW Token Bucket
- [x] TRADER_STANDARD
- [x] TENANT_STANDARD
- [x] Broker current TRADER_STANDARD mapping documented
- [x] rate-limit public errors

### Trading API

- [x] Place Order
- [x] Cancel Order
- [x] Batch Cancel
- [x] Query Order
- [x] Open Orders
- [x] Executions
- [x] Balance
- [x] Position
- [x] Leverage
- [x] Position Mode
- [x] Durable Order / Execution History

### Broker

- [x] Broker signed login
- [x] same-location customer scope
- [x] customer cashIn
- [x] customer cashOut
- [x]代客下单 / 撤单
- [x] customer balance / position
- [x] customer order / execution history
- [x] private execution stream
- [x] foreign tenant customer rejection E2E
- [x] reconnect E2E

### Tenant

- [x] Tenant Service API Key
- [x] User management
- [x] Symbol LIST / ENABLE / DISABLE
- [x] Robot management contract
- [x] Settings
- [x] Audit contract
- [x] Tenant Trade Query
- [x] cross-location rejection

### WebSocket Contract

- [x] public Topic catalog
- [x] private Topic catalog
- [x] Broker customer Topic scope
- [x] depth snapshot + diff
- [x] updateId Gap recovery
- [x] reconnect / state rebuild semantics
- [x] ambiguous write replay warning

### Documentation

- [x] Quick Start
- [x] Authentication Reference
- [x] Market Data Reference
- [x] Core Trading Reference
- [x] Broker Reference
- [x] Tenant Management Reference
- [x] WebSocket Reference
- [x] Rate Limits
- [x] Versioning / Changelog
- [x] MkDocs static portal config
- [x] CI build
- [x] OpenAPI spec validator CI
- [x] OpenAPI catalog coverage CI

## 3. GA Blockers

### P0 — Trading Core Performance

- [ ] OrderSvr 单热点吞吐达到可对外 SLA
- [ ] 解决当前约 16 orders/s 的热点性能瓶颈
- [ ] callback durability batching / 其它真实瓶颈完成验证
- [ ] 1000/16 压测达到正式目标
- [ ] 无假成功 / durable loss

### P0 — Order Cluster Recovery

- [ ] same-epoch restart PARTITION_NOT_READY 根因修复
- [ ] primary/replica restart E2E
- [ ] failover / recovery / snapshot / journal consistency PASS

### P0 — SDK

- [ ] Java SDK
- [ ] Python SDK
- [ ] SDK Trader E2E
- [ ] SDK Broker E2E
- [ ] SDK reconnect E2E
- [ ] SDK rate-limit behavior

### P0 — External WebSocket Transport

- [ ] 冻结公开 WebSocket URL
- [ ] 冻结 raw wire frame schema
- [ ] 冻结 ping/pong / heartbeat contract
- [ ] Java 之外的第三方客户端可以不逆向内部 gateway-api 直接接入

### P0 — Machine-readable OpenAPI

- [x] 28/28 public catalog methods mapped to request schemas
- [x] authentication / API Key management request schemas
- [x] market data request schemas
- [x] trading / account / history request schemas
- [x] Broker cashIn/cashOut request schemas
- [x] Tenant control-plane request schemas
- [x] Broker key type / customer compatibility fields represented
- [x] CI enforces catalog ↔ request-schema coverage
- [ ] method-specific response schemas
- [ ] richer Broker customer ownership constraints represented beyond descriptive fields

### P0 — Broker Cash Idempotency

- [ ] externalRef 正式字段名冻结
- [ ] cashIn 幂等规则
- [ ] cashOut 幂等规则
- [ ] ambiguous network outcome recovery
- [ ] duplicate request E2E

### P1 — Sandbox

- [ ] sandbox environment
- [ ] sandbox domain / base URL
- [ ] sandbox API credentials issuance
- [ ] demo funding
- [ ] reset strategy
- [ ] sandbox documentation

### P1 — Developer Portal Deployment

- [x] static site build
- [ ] public/staging deployment
- [ ] domain
- [ ] TLS
- [ ] API Docs links from Trade/Tenant/Platform Web

### P1 — Operational SLA

- [ ] API availability target
- [ ] request timeout contract
- [ ] rate-limit SLA
- [ ] maintenance policy
- [ ] incident/status page strategy

## 4. Release Gate

只有以下条件同时成立才允许标记：

`DC Open API v1 — External GA`

最低门槛：

```text
core performance PASS
cluster recovery PASS
Trader E2E PASS
Broker E2E PASS
Tenant E2E PASS
Java SDK PASS
Python SDK PASS
external WebSocket contract frozen
OpenAPI schemas aligned
sandbox available
Developer Portal published
security review PASS
```

## 5. 文档发布状态标签

External GA 前 Developer Portal 页面应显示类似：

`Developer Preview`

或：

`Open API v1 — Pre-GA`

不要显示 `Production Ready` / `GA`。

## 6. 当前优先级

接下来工程优先级不应继续无限扩写文档，而应转回：

1. OrderSvr recovery blocker
2. OrderSvr hotspot performance
3. method-specific OpenAPI schema
4. Java SDK
5. Python SDK
6. Sandbox
7. Developer Portal staging deployment
