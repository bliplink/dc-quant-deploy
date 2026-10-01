# 快速开始

准备 API Key、Secret、租户 `location` 和所属环境的 GW HTTP 地址。Secret 只能留在受控后端，不要写进浏览器或日志。完整的签名 Python 示例、行情/订单/账户请求体见[中文快速开始全文](openapi/QUICK_START.zh-CN.md)。

1. 对**实际发送的原始 JSON body + expiry** 计算 `HEX(HMAC-SHA256(secret_key, UTF8(raw_http_body + expiry)))`；`expiry` 为毫秒时间戳。
2. 向 GW 的 `POST /api` 发送 `LoginSvr/apiKeyLogin`，Header 携带 `apikey`、`expiry`、`signature`。
3. 保存返回的 `sid` / `token`、权威 `user_id`、`location`、`client_type`、权限快照与限流 profile。
4. 后续用 `POST /httpapi/` 和 `sessionId` Header 查询行情、下单、查询活动单/资产/持仓。
5. `code=0` 仅表示本次请求受理；订单最终状态要通过查询或私有事件确认。写请求超时后先按原 `ClOrdID` 核对，不可盲目重发。

下一步可查看[认证与权限](authentication.md)、[Trader API](trader.md)、[Broker API](broker.md)及[由 YAML 生成的方法目录](openapi/CATALOG_GENERATED.md)。
