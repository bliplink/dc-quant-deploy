# WebSocket 会话恢复设计（暂缓实施）

## 1. 当前阶段决策

- 登录统一使用 WebSocket，经 GW 调用 LoginSvr 完成认证。
- 当前尚未实现服务端 token 恢复协议。浏览器刷新或进程重启后，Web 应回到 URL 所属租户的登录页，不能仅凭浏览器保存的数据恢复认证状态。
- 本阶段优先完成 Robot 报价、下单、撮合、行情、资金、历史查询和 Web 展示闭环；会话恢复列入后续安全改造。

## 2. 无 Redis 的推荐实现

使用 MySQL 持久化一次性轮换的 `resumeToken`。当前 WebSocket 连接的认证身份仍保存在 GW 内存中，只有首次登录、断线恢复、续期、退出和撤销时访问 LoginSvr/MySQL，正常业务请求不查询会话表。

LoginSvr 负责：

- 生成至少 256 位随机 `resumeToken`，数据库只保存 SHA-256/HMAC 哈希。
- 保存 `sessionId`、用户、权威 `location`、角色、客户端类型、设备、版本、过期时间和撤销状态。
- 在一个事务中校验并轮换 token，旧 token 立即失效，防止重放。
- 在退出、修改密码、用户禁用或租户停用时撤销相应会话。

GW 负责：

- 接收 `LOGIN`、`SESSION_RESUME`、`SESSION_REFRESH`、`LOGOUT` 等 WebSocket 消息。
- 调用 LoginSvr 验证后，把 `userId/userName/location/role/clientType` 绑定到新的 WebSocket SID。
- 后续订阅、查询和交易只使用绑定的服务端权威身份，不信任客户端再次传入的用户或租户字段。

Web 负责：

- 首次登录只通过 WebSocket 发送用户名和密码。
- 不保存明文密码；短期凭证仅放内存或 `sessionStorage`。
- 会话恢复功能上线后，持久化 `sessionId + resumeToken`，建立新 WebSocket 后发送 `SESSION_RESUME`。
- URL 中的 `location` 只用于选择租户页面。若 URL location 与服务端会话 location 不一致，清除本地会话并回到该租户登录页。

## 3. 恢复流程

```text
Web 建立新 WebSocket
  -> GW: SESSION_RESUME(sessionId, resumeToken, urlLocation, deviceId)
  -> LoginSvr: 校验 MySQL 会话并事务轮换 token
  -> GW: 使用 LoginSvr 返回的权威用户/location/角色绑定新 SID
  -> Web: 保存新的 resumeToken，恢复私有 topic 订阅和页面数据
```

恢复失败、token 过期、token 已撤销或租户不匹配时，GW 返回明确错误码，Web 清理本地凭证并跳转到 URL 对应租户的登录页。

## 4. MySQL 表的关键字段

建议表 `user_login_session` 至少包含：

- `session_id`、`token_hash`、`token_version`
- `user_id`、`user_name`、`location`、`role_code`
- `client_type`、`device_id`
- `expires_at`、`last_active_at`、`revoked`、`created_at`

唯一索引：`session_id`、`token_hash`；普通索引：`(location, user_id)`、`expires_at`。定时任务清理过期与长期撤销记录。

## 5. 后续验收条件

- 页面刷新、网络短断和 GW 重连后可以恢复同一用户与租户。
- token 只能成功使用一次，轮换前的旧 token 无法重放。
- 修改 URL、topic 或请求体不能切换用户/location。
- 退出、修改密码、禁用用户、停用租户后，已有和保存的会话都不能恢复。
- 多个 GW 实例通过同一 MySQL 能一致地恢复和撤销会话。

