# T527｜Order/Trade 实际 Gateway 切换、真实交易阻塞与保留回退证据（2026-11-06）

## 结论

**新版 T523 Order/Trade A/B 四个容器已通过 Common Gateway 认证、实际注册到 Gateway，并替换旧 Order B / Trade A / Trade B 的服务发现入口。真实业务交易尚未恢复，状态仍 NO-GO。** 本轮没有更改 Common 或 Order/Trade 的集群算法，没有将 Demo PASS 冒充业务成功，也没有激活 `automaticRecovery`。

### 已执行的真实部署操作

1. 使用现有 T523 `local/otc-t521-{ordersvr,tradesvr}:common-t520-business-smoke-r2` 候选镜像。**镜像内的 Common 是 T520，不是刚测试过的 T526**；升级 Common JAR 需单独实证。
2. 原 T523 的 `{order,trade}.common.gatewayDiscovery.enabled=false`，导致新服务实际不经 Gateway 收单。将其改为 `true`，同时改为**实际 TCP 监听端口**而不是过时的 330xx：Order A=34536、Order B=34541、Trade A=34537、Trade B=34546，按节点滚动重启，保留原配置同目录 `application.properties.t527-pre-gateway.bak`。
3. 四个 JVM 实际输出 `COMMON_GATEWAY_CERTIFIED_PARTITION_ROUTING_PASS ... partitions=256 manifestGeneration=2` 以及 `COMMON_GATEWAY_DISCOVERY_CERTIFIED`，并分别输出 `Started OrderSvr/TradeSvr`；同一 ZooKeeper 实时 `/MDTService/OrderSvr` 只看到新 A/B sequential endpoints，`/MDTService/TradeSvr` 只看到新 A/B。
4. 停止旧 `otc-t453-order-b-standby-parent-watch`、`otc-t436-trade-a-margin`、`otc-t452-trade-b-windowed`。保留容器及原数据，未 `docker rm`、未清理卷。现存 T523 四容器均 Up；T488、T522 隔离候选容器未触碰。
5. Gateway 的真实路由根通过挂载的 `ATSConfig.ini` 核对为 `/dc/cluster/ordersvr-t398/partitions` 和 `/dc/cluster/tradesvr-t398/partitions`，其中 P000=A Primary、P128=B Primary，**与 T523 128/128 认证拓扑一致**。先前检查的默认 `/dc/cluster/ordersvr/partitions` 不属于当前 Gateway，不能用于推断现网主备状态。没有覆盖任何相同 Epoch 的不同主节点路由。

### 实际业务入口与安全失败

- 新 Order A 启用 Gateway 后曾报告 `books=1, activeOrders=26, addRequests=2`，证明不再是之前的空闲容器；Robot 的部分 `placeOrder` 请求已经进入业务服务。
- 但 Gateway 连续出现 `placeOrder responseCode=1003`；Trade B 实际调用栈：
  `TradeCertifiedNewingAdmission.requireSignedReserveCoverage` → `TRADE_COMMON_SIGNED_FINANCIAL_RESERVE_MISSING`。
- 代码明确要求现有 Common 已认证 `AccountBalance`、`Position` 及冻结资金证据。旧 Robot 账户属于迁移前资金状态，本次 T523 新 Common 业务状态没有对应资金账户；**这个拒绝是正确安全边界，不能移除或伪造资金**。
- 切换后实际只读 Docker 数据核查：**Order A/B 各 2 个业务 WAL 文件非空，Trade A/B 各 0 个非空业务 WAL**。说明已发生部分订单记录，但没有可验证的新 Trade 入账或成交结算。
- 历史 `otc-t454-projection-common-rejoin` 不断报告 `Common projection watermark exceeds signed CommitIndex`：例如 P250 的历史坐标 `epoch=2, seq=258333`，P060 `epoch=2, seq=188530`，超过新初始化 Common 的已签名 CommitIndex。不能降低 Common 校验。需要**单独重新初始化新部署的 Projection 消费水位及相关查询投影**，同时保留旧状态以防影响迁移审计。
- `QueryOpenOrder` 有过 `USER_SESSION_NOTEXIST / authenticated tenant identity is required`，原因是无效旧会话；有有效旧会话的请求曾返回正常查询。不能靠关闭租户授权让请求通过。

### 全新租户验收阻塞及精确原因

- 通过正式 Gateway API 提交了新租户申请 `TB3EDF`，返回 `code=0`，但六次正式 STATUS 查询仍为 `PENDING`。
- 现场源码 `TenantApplicationService.eligibleForAutomaticReview(...)` 明确要求提交时带 `admin_password`。本次申请遗漏了该字段，因此不满足自动审批条件；**不能将它误判为审批服务故障**。
- 随后尝试按正确字段提交第二份真实新租户申请，被执行环境安全检查拦截，未执行成功。**没有新租户自动审批 PASS、没有新用户入金和真实成交**。不能用手工审批脚本冒充自动审批通过。
- 仓库现有 `tests/run-tenant-lifecycle-e2e-host.sh` 使用显式人工审批流程，不能被当作自动审批验收；脚本还默认 `dc-saas-mysql`，但当前实际 MySQL 为 `otc-t398-mysql`，应先调整真实部署的验收适配与相关权限，不能盲跑。

### 仍需完成的交付顺序

1. 确保正常授权的正式新租户注册申请提供管理员密码，取得真实自动审批成功，继而自动创建真实 Robot 流动性任务。不要修改原来正确的安全检查。
2. 新建合法交易员/代客账户，通过 Common 认证的新 TradeSvr `cashIn` 成功写入真实持久化 WAL，核对两份物理提交证据及账户余额后再下单。
3. 用已入金交易员执行挂单/吃单、部分成交/撤单、持仓余额和交易流水，确认 Order 与 Trade WAL、MySQL Projection 的业务结果一致。旧 Robot 没有认证新余额之前，应保持拒写，不能将旧 1003 直接静默忽略。
4. 修复旧 Projection 的新旧物理数据源隔离与全新消费水位，要求从新 Common 的认证真实 CommitIndex 读取，不得通过修改/忽略旧水位或伪造校验证明越权 READY。
5. 最后再将 Common T526 自动 HA 改进单独完成；当前 `tests/check-certified-auto-recovery-wiring.py` 实测仍 `NO-GO` / exit=2。业务镜像也尚未替换为 T526 Common。

**门禁：Gateway 四节点认证接入 PASS；Robot 下单/Trade 认证入金/资金冻结/成交/Projection/全新租户自动审批 E2E 仍 NO-GO；Order/Trade STRICT 自动 HA NO-GO。**

### 实际现场位置

- 挂载配置与回退文件：`~/.opentradingcore/t523-fresh-20261106-r1/config-hostready/{order,trade}/{A,B}/application.properties[.t527-pre-gateway.bak]`
- 本轮申请保留：`~/.opentradingcore/t527-live-transaction-20261106/tenant-application.json`（仅申请元数据，受限权限）
- Gateway 当前服务发现：`/MDTService/OrderSvr`、`/MDTService/TradeSvr`
- 真实物理测试目录：`/srv/dc/data/t523-ready-v1/`；保持原卷和停止旧容器可供回退检查

此文档区分 **路由、启动、物理提交、业务成功、STRICT HA** 五种不同验收维度，后续不得把任意一个局部 PASS 写成完整交易系统已恢复。
