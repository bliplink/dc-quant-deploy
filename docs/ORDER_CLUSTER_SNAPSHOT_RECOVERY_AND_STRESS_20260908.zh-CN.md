# OrderSvr A/B 跨 Epoch 快照恢复与压力验收（2026-09-08）

## 1. 结论

本轮在生产主机 `18.140.45.126` 的**独立 Compose 项目** `dc-saas-order-cluster-dev` 中完成了跨 epoch 快照重基线、恢复 readiness、在线角色反转、Primary 进程故障注入和双顺序吞吐回归。隔离集群最终为健康状态，现有量化及 SaaS 生产容器未替换、未重启。

验收结论：

- Common 单测：20/20；OrderSvr 单测：137/137；失败、错误、跳过均为 0。
- P027 在线 A→B→A 两次跨 epoch 切换通过；每次都先完成恢复和 promotion snapshot barrier，再开放 readiness。
- 真实停止隔离 OrderSvrA 后，P027 按同步双副本策略保持 fail-closed；A 恢复并完成新 epoch 快照重基线后，B 自动开放；随后 B→A 恢复通过。
- ABBA、BAAB 两轮共 16,000 个计时请求全部成功，0 失败。四个样本综合中位数从单主 88.990 TPS 提升到分片双主 131.944 TPS，提升 48.27%。
- 本轮吞吐是 `GW 分区路由 + OrderSvr command journal + TCP 同步复制` 探针，不是完整登录、资金、撮合、成交业务 TPS；不能据此宣称完整交易链路达到 131.944 TPS。

## 2. 代码与镜像

| 仓库 | 分支 | 验收提交 |
|---|---|---|
| `bliplink/com.app.common` | `feature/cluster-local-common` | `2228a7b` |
| `bliplink/com.app.dc.ordersvr` | `feature/cluster-local-common` | `93fe60b` |
| `bliplink/dc-quant-deploy` | `feature/cluster-local-common` | 报告提交的父提交为 `8f8a1bd` |

隔离环境使用不可变公共镜像：

- `ghcr.io/bliplink/ordersvr:cluster-dev-93fe60b`
- `ghcr.io/bliplink/ordersvr:gw-cluster-dev-93fe60b`

部署脚本已验证 OrderSvr/GW 内嵌 Common revision 和 JAR SHA-256 一致。正式合并和生产切流前仍需发布正式 Common Maven 版本，不应长期依赖开发镜像中的本地依赖构建方式。

## 3. 本轮实现

### 3.1 一致快照与恢复屏障

- 每个 partition 使用共享/独占屏障：业务写路径持共享锁，快照和恢复持独占锁。
- 快照记录 `snapshotId`、epoch、snapshot sequence、已提交 state watermark 和 commit marker sequence。
- 恢复先校验 journal baseline 身份，再修改内存 OrderManager；身份不匹配时 fail-closed。
- snapshot barrier、state journal、commit watermark、同步复制和 readiness 必须成套启用。

### 3.2 跨 Epoch journal rebase

- Replica 仅接受以 `SNAPSHOT_BEGIN` 开始的更高 epoch。
- 旧 epoch 活跃 journal 移入 `.archive`，不删除分叉数据。
- 新 journal 从已校验快照 baseline 继续 sequence；baseline 在进程重启后仍可加载。
- 损坏快照、身份不一致、越界 sequence 和未提交 state 均阻止 promotion。

### 3.3 Promotion readiness

- 新 Primary 完成 commit-aware recovery 后，还必须把候选 epoch 的快照安装到 Replica，才能标记 ready。
- 首次空 partition 支持显式 bootstrap；非空未知 journal 不允许被 bootstrap 覆盖。
- 修复故障中发现的重试问题：若 promotion barrier 已在本地写入候选 epoch 快照和 `SNAPSHOT_BEGIN`，但同步复制失败，只允许“有 BEGIN、无 END、且无业务/状态事件”的未完成传输重试。
- 已完成 END 的同 epoch 重启、或夹有业务事件的 tail，仍拒绝自动重开，必须由控制面推进新 epoch。

## 4. 隔离部署

隔离资源：

- Compose project：`dc-saas-order-cluster-dev`
- 数据根目录：`/data/dc-saas-order-cluster-dev`
- 独立 ZooKeeper：`127.0.0.1:32182`
- 独立 GW HTTP：`127.0.0.1:33302`
- OrderSvrA：业务端口 `33336`，复制端口 `19111`
- OrderSvrB：业务端口 `33337`，复制端口 `19112`

升级前的旧隔离数据已移动到可恢复备份：

`/data/dc-saas-order-cluster-dev/backups/pre-cross-epoch-recovery-20260907-225032`

此前保留的分叉证据仍在：

`/data/dc-saas-order-cluster-dev/backups/journal-divergence-20260907-162620`

