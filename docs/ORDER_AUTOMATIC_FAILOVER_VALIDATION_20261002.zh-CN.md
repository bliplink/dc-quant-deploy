# Order 自动 Failover 隔离验证记录（2026-10-02）

> 范围：仅 Colima 隔离集群 `dc-saas-order-cluster-dev`。没有修改正式 SaaS 运行环境。

## 1. 本轮实现

### Common

提交：

```text
97d4eff30bd3 feat(common): add lease-guarded partition failover runtime
```

核心内容：

- ZooKeeper session timeout / connection timeout 可通过配置覆盖；
- 受 ephemeral lease 保护的单 controller；
- membership + assignment watcher；
- version CAS 更新 assignment；
- epoch 单调递增；
- fail-closed 的 `PartitionFailoverController`；
- assignment JSON 未知字段保留；
- exact-node replication TCP 增加向后兼容的只读 control request/response；
- 借用 OrderSvr 已有 ZooKeeper session，不创建第二套控制面 session；
- runtime 关闭时只释放自己的 controller lease，不关闭全局 ZooKeeper client。

Common 全量测试：

```text
108 tests
0 failures
0 errors
0 skipped
```

隔离构建 Common JAR SHA-256：

```text
739c86e79dd0684a1dfa1bfcabc6b0f0ff12a80d16b0c3221ec821e06cf35d04
```

### OrderSvr

提交：

```text
45ac529fc307 feat(order): add automatic safe partition failover
```

基线已包含：

```text
71e87ab fix(order): serialize per-partition replica sends
```

核心内容：

- `OrderAutomaticFailoverService`；
- `OrderFailoverProofProvider`；
- replication TCP 上的 `FAILOVER_PROOF` control handler；
- `OrderFailoverPromotionSafety`；
- 候选新主和另一同步副本必须给出一致的 durable committed prefix；
- commit watermark、journal tail、snapshot baseline、assignment epoch/role 全部校验；
- 任一 proof 超时、旧版本不支持、prefix 不一致、未提交 STATE 尾、异步复制模式都会 fail-closed；
- 自动 Failover 默认关闭，必须显式配置开启。

Order 聚焦测试通过；全量最终门禁：

```text
241 tests
0 failures
0 errors
0 skipped
```

说明：全量无重跑时曾分别出现两个既有并发时序测试单次抖动：
`OrderBusinessFailoverIntegrationTest` 和
`OrderReplicationBatcherTest.concurrentRecordsShareOneCumulativeAck`。
前者单独连续 3/3 PASS，后者连续 10/10 PASS；使用 Surefire 失败自动重跑后的完整 241 用例全绿。

## 2. 隔离镜像

OrderSvr：

```text
local/dc-saas-ordersvr:diag-45ac529-20261002
Order revision: 45ac529fc307
Common revision: 97d4eff30bd3
Common SHA-256: 739c86e79dd0684a1dfa1bfcabc6b0f0ff12a80d16b0c3221ec821e06cf35d04
```

GW：

```text
local/dc-saas-gateway:cluster-dev-reset-20261002
Common revision: 97d4eff30bd3
Common SHA-256: 739c86e79dd0684a1dfa1bfcabc6b0f0ff12a80d16b0c3221ec821e06cf35d04
```

镜像内已验证：

- `OrderAutomaticFailoverService.class` 存在；
- OrderSvr / GW 内嵌 Common JAR SHA 完全一致。

## 3. 隔离运行配置

三台 OrderSvr：

```properties
order.cluster.failover.enabled=true
order.cluster.failover.nodes=OrderSvrA,OrderSvrB,OrderSvrC
order.cluster.failover.safetyPollMillis=1000
order.cluster.failover.minimumLiveSynchronizedReplicas=2
```

ZooKeeper client：

```text
sessionTimeoutMs=6000
connectionTimeoutMs=5000
negotiated timeout=6000
```

ZooKeeper server max session timeout 保持 40000ms，因此 6000ms 是客户端真实请求并协商生效，不是服务端截断。

## 4. 故障前门禁

P027：

```json
{
  "partitionId": "P027",
  "epoch": 179086255931373,
  "primary": "OrderSvrA",
  "replicas": ["OrderSvrB", "OrderSvrC"],
  "learners": [],
  "state": "READY"
}
```

controller lease：

```text
owner = OrderSvrA:4a9e7159-0cc3-4b0b-86e8-f54285438f15
ephemeralOwner = A 的 ZooKeeper session
```

正常 GW 逻辑写入：

```text
AUTO-FAILOVER-BASELINE-08
replicaStatus:OK
```

## 5. 真实故障注入：kill A

本轮没有启动 Python controller，也没有手工改 assignment。

故障注入：

```text
docker kill dc-saas-cluster-ordersvr-a
```

关键时间：

```text
kill time                    2026-10-02 06:10:01.204 +08
automatic assignment CAS     2026-10-02 06:10:09.542 +08
B promotion READY            2026-10-02 06:10:10.115 +08
GW first successful write    kill 后 9520 ms
```

即：

- kill → 自动 CAS：约 **8.34 秒**
- CAS → B READY：约 **0.57 秒**
- kill → GW 恢复成功写入：约 **9.52 秒**

controller 自动日志：

```text
ORDER_AUTO_FAILOVER_APPLIED
partition:P027
oldPrimary:OrderSvrA
newPrimary:OrderSvrB
oldEpoch:179086255931373
newEpoch:179086255931374
```

自动接管后的 assignment：

```json
{
  "partitionId": "P027",
  "epoch": 179086255931374,
  "assignmentVersion": 1,
  "primary": "OrderSvrB",
  "replicas": ["OrderSvrC"],
  "learners": ["OrderSvrA"],
  "state": "READY"
}
```

controller lease 自动转移到 B：

```text
OrderSvrB:197b5e32-20ac-4fe9-86ad-497e0e9b2d32
```

新主 B 的恢复和复制：

```text
ORDER_PARTITION_PROMOTION_READY node:OrderSvrB
eventId:AUTO-FAILOVER-083
replicaStatus:OK
```

因此本轮证明：

