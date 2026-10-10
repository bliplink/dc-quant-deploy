# 2026-10-10 首次全新环境 Trial + Tape + Robot 真实业务验收

## 环境与版本

- Mac mini / Colima，`saas-crypto`，刚通过冷重建的完整 Demo 集群；此结果不是正式 200 租户压测，也不是 HA 故障注入结果。
- `AdminSvr` 原镜像 `sha-7baddbd...` 的 `TrialLiquidityBootstrapWorker.assertTrial` 只接受 `reviewer_id=AUTO_APPROVAL`，导致平台管理员合法审批的 TRIAL 租户在 `CREATE_MAKER / RETRY` 重复失败直至第 30 次进入 `FAILED`。审查实际数据库 `A7C924` 和 `B7C924` 确认审批状态均为 `APPROVED`、审批人为平台管理员、租户状态 `TRIAL`，各有 2 个普通用户，且无需为内部流动性账户消耗普通用户配额。
- [AdminSvr df1b6e5](https://github.com/bliplink/com.app.dc.adminsvr/commit/df1b6e583b3e70af19cfb2459508061ec9598ca9) 修复过度限制的审批人检查：仍须验证真实审批人非空、租户有效期、TRIAL 状态、trade_enabled、source_application_id 等全部条件；允许平台人工审批与自动审批。相关 Maker、Robot、用户和 Tape 单元测试通过；[GH Actions 38035794888](https://github.com/bliplink/com.app.dc.adminsvr/actions/runs/38035794888) SUCCESS，已发布 ARM64/AMD64。
- **实际已在 Mac 替换 AdminSvr** 到 `ghcr.io/bliplink/adminsvr:sha-df1b6e583b3e70af19cfb2459508061ec9598ca9`。OrderSvr A/B/C 未重启，未降低 `SYNC_PER_RECORD`。
- 仅针对两条精确匹配 `FAILED / CREATE_MAKER / attempts=30 / funding_confirmed=0 / tape_funding_confirmed=0`，且关联订单来源申请 `APPROVED`、租户活跃有效、审批人非空的测试任务进行受限重排队 (`RETRY`)，执行结果 `ROW_COUNT()=2`。这不是跳过业务逻辑、写现金余额或修改 Robot 状态；后续账户、入金、Robot 全由 AdminSvr Worker 按持久化步骤及幂等规则自主处理。

## 业务验收结果（实机）

| 项目 | A7C924 | B7C924 |
|---|---|---|
| 租户申请、审批、注册、管理员/交易员登录 | PASS | PASS |
| TRIAL 流动性引导 | `DONE / COMPLETE` | `DONE / COMPLETE` |
| 独立 Maker / Tape 账户 | 已生成 | 已生成 |
| Maker / Tape 模拟资金确认 | 1 / 1 | 1 / 1 |
| 启用的 BTCUSDT Robot | `RUNNING` | `RUNNING` |
| 开放报价挂单数 | 40 | 40 |
| `verify-trial-tape-live-host.py` | PASS | PASS |
| 最近成交数据项（首次检查） | 16 | 11 |
| Tape 用户持久化 Trade 流水（首次检查） | 16 | 11 |
| 12 秒观测窗口 Tape 新增资金流水 | +1 | +1 |

上述 `verify-trial-tape-live-host.py` **只读**检查 MDSvr 公开双边盘口深度、最近成交 ID 变化与 Tape 账户 Trade 持久化流水同步增长，确认主动点价成交确实发生，而不仅是启用开关或历史 24h 统计的显示。内部 Demo=1 IOC 不一定写 `dc_orders_execorders`，因此不能用这个表的计数作为唯一依据。

## API Key / Broker 尚未通过的部分

生命周期 E2E 使用被审核的**独立、不影响现网 RobotSvr**镜像 `ghcr.io/bliplink/robotsvr:sha-36b80cfca6c70e9c13e1b5f0114b4eb87d0d9872`，原始镜像 ID 通过 `broker-runner-image-review.py` 不可变摘要审核，未把现网 RobotSvr 加入授权名单，也没有绕过任何门禁。

- 已 PASS：两租户独立注册与登录、Trader 自助申请 `ACCOUNT_READ` Key、自身 Key 列表、签名 API Key 登录、`TradeSvr/queryAccountBalance` 真正账户余额查询。
- **BLOCKED**：只读 Trader Key 测试发送下单请求，实际收到 `1004 / INVALID_REQUEST`，要求 `9016 / TRADE_PERMISSION_DENIED`。OrderSvr `StrategyFacade.routeNewOrder` 将所有 `SecurityException` 误归类为 `Consts.ArgErrorCode`。修复已提交 [OrderSvr 12a519c](https://github.com/bliplink/com.app.dc.ordersvr/commit/12a519c419fb633ce5f19f4f33abdbe17bc5ead0)，只把精准的缺少 `ORDER_WRITE` Scope 映射到 `9016`，租户身份冲突仍是 `1004`；8 项专门/权限测试通过。**尚未升级线上 Order A/B/C**：安全停写/副本切换仍未形成分布式闭环，不能因该 API 修复热替换生产式订单副本；因此完整 Trader、Broker 签名下单、撤单和权威成交对账仍未通过。
- **已知观测问题**：`TrialLiquidityBootstrapWorker` 的 `VERIFY` 在首次盘口尚未就绪时可能短暂重试，即使最终转为 `DONE / COMPLETE`，`last_error_code/message` 仍保留过时的 `IllegalStateException`，后续需要在成功完成的事务中清空已解决错误，不应误判为当前系统失败。

## 压测与高可用门槛

`check-tenant-ramp-readiness.py` 在空库时会明确返回 `MARKET_ACTIVITY_BASELINE_EMPTY`，且始终 `nextRampAuthorized=false`。现已拥有 2 个活动租户，但 200 租户自动扩容需要先有更多阶段性资源遥测和 Order/Trade HA 及 Projection 权威水位对账。**不应因为此轮 2 租户交易成功就宣称系统承载 200 租户。**

后续按照以下先后推进：确认新 Robot 的无故障持续运行和公开行情时效 → 修复已提交 Order 权限码并安全验收 → 完成 Broker 客户权限/清理对账 → Order/Trade HA 故障注入 → 10/25/50/100/200 租户阶梯压测。自动 WAL 归档及回收必须以副本安全提交/Projection 水位/备份证据为准。
