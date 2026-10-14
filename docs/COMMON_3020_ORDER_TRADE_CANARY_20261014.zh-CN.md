# Common 3.0.20 — Order/Trade 恢复统一与 Order-C 灰度验收

日期：2026-10-14；分支：saas-crypto；Mac mini / Colima Demo。

## 已提交

- Common 3b9f278：共享 LocalSnapshotWalRecoveryBoundary，复用已有 DurableRecoveryTransactionControl 与 SnapshotDiffStateMachineAdapter；tag com-app-common-v3.0.20，中央发布构建 38498888783 SUCCESS。
- com.app.dc 3966437：依赖 Common 3.0.20，排除旧 JDBC 5.1.24，明确依赖 Connector/J 8.0.33。
- Order 2a56720：在恢复订单业务 Snapshot 之前检查本地 WAL / commit / baseline。
- Trade 3b62137：恢复规划与 Order 统一走 Common 的 Snapshot/WAL 恢复边界。

## 本地测试

- Common：265 PASS / 0 fail。
- Order：365 tests / 0 fail / 3 skip。
- Trade 最新 saas-crypto：228 PASS / 0 fail。
- Trade 旧的本地恢复分支：299 PASS / 0 fail；与远端 saas-crypto 已经有大量差异，不能用旧分支覆盖较新的代码。
- 官方 Common 3.0.20 关键单元回归：Order 10 PASS，Trade 2 PASS。

## 本地 ARM64 交付镜像（非正式 GHCR 多架构）

- dc-saas/ordersvr:common-3020-jdbc8-20261014，image sha256:0f7fc593cc6cfc0d5e81d06fa5514c0d19ff74842ae30c8549eefea97cbc312e
- dc-saas/tradesvr:common-3020-jdbc8-20261014，image sha256:42b9fdf987173a8317f8c9157f64f4c8bf1dd7270c8abb3424d4f244804d48b2
- 两镜像内 com.app.common-3.0.20.jar SHA256 均为 fee519bab75e152b1a04e5516befd146b973ccd347e9b9a5fc33e4b65c2f3fc7；仅 mysql-connector-j-8.0.33，无 5.1.24。

## Order-C 真实部署与回滚

Order-B 在本轮检查中持有 256/256 Primary，Order-A、Order-C 各 0 Primary。本轮仅更换了非 Primary 节点 Order-C，没有停 Order-A/B。

第一次 LOCALQA 镜像因旧 JDBC 5.1.24 报 caching_sha2_password 不兼容，已回滚旧版本。修复 com.app.dc 的传递依赖后重新部署 Order-C 正式 Common 3.0.20 镜像。

第二次启动后，Order-C 正常加载 BTCUSDT/ETHUSDT/SOLUSDT/UNIUSDT 规则，检查窗口内 0 个数据库认证错误，容器 running、重启 0。只读集群预检：256/256 READY、Order-B 256 Primary、768 份 Snapshot 全部齐全无分歧、最近恢复报错 0；主站/交易终端 HTTPS 200。

回滚：旧 Order-C 镜像 dc-saas/ordersvr:cluster-dev-local-c361e3e3d-20261012034946，保留原数据和配置。

## 尚未完成，不得误报

- 其他 Order A/B 和 Trade A/B 仍为旧镜像。完整运行时 Journal 安装、恢复事务和归档的 Common 生产接线未完成；本轮统一的是边界接口及校验，不能称为全部 HA 机制完全统一。
- Order 全量滚动升级预检 BLOCKED：宿主机磁盘占用约 94%、写入排空与 Replica 持久水位、Projection 水位和可靠回滚证明尚未齐备。
- Trade 现有 Snapshot 与 WAL 不匹配的 9 个分区尚未完成新镜像验收。不能通过伪造 HEAD、忽略 Epoch 或删除当前 WAL 绕过。
- 后续先验证 Order-C 已实际追平的持久水位；在单节点正确、安全有回滚的条件下继续，Trade 再按相同 Common 机制做滚动/重建验证。MD 自动主切仍不启用。Gateway 不改；无数据清空、无主节点故障注入。