1. 主节点 JVM 失联后，membership 与 controller lease 随同一 ZooKeeper session 到期；
2. B/C 中只有一个 controller 获得 lease；
3. controller 在 CAS 前完成 Order durable-prefix proof；
4. assignment 自动从 A 推进到 B，并递增 epoch；
5. B 完成 commit-aware promotion 后才 READY；
6. GW 在约 9.52 秒内恢复成功写入；
7. B 成为主后仍保留 C 同步副本，没有以单副本冒充正常同步耐久。

## 6. A 重返与安全恢复

A 重启后没有自动抢主，而是先保持 learner。

恢复流程：

1. 启动 A 并等待 membership/health；
2. B 保持 primary；
3. 将 A+C staged 为 B 的同步 replicas；
4. 发送一笔写入触发 A catch-up；
5. 日志确认 `replicaStatus:OK`；
6. 再执行计划内 B → A 切换；
7. A 完成新的 promotion barrier 后 READY。

中间同步写：

```text
AUTO-RESTORE-STAGE-00
epoch=179086255931375
seq=66497
replicaStatus:OK
```

最终 assignment：

```json
{
  "partitionId": "P027",
  "epoch": 179086255931376,
  "assignmentVersion": 3,
  "primary": "OrderSvrA",
  "replicas": ["OrderSvrB", "OrderSvrC"],
  "learners": [],
  "state": "READY"
}
```

最终正常写：

```text
AUTO-RESTORE-FINAL-00
seq=66501
replicaStatus:OK
```

## 7. 当前隔离运行态

当前隔离集群：

- OrderSvrA/B/C：新 Order 镜像；
- GW：新 Common 镜像；
- P027：A 主 + B/C 双同步副本 + READY；
- 自动 Failover：在三台 OrderSvr 的隔离 application.properties 中显式开启；
- 正式 SaaS 环境：未修改。

本轮为了避免混入其他会话尚未提交的 C 节点部署脚本改动，没有提交 `deploy-order-cluster-dev.sh` 的临时 failover 配置；隔离运行配置是直接写入 Colima 的隔离配置目录。

## 8. 单同步副本 fail-closed 验证

从 `P027 = A 主 + B/C 双同步副本` 基线同时停止 A 和 C，仅保留 B。

故障前：

```text
epoch=179086255931376
dataVersion=40
FAILCLOSED-BASELINE
replicaStatus:OK
```

停止 A+C 后持续探测约 13 秒：

```text
83 attempts
0 success
```

B controller 持续记录：

```text
ORDER_AUTO_FAILOVER_RECONCILE
partition:P027
outcome:INSUFFICIENT_SYNCHRONIZED_REPLICAS
oldPrimary:OrderSvrA
epoch:179086255931376
```

故障期间：

- P027 primary 仍为 A；
- epoch 仍为 `179086255931376`；
- ZooKeeper `dataVersion` 仍为 40；
- 没有 `ORDER_AUTO_FAILOVER_APPLIED`；
- 没有任何成功业务写入。

因此已证明：只剩 B 一个同步副本时，controller 不会为了可用性牺牲同步耐久门禁。

随后只恢复 C，A 继续停机。C 重新健康并注册后，B+C 两份 durable proof 再次可用，controller 才允许自动 A→B：

```text
C healthy/membership ready
A -> B automatic CAS
new epoch=179086255931377
dataVersion=41
B promotion READY
FAILCLOSED-RECOVER-000
replicaStatus:OK
```

从 C 容器启动到 C 健康/注册约 18.39 秒；健康后到 CAS 约 2.16 秒；CAS 到 B READY 约 68ms。这里容器健康启动时间不属于故障检测窗口本身。

之后 A 按 learner → synchronized replica → planned primary 的顺序恢复，最终：

```text
P027 epoch=179086255931379
primary=OrderSvrA
replicas=OrderSvrB,OrderSvrC
learners=[]
READY
FAILCLOSED-RESTORE-FINAL-00
replicaStatus:OK
```

## 9. ZooKeeper 整体断连 / 重连验证

在 A 主 + B/C 双同步副本的健康状态下停止隔离 ZooKeeper 9 秒，超过 6 秒 client session timeout。

断连期间：

- A/B/C 进程和 health 均保持正常；
- controller 无法获得有效控制面，因此没有 assignment CAS；
- P027 业务数据面仍可基于已缓存 assignment 正常完成一笔同步复制探测；
- 没有出现双主。

ZK 重启后三台客户端均重新建立连接并记录：

```text
CONNECTION_CLOSED
...
Session establishment complete ... negotiated timeout = 6000
CONNECTION_SUCCESS
```

恢复后：

```text
P027 epoch=179086255931379
dataVersion=43
primary=OrderSvrA
replicas=OrderSvrB,OrderSvrC
```

与故障前完全一致；没有 `ORDER_AUTO_FAILOVER_APPLIED`。三节点 membership 恢复，controller lease 仍只有一个 owner，最终写 `ZK-RESTART-FINAL-00` 为 `replicaStatus:OK`。

因此已证明：ZooKeeper 控制面不可用时 controller fail-closed，不会凭 TCP 状态自行改派。

## 10. stale epoch wire fencing 验证

直接对真实 B 节点 replication TCP `127.0.0.1:19112` 使用 Common binary protocol 注入一个 `currentEpoch - 1` 的伪旧主复制 batch。

注入前 B durable proof：

```text
currentEpoch=179086255931379
journalLastSeq=66517
role=SYNC_REPLICA
```

返回 ACK：

```text
status=3 (STALE_EPOCH)
partition=P027
batchEpoch=179086255931378
message=current epoch=179086255931379
```

注入后重新读取 B durable proof：

```text
journalLastSeq=66517
assignmentEpoch=179086255931379
```

journal tail 没有变化，`STALE-EPOCH-INJECT` 没有被追加。因此旧 epoch writer 在 replication wire 层被明确围栏，而不是只依赖路由层避免请求到达旧节点。

## 11. controller lease holder 故障与竞争验证

验证开始时 controller lease owner 为 B，而 P027 primary 为 A。

只停止 B：

```text
old lease=OrderSvrB:197b5e32-20ac-4fe9-86ad-497e0e9b2d32
```

