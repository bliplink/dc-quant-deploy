# DC Open API Sandbox / Demo Strategy

> 本文定义未来对外 Developer Sandbox 的边界。当前内部 E2E fixture 不等于正式客户 Sandbox。

## 1. Sandbox 目标

外部开发者需要一个不会影响生产资金和真实客户的环境，用于：

- API Key 登录
- Market Data
- Place / Cancel Order
- Balance / Position
- Broker customer lifecycle
- Deposit / Withdraw demo flow
- WebSocket
- reconnect
- rate-limit behavior

## 2. 当前状态

当前部署已经有内部 E2E location / customer / robot fixture，用于自动验收。

这些 fixture 的目的：

- 验证部署
- 验证隔离
- 验证 Broker / Tenant API
- 验证交易链

它们**不是**面向外部客户的长期 Sandbox credential。

不得把内部 E2E API Secret 直接放到公开文档或代码仓库。

## 3. Sandbox 与 Production 必须隔离

推荐：

```text
Production
  -> production domain
  -> production tenant
  -> production API keys
  -> real funds / authoritative balances

Sandbox
  -> sandbox domain or explicit sandbox environment
  -> sandbox-only tenant/location
  -> sandbox-only API keys
  -> demo funds
```

Sandbox Key 不能用于 Production，Production Key 不能用于 Sandbox。

## 4. Sandbox Broker

可以提供一个开发者自助 Broker tenant：

- 独立 location
- customer quota
- symbol quota
- demo USDT
- Robot liquidity
- Broker API Key
- Trader API Key

Broker 可以测试：

```text
Create Customer
Deposit demo funds
Place maker/taker order
Cancel
Query orders
Query executions
Query position
Query balance
Withdraw demo funds
WebSocket private streams
Reconnect
```

## 5. Demo Funds

Sandbox 的 cashIn/cashOut 只代表测试账本变更。

必须在 UI / API 文档中明确：

`SANDBOX / DEMO — NO REAL ASSET VALUE`

不能让 Sandbox posting 被误认为真实充值、提现或链上转账。

## 6. Sandbox Rate Limits

Sandbox 应保留和生产相同的算法：

`Token Bucket`

但可以使用独立 profile，例如未来：

`SANDBOX_STANDARD`

具体 QPS 在正式实现前不写死。

开发者仍应能验证：

- 10003 RATE_LIMIT_EXCEEDED
- backoff
- reconnect
- burst behavior

## 7. Credential Issuance

推荐流程：

```text
Developer registration
 -> create sandbox tenant/account
 -> generate API Key + Secret
 -> secret shown once
 -> optional IP whitelist
 -> developer stores secret
```

Secret：

- 不在后续 LIST API 中返回
- 不写日志
- 不嵌入前端源码
- 可以 rotate / revoke

## 8. Sandbox Market Data

可以选择：

1. 跟随真实外部行情但只在 Sandbox 撮合；
2. 使用固定测试行情 / Robot。

如果复用真实 Binance reference market，也必须明确：

- Sandbox order 不会发送到 Binance
- Sandbox balance 是 demo balance
- 只有明确配置 hedge 的内部 Robot 才可能使用外部 venue

External Sandbox 默认不启用真实资金或真实外部交易。

## 9. Reset Strategy

Sandbox 数据需要可重置：

- reset customer
- reset orders
- reset positions
- reset demo balances
- rotate API Key

但 reset 必须是显式管理操作，不能偷偷改变 Production 风格接口语义。

## 10. Sandbox 文档要求

Developer Portal 后续应显示：

- Sandbox Base URL
- Production Base URL
- Sandbox WebSocket endpoint
- 如何获得 sandbox credentials
- demo funding
- rate limits
- reset behavior
- 数据保留周期

这些 URL 在真正部署前保持 `TBD`，不能提前虚构。
