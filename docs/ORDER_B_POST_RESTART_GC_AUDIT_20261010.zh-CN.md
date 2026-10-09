# OrderSvr B 重启后 GC 复核与内存保留风险审查（2026-10-10）

## 本轮结论

**此前 Order B 老年代 1535.8/1536 MiB、频繁 Full GC 的问题确实存在；但本轮核查发现容器在 2026-10-10 05:21（Asia/Shanghai）左右已经重新启动。** 因此，不能将旧观测继续描述为当前状态，也不能把重启后暂时降低的内存视为修复。

- 当前三个 Order 容器仍使用 `ghcr.io/bliplink/ordersvr:sha-26b01eb`，并未因本轮调查升级镜像。
- Order A 启动时间约 2026-10-10 05:09（+08:00），重启计数 **1**；Order B 约 05:21，计数 **2**；Order C 启动更早，重启计数 **0**。本轮**未重启**容器、改变 Placement 或修改订单/资金数据。重启的直接原因尚未查明，不能直接归因于 GC，也不能声称完成 HA 验收。
- 重启后 Order B Docker 内存约 **1.02 GiB / 3 GiB**；在线两次 4 秒 GC 观测均没有出现新的 Full GC。大约 05:59（+08:00）B 老年代约 **91 MiB / 已提交 104 MiB / 上限 1536 MiB**。与上限的比率仅 **5.93%**，与“已提交”容量的比率却达 **87.55%**。A 约 **367.1 MiB / 1536 MiB 最大容量（23.90%）**，C 约 **39 MiB / 1536 MiB（2.54%）**。仅凭已提交老年代接近满载推断 OOM/Full GC 会产生误报。
- 最新只读门禁 `NOT_READY`：13 租户最近 300 秒有 **604 条市场成交落库行**，其中 1 户低于最低活动门槛；CPU PSI `avg10=54.32%`，Robot 利用率约 **102.69%** 的 1.25 核配额。B **3 秒 0 次 Full GC**，老年代使用最大容量的 **6.05%**，Docker 内存 **34.3%**。因此当前阻断主要是 **CPU 调度压力和 Robot 配额**，不是 B 的实时 Full GC。
- `market_trade` 是行情落库事件，**不是**真实下单 TPS 或资金一致性证明；不能用其数量宣布 200 租户能力已达标。

## 对最新 saas-crypto Order 源码的有界性初查

| 组件 | 已存在的约束/机制 | 仍需证明的风险 |
|---|---|---|
| `OrderManager.ht` / `htOrders` | 活动订单总数在本轮 B 性能日志约 680–770，当前 8 个订单簿；取消/成交有移除路径 | 此指标只统计活动订单，**不能反映所有缓存/幂等记录** |
| `OrderClientIdempotencyRegistry` | 默认终态保留 24 小时、最多 200,000 个终态条目；demo 终态采用特殊淘汰 | **非终态/在途**条目容量不能仅从活动订单数推断；需隔离环境比对对象分布、分区恢复、清理后数量 |
| `OrderPartitionJournal.PartitionState` | `recentRecords` 每分区最大 512 条，并将历史写 ChronicleQueue | 需观测 Chronicle/复制相关堆外内存、快照和临时对象，不可直接推定是该缓存泄漏 |
| `OrderAsyncReplicationDispatcher` | `maxPendingRecords` 配额检查、按分区队列退避发送 | 排队容量/滞后需要配合 ACK 和超时日志审计；不能仅靠 `pending` 存在断言泄漏 |
| `RecentExecutionFacade` | 每 `location,user,symbol` 最多 1,000 条 | **身份 key 数量无全局上限**，多租户长周期是否积累需隔离测试，不应改写回放或会计数据来“清理” |
| `OrderReplicationBatcher` | 每次批次 `maxRecords`，ACK 完成后释放等待记录；拒绝重复 sequence | 超时后的队列积压和按分区数量需要压力边界测试 |

这些是**源码审查线索，不是堆对象归因**；本轮未进行会触发 Stop-the-World 或大量 IO 的 `jmap -dump`，也没有更改关键幂等语义/Journal 清理规则以避免丢单。

## 已落地的监控修正

`scripts/observe-order-jvm-gc.py` 同时输出：

- `old_used_mib`、`old_committed_mib`、`old_committed_pct`；
- `old_max_mib`、`old_max_pct`（相对 JVM `MaxCapacity`）；
- `full` / `full_ms`、Young GC、Safepoint / Sync 时间的**区间增量**。

`tests/check-tenant-ramp-readiness.py` 改以 `oldGenerationMaxPercent` 判断超出 95% 的硬阻断，仍对任何新的 Full GC、CPU PSI、容器内存与市场持续性单独设阻断；无可读 HotSpot MaxCapacity 时 fail closed。不会因 B 重启后已提交老年代只有 102MiB、用了 98MiB，误判已触及 1536MiB 的最大容量。离线反例测试覆盖这一情形。

复核：

```bash
python3 -m unittest discover -s tests -p 'test_order_gc_perfdata.py' -v
python3 -m unittest discover -s tests -p 'test_tenant_ramp_readiness.py' -v
python3 scripts/observe-order-jvm-gc.py --samples 7 --interval 10
python3 tests/check-tenant-ramp-readiness.py --output /tmp/otc-ramp.json
```

**下一步要完成的事：** 连续采集 B 的 GC 次数、老年代上限占用和容器 RSS/CPU 变化至少数小时，结合 Order B 源码，验证是否随订单生命周期持续上涨且 Full GC 无法回落；在隔离环境中做内存对象快照与有界缓存修复，然后再执行 HA 滚动验收。当前 Demo 不允许盲目开启 50/200 租户压力测试。本轮未操作任何生产交易凭据或下单。