约 8.39 秒后，lease 唯一转移到 A：

```text
new lease=OrderSvrA:bf1e757f-9f01-4ca1-a16d-990973bf6b6c
```

由于 P027 primary A 始终在线：

```text
P027 epoch=179086255931379
dataVersion=43
primary=OrderSvrA
```

完全没有变化，也没有 `ORDER_AUTO_FAILOVER_APPLIED partition:P027`。

同一时段 A controller 对另一个以 B 为 primary 的 P132 观察到副本条件不足，明确记录 `INSUFFICIENT_SYNCHRONIZED_REPLICAS`，也没有误切。

B 恢复 membership/health 后，最终写 `LEASE-RACE-FINAL-00` 第一次即成功，A 日志 `replicaStatus:OK`。

因此已验证 controller lease holder 自身失联时，不会出现双 controller 写 assignment，也不会把“controller 故障”误判成“当前 primary 必须切换”。

## 12. 当前隔离运行态

当前隔离集群再次恢复为：

- OrderSvrA/B/C：healthy；
- GW：healthy；
- P027：A 主 + B/C 双同步副本 + READY；
- 自动 Failover：仅隔离 application.properties 显式开启；
- Common / Order 镜像仍为本轮不可变隔离镜像；
- 正式 SaaS 环境：未修改。

## 13. 256 分区并行自动 Failover 压测

为避免污染 P027/P132 故障证据环境，本轮临时停止隔离容器但保留原 bind-mounted 数据目录，另建：

```text
/data/dc-saas-order-cluster-scale-256
```

仅复制 control / gateway / node 配置，不复制 journal、snapshot 或 ZooKeeper 数据。scale ZooKeeper fresh seed：

```text
P000 ... P255
256 partitions
epoch=1
primary=OrderSvrA
replicas=OrderSvrB,OrderSvrC
state=READY
```

统一资源配置：

```text
Order A/B/C: 3GiB memory, 1.5 CPU, -Xmx2048m
GW: 768MiB memory, 0.5 CPU, -Xmx384m
ZooKeeper client session timeout: 6000ms
connection timeout: 5000ms
```

故障前门禁：

- A/B/C/GW 全部 healthy；
- A 当前容器 256/256 分区 READY；
- 三节点没有 recovery/promotion failure；
- B/C 对 P000/P127/P255 的 durable proof 均通过；
- controller lease 唯一；
- GW 真实逻辑路由命中 P231；
- 故障前 P231 写入 `replicaStatus:OK`。

故障注入：

```text
docker kill dc-saas-cluster-ordersvr-a
```

本轮不运行 Python controller。256 分区全部由 OrderSvr 内置 lease/watcher/proof/CAS runtime 完成接管。

总体结果：

```text
256/256 automatic CAS
256/256 OrderSvrB promotion READY
256/256 ZooKeeper assignment guard PASS
0 failover/promotion errors

kill -> all CAS observed        ≈ 10.49s
kill -> all READY observed      ≈ 12.22s
P231 GW first successful write  ≈ 11.74s
```

按分区统计：

| 指标 | min | p50 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|
| kill → CAS | 7.230s | 8.981s | 10.522s | 10.638s | 10.731s |
| kill → READY | 8.134s | 9.989s | 11.794s | 12.029s | 12.054s |
| CAS → READY barrier | 0.249s | 1.280s | 1.695s | 1.782s | 1.815s |

首尾记录：

```text
first CAS partition   P000
last CAS partition    P255
first READY partition P027
last READY partition  P240
```

自动接管后 256 个 assignment 全部满足：

```text
primary=OrderSvrB
replicas=[OrderSvrC]
learners=[OrderSvrA]
epoch=2
state=READY
```

P231 的 GW 连续探测在故障期间返回 `SERVER.OrderSvr is not Online`，第 126 次探测恢复为 `code=0 / OK`，从 kill 到成功约 11.743 秒。

接管完成后的资源快照：

```text
OrderSvrB CPU≈34.23% MEM≈792.7MiB / 3GiB
OrderSvrC CPU≈0.18%  MEM≈631.9MiB / 3GiB
GW        CPU≈0.13%  MEM≈200.7MiB / 768MiB
```

因此在当前单机 Colima 测试资源下，256 分区并行 failover 的 p99 恢复时间约 12.03 秒，且没有发现双主、错误 epoch、proof failure 或 promotion failure。

测试结束后 scale 容器已停止，scale 数据目录保留约 294MiB 供复测；原证据环境已重新挂回：

```text
P027 epoch=179086255931379
dataVersion=43
primary=OrderSvrA
replicas=OrderSvrB,OrderSvrC
state=READY
```

原 control/config SHA 未变化，恢复后的 `POST-SCALE256-EVIDENCE-010` 写入为 `replicaStatus:OK`。

## 14. 仍未完成的故障矩阵

本轮已完成：

- 健康三节点同步 → A 失联 → B 自动升主 → C 保持同步副本；
- 单同步副本不足时 fail-closed；
- 第二同步副本恢复后再自动接管；
- A learner 重返并恢复双同步副本；
- ZooKeeper 断连/重连 fail-closed；
- controller lease holder 失联与唯一 lease 转移；
- stale epoch replication wire fencing；
- 256 分区并行 failover p50/p95/p99。

仍需单独验证：

1. Trade/Projection/Robot 下游业务基线已验证通过；仍需在包含新 Order 自动 failover 代码的独立三节点 integration stack 中做“持续业务流 + 主节点故障”联合回归；
2. 若要支持“副本失联但主继续接单”，必须实现并显式标记 `DEGRADED_LOCAL_DURABLE`，不能复用普通 `READY` 或伪造同步 ACK；
3. Order PR CI 与正式 Order 镜像 Common provenance 已补齐；正式发布仍需 Common/Order PR 合并、Common 正式版本可用、旧 cluster-dev workflow 升级、不可变镜像与最终业务验收。

## 15. 下游业务基线、CI provenance 与隔离性补充

### 15.1 Trade / Projection / Robot 业务基线

