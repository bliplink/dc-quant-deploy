# WebSocket 登录与专业交易 Web 验收报告

> 状态更新（2026-08-31）：刷新和断线免密码恢复已经实现并通过生产验收。本报告中“刷新需重新登录”的阶段性结论已由 [WebSocket 会话恢复生产验收报告](WEBSOCKET_SESSION_RESUME_ACCEPTANCE_20260831.zh-CN.md) 替代。

文档版本：V1.0

日期：2026-08-31

分支：`saas-crypto`

生产环境：`18.140.45.126`

## 1. 结论

WebSocket 登录、租户 URL 绑定、桌面/手机双语交易工作区及完整 Web 交易闭环通过生产环境验收。浏览器登录不再调用 HTTP 登录接口；GW 在 WebSocket 握手后的登录消息中调用 LoginSvr 校验用户名、密码和 URL location，验证成功后把权威用户与租户绑定到当前 SID，错误密码返回 `USER_ACCOUNT_OR_PWD_ERROR` 且不建立业务会话。

交易页已经达到本阶段生产基础样式：Bybit 类专业深色视觉、橙色行情图主题、五面板合约布局、悬停十字光标直接拖动、右下角缩放、恢复默认布局、桌面/手机响应式重排和中英文切换。字段仍使用 DC 自身协议与业务定义，不复制外部交易所文案。

当前不宣称“刷新免登录”。站内 SPA 路由切换保持同一 WebSocket；浏览器刷新、关闭页面或连接中断后需要重新登录。无 Redis 的 MySQL 一次性 token 恢复方案已记录在 `WEBSOCKET_SESSION_RESUME_DESIGN.zh-CN.md`，本阶段未提前实现。

## 2. 发布基线

| 组件 | 基线/镜像 | 状态 |
|---|---|---|
| dc-trade-web | `04ded17cd3de3a5fb8a5cfd0b25d2cce72ca7676` / `ghcr.io/bliplink/dc-saas-trade-web:source-04ded17cd3de3a5fb8a5cfd0b25d2cce72ca7676` | 已公开、已部署、健康 |
| GW | `ghcr.io/bliplink/gw:saas-crypto` | `login=true`，已部署 |
| 部署与 E2E | `e5f4966` | WS 登录、移动端与 K 线轮询测试已提交 |

## 3. WebSocket 身份认证

| 场景 | 结果 | 硬断言 |
|---|---|---|
| 正确用户名/密码/location | PASS | 返回认证用户、角色、location 和 token，SID 可继续发送业务请求 |
| 错误密码 | PASS | 返回错误码 `9005`，不创建业务会话 |
| 登录后进入交易页 | PASS | 使用 SPA 路由，不触发页面 reload，原 WS SID 保持有效 |
| 登录后初始化 | PASS | 使用认证 SID 请求租户品种，再进入交易页，不依赖未认证 HTTP 会话 |
| 页面刷新 | 符合当前设计 | 清除内存会话并回到 URL 所属租户登录页，不使用伪造的本地 token 恢复 |
| 租户注册 | PASS | location 只来自租户 URL；用户不填写租户，注册后自动归属该 location |

## 4. 完整 Web 交易闭环

生产 E2E 使用同一租户的两个独立浏览器会话，经真实 GW、LoginSvr、OrderSvr、TradeSvr、MDSvr、MySQL 和 ClickHouse 执行：

1. 双用户分别通过 WebSocket 登录。
2. 页面添加测试 USDT，账户总额、可用额和资金流水同步更新。
3. 卖方提交限价挂单，买方 Web 订单簿出现对应档位。
4. 卖方撤单，活动委托和盘口同步移除。
5. 双方重新报单并撮合，订单历史、成交历史、最近成交和持仓更新。
6. MDSvr/ClickHouse 产生 location-aware K 线；Web 显示 Last、Mark、Index。
7. Web 使用 Market/IOC/ReduceOnly 平仓，最终 MySQL 权威持仓数量归零。

