# TradeSvr Fresh Partition Bootstrap 验证记录（2026-10-02）

## 1. 背景

在独立 failover integration 环境中，以全新本地 durable state 启动 TradeSvr A/B，同时 ZooKeeper 已存在 256 个 READY assignment 时，Trade lifecycle 会持续失败并反复输出：

```text
TRADE_LOCAL_RECOVERY_BASELINE_MISSING
```

该现象会阻止 Trade partition 进入 READY，并进一步造成 ProjectionSvr 在 Trade 尚未可服务时持续重试。此前观察到的 `invalid projection wire magic` 在 Trade READY 之后不再复现，因此 wire magic 异常属于该启动故障的下游连锁症状，而不是 Trade/Projection codec 版本不兼容。

## 2. 根因

`TradeRecoveryApplier.hasBaseline()` 的 authoritative recovery 要求本地至少具备下列之一：

- snapshot；
- journal delta；
- `committedStateSeq != 0`。

完全全新的 partition 三者都不存在，因此即使该 partition 的正确状态就是“空状态”，authoritative recovery 也会 fail closed。

不能通过单纯跳过 recovery 或直接 mark READY 解决，否则会破坏恢复边界，并且 replica 在未来 promotion 时仍缺少 durable baseline。

## 3. 修复设计

新增 `TradeFreshPartitionBootstrap`，只在能够证明 partition 为全新空状态时写入真实持久化的空 snapshot。

允许建立 fresh baseline 的条件全部满足时才执行：

1. assignment epoch 必须为 1；
2. 当前节点必须是该 assignment 的 primary 或同步 replica；
3. snapshot 不存在；
4. partition journal `lastSeq == 0`；
5. commit watermark：
   - `stateSeq == 0`
   - `stateEpoch == 0`
   - `commitMarkerSeq == 0`
6. 本地不存在属于该 partition 的 resident business state：
   - account balance
   - position
   - account/symbol config
   - open/order image
   - execution dedupe
   - cash request ledger
7. 在 partition lock 内再次读取 assignment，防止安装 baseline 过程中角色/epoch 变化。

满足条件后落盘：

```text
snapshotSeq=0
committedStateSeq=0
committedStateEpoch=0
epoch=1
locations=0
```

该 bootstrap **不会直接标记 partition READY**，也不会修改 `TradeRecoveryApplier` 的 fail-closed 规则。后续仍由正常 recovery planner/applier 读取该 durable snapshot，再经过 promotion readiness gate。

Primary 和 replica 都建立本地 fresh baseline，因此从未发生过交易的 partition 在未来切主时，不会因为目标 replica 没有本地 baseline 而无法 promotion。

## 4. 自动化测试

在 TradeSvr 源码导出基线上新增 focused tests，覆盖：

- primary 创建 seq=0 baseline；
- replica 创建本地 seq=0 baseline；
- planner 可在进程重启语义下重新读取 seq=0 snapshot；
- epoch > 1 不允许 fresh bootstrap；
- 已有 journal history 不允许 fresh bootstrap；
- 已有 resident balance/business state 不允许 fresh bootstrap。

随后运行 TradeSvr 全量测试：

```text
401 tests
0 failures
0 errors
```

## 5. 真实 integration 空盘启动

测试环境：

```text
ZooKeeper: dc-saas-int-zk / 127.0.0.1:32482
TradeSvrA: service 34640 / replication 19421
TradeSvrB: service 34641 / replication 19422
Trade root: /dc/cluster/tradesvr/partitions
durable root: /data/dc-saas-failover-integration/data
image: local/dc-saas-tradesvr:fresh-bootstrap-20261002
```

清空 TradeSvrA/B durable dirs 后，以 256 个 READY assignment 启动。

结果：

```text
TradeSvrA primary READY: 128/128
TradeSvrB primary READY: 128/128

TradeSvrA local latest.json: 256/256
TradeSvrB local latest.json: 256/256

TRADE_LOCAL_RECOVERY_BASELINE_MISSING: 0
```

两端均为所有 resident partitions 建立本地 seq=0 baseline，而不是只为本机 primary 建 baseline。

## 6. Untouched Partition 双向 Role Reversal

选择从未发生业务写入的 `P000`。

初始状态：

```text
epoch=1
assignmentVersion=1
primary=TradeSvrA
replica=TradeSvrB
dataVersion=0

TradeSvrA snapshotSeq=0 committedStateSeq=0 epoch=1 locations=0
TradeSvrB snapshotSeq=0 committedStateSeq=0 epoch=1 locations=0
```

### 6.1 A → B

通过 `trade_cluster_transition_host.py` 生成 dry-run plan，确认只修改 P000，随后 CAS apply：

```text
epoch: 1 -> 2
assignmentVersion: 1 -> 2
primary: TradeSvrA -> TradeSvrB
replica: TradeSvrB -> TradeSvrA
dataVersion: 0 -> 1
```

TradeSvrB 日志：

