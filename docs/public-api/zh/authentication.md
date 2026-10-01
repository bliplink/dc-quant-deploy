# 认证与权限

Open API v1 使用 GW 原生 envelope。通过 `LoginSvr/apiKeyLogin` 把签名 API Key 换成 Session；随后在 `POST /httpapi/` 请求头中携带 `sessionId`。签名原文是 `raw_http_body + expiry`，算法为 HMAC-SHA256；`expiry` 是毫秒时间戳。代码示例见[快速开始](quick-start.md)。

| Key 类型 | `client_type` | 权限边界 |
| --- | --- | --- |
| Trader | `API` | 自己的账户、订单和行情 |
| Broker | `TenantAPI`，`api_key_type=broker` | 自己 `location` 内获授权的客户 |
| Tenant 服务 | `TenantAPI` | 自己 `location` 的管理能力 |

Session 返回的 `user_id`、`location`、`permissions` 和 `rate_limit_profile` 是权威快照，请求体不能自行扩大权限。Broker 请求必须通过服务端客户归属校验，不能靠请求中的 `UserID` 越权。API Key 还可设置 IP 白名单。

遇到 `9002 USER_SESSION_NOTEXIST` 时，应重新签名登录、重连、重新订阅并查询活动单/资产/持仓恢复本地状态。不要无限重试过期 Session 或结果不明的写请求。字段、错误码和安全细节见[完整认证参考](openapi/AUTHENTICATION_REFERENCE_V1.zh-CN.md)。
