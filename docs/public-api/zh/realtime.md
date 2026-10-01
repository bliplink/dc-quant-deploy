# 实时订阅与恢复

GW 提供公开行情和私有订单/账户 Topic。深度盘口需要初始 image 加有序 diff；发现 `updateId` 缺口时必须重新取快照。Broker 私有 Topic 只能订阅同一 `location` 内获授权客户的数据。

推荐顺序：签名登录 → 使用返回的 `user_id`、`location`、`client_type` 和 `sid/token` 连接 → 校验 GW 返回身份 → 订阅 → 断线后重新登录、重建订阅、查询活动单/资产/持仓。

`placeOrder`、`cancelOrder`、`cashIn`、`cashOut` 等写请求在断线时可能已被接受，不能因为没有收到响应就盲目重放。订单按原 `ClOrdID` 核对，资金按对应流水标识核对。

外部非 Java 客户端使用的 WebSocket URL、原始帧与心跳契约尚未冻结为 External GA。当前已验证行为、Topic 和恢复规则见[完整 WebSocket 参考](openapi/WEBSOCKET_TOPICS_V1.zh-CN.md)。