当前完整 `dc-saas-*` SaaS 栈仍运行旧 Order revision `943b6dd...`，镜像中不存在 `OrderAutomaticFailoverService`。因此本节只证明下游业务链健康，不把它表述为“新自动 failover 联合回归通过”。

当前 Trade ZooKeeper assignment 实时检查：

```text
256/256 READY
TradeSvrA primary = 128
TradeSvrB primary = 128
current assignment duplicate primary = 0
```

近 10 分钟门禁：

```text
TradeSvrA recovery/uncommitted-tail errors = 0
TradeSvrB recovery/uncommitted-tail errors = 0
Projection PARTITION_NOT_READY / unroutable errors = 0
```

Robot 专用隔离租户 `R376BD` 真实 E2E 通过：

- APSSvr Binance ticker 驱动的 10 bid + 10 ask 深度稳定；
- Tape K-line 产生成功；
- 用户真实吃单后，被部分成交档位自动补回 10+10；
- trader execution 持久化 2 条；
- Robot 内部 Demo 订单持久化计数为 0；
- foreign-location orders 为 0；
- 未提供外部 Binance credential，hedge 保持关闭。

本轮 Robot E2E 前后 Projection watermark：

```text
Order projection max journal_seq: 2383429 -> 2385310
Trade projection max journal_seq: 1073729 -> 1074629
```

说明真实 Order/Trade 业务事件持续推动 Projection 前进。

`run-saas-acceptance.sh --quick` 的 service log / Robot log / MD cluster / Order cluster / Trade cluster 配置检查均通过；runtime validation 随后被一个已滞后的 Web 门禁阻断：当前主站标题为 `OpenTradingCore`，脚本仍硬编码要求 `<title>Trade</title>`。这不是 Trade/Projection/Robot 运行故障，应更新验收条件而不是回退主站标题。

### 15.2 Order PR CI 与正式镜像 Common provenance

Order 新增提交：

```text
81f5819bf4eb9d82cecc84400fb60ed6873a4bc0
ci(order): pin failover common dependency
```

已推送到 `origin/fix/order-recovery-boundary`。

`partition-cluster-ci.yml` 现在固定：

```text
com.app.common repo: bliplink/com.app.common.git
commit: 97d4eff30bd350da334da2edf3ffd101f3a1734d
CI-installed GAV: io.github.bliplink:com.app.common:3.0.14
```

本地 JDK8/Maven 容器等价验证：

```text
Common exact commit build/install: PASS
Order cluster tests: 154
failures: 0
errors: 0
skipped: 0
```

正式 `docker-publish.yml` 同步固定到相同 Common revision，并把发布 GAV 更新为 `3.0.14`。Order release package 验证：

```text
packaged Common: com.app.common-3.0.14.jar
SHA-256: 9996fbbc9b300216dba8c990a2101f91994e12c7a03ee5e3af9c858c1da7846b
PartitionFailoverController.class: present
ReplicationControlRequest.class: present
package provenance: PASS
```

旧 `cluster-dev-publish.yml` 仍绑定旧 `feature/cluster-local-common` / Common 3.0.5 / 旧 GW 开发链，尚未机械升级；它需要与 GW 依赖一起单独迁移，避免只改版本号造成开发镜像链断裂。

### 15.3 固定容器名并发冲突与证据环境恢复

一次早期 scale 尝试复用了固定 `dc-saas-cluster-*` 容器名；期间另一会话重新创建了同名 dev 容器，导致故障注入实际命中 dev OrderSvrA。P027 真实自动切到 B 后，按 dataVersion CAS + staged sync-replica + `replicaStatus:OK` 门禁完成安全恢复，没有回退 epoch。

最终 dev P027：

```text
epoch=179086255931382
assignmentVersion=9
dataVersion=46
primary=OrderSvrA
replicas=[OrderSvrB,OrderSvrC]
learners=[]
state=READY
final probe eventId=RESTORE-AFTER-SCALE-080113-FINAL
replicaStatus=OK
```

后续 256 分区复核改为完全独立的容器名、端口、ZooKeeper 端口和 partition root，避免再与并发会话共享控制面。

### 15.4 当前联合业务门禁结论

- 自动 failover 控制面、proof、CAS、256 分区规模指标：已通过；
- 当前完整 SaaS 的 Trade/Projection/Robot 业务链：基线已通过；
- **新 Order 自动 failover + Trade/Projection 持续真实业务流的同一套 integration 环境联合故障回归：已关闭并通过。**
- 故障后的业务分区能自动切主并继续撮合/平仓；不满足同步副本门槛的其它分区保持 fail-closed，没有误切主。

旧 primary 作为 learner 追平后的自动冗余自愈也已在后续第 19 节工程化并通过真机验证：只有 durable proof 完全一致、无未提交 STATE tail、controller lease 有效且 ZooKeeper CAS 成功时，learner 才会自动晋回同步 replica。正式环境仍未部署本轮自动 failover 代码。

## 16. 256 分区独立 bridge 复核

为排除并发会话复用固定容器名、宿主机 host-network 端口冲突和外部控制面干扰，另外建立完全独立的 Docker bridge 复核环境。该环境使用独立 network、独立 ZooKeeper、独立 OrderSvr A/B/C 容器、独立 partition root /dc/cluster/ordersvr-scale256-bridge/partitions 和独立数据根 /data/dc-saas-order-cluster-scale-256-bridge，不与宿主机现有 Order/GW/ZooKeeper 端口共享监听。

故障前门禁全部通过：256/256 assignments 均为 epoch=1、assignmentVersion=1、primary=OrderSvrA、replicas=[OrderSvrB,OrderSvrC]、learners=[]、state=READY、ZooKeeper dataVersion=0；A/B/C membership 全部存在；controller lease 唯一；三节点 ZooKeeper negotiated timeout 均为 6000ms。

故障注入为 SIGKILL OrderSvrA，时间 2026-10-02T10:01:50.896+08:00；不运行外部 Python controller。结果为 256/256 automatic CAS、256/256 OrderSvrB promotion READY、256/256 assignment guard PASS。接管后全部 assignment 为 primary=OrderSvrB、replicas=[OrderSvrC]、learners=[OrderSvrA]、epoch=2、assignmentVersion=2、dataVersion=1；controller lease 转移到 OrderSvrC；没有发现 CAS_CONFLICT、STALE_BEFORE_CAS、PROMOTION_UNSAFE 或 ORDER_PARTITION_RECOVERY_FAILED。

