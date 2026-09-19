# DC Broker API v1

当前基线：2026-09-19。

Broker API 面向希望使用 DC 作为交易核心、但自行开发客户系统、Web/App、运营后台和交易前台的租户。

Broker API Key：

```text
type = broker
client_type = TenantAPI
```

默认权限：

```text
MARKET_READ
ACCOUNT_READ
ORDER_READ
ORDER_WRITE
TENANT_READ
TENANT_WRITE
CUSTOMER_CASH
```

默认交易限流基线与 Trader API 一致，使用 `TRADER_STANDARD`。

## 1. Broker 可以做什么

Broker 同时拥有两类能力：

1. Tenant Management：创建/查询/启停本租户客户和其他租户配置；
2. Broker Trading：使用与 Trader 完全相同的交易 API，代表本租户客户进行交易。

另外 Broker 独有客户资金操作：充值、提现。

## 2. 客户生命周期

创建交易客户：

```json
{
  "externalCustomerId": "CUST-100001",
  "username": "client001",
  "name": "Client 001",
  "email": "client001@example.com"
}
```

当前服务端会生成内部 `user_id/customerId`，并初始化：

- TRADER role；
- USDT balance account；
- trading account config；
- tenant enabled symbol config；
- `enable_trade=1`。

租户应保存自己的 `externalCustomerId` 与 DC `customerId` 的映射。后续可以把 `externalCustomerId` 做成正式幂等字段。

## 3. Broker 代客交易

Broker 与 Trader 使用完全相同的交易字段和方法，区别是 Broker 必须指定目标 `customerId/userId`。

例如：

```json
{
  "customerId": "dc-customer-user-id",
  "symbol": "BTCUSDT",
  "side": "BUY",
  "orderType": "LIMIT",
  "quantity": "0.01",
  "price": "60000",
  "timeInForce": "GTC"
}
```

服务端强制：

```text
broker.location == customer.location
```

跨租户 customerId 必须拒绝。

交易能力详见 [Trading API v1](TRADING_API_V1.zh-CN.md)。

## 4. 客户信息

Broker 使用 `TENANT_READ/TENANT_WRITE` 管理客户：

- Create customer；
- List/Get customer；
- Enable/Disable customer；
- Reset customer password；
- 后续扩展 KYC/profile metadata 时仍保持 tenant scope。

管理型 `type=tenant/service` Key 也可以做客户管理，但它们没有交易权限。

## 5. 客户充值 / 提现

只有 Broker Key 的 `CUSTOMER_CASH` scope 可以通过 Open API 对客户执行资金变更。

### Deposit

业务模型：

```json
{
  "customerId": "dc-customer-user-id",
  "currency": "USDT",
  "amount": "10000",
  "externalRef": "DEP-20260919-00001"
}
```

当前运行时映射到 `TradeSvr/cashIn`。

### Withdrawal

```json
{
  "customerId": "dc-customer-user-id",
  "currency": "USDT",
  "amount": "1000",
  "externalRef": "WD-20260919-00001"
}
```

当前运行时映射到 `TradeSvr/cashOut`。

Trader API Key 即使拥有 `ORDER_WRITE` 也不能调用客户充值/提现。

## 6. Broker 与普通 Tenant Key

| 能力 | Tenant/Service Key | Broker Key |
| --- | --- | --- |
| 客户资料 | ✅ | ✅ |
| 租户设置 | ✅ | ✅ |
| 行情 | 可选 MARKET_READ | ✅ |
| 代客户下单/撤单 | ❌ | ✅ |
| 客户订单/成交 | 管理查询 | ✅ Trading API |
| 客户余额/持仓 | 管理查询 | ✅ Trading API |
| 客户充值/提现 | ❌ | ✅ CUSTOMER_CASH |

## 7. 审计模型

交易账户 owner 始终是 customer：

```text
owner_user_id = customerId
location      = tenant
```

Broker Key 是 actor。后续外部审计记录应同时保留：

```text
owner = customerId
actor = broker api key / tenant admin identity
```

这样可以区分“订单属于谁”和“是谁代表客户发送”。
