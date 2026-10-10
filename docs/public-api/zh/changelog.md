# API 文档更新记录

## 2026-10-10 — Trader 账户查询路由说明修正

- `TradeSvr/queryAccountBalance` 与 `TradeSvr/queryTradePosition` 示例现在包含 `key: "YOUR_TENANT_LOCATION"`，该字段仅是网关**分区路由键**，不是账户选择器。
- 交易员的租户、用户身份和权限始终以认证后的 `sessionId` 为准，不允许通过修改 `key` 或 `content` 访问其他账户。本次仅修正参考示例，**没有**宣称新增 API 方法或已通过真实 API Key 全链路验收。

## 2026-10-01 — 中英文开发者预览版

- 现有 Open API v1 契约仍是唯一来源；此次文档发布没有声称新增 GW 方法。
- 中英文总览、快速接入、认证、Trader、Broker、实时订阅、限流、发布状态和方法目录由同一次构建发布。
- 两种语言的 28 方法目录都从同一份已校验 OpenAPI YAML 生成。完整字段级文字参考目前仍主要为中文，英文页面会明确链接到原文。

后续 API 变更需同步更新 OpenAPI YAML 和两种语言的更新记录。双语检查工具会拦截单边指南修改，并要求接口/参考源文件变更时补齐双语说明。
