# OrderSvr 恢复门与单机 A/B TPS 验收报告

日期：2026-09-08（Asia/Shanghai）

## 结论

本阶段完成了“分区恢复成功后才允许接单”的服务端就绪门和 OrderSvr 生命周期编排，所有危险开关默认关闭。生产机上的隔离集群已更新到开发镜像并通过 A/B 路由、epoch fence、shadow journal 和同步复制验证；现有量化与 SaaS 服务未切换。

在同一台生产主机、相同镜像、相同请求、相同并发和同步复制策略下，将两个分区从单主承载改成 A/B 各承载一个主分区后，TPS 没有提高，而是下降：

| 拓扑 | TPS 中位数 | TPS 均值 |
| --- | ---: | ---: |
| 单主：P027/P132 均由 OrderSvrA 承载 | 206.35 | 182.37 |
| 分片双主：P027→A、P132→B | 106.58 | 103.40 |
| 变化 | **-48.35%** | **-43.30%** |

结论仅适用于当前“单机混部 + 两个 JVM + 双向同步复制”部署。它不能推导多台物理机的扩展结果，也不代表完整下单、撮合、资金和 TradeSvr 业务 TPS。

## 代码与镜像

- Common `feature/cluster-local-common`：`2228a7b`，增加 `service + partition + epoch` 精确就绪门。
- OrderSvr `feature/cluster-local-common`：
  - `d446f2f`：恢复生命周期、角色撤销、旧 epoch 拒绝和启动顺序接线。
  - `bfe69f7`：仅隔离环境可开启的集群数据路径压测探针。
- Deploy `feature/cluster-local-common`：
  - `7ff0d5f`：TPS 对照工具。
  - `b49349b`：ABBA/BAAB 反向顺序消除顺序偏差。
  - `024ee63`：压测与 LoginSvr 隔离。
  - `e51f2a6`：同时校验 HTTP 状态、业务 `code=0`、路由就绪与 journal 数量。
- 隔离镜像：
  - `ghcr.io/bliplink/ordersvr:cluster-dev-bfe69f7`
  - `ghcr.io/bliplink/ordersvr:gw-cluster-dev-bfe69f7`
- 镜像内 Common revision：`2228a7be7de4897df74712450a9773b92f7e86fc`。

## 正确性测试

- Common：20/20 通过。
- OrderSvr：119/119 通过。
- 覆盖恢复成功、无恢复结果、恢复异常、丢失主角色、恢复期间 assignment 变化、assignment 删除。
- 修正原故障切换集成测试的异步竞态后，全套测试稳定通过。
- 隔离服务器 A/B 验收：`/data/dc-saas-order-cluster-dev/evidence/20260907-162801/result.json`。
- 最终 assignment：
  - P027：epoch `178879878481820`，Primary `OrderSvrA`，Replica `OrderSvrB`。
  - P132：epoch `178879878481821`，Primary `OrderSvrB`，Replica `OrderSvrA`。
- 隔离 ZooKeeper、OrderSvrA、OrderSvrB、GW 均为 healthy；日志无复制失败、复制超时或 OOM。

## TPS 方法与结果

压测探针只有 `order.cluster.perfProbe.enabled=true` 时才注册；普通 SaaS/生产配置默认为 false。探针经过以下真实路径：

`HTTP → GW 逻辑 OrderSvr 路由 → 物理 A/B → 服务端 epoch fence → Chronicle journal → TCP 同步复制 → Replica ACK → HTTP code=0`

探针不访问 LoginSvr，不创建订单，不进入撮合、资金或数据库业务。每个模式运行两次 1000 请求、并发 8、预热 100；先 ABBA，再 BAAB，共 8000 个计时请求。每个请求均满足：

1. HTTP 成功；
2. JSON 业务码为 0；
3. 唯一事件 ID 在 Primary journal 成功日志中恰好出现一次；
4. 同步复制 ACK 为 OK。

原始结果：

- ABBA：单主 206.35 TPS，双主 143.06 TPS，下降 30.67%。
- BAAB：单主 158.40 TPS，双主 63.74 TPS，下降 59.76%。
- 合并中位数：单主 206.35 TPS，双主 106.58 TPS，下降 48.35%。
- 合并证据：`docs/evidence/order-cluster-throughput-combined-20260907.json`。

## 排除的无效样本与发现

早期压力样本使用 `placeOrder`，每个请求都会因隔离环境没有 LoginSvr 而输出异常栈，约 90 MB 同步日志污染了结果，已明确排除。

一次 2000×32 压测超过 10 分钟后被终止，留下主副 journal 序号差。随后提升 epoch 时，现有 catch-up 正确地拒绝跨 epoch 增量追赶：`replica catch-up crosses epoch`。这证明当前系统还不能在缺少 snapshot 恢复的情况下处理“有缺口后直接换主”。旧隔离数据没有删除，已移动到：

`/data/dc-saas-order-cluster-dev/backups/journal-divergence-20260907-162620`

重建空的隔离 journal 后，A/B 正确性与最终 TPS 测试全部通过。

## 当前安全边界

- `state/commit/snapshot/lifecycle/EnforceReadiness` 在服务器隔离部署中仍保持关闭。
- 当前已实现的是可验证的恢复就绪门和生命周期代码，不是已经启用的自动故障切换。
- 自动接管前仍必须补齐定时/事件驱动的静默快照、快照传输、跨 epoch 缺口恢复、控制器提升 epoch 和故障注入验收。
- 当前 TPS 对照测的是同一新版本的两种拓扑，不是旧版本与新版本的代码回归对照。

## 后续优化建议

1. 一台机器部署两个 OrderSvr 可用于故障隔离验证，但不应以提高 TPS 为目标；正式扩容应拆到独立物理机或独立故障域。
2. 将逐单同步复制优化为有上限的 group commit/batch ACK，并分别统计 journal、网络、Replica apply 的耗时。
3. Primary 与 Replica 使用独立执行器和队列，避免双主时两个 JVM 同时承担入站主流量与反向复制流量造成争用。
4. 压测配置关闭逐请求 DEBUG 文件日志，使用计数器、journal watermark 和抽样日志证明完整性。
5. 在 state/commit/snapshot 全链路完成后，分别测试 RPO、RTO、故障期间拒单时间、恢复期间重复/丢失和真实业务 TPS。
6. 最后在完整 SaaS 栈使用已认证会话测试下单、撤单、成交、资金更新和行情广播；该结果才能称为核心交易 TPS。
