# MDSvr 基于 Order Snapshot 的故障接管机制（2026-10-10）

## 定位与当前状态

MDSvr 是 OrderSvr 权威撮合订单簿的派生行情服务。**不要为 MDSvr 再造 Order 风格的同步 WAL、磁盘副本或 MD→MD 盘口复制。** 接管节点可从 OrderSvr 的 `subscribeWithImage` 取得市场完整快照，并持续应用后续事件。K 线、最近成交、24h 统计的恢复需单独证明，不能由盘口快照代替。

该机制可减少正常行情写盘/复制开销，但**不等于可以直接将当前 MD HA 标记为通过**：截至本次只读实机检查，256 分区 A/B 各持 128 个 Primary，所有 256 个分区只有一个指定 Replica，现网故障接管仍为 `BLOCKED`，10 租户真实 MD-B SIGKILL 已证明 4/10 市场中断。保留 `scripts/check-md-failover-preflight.py` 的 fail-closed 规则，不在 Demo 自动变更主分区。

## 已提交且经过本地验证的基础代码

- `com.app.dc.mdsvr` `15d3af2`：本机在 watched assignment 中获得新的 Primary/epoch 时，合并一次 Order 盘口 `subscribeWithImage` 订阅刷新；对同一 listener 先 unsubscribe 后 subscribe；刷新失败会由已有的 2 秒路由对账任务重试。相同 assignment 不增加额外订阅，也不持久化行情日志。每个市场仍需收到完整 Order Snapshot 才可获得本地发布资格；仅 read-route READY 不代表行情 READY。本地 Maven 全量 **88/88 PASS**。
- `com.app.common` `46fe54c`：当 ZooKeeper 状态为 `ConnectedReadOnly` 时将其视为不可写控制面，通知断联并禁止基于 `isConnected()` 的 MD 旧主发布授权。相关 ZK/Failover 单测 **22/22 PASS**，GitHub Actions Java Maven PASS、publish SKIPPED。此提交尚未发布到 Maven Central，也尚未被运行镜像引用。
- MD GitHub Actions [run 38058127280](https://github.com/bliplink/com.app.dc.mdsvr/actions/runs/38058127280) **PASS**，GHCR 已生成 `ghcr.io/bliplink/mdsvr:sha-15d3af2`；用 `docker manifest inspect` 读取远端清单，确认同时包含 `linux/amd64` 和 `linux/arm64`。本镜像尚未包含待发版的 Common ZooKeeper 修复；运行中 A/B/C 仍为 `ghcr.io/bliplink/mdsvr:sha-48544e5`，未部署新镜像。

## 新一轮代码验证与实际边界（2026-10-10）

- [MDSvr 3366041](https://github.com/bliplink/com.app.dc.mdsvr/commit/3366041) 新增 `MdImageRecoveryFailoverController`（隔离开发阶段）：一个合法健康 Replica/Learner 可以接管；必须持有控制器租约、旧主发布隔离证明和分区版本 CAS，先进入新 epoch 的 `RECOVERING`，只有拿到 Order 所有活跃市场完整 image 和连续增量证明才能变更为 `READY`。恢复中的候选再次故障时，可更换其他已分配节点并重新增加 epoch。
- 修改 `MdPartitionRuntime`：在 `RECOVERING` 阶段触发一次合并的 Order Snapshot 重新订阅，不等待 READY；此阶段不开启 read-route 或行情发布权限，并保持正确的重建 epoch。
- 本地 MDSvr 全量 Maven 单测 **100/100 PASS**，覆盖旧主仍存活、缺少租约、CAS 冲突、完整快照未到、双重故障等。
- **现状限制**：状态机尚未接入可信的旧主隔离证明、Order 实时全市场库存以及现网控制器线程；不可宣称已完成自动接管。Common 的 ZooKeeper 只读安全修复亦未进入运行镜像。禁止使用永远成功的测试 callback 绕过证据。
- 部署只读门禁现在认可单个已分配候选，无需 MD 复制日志；但仍返回 `BLOCKED`，直到可信旧主隔离、Order source/freshness、Robot 对账和隔离故障注入全部通过。
- [Common f4febef](https://github.com/bliplink/com.app.common/commit/f4febef) 加强 ZooKeeper 新会话回调和首次连接返回路径，不会把 `ConnectedReadOnly` 误作为有写授权；Common 的 ZK/分区控制器测试 **23/23 PASS**。仍需正常 Maven Central 版本递增和多服务依赖更新后才能计入生产镜像。
- 部署只读安全脚本 + CAS/learner 回归 **30/30 PASS**。此次没有对运行中的十租户分区 ZK 写入，没有重新启动 MD-A/B/C 或中断 Order/Trade。
- [MDSvr GitHub Actions run 38060064795](https://github.com/bliplink/com.app.dc.mdsvr/actions/runs/38060064795) **PASS**；远端 `ghcr.io/bliplink/mdsvr:sha-3366041` 清单确认包含 `linux/amd64` 与 `linux/arm64`。该镜像没有集成未发版的 Common `f4febef`，控制器仍未接到真实证明通道，因此不得替换现网 MD。
- 2026-10-10 14:35 UTC Mac 实机只读 preflight：256/256 READY，A/B Primary 各 128，`withoutRecoveryCandidateCount=0`，三 MD ephemeral membership 均有效。**decision=BLOCKED**，尚缺 Order 当前完整市场 image proof、已配置/认证的 CAS fencing 控制器、新 epoch 的市场就绪证明，以及 Robot 对账。运行镜像仍是 `sha-48544e5`。

## MD 盘口断档自动恢复补丁（2026-10-10）

- [MDSvr `1745b42`](https://github.com/bliplink/com.app.dc.mdsvr/commit/1745b42)：当 Order depth diff 发现缺失前驱序号或尚未建立完整盘口时，先撤销该市场发布 READY，再异步触发一次 `subscribeWithImage`，主动申请新的 Order 完整 Image，不再只被动等待新行情。
- `MdDepthGapRecovery`：一个 daemon 任务合并所有处于断档状态的市场重订阅；初次立即请求，失败后退避从 5 秒到最多 60 秒；同一市场故障未修复期间只打一次断档告警。成功安装完整 Image 后解除该市场的恢复请求。正常无断档时不运行定时任务、不新增磁盘 I/O 或 MD 间复制。若 Order/GW 源端长期不返回真正完整新 Image，市场仍会保持不就绪，不能伪造 READY。
- `LocalDepthBook`：没有 Snapshot 序号或盘口 entries 为 null 时拒绝 Image；没有已安装完整 Image 时拒绝仅靠增量建立盘口；兼容原有正常 applySnapshot 调用。限频和并发竞争测试覆盖同时断档 1000 次、多个市场合并请求与失败重试。
- Mac mini 隔离 Maven 测试 **106/106 PASS**，代码提交并推送 `saas-crypto`，GitHub Actions [run 38061084918](https://github.com/bliplink/com.app.dc.mdsvr/actions/runs/38061084918) 由 push 触发。此处不以 Actions 启动代替镜像构建成功；需另行核验 GHCR digest/双架构。
- **依然未完成的关键证明**：Order `PublishMarketDept` 的完整盘口消息由订单簿变化及 `enableFullOrderBookOnChange` / 1 秒节流控制产生。仅调用 Gateway 的 `subscribeWithImage` 并不从代码上证明 Image 一定是订阅时刻的 Order 当前 HEAD。真正自动选主前，必须确认 Gateway 的缓存/重放语义，建立当前完整市场库存、Snapshot 与后续深度增量连续性证明，以及旧主接收侧 fencing。不能仅以重订阅成功替代全部市场的权威新鲜度验证。
- Mac Demo 三个 MD 仍保留旧的 `sha-48544e5`，未注入故障或切换现网分区；持续租户验收与受控切主另行进行。

## 后续自动切主的正确控制面

1. **故障判断**：只认物理 MD ephemeral membership/session 及租约状态；单次 TCP 断开、健康检查失败和 Docker running 状态不足以认定旧 Primary 已失权。ZooKeeper read-only 状态不授予主身份。
2. **唯一修改者**：以临时节点持有一个控制器租约；按当前 ZK `dataVersion`、assignment epoch 和身份执行 CAS 更新，不采用两个 MD 各自本地判断。
3. **目标选取**：在剩余健康的 MD B/C 中选择支持相同 market/topic 路由的实例；对重新分配的分区先关闭旧 Primary 发布权。不要使用“Replica 必须有 MD 持久日志水位”作为行情恢复的前提，但仍必须证明下游没有双主、源快照能够重建完整的当前盘口。
4. **新 Primary READY**：路由角色与市场发布权分开；角色变更后调用 `subscribeWithImage`，只有收到正确租户产品的完整 Snapshot、随后序号连续且 epoch/owner 有效，才准向 GW/Web 发布。不能用旧内存中的快照直接授权。缺少 Snapshot 时宁可显示恢复中，也不能发陈旧盘口。
5. **重连与反向切换**：旧主重新注册为 learner/replica，通过 Order 重建；小批次重均衡，不自动夺回原 Primary。对 stale writer 要有接收侧 owner epoch/fencing 的端到端验证，而不只靠本地 `canPublish`。
6. **行情之外的数据**：Trade 最近成交、Kline、24h 窗口统计应使用权威成交数据/持久化历史补齐，验证去重和水位。Robot 从 Order 核对活动订单后再恢复报价，不能仅依据 MD 恢复而伪造订单状态。

## 验收门禁（未通过前不杀现网 MD 主节点）

- 三节点隔离环境持续 10 租户交易；定向关闭 MD-A → B/C 自动获取其原分区、重新订阅、快照恢复；逆向关闭 B/C 并重复验证。
- 每个市场比较 `location+market+security`、epoch、snapshot `lastUpdateId`、连续增量、盘口十档/未交叉、最新成交与 Kline；测量故障检出、CAS、第一张有效行情、Robot 恢复的耗时。
- 验证唯一主发布者、旧主复活/网络分区/只读 ZK/乱序重放，Robot 挂单与 Order、账户、持仓一致。
- 通过隔离环境后才安排 Mac 受控注入，再考虑增加到 25/50/200 租户；不得以单纯单测通过替代真实故障接管。

### 不增加热路径负担的边界

- **禁止** MD 间同步写盘、双写数据库、每帧 ZK 查询、每订单强制持久化行情水位。
- 角色变化时才重新订阅一次；正常时复用已有 watcher 和缓存分区 assignment。
- 若未来为审计提供 Order 对账 manifest，使用按需、限频只读检查；不作为日常行情的必经环节。
