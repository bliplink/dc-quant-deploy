# Tenant API 集成指南

> 面向租户自建业务系统。  
> Tenant API 的范围高于单一 Trader API，适合开发自己的 SaaS / Broker 产品。

## 1. Tenant API 的定位

租户可以选择：

1. 直接使用 Tenant Web + Trade Web；
2. 自己开发全部前端 / 后端，只使用 DC 交易核心。

Tenant API 服务于第二种模式。

## 2. 可复用平台能力

租户可以按权限使用：

- 用户 / 客户账户；
- API Key；
- 资金；
- 订单；
- 持仓；
- 行情；
- 历史；
- Robot；
- symbol；
- tenant settings。

## 3. Tenant 管理接口

当前 v1 catalog：

- `AdminSvr/tenantUserAdmin`
- `AdminSvr/tenantSymbolAdmin`
- `AdminSvr/tenantRobotAdmin`
- `AdminSvr/tenantSettingsAdmin`
- `AdminSvr/tenantTradeAdmin`
- `AdminSvr/tenantUserRegistration`

租户只能操作自己的 location。

## 4. 交易接口

Tenant 可以为自己管理的交易用户调用统一交易协议：

- placeOrder；
- cancelOrder；
- cancelBatchOrder；
- queryOrder；
- queryOpenOrder；
- queryExecOrder。

交易 schema 与 Trader / Broker 尽量复用。

## 5. 账户接口

包括：

- queryAccountBalance；
- queryTradePosition；
- account config；
- leverage；
- position type。

## 6. Market / Robot

租户可以：

- 使用平台提供的行情；
- 使用平台提供的 Robot；
- 自己开发行情接入；
- 自己开发 Robot。

但无论哪种方式，核心交易仍通过统一 GW / Order / Trade contract。

## 7. 自定义市场扩展

当前先按 Crypto 定义。

未来 FX / 商品 / 债券应通过：

- MarketIndicator；
- SecurityID；
- symbol metadata；
- market-specific configuration

扩展，而不是复制一套新的交易核心。

## 8. API 权限

Tenant key 权限必须显式配置。

不能因为是 Tenant 就默认拥有平台管理员权限。

权限需要覆盖：

- tenant read；
- tenant write；
- market read；
- account read；
- order read；
- order write。

## 9. 与 Broker API 的区别

Tenant API：

- 管整个租户自己的系统；
- 可以管理多个客户 / trader；
- 可以管理 symbol / Robot / settings。

Broker API：

- 更偏 Broker 客户和交易业务；
- 核心目标是 customer lifecycle + customer trading。

两者可以复用底层 method，但文档面向不同客户角色。

## 10. 集成验收

至少验证：

- tenant API key；
- user registration；
- API Key management；
- symbol query / admin；
- Robot query / admin；
- customer/account；
- cash；
- trading；
- history；
- location isolation；
- 权限越权拒绝。


## 11. Rate Limits

TenantAPI session 当前使用：

`TENANT_STANDARD`

默认：

| Parameter | Value |
|---|---:|
| Refill rate | 20 requests / second |
| Burst | 10 |
| Scope | sessionId |

算法为 Token Bucket。

超限返回：

`10003 RATE_LIMIT_EXCEEDED`

profile 非法返回：

`10005 RATE_LIMIT_PROFILE_INVALID`

当前没有接口级 weight。

完整说明：

`docs/api/RATE_LIMITS.zh-CN.md`
