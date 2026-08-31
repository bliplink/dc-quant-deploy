# WebSocket 会话恢复设计与实现

## 1. 实施结论

会话恢复复用 GW 已有 WebSocket `CONNECT/login` 协议，GW 不增加新方法、不保存新状态，也不写 SaaS 租户逻辑：

- 首次登录：`userName + pwd + authType=PASSWORD`。
- 页面刷新或断线恢复：`userName + pwd=<上一次 token> + authType=TOKEN`。
- GW 继续把字段透传给 LoginSvr；LoginSvr 成功后返回新的 `sid/token`，GW 按原逻辑绑定新连接。
- `location` 仍由租户专属 URL 自动带入，Web 不允许用户填写租户。
- LoginSvr 返回的用户和 `location` 是恢复后的权威身份；Web 只有认证成功后才恢复订阅。

代码基线：LoginSvr `6164727`，dc-trade-web `7421d5d`，GW 零代码改动。

## 2. 无 Redis 的会话模型

复用 MySQL `dc_users_session`，不新增 Redis 和数据库表。当前 token 同时是 LoginSvr 会话凭证和 GW SID：

- 密码登录生成 256 位 CSPRNG 随机 token（Base64URL 43 字符）。
- token 恢复在 MySQL 事务中把旧主键 token 更新为新 token，并写登录审计。
- `UPDATE ... WHERE token=<old>` 只能命中一次；并发重放旧 token 时只有一个请求能成功。
- 会话有效期继续使用 LoginSvr `validTime`；SQL 轮换同时检查 `create_time`。
- 用户被禁用、用户更新时间晚于会话创建时间、租户停用或试用到期时拒绝恢复。
- 显式退出删除当前 `dc_users_session` 记录并清除 LoginSvr 缓存。

当前表以明文随机 token 作为主键，这是复用旧 SID 模型、不做 schema 改造的已知安全约束。生产必须使用 TLS、限制数据库权限、禁止输出 token 日志。若以后要求数据库泄露后 token 仍不可用，应升级为“公开 session_id + 仅保存 resume token 哈希”的独立会话表。

## 3. 恢复数据流

```text
Web 刷新或 WebSocket 断开
  -> 从 sessionStorage（可选“记住登录”时从 localStorage）读取用户名/token/location
  -> 校验 URL location 与保存的会话 location 一致
  -> 建立 WebSocket
  -> GW CONNECT: userName + pwd=oldToken + authType=TOKEN + Location + deviceId
  -> GW 按原有 login 流程透传 LoginSvr
  -> LoginSvr 校验用户、租户、客户端、有效期和旧 token
  -> MySQL 事务原子轮换 oldToken -> newToken
  -> LoginSvr 返回正常 login 结果（新 sid/token + 权威 location）
  -> GW 按现有逻辑把新 SID 绑定当前连接
  -> Web 保存 newToken
  -> 恢复订单、成交、持仓、资金、OrderBook、最近成交和 K 线订阅
```

恢复失败时 Web 清除本地凭证，回到当前 URL 对应租户的登录页，不展示伪登录状态。

## 4. Web 存储规则

- 密码从不写入 `localStorage` 或 `sessionStorage`。
- 旧版 `userRemember.info2` 在首次加载登录页时立即移除。
- 默认只在 `sessionStorage` 保存当前 token，刷新可恢复，关闭标签页后消失。
- 勾选“记住登录状态”后，token 可写入 `localStorage`，但每次恢复都会立即轮换。
- 保存的 location 与 URL location 不一致时不恢复。
- 每个浏览器生成非敏感 `deviceId`；当前版本用于审计上下文，不作为单独认证因子。

## 5. 安全与兼容规则

- token 模式必须同时匹配 `user_id`、`location` 和 `client_type`。
- 旧 token 在成功恢复后立即失效；重放返回 `USER_SESSION_NOTEXIST`。
- 跨租户 token 登录返回认证失败，且不会消耗当前有效 token。
- ClickHouse 登录存储模式不支持原子主键轮换，因此 fail-closed；SaaS LoginSvr 必须使用 MySQL。
- 旧客户端未发送 `authType` 时默认走密码登录，保持向后兼容。
- GW 不解析 token 业务含义，只消费 LoginSvr 的成功/失败结果和新 SID。

## 6. 验收条件

自动化脚本：`tests/run-web-session-resume-e2e-host.sh`。

- 页面刷新后自动恢复，用户和 location 不变，token 已轮换。
- 网络短断后 WebSocket 自动登录，再恢复全部订阅。
- 轮换前的旧 token 无法重放。
- 修改 location 后不能恢复其他租户。
- 当前 token 仍能调用 `userInfo`。
- 点击退出后数据库会话被删除，保存的 token 无法再使用。
- 浏览器存储中不存在旧版保存密码字段。
