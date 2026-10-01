# OpenTradingCore 开发者文档

通过 Trader API 为自己的账户编写交易前端或 Robot 策略；通过 Broker API 为同一租户内的客户构建交易所网站和后台。这两种接入都使用 OpenTradingCore GW 的统一请求 envelope，但身份和客户权限边界不同。

!!! warning "开发者预览版，尚未达到 External GA"
    当前环境只使用模拟资金。文档可用于评估和 Demo 接入，但交易稳定性、SDK、外部 WebSocket 和资金幂等性等正式开放门禁尚未完成。不要接入真实资金，也不要把文档站视为生产 SLA。

| 我想做什么 | 从这里开始 |
| --- | --- |
| 用自己的账户交易或写策略 Robot | [Trader API](trader.md)、[快速开始](quick-start.md) |
| 为自己的客户构建 Broker 交易站点 | [Broker API](broker.md)、[认证与权限](authentication.md) |
| 查看 28 个方法、权限和请求 schema | [由 YAML 生成的方法目录](openapi/CATALOG_GENERATED.md)、[下载 OpenAPI YAML](openapi/crypto-openapi-v1.yaml) |
| 处理实时订阅和断线恢复 | [实时订阅](realtime.md) |

当前传输是签名登录 `POST /api`，随后通过 `POST /httpapi/` 发送携带 Session 的请求。不存在每个方法独立的 `/v1/order` REST 路径。`api.opentradingcore.com` **只提供文档**；实际请求应发给所属环境的 GW 地址，公开生产 API 基地址尚未冻结。

此中文站点保留完整的字段级参考。英文站点提供接入路径、关键指南和机器目录；尚未完成的英文字段级翻译会明确标注。查看[发布状态](status.md)。