## 5. 功能与故障验收

### 5.1 首次 bootstrap

- P027：OrderSvrA bootstrap ready。
- P132：OrderSvrB bootstrap ready。
- readiness、state、commit、snapshot、promotion barrier 和 cross-epoch rebase 配置均为 required/enabled。

基本路由证据：

`/data/dc-saas-order-cluster-dev/evidence/20260907-225254/result.json`

### 5.2 在线角色反转

P027 执行 A→B→A：

- B promotion epoch：`178882168586085`
- A promotion epoch：`178882168586086`
- 两次 readiness 均在恢复及快照复制之后开放。
- A/B `.archive` 计数均从 1 增加到 2。
- 两次探针均取得 `replicaStatus=OK`。

证据：

`/data/dc-saas-order-cluster-dev/evidence/20260907-225445-role-reversal/result.json`

### 5.3 Primary 进程故障

执行过程：

1. 停止隔离 OrderSvrA。
2. 控制面将 P027 提升为 B 主、A 备并推进 epoch。
3. 因 required Replica 不可用，B 无法完成 promotion barrier，GW 返回 `PARTITION_NOT_READY`，未提前接单。
4. 重启 A；B 自动重试未完成的快照传输，A 完成 rebase 后 B readiness 开放。
5. 再推进 epoch 并切回 A 主、B 备，恢复通过。

最终通过的 epoch：

- B：`178882376161883`
- A：`178882376161884`

证据：

`/data/dc-saas-order-cluster-dev/evidence/20260907-232917-node-failure-recovery/result.json`

当前两节点策略明确选择一致性：任一节点宕机后，不会降级为单副本继续写入。若产品要求单节点故障期间持续交易，需要增加第三副本/多数派协议，或定义并审批可观测、可回收的降级写策略；不能在现有同步双副本上同时承诺 RPO=0 和单节点持续可写。

## 6. 吞吐回归

参数：每个样本 2,000 个计时请求，32 并发，另有 200 个 warmup；每次拓扑切换先等待 readiness，再开始计时。

| 顺序 | 单主中位 TPS | 分片双主中位 TPS | 变化 | 失败 |
|---|---:|---:|---:|---:|
| ABBA | 120.621 | 137.031 | +13.60% | 0 |
| BAAB | 71.994 | 131.944 | +83.27% | 0 |
| 四样本综合中位数 | 88.990 | 131.944 | +48.27% | 0 |
| 四样本平均值 | 96.307 | 134.487 | +39.64% | 0 |

证据：

- `/data/dc-saas-order-cluster-dev/evidence/20260907-233120-throughput/result.json`
- `/data/dc-saas-order-cluster-dev/evidence/20260907-233339-throughput/result.json`

单次结果离散较大，表明同机 CPU/cgroup、page cache 和宿主负载对尾延迟影响明显。两个相反顺序都显示分片双主提升，但正式容量结论应在独立节点、更长稳态、真实业务 payload 和固定资源配额下重测。

## 7. 压测后状态

压测后基本双分区路由及同步复制复测通过：

`/data/dc-saas-order-cluster-dev/evidence/20260907-233651/result.json`

当时资源快照：

| 容器 | CPU | 内存/限制 |
|---|---:|---:|
| OrderSvrA | 0.09% | 244.1 MiB / 384 MiB |
| OrderSvrB | 0.10% | 203.1 MiB / 384 MiB |
| GW | 0.09% | 165.2 MiB / 320 MiB |
| ZooKeeper | 0.11% | 59.92 MiB / 256 MiB |

数据占用约为 A 12 MiB、B 13 MiB；四个隔离容器均 healthy。

受保护生产容器保持原镜像：

- `dc-saas-ordersvr`：`ghcr.io/bliplink/ordersvr:sha-cedac79`
- `dc-saas-gateway`：`ghcr.io/bliplink/gw:saas-crypto`
- `dc-gateway`：`ghcr.io/bliplink/gw:latest`

## 8. 尚未完成与下一阶段

本轮不能替代完整交易业务验收，尚需：

1. 把隔离栈扩展到 LoginSvr、TradeSvr、资金、MDSvr，并用真实登录用户验证下单、撮合、成交、撤单、资金和持仓 state 在故障前后完全一致。
2. 增加自动控制面：故障检测、epoch 单调推进、Primary/Replica 指派、切换审计和人工熔断；当前角色变更由验收脚本显式写 ZooKeeper。
3. 在独立主机或至少独立 CPU 配额上执行真实业务稳态压测、突发压测、长稳压测和故障中压测。
4. 增加周期快照、快照保留/清理策略、journal archive 容量告警和恢复演练。
5. 正式发布 Common/Gateway 依赖，完成分支合并评审后才进入生产流量灰度。