| 验收项 | 结果 | 关键证据 |
|---|---|---|
| Deposit | PASS | 两用户余额与资金流水一致 |
| Resting order / cancel | PASS | Web 盘口出现后撤销，数据库状态一致 |
| Execution | PASS | 最近成交 `price=60000, qty=0.001`，双方 execution/历史可见 |
| K 线 | PASS | 持久化 9 行 location-aware K 线，页面无需刷新即可轮询显示 |
| Mark / Index | PASS | 来自实时 APSSvr/MDSvr 链路，不使用静态页面常量 |
| Close position | PASS | Web 平仓成功，最终双方持仓为 0 |

## 5. 桌面交互与视觉

| 验收项 | 结果 |
|---|---|
| 五面板合约布局 | PASS：行情图、订单簿/最近成交、下单、持仓/历史、资产 |
| 直接拖动 | PASS：鼠标悬停拖动区域显示十字移动光标，无独立编辑/锁定模式 |
| 缩放与恢复 | PASS：右下角缩放；“恢复布局”保留并恢复默认配置 |
| 图表填充 | PASS：初始容器/iframe 高度 525/525；调整后 589/589，无下方大块空白 |
| 行情图视觉 | PASS：主色 `#f7a600`、图标 `#a7abb4`、pane `#111318` |
| 交易视觉 | PASS：页面 `rgb(11,14,17)`、买入 `rgb(32,178,108)`、卖出 `rgb(239,69,74)` |
| 中英文 | PASS：登录、行情、下单、订单、成交、持仓、资金和状态字段切换 |
| 下单易用性 | PASS：限价/市价/条件单、TIF、ReduceOnly、数量与价格前端校验 |

### 桌面英文

![桌面英文交易工作区](evidence/workspace-en.png)

### 桌面中文

![桌面中文交易工作区](evidence/workspace-zh.png)

## 6. 手机响应式

在 `390 × 844` 视口执行真实浏览器验收：页面无水平溢出，五个交易面板按纵向自动排列，行情抽屉响应式展示，下单控件满足触屏操作，中英文均可使用。

![手机英文交易工作区](evidence/workspace-mobile-en.png)

![手机中文交易工作区](evidence/workspace-mobile-zh.png)

## 7. 交易与数据库证据

### 买方交易闭环

![买方挂单撤单成交与持仓](evidence/buyer-trading-flow.png)

### 卖方成交历史

![卖方成交历史](evidence/seller-trade-history.png)

### Web 行情与 K 线

![Web 最近成交、标记价格、指数价格与K线](evidence/web-market-data.png)

### 数据库权威记录

![MySQL订单、执行、资金、持仓与ClickHouse行情证据](evidence/database-evidence.png)

仓库中的上述 Web 图片已在 2026-08-31 从生产 E2E 目录重新同步并核对 SHA-256，报告引用的不是本地静态原型截图。

## 8. 部署复核

最终 `validate-saas.sh` 结果：

- SaaS-only compose 模型通过。
- 14/14 容器运行。
- MySQL 41 张表，27 张表包含 location 字段。
- MySQL、ClickHouse、ZooKeeper 仅绑定 loopback 接口。
- ClickHouse K 线表具备 location 维度。
- dc-trade-web 健康检查通过。

同机量化系统未被停止、重建或修改。本轮仅对 SaaS 的 GW、LoginSvr、OrderSvr、TradeSvr、RobotSvr、APSSvr 和 Web 做定向更新。

## 9. 后续安全项

- 按 MySQL 方案实现一次性轮换 `resumeToken`，覆盖刷新、短断线、GW 重连、退出、改密、用户禁用和租户停用。
- 会话恢复后仍必须以 GW 绑定的权威 location 为准，URL、Topic 和请求体不能切换租户。
- 真实资金上线前补齐 TLS、MFA、风控审计、限流、WAF、密钥管理、高可用与灾备。
- 本报告证明功能链路和界面运行正确，不构成真实资金生产许可。