| 指标 | min | p50 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|
| kill → CAS | 7.683s | 9.136s | 10.853s | 11.001s | 11.129s |
| CAS → READY | 0.494s | 1.526s | 5.650s | 6.491s | 6.743s |
| kill → READY | 8.437s | 11.137s | 16.350s | 17.199s | 17.558s |

补充观测：CAS span=3.446s，READY span=9.121s；first CAS=P000，last CAS=P255，first READY=P027，last READY=P240。

因此当前单机 Colima 环境下已有两次独立 256 分区样本：样本 A（含 GW）kill→READY p99≈12.03s；样本 B（完全 bridge 隔离）kill→READY p99≈17.20s。两次结果说明当前测试机资源和 JVM/Chronicle 初始化/调度抖动会明显影响 256 分区 promotion tail；容量/SLO 不应只取单次最好值。若按当前两次样本做保守工程门禁，可先把 256 分区 kill→READY p99 预算按约 18 秒看待，再通过多轮重复压测确定稳定分布。

本轮继续尝试验证 A 重返 learner 时，独立 scale 测试的 ZooKeeper/B/C 容器被外部测试流程停止，A 随后因 bridge ZooKeeper DNS 不可解析而启动失败。该现象属于测试环境生命周期中断，不计为 OrderSvr recovery failure；因此本轮 bridge 样本只记为“主故障自动接管 + 256 分区 promotion”通过，不新增“A 重返 learner”PASS。此前 P027 单分区故障矩阵中的 learner 重返与双同步副本恢复证据仍有效。

## 17. 持续真实业务流故障回归发现与 safety 修复

在包含新 Order A/B/C、Trade A/B、Projection、GW、Login、MySQL 和交易 Web 的独立 integration 栈中，使用隔离租户 `HAFO_E2E` 执行持续真实业务流。故障前门禁为 256/256 Order assignment 均为 `A primary + B/C synchronized replicas`、epoch=1、dataVersion=0，controller lease 唯一在 A。

故障前业务已实际通过：

- buyer/seller 正常登录并入金；
- 一笔 60000 × 0.001 BTCUSDT 真实撮合成功；
- 连续 3 次挂单 → 撤单循环成功，0 次失败；
- 随后对 `OrderSvrA` 执行 SIGKILL。

A 的 ZooKeeper ephemeral membership 消失后，controller lease 正确转移到 B，但旧 integration Order 镜像仍未执行 assignment CAS。B 持续返回：

```text
ORDER_AUTO_FAILOVER_RECONCILE ... outcome:PROMOTION_UNSAFE
```

直接通过 exact-node replication control RPC 查询 B/C 的 `FAILOVER_PROOF` 后确认，两副本真正的 durable state 前缀一致：

```text
journalLastSeq           equal
committedStateSeq        equal
committedStateEpoch      equal
commitMarkerSeq          equal
lastStateSeq             equal
baselineEpoch            equal
```

但由于节点恢复/压缩时点不同，snapshot 物理压缩点不同。例如 P000：

```text
OrderSvrB baselineSeq=0,  baselineSnapshotId=P000-1-0-...
OrderSvrC baselineSeq=19, baselineSnapshotId=P000-1-19-...
journalLastSeq=30 on both nodes
baselineEpoch=1 on both nodes
```

部署中的旧 `45ac529` safety 实现错误地要求 `baselineSeq` 与 `baselineSnapshotId` 也完全相同，因此把“相同 durable prefix、不同 snapshot compaction point”的同步副本误判为不安全。

修复内容：

```text
fix(order): allow equivalent replica snapshot baselines
remote commit: e7535d075ac24732f9b9ba380cd0bc1537fd260b
```

修复后的 safety 仍要求 journal / committed state / commit marker / last state / baseline epoch 一致，只取消对 snapshot 物理文件身份和压缩 seq 完全一致的要求。新增测试覆盖：

- 相同 durable state + 不同 snapshot compaction point：允许 promotion；
- baseline epoch 不同：仍拒绝 promotion。

验证：

```text
focused OrderFailoverPromotionSafetyTest: PASS
Order full suite: 243 tests
failures: 0
errors: 0
```

随后不恢复 A、不清空故障现场，只把 C、B 依次替换成包含该提交的新 Order integration 镜像。B 重启期间只有 C 一个同步副本时继续 fail-closed；B 返回后，controller 自动完成：

```text
256/256 automatic CAS
primary=OrderSvrB
replicas=[OrderSvrC]
learners=[OrderSvrA]
epoch=2
assignmentVersion=2
dataVersion=1
state=READY
```

原故障现场修复后的真实业务恢复验证：

```text
order churn: 18/18 success
failed cycles: 0
matched trade #1: PASS, ~1.91s
matched trade #2: PASS, ~1.79s
```

MySQL 权威状态检查：

```text
HAFO_E2E orders=48
executions=8
open_orders=0
duplicate ClOrdID=0
duplicate ExecID=0
```

Order B/C、Trade A/B、GW 均保持运行且无 OOM。Projection 在 B/C 重启/切换窗口出现过短暂 `invalid projection wire magic`，但稳定后连续 5 分钟：

```text
invalid projection wire magic = 0
Projection GAP retry          = 0
```

因此本轮证明：

1. 持续真实业务流能够暴露旧 snapshot-identity safety 误判；
2. fail-closed 行为本身正确，没有发生不安全切主或双主；
3. 修复后的 safety 可在原故障现场完成 256/256 自动接管；
4. 接管后的 Order/Trade 真实交易与数据库一致性恢复通过。

仍需最后补一轮“故障前即全部使用 e7535d0 新镜像”的干净连续业务流 + SIGKILL A 复测，才能把第 15.4 节的联合故障回归门禁改为完全关闭。

## 18. 干净持续业务流 + SIGKILL primary 最终联合回归

