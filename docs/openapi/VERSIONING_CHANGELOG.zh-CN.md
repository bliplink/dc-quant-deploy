# DC Open API v1 Versioning & Changelog

## 1. Versioning Policy

当前公开版本：

`v1`

兼容性原则：

同一个 v1 内不能静默改变：

- 字段含义
- permission 含义
- Trader/Broker/Tenant identity scope
- order 状态语义
- error code 含义
- WebSocket topic 恢复合同
- rate-limit profile 含义

## 2. Breaking Change

以下修改需要新版本或正式迁移周期：

- 删除公开字段
- 修改字段类型
- 把可选字段变成必填
- 修改签名算法
- 修改 customer/location 权限边界
- 修改公开 Topic 名称且不保留兼容期
- 改变订单状态机外部语义

推荐：

```text
v1 remains stable
v2 introduced in parallel
migration window
v1 deprecation notice
v1 retirement
```

## 3. Non-breaking Change

通常可以在 v1 内新增：

- optional response field
- new endpoint/method
- new optional order capability
- new public error code（需要先加入 whitelist/documentation）
- new WebSocket topic

但仍必须同步：

```text
implementation
tests
OpenAPI
Markdown
SDK
changelog
```

## 4. Current Changelog

### 2026-09-28

Developer documentation baseline established:

- Trader / Broker / Tenant API role boundaries
- Authentication Reference
- Core Trading Reference
- Trading Operations Reference
- Market Data Reference
- Broker API Reference
- Tenant Management Reference
- WebSocket topic / recovery contract
- Token Bucket Rate Limits reference
- Broker current rate profile corrected to TRADER_STANDARD 100 req/s, burst 30
- OpenAPI machine catalog includes broker key type and customer cashIn/cashOut
- MkDocs Developer Portal build added
- Developer Portal CI validation added

### 2026-09-19 baseline

- Crypto Open API v1 GW-native transport defined
- signed `/api` login
- session `/httpapi/`
- permission scopes
- public error whitelist
- Tenant Service isolation
- Trader/Broker common trading contract

## 5. Deprecation Notice Requirements

未来任何 deprecated 能力必须在文档中写清：

- deprecated date
- replacement
- migration example
- end-of-support date
- removal version

不得只在代码里删除后再让客户发现。
