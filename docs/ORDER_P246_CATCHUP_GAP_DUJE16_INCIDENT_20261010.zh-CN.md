# Order HA P246 追赶 GAP / DUJE16 不可交易调查（2026-10-10）

## 结论（只读验收，未修复线上分区）

**P246 的 ZooKeeper assignment 虽然显示 `state=READY`，但其 Primary OrderSvrA 的实际分区就绪栅栏未通过。** `DUJE16/BTCUSDT` 定向授权 `OrderSvr/queryOpenOrder` 返回 `code=1016 PARTITION_NOT_READY service=OrderSvrA, partition=P246, epoch=1`。这不是成功返回空挂单，不能凭 Robot DB `open_order_count=0` 判断已撤单。

- 受影响租户：`DUJE16`，Robot `trial-liquidity-BTCUSDT`，持续租约心跳但仍 `enabled=1/DEGRADED/0`，原历史错误 `gateway TCP response is empty for cancelBatchOrder`；最近 300 秒该租户 `dc.market_trade=0`。MDSvr 公开接口/浏览器仍显示 10 买 + 10 卖和旧成交历史，**不证明 OrderSvr 此分区可接单或 Robot 已恢复**。
- ZooKeeper `/dc/cluster/ordersvr/partitions/P246`：`epoch=1`、`primary=OrderSvrA`、`replicas=[OrderSvrB,OrderSvrC]`、`state=READY`。P245/P247 显示其他分配，三台容器运行。
- Order A 最近 3 分钟：`P246` **34 次恢复失败、919 次 PARTITION_NOT_READY 拒绝**；B/C **0 个分区恢复失败**。后续门禁采样（2026-10-09 22:44 UTC）A 为 **35 次失败、1020 次请求被拒**，**只有 P246** 出现该类告警。日常持续新日志在变，计数为各自窗口。
- Order A 实际错误堆栈来自 `OrderSnapshotReplicationManager.beginTransfer → OrderReplicationManager.catchUp`：
  `ReplicationAck[status=GAP,partition=P246,epoch=1,replicatedSeq=578109,expectedSeq=578110,message=replication sequence gap]`。
  A 日志同时显示 `ORDER_PARTITION_SAME_EPOCH_RESTART` 的提交状态 `committedStateSeq=578109`、`commitMarkerSeq=578110`，以及 `ORDER_REPLICA_CATCHUP_REBASE` 试图从更高的 `SNAPSHOT_BEGIN` 序号（约 578985 起，之后持续增长）重放；副本期望 578110，反复返回 GAP。**该序号差不能通过直接修改 ZK epoch/标记 READY 或跳过日志证明安全**。
- 只读解析快照元数据：`OrderSvrA/snapshot/P246` 约 110 KB、`books=1`、`clientOrderReservations=99`、`epoch=1`、`committedStateSeq=578109`、`commitMarkerSeq=578110`；`OrderSvrB` 和 C 对应快照仅 253 字节、`books=0`、`clientOrderReservations=0`、`committedStateSeq=0`。不可直接认为副本含有主节点完整业务状态。
- B 的 `snapshot/.install/P246` 发现约 **898 个未完成安装目录（3.6 MB）**；Order A 的 `journal/.archive` 总计约 **1.7 GB**。本机磁盘约 **64 GiB 可用，86% 已用**；需监控增长，但未删除任何 Journal、快照、归档或安装目录。
- 读取 `OrderReplicaReplicationHandler` 当前代码发现：`batch.epoch>localEpoch` 时有 `SNAPSHOT_BEGIN` 重基路径，同一 Epoch 的旧副本如果仍要求之前的连续 seq，现有逻辑会返回 `GAP`；这与 P246 的现象一致。**但开放同 Epoch 跳序号需要证明无已提交业务事件被跳过以及副本安装快照的一致性，不能仅凭日志直接改放行规则。**

## 已落地防扩容保护

`tests/check-tenant-ramp-readiness.py` 增加只读三节点 `docker logs --since 180s` 恢复错误/分区栅栏扫描：

- 输出仅含 **容器名、分区号、恢复失败数、就绪拒绝数**，不回传日志里的客户身份、SignalID、登录 Token 或订单详情；
- 任何 `Pxxx` 恢复失败或 `PARTITION_NOT_READY` 都会使门禁出现 `ORDER_PARTITIONS_UNREADY:Pxxx`；
- 日志无法读取时 `TELEMETRY_UNAVAILABLE`，仍 fail closed；
- 真实门禁：`NOT_READY`，原因为 `CPU_PSI_HIGH`、`ROBOT_CPU_QUOTA_UTIL_HIGH`、`ENABLED_ROBOTS_UNHEALTHY:1/13`、`ORDER_PARTITIONS_UNREADY:P246` 及观测窗口内 `ORDER_B_FULL_GC`；
- 真实观测的 300 秒行情入库 **348 行**，只能代表 `dc.market_trade`，绝不是权威下单/成交 TPS。

执行方式：
```bash
python3 -m unittest discover -s tests -p test_tenant_ramp_readiness.py -v
python3 tests/check-tenant-ramp-readiness.py --output /tmp/otc-p246-gate.json
```
退出码 `2` 代表 `NOT_READY`，此时不自动启动下一档租户压测。

## 风险与恢复边界

**在 P246 的权威一致性未证实前，不做：** Robot `RESTART`、直接 SQL 标记 `RUNNING`、重建 Order、SIGKILL 主节点、强制切到 B/C、改 ZooKeeper 分配、修改 Epoch、手工清理/覆盖 Journal 或快照、启动 50/200 租户压力测试。这些操作可能把业务状态不一致掩盖为表面恢复。

**下一步必须先做**：基于主/副本 Journal 和提交标记核对 `578109/578110` 之后的事件类型与权威已提交边界；为同 Epoch 快照重基的安全性编写隔离环境验证/单元测试，严格排除跨越任何已提交业务事件；之后进行受控 HA 恢复、订单/成交/持仓/资金/Projection watermark 一致性核验，最后才单租户恢复 Robot 并连续监控。

**本轮没有实施任何 ZK/Journal/快照修复、没运行真实订单、没有停止或重启现网服务。**
