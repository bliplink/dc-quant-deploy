# DC Open API v1 文档入口

当前基线：2026-09-19。

本目录是 DC Crypto Open API v1 面向外部开发者的 Markdown 文档源。Markdown 是源文件，后续 Web 只需要链接由静态文档工具生成的站点，不应人工维护第二份 HTML 文档。

## 文档入口

- [Trader API v1](TRADER_API_V1.zh-CN.md)：交易员、量化程序、租户自研 Robot 使用。
- [Tenant API v1](TENANT_API_V1.zh-CN.md)：租户后台、租户自动化和 Tenant Service 使用。
- [WebSocket / Topic Reference v1](WEBSOCKET_TOPICS_V1.zh-CN.md)：行情、订单、成交、资金、持仓订阅以及重连/Gap 规则。
- [OpenAPI 3.0 HTTP 传输规范](crypto-openapi-v1.yaml)：机器可读 HTTP envelope / response schema。
- [总体架构与安全基线](../CRYPTO_OPEN_API_V1.zh-CN.md)。
- [字段级调用参考与公共错误码](../DC_OPEN_API_V1_REFERENCE.zh-CN.md)。

## 发布到 Web 的约定

文档使用标准 Markdown、相对链接、稳定标题和代码块，避免依赖 GitHub 私有渲染能力，因此可以直接交给 MkDocs、VitePress、Docusaurus 等工具生成纯静态 HTML。

推荐后续发布链路：

```text
docs/openapi/*.md + crypto-openapi-v1.yaml
                |
                v
        static docs build
                |
                v
       generated HTML/assets
                |
                v
 Trade Web / Tenant Web / Platform Web
       "API 文档" 链接
```

生成 HTML 后应把 Markdown 继续作为 Source of Truth；API 变更先改 Markdown/OpenAPI/CI contract，再重新生成站点，不直接编辑生成后的 HTML。

## 身份边界

- Trader API Key -> `client_type=API`。
- Tenant Service API Key -> `client_type=TenantAPI`。
- Trader API 不能进入 Tenant Control Plane。
- TenantAPI 不能进入 OrderSvr/TradeSvr Trader 交易接口。
- 所有租户/用户身份最终以 LoginSvr Session 为准。