使用独立 integration tenant `IHF003_E2E`，通过真实 Web 登录、入金、挂单、撤单、撮合、持仓和平仓链路执行最终联合故障回归。业务路由键 `IHF003_E2E\u001f4\u001fBTCUSDT` 按 CRC32/256 映射到 `P143`。

故障前 `P143` 通过 exact-node control RPC 证明为安全双副本拓扑：

```text
primary=OrderSvrA
replicas=[OrderSvrB,OrderSvrC]
learners=[]
epoch=4
assignmentVersion=7
state=READY
```

故障注入点位于 buyer/seller 登录、两笔入金、10000 限价挂单与撤单完成之后；浏览器随后每 250ms 通过真实 `/httpapi/ -> OrderSvr.queryOpenOrder` 持续探测业务可用性。收到 `fault-ready` 后立即对 `OrderSvrA` 执行 SIGKILL。

浏览器实际观测：

```text
firstFailureMs = 265ms
recoveryMs     = 7069ms
outageMs       = 6804ms
probe samples  = 27
failed samples = 25
```

故障期间返回业务错误码 `1003`，恢复后重新返回 `code=0`。自动 failover 最终将 P143 切到：

```text
primary=OrderSvrB
replicas=[OrderSvrC]
learners=[OrderSvrA]
epoch=5
assignmentVersion=8
state=READY
```

同一节点故障中，其余 254 个仍只有一个同步副本的 A-primary 分区全部保持：

```text
outcome=INSUFFICIENT_SYNCHRONIZED_REPLICAS
```

它们没有发生不安全 CAS；故障后 primary 统计仍有 254 个 assignment 保持 `OrderSvrA`，从而同时验证了“安全分区接管、非安全分区 fail-closed”。

P143 恢复后，原浏览器流程继续完成：

```text
login: PASS
deposit: PASS
cancel: PASS
execution: PASS
closePosition: PASS
reduceOnlyPreview: PASS
```

MySQL 最终权威状态：

```text
orders=5
executions=4
open_orders=0
nonflat_positions=0
used_margin=0
freezed_margin=0
freezed_commission=0
```

随后恢复 OrderSvrA。A 以 learner 身份重新追平 P143 后，通过 `OrderSvrC FAILOVER_PROOF` 与 `OrderSvrA LEARNER_PROOF` 比对，以下 durable prefix 完全一致：

```text
journalLastSeq=98
committedStateSeq=97
committedStateEpoch=5
commitMarkerSeq=98
lastStateSeq=97
lastScannedSeq=98
baselineEpoch=5
```

在 proof 无差异且无 uncommitted tail 的门禁下，以 ZooKeeper dataVersion CAS 将 A 从 learner 提回同步 replica。最终 P143：

```text
primary=OrderSvrB
replicas=[OrderSvrC,OrderSvrA]
learners=[]
epoch=5
assignmentVersion=9
state=READY
```

A/C 两节点随后均能以 `SYNC_REPLICA` 身份重新提供一致的 `FAILOVER_PROOF`。

因此第 15.4 节的“新 Order 自动 failover + 持续真实业务流联合故障回归”门禁正式关闭。随后第 19 节已继续完成“learner durable proof 已追平 -> 自动 CAS 晋回同步 replica”的自动冗余自愈能力，因此该人工恢复步骤也不再是发布阻塞项。
## 19. learner 自动冗余自愈验证

持续业务 failover 验收暴露的最后一个工程缺口是：旧 primary 作为 learner 恢复后，即使 durable prefix 已与同步副本完全一致，assignment 仍会停留在 learner，必须人工 proof + CAS 才能恢复双同步副本。

OrderSvr 增加自动冗余修复能力：

```text
local test commit: dae88083bf063c2e270934bd13fa9a55c08672d7
remote commit:     a45a739cc609f803a76f75ff9fdf0077dc8b6ac5
message:           feat(order): auto-repair caught-up learners
```

实现仍沿用现有自动 failover controller 的同一 ZooKeeper session 与 controller lease，不创建第二套控制权。默认低频扫描：

```text
order.cluster.failover.replicaRepairPollMillis=5000
```

只有当前 controller lease holder 执行 repair。每个 learner 晋升前必须同时满足：

1. control plane connected 且 lease 仍由当前 controller 持有；
2. assignment 仍为 READY/ACTIVE，primary membership 在线；
3. 至少一个现有同步 replica 在线并能提供合法 `FAILOVER_PROOF`；
4. learner 在线并能提供合法 `LEARNER_PROOF`；
5. 同步副本 proof 与 learner proof 均无 uncommitted STATE tail；
6. durable prefix 完全一致：`journalLastSeq`、`committedStateSeq`、`committedStateEpoch`、`commitMarkerSeq`、`lastStateSeq`、`baselineEpoch`；
7. CAS 前重新读取 assignment，ZooKeeper dataVersion / epoch / primary / replica / learner 角色均未变化；
8. CAS 只做 `learner -> replicas`、`assignmentVersion +1`，不改变 primary、epoch 或 state。

任何 proof 不一致、membership 变化、lease 丢失、assignment stale 或 CAS conflict 都保持 learner，不降低 fail-closed 门槛。

新增 focused tests 覆盖 durable prefix 一致/不一致、uncommitted tail、无 lease、primary/learner 离线、CAS 前 assignment 变化、多 learner 顺序修复，以及从 recovered assignment learners 恢复 managed nodes。

最终 Order 全量：

```text
tests=258
failures=0
errors=0
skipped=0
```

### 19.1 256 分区历史现场自动恢复

三台 integration OrderSvr 滚动到：

```text
local/dc-saas-ordersvr:auto-repair-dae8808-20261002
Order revision: dae88083bf063c2e270934bd13fa9a55c08672d7
Common revision: 97d4eff30bd3
```

升级前环境保留了多轮真实故障后的 learner 拓扑。新 controller lease 由 OrderSvrC 持有后，runtime 自动逐分区做 proof + CAS。最终：

```text
partitions=256
replica_counts={2:256}
learner_counts={0:256}
```

即 256/256 分区全部恢复成双同步副本。此前曾因跨 epoch GAP 等待 snapshot rebase 的 P059，也只有在重启/rebase 完成并能提供与同步副本一致的 durable proof 后才自动晋升，没有绕过 proof 门禁。

