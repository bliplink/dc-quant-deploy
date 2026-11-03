# T453｜Order B Common STANDBY ZK 客户端发现补丁与交易路由诊断（2026-11-03）

## 故障复现

- 旧 Order B `otc-t450-order-b-common-rejoin` 已于 07:15 经 Common 可信 E2 恢复并成功注册，随后 Gateway `otc-t451-gateway-standby-parent-watch` 自动连接它。
- Trade B `otc-t452-trade-b-windowed` 于 07:28 恢复后，Gateway 显示 `TradeSvrB cycle:2`；Order B 的 RPC 客户端于 **07:28:56** 输出 `Host:127.0.0.1,Port:33046:CONNECTION_LOGIN_SUCCESS`。
- **但 Order B 08:19—08:21 仍实时报 `[1015] SERVER.TradeSvr is not Online`**，包含 `DAYWUB` Robot 真实新单，`TradeSvrClient.updateOrder` 抛错，Order 发出 `Trade_Correct/Rejected`。另有待撤单状态因未取得 Trade 认证释放而保持 `ORDER_COMMON_PENDING_CANCEL_STILL_RECOVERING`。这是业务 NO-GO，不能以 TCP connected 断言交易正常。
- ZooKeeper 的 `/dc/cluster/tradesvr-t398/partitions/P144` 为 `epoch=2,primary=TradeSvrB,state=READY`，另 P129、P238 相同，P144 对应 DAYWUB（CRC32 % 256）。
- 只读、独立容器诊断 `TradeRouteProbe` 复用与 Order B 相同的配置和 ZK，实际验证：`DAYWUB → P144/TradeSvrB/Epoch2`；`JRHHXA → P242/TradeSvrB/Epoch2`；`KCV203 → P240/TradeSvrB/Epoch2`；新建一个同类型 Common RPC 客户端，第一次查询未连接，但约 3 秒后 `physical=true`。因此问题局限在长时间运行的 Order B 客户端连接/服务发现实例，不是全局错误的分区哈希或不可达的 Trade B。
- 已发现部署版本缺口：T450 Order B 只覆盖 Common `GwClient` 的 T449 物理重连；未包含 T451 `ZkCluster` 对 `RegType=2` 目录子节点变更监听修复。Gateway 和 Trade B 已包含 T451。该缺口与长时间运行的 RPC 连接失效症状相符，但**尚未完成补丁后的真实订单验证，不能直接宣称它是唯一根因**。

## 本轮受控操作

- Common T451 目录监听源码及回归记录见 `docs/T449_T450_COMMON_ZK_CLIENT_AUTO_REJOIN_ACCEPTANCE_20261103.zh-CN.md`；Common 的 `saas-crypto-latest` 已包含 T451，原 T451 全量回归 `706 tests,0 failures,0 errors,72 skipped`。
- 用 `local/otc-t450-ordersvr:common-zk-rejoin` 为基础，**只覆盖 T451 编译的 `ZkCluster*.class` 5 个类**，不修改业务路由或 Order 状态机，也不覆盖其它业务类。镜像：`local/otc-t453-ordersvr:standby-parent-watch`。
- 用原容器相同环境、host 网络和 **同一数据卷**创建 `otc-t453-order-b-standby-parent-watch`。旧 `otc-t450-order-b-common-rejoin` 停止、保留用于回退；新容器实际启动。没有删除任何 WAL、分区、快照、RSA 或 MySQL 数据。
- T453 新容器已经恢复 **5 个订单簿、994 个活动订单**，主线程正在 `DurableWalCommitIndex.loadAndVerify` / `DurableWalCommitQuorum.verify` 校验历史提交证书。08:31 仍无启动异常、无 OOM、尚未完成服务注册/READY。
- 此时 `DAYWUB` Robot 显示 `ERROR`、活动挂单计数 0，属于 Order B 认证恢复窗口。Trade 财务 Projection/ReadModel 五分区的游标差值均为 0（当次 P144 `60103/60103`）。

## 验收门禁

1. Order B T453 自主完成认证冷启动、公开 TCP、ZK 当前所有权注册，Gateway **无需重启**自动重新订阅。
2. T453 Order B 的 `TradeSvrClient` 到 Trade B 恢复后，再观察 `DAYWUB` 真实 Robot 新单，不再发出 `[1015]`，检查可靠撤单及认证资金释放。
3. 验证 P144 财务 Projection/ReadModel 推进且字段与 Mutation 后状态完全一致，Robot 重新 RUNNING、挂单持续且能撮合成交。
4. 之后再进入 Order/Trade A/B **自动双向主切**和 Snapshot+WAL 认证一致性。

**当前：T453 镜像构建及启动已完成，交易业务 NO-GO，禁止提前宣布修复通过。**