```text
TRADE_PARTITION_RECOVERY_STARTED node:TradeSvrB, partition:P000, epoch:2
TRADE_PARTITION_READY node:TradeSvrB, partition:P000, epoch:2, committedStateSeq:0, locations:0
TRADE_PARTITION_RECOVERY_TIMING ... totalMs:21, snapshotSeq:0, deltaFromSeq:0, deltaThroughSeq:-1
```

结果：PASS。

### 6.2 B → A

随后生成 B→A restore plan：

```text
epoch: 2 -> 3
assignmentVersion: 2 -> 3
primary: TradeSvrB -> TradeSvrA
replica: TradeSvrA -> TradeSvrB
dataVersion: 1 -> 2
```

TradeSvrA 日志：

```text
TRADE_PARTITION_RECOVERY_STARTED node:TradeSvrA, partition:P000, epoch:3
TRADE_PARTITION_READY node:TradeSvrA, partition:P000, epoch:3, committedStateSeq:0, locations:0
TRADE_PARTITION_RECOVERY_TIMING ... totalMs:1, snapshotSeq:0, deltaFromSeq:0, deltaThroughSeq:-1
```

最终：

```text
P000 epoch=3
primary=TradeSvrA
replica=TradeSvrB
state=READY
dataVersion=2
```

结果：PASS。

该结果直接证明：fresh bootstrap 生成的 replica-local baseline 能支撑后续 untouched partition promotion，而非仅让首次启动绕过 recovery。

## 7. 验收工具 Race 修复

B→A CAS 后第一次立即运行 `verify-ready` 时，assignment 已更新，但目标节点尚未来得及输出 READY 日志，因此出现假失败。

实际约 1–2 秒后目标节点正常输出 READY，Trade recovery 本身没有失败。

已修正 `trade_cluster_transition_host.py verify-ready`：

- 默认最多等待 30 秒；
- 周期性轮询目标容器 READY evidence；
- 等待前先验证 assignment；
- 看到目标 epoch READY 后再次验证 assignment 未变化；
- 新增 timeout/poll 参数；
- 新增“第一次日志为空、第二次出现 READY”的 race 单测。

验证：

```text
python3 -m unittest tests.test_trade_cluster_transition_host
4 tests
OK
```

真实 P000 restore plan 重新执行 `verify-ready`：PASS。

对应部署仓库 commit：

```text
c5301cb44a7f52554abee682ec8be62364b7c538
test(trade): wait for partition readiness evidence
```

## 8. Projection 连锁问题复核

Trade baseline 缺失期间，ProjectionSvr 曾持续出现：

```text
invalid projection wire magic
```

检查结果：

- Trade 与 Projection 所用 Common JAR SHA 一致；
- Projection 使用 partition-aware `requestAsyncToPartition`；
- Trade binary projection handler 存在；
- Trade 256 partitions READY 后重新启动 Projection：
  - `invalid projection wire magic = 0`
  - invalid Trade/Order projection binary = 0
  - 启动初期约 4–5 秒出现 GAP retry，原因是 exact Trade route 尚未 online；
  - 稳定后 GAP retry = 0；
  - 日志恢复到 KB 级，不再出现 GB 级风暴。

因此当前证据支持：wire magic 异常是 Trade recovery 未 READY 的下游症状，不是 codec incompatibility。

## 9. Release / Upstream 阻塞

当前正式 Trade GitHub 仓库：

```text
bliplink/com.app.dc.tradesvr
```

当前 integration 所依据的部署镜像 revision：

```text
31986253ed36117104b5b67b6d3cb2f3e0fefbfb
```

该 revision 已不在远端可 fetch 对象中。

对比部署源码导出与远端 `origin/saas-crypto`，存在约 64 个文件 delta，包括：

- bounded recovery；
- cash request ledger / cash recovery；
- posting validation；
- snapshot/recovery 内存与 streaming 优化；
- recovery ownership / order image；
- 多组已验证测试；
- 本次 fresh-bootstrap。

此外部署源码依赖未发布的本地 Maven 坐标：

```text
io.github.bliplink:com.app.cluster-recovery:3.0.14-recovery-e95850b-1
```

因此当前**不能**把 fresh-bootstrap 作为一个小补丁直接 cherry-pick 到远端 `saas-crypto` 后发布，否则可能回退当前部署镜像已经具备的安全能力。

正式 release 前应先恢复/重建“当前部署 Trade 源码基线 + 依赖版本”，再将 fresh-bootstrap 纳入该基线并重新跑完整 CI/HA 验收。

## 10. 当前结论

当前可判定：

```text
Trade fresh bootstrap defect: reproduced
Trade fresh bootstrap code fix: PASS
Trade full unit suite: 401/401 PASS
fresh empty A/B boot: PASS
A/B each 256 local baselines: PASS
untouched P000 A->B promotion: PASS (21ms)
untouched P000 B->A recovery: PASS (1ms)
transition readiness race fix: PASS
formal release/upstream merge: NOT YET
formal SaaS rollout: NOT TOUCHED
```