### 19.2 P143 受控 learner 自动晋升

为排除大规模历史修复只是偶然的可能，对已健康的 P143 做单分区受控实验。实验前：

```text
primary=OrderSvrB
replicas=[OrderSvrC,OrderSvrA]
learners=[]
epoch=5
assignmentVersion=9
dataVersion=8
state=READY
```

先通过 A/C `FAILOVER_PROOF` 验证两同步副本 durable prefix 完全一致、无 uncommitted tail；然后仅通过 ZooKeeper CAS 将 A 降成 learner：

```text
primary=OrderSvrB
replicas=[OrderSvrC]
learners=[OrderSvrA]
epoch=5
assignmentVersion=10
state=READY
```

之后不执行任何人工 proof/CAS 恢复，只观察自动 repair runtime。结果：

```text
demotion -> automatic repair = 1158ms
log: ORDER_AUTO_REPLICA_REPAIRED partition:P143 learner:OrderSvrA
```

自动恢复后：

```text
primary=OrderSvrB
replicas=[OrderSvrC,OrderSvrA]
learners=[]
epoch=5
assignmentVersion=11
dataVersion=10
state=READY
```

primary 与 epoch 均未变化。最终 A/C 再次都以 `SYNC_REPLICA` 身份提供 `FAILOVER_PROOF`，且以下字段完全一致：

```text
journalLastSeq=101
committedStateSeq=97
committedStateEpoch=5
commitMarkerSeq=98
lastStateSeq=97
lastScannedSeq=101
baselineEpoch=5
```

因此“故障节点回来后自动恢复冗余”门禁已关闭：Order 自动 HA 现在覆盖 `primary failover -> learner catch-up -> proof-guarded replica repair` 完整闭环。

## 20. Web `/httpapi` 旧请求 60 秒悬挂与超时收敛

在第 18/19 节已经验证控制面自动切主和 learner 自动 repair 后，继续对真实浏览器业务流做独立复测，发现一个与控制面不同层次的用户感知问题：**primary 已经在数秒内完成切换，但故障瞬间已经发往旧 primary 的 HTTP 请求可能继续悬挂，直到 Nginx 默认 60 秒 upstream 超时。**

### 20.1 默认 Nginx 超时：控制面 6.5 秒，业务探针被拖到约 59.4 秒

使用 `IHF003_E2E` 做独立复测，业务路由命中 P143。故障注入前实际拓扑：

```text
primary=OrderSvrB
replicas=[OrderSvrC,OrderSvrA]
learners=[]
epoch=5
assignmentVersion=11
state=READY
```

浏览器完成真实登录、入金、挂单与撤单后启动每 250ms 的 `OrderSvr.queryOpenOrder` 探针，并在 `fault-ready` marker 出现后对当前 primary `OrderSvrB` 执行 SIGKILL。

控制面结果：

```text
B -> C
epoch: 5 -> 6
kill -> new primary READY: 6519ms
```

但浏览器探针观测为：

```text
firstFailureMs = 772ms
recoveryMs     = 60171ms
outageMs       = 59399ms
```

其中一笔已经进入旧 backend 的请求在 GW 检测到 B 断开后仍未完成 callback；Trade Web Nginx `/httpapi` 没有显式 `proxy_read_timeout`，因此使用默认 60 秒，最终返回 504。浏览器流程已经完成撮合和平仓，但最终因捕获到这次 504 console error 而 `browser_rc=1`。

MySQL 权威状态仍然收敛：

```text
orders=5
executions=4
nonflat_positions=0
used/freezed margin=0
```

恢复 B 后自动冗余修复继续通过：

```text
ORDER_REPLICA_CATCHUP_OK partition:P143 epoch:6 replicatedSeq:146
ORDER_AUTO_REPLICA_REPAIRED partition:P143 learner:OrderSvrB
final primary=OrderSvrC
final replicas=[OrderSvrA,OrderSvrB]
learners=[]
epoch=6
assignmentVersion=13
state=READY
```

### 20.2 显式 12 秒 `/httpapi` 上游等待：完整浏览器交易 PASS

在隔离 Trade Web 上将 `/httpapi` 调整为：

```nginx
proxy_connect_timeout 2s;
proxy_read_timeout 12s;
proxy_send_timeout 12s;
```

随后使用全新 tenant `IHF004_E2E` 做第二轮独立 live failover。业务路由命中 P149，故障前：

```text
primary=OrderSvrA
replicas=[OrderSvrB,OrderSvrC]
learners=[]
epoch=4
assignmentVersion=7
state=READY
```

在同样的真实浏览器交易流中 SIGKILL A，结果：

```text
A -> B
epoch: 4 -> 5
kill -> new primary READY: 8912ms
firstFailureMs = 1046ms
recoveryMs     = 11695ms
outageMs       = 10649ms
probe samples  = 47
failed samples = 42
browser_rc     = 0
```

故障窗口先返回 `1003`，随后短暂返回 `1016`，新 primary 完成 promotion 后恢复 `code=0`。与上一轮约 59.4 秒相比，用户可见业务不可用窗口缩短约 48.75 秒，约 82%。

浏览器继续完成挂单、撤单、撮合、持仓和 reduce-only 平仓。MySQL 最终权威状态：

```text
orders=5
executions=4
nonflat_positions=0
balances_nonzero_margin=0
buyer balance=99999.952
seller balance=99999.952
```

恢复 A 后，自动 learner catch-up / replica repair 也再次通过：

```text
ORDER_REPLICA_CATCHUP_OK partition:P149 epoch:5 replicatedSeq:94
ORDER_AUTO_REPLICA_REPAIRED partition:P149 learner:OrderSvrA
final primary=OrderSvrB
final replicas=[OrderSvrC,OrderSvrA]
learners=[]
epoch=5
assignmentVersion=9
state=READY
```

Trade Web 正式修复已提交：

```text
repository: bliplink/dc-trade-web
branch: fix/httpapi-failover-timeout
commit: 7a9607438d81e1e8f7b72403c9add2069067a96b
PR: #1
```

该改动**不做透明订单重试**，避免在请求结果未知时制造重复下单风险；它只把失败旧连接的 HTTP 等待时间从默认 60 秒收敛到有界窗口。更底层的长期优化仍是让 GW/gateway connector 在 backend 断开时主动完成或失败该连接上的 pending callback，使用户感知恢复进一步贴近实际 primary READY 时间。

## 21. GitHub Actions / GHCR 正式镜像最终验收

在 Common 3.0.15 按与 3.0.14 相同的真实 tag push 流程发布 Maven Central 后，`com.app.dc:saas-crypto` 已统一引用：

```text
io.github.bliplink:com.app.common:3.0.15
```

随后所有 SaaS Java 服务均由 GitHub Actions 重新构建镜像。Actions 日志逐一确认服务在 build 阶段从 Maven Central 下载或打包 `com.app.common-3.0.15.jar`；服务 POM 不再直接声明 Common，服务 workflow 也不再直接 clone/build `com.app.common`，只保留 clone/build `com.app.dc`。

隔离 integration 栈的核心正式镜像包括：

```text
LoginSvr      ghcr.io/bliplink/loginsvr@sha256:e8db1d8f90cc7908bf852c2ea0d3562cc185fa66c9949afd0466d62b9399594c
AdminSvr      ghcr.io/bliplink/adminsvr@sha256:007e2549d0702a0cc2b58d41ecbd285f59ec72a3adee4beb6213588e611821a4
OrderSvr A/B/C ghcr.io/bliplink/ordersvr@sha256:eb7fe76a179db4f9bceeafabe0cd639939f44eb3ecac0ac0c83bc97aae3da48a
TradeSvr A/B  ghcr.io/bliplink/tradesvr@sha256:1ca81617f3c694fd0e52a84b4c6089d8526243f3c212e58702fddbae6feda5c9
ProjectionSvr ghcr.io/bliplink/projectionsvr@sha256:889ea7555dc4060c94a22c461d23e165e91ce55ef48dfb1ab000ba4d5bd11587
APSSvr        ghcr.io/bliplink/apssvr@sha256:b789a3766d546f67203460bb3b42460def5e5c9580bd3c0c182bb7239019ef63
```

运行中的 Login/Admin/Order/Trade/Projection 容器内部均确认存在：

```text
/srv/dc/dc/<Service>/lib/com.app.common-3.0.15.jar
```

### 21.1 正式镜像浏览器业务基线：GHCR01_E2E

使用全新 tenant `GHCR01_E2E`，在正式 GHCR 后端上执行真实浏览器流程：

```text
public registration     PASS
buyer/seller login      PASS
deposit                 PASS
resting limit order     PASS
cancel                  PASS
matched execution       PASS
position update         PASS
reduce-only close       PASS
final flat position     PASS
```

最终浏览器输出 `status=PASS`。隔离栈未为该 tenant 配置可路由 MDSvr 分区，因此 recent-trade/K-line 门禁按测试设计标记 `SKIPPED_MDSVR_NOT_ROUTABLE`，不影响 Order/Trade/Projection 正式镜像验收。

为消除浏览器自动化误报，正式 E2E 同步修复了三个纯 UI 时序点：

- Deposit 填值后等待 `Confirm Deposit` 从 disabled 变为 enabled 再点击；
- 下单前等待 `.placeOrderWrap` 退出 `publicMode` 且 Limit 按钮恢复 pointer-events；
- `Open Orders` 已经 `aria-selected=true` 时不再重复点击。

连续浏览器测试还暴露出测试机自身内存耗尽：Colima 16 GiB 内存仅剩约 200 MiB、无 swap，旧 Playwright runner 曾出现 `OOMKilled=true` 且 `/dev/shm=64MiB`。测试环境增加 2 GiB 临时 swap，并将 runner 以 `--ipc=host` 重建后，`/dev/shm` 提升到约 7.8 GiB，后续正式镜像基线稳定通过。该问题属于验收基础设施资源不足，不是服务进程 OOM。

### 21.2 正式镜像 live failover：GHCR02_E2E

使用全新 tenant `GHCR02_E2E`。业务键 `GHCR02_E2E + 4 + BTCUSDT` 命中 P046，故障前：

```text
primary=OrderSvrB
replicas=[OrderSvrC,OrderSvrA]
learners=[]
epoch=5
assignmentVersion=9
state=READY
```

浏览器完成登录、两边入金、10000 价位真实挂单与撤单后启动 `queryOpenOrder` failover probe。收到 `fault-ready` 后确认当前 primary 仍为 B，并对正式 GHCR OrderSvrB 执行 SIGKILL：

```text
killed image:
ghcr.io/bliplink/ordersvr@sha256:eb7fe76a179db4f9bceeafabe0cd639939f44eb3ecac0ac0c83bc97aae3da48a

B -> C
epoch: 5 -> 6
kill -> new primary READY: 6942ms
firstFailureMs: 793ms
recoveryMs: 8274ms
business outageMs: 7481ms
browser_rc: 0
```

切主后浏览器继续完成 60000 买卖撮合、execution history 校验与 reduce-only 平仓，最终 `status=PASS`。

MySQL 最终权威状态：

```text
orders=5
executions=4
open_orders=0
nonflat_positions=0
buyer used/freezed margin=0
seller used/freezed margin=0
buyer balance=99999.952
seller balance=99999.952
```

恢复被 kill 的 OrderSvrB 后，它重新注册并自动完成 learner catch-up / replica repair，最终：

```text
primary=OrderSvrC
replicas=[OrderSvrA,OrderSvrB]
learners=[]
epoch=6
assignmentVersion=11
state=READY
```

本轮没有观察到 `ORDER_AUTO_FAILOVER_FAILED`、`PROMOTION_UNSAFE`、`RECOVERY_FAILED` 或服务 OOM。至此，正式 GitHub Actions 镜像已经完成：

```text
Maven Central Common 3.0.15
-> com.app.dc source build
-> GitHub Actions service image
-> GHCR immutable digest
-> real browser business baseline
-> live primary SIGKILL
-> automatic failover
-> post-failover matching/close
-> authoritative DB reconciliation
-> killed node replica repair
```
