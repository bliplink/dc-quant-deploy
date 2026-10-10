# OrderSvr → MDSvr 分区市场全集及快照提交边界合约（2026-10-10）

## 已真实提交的代码

**OrderSvr**：[f2df4a9](https://github.com/bliplink/com.app.dc.ordersvr/commit/f2df4a97eb696cd85526bc6253eea41399302b47)，在 `OrderSnapshotManager.loadLatestMdMarketManifest(partitionId)` **只读加载已持久化的本地分区快照**，利用 `OrderMdMarketManifest.fromCommittedSnapshot` 生成 JSON 序列化兼容的市场版本清单：

- `version=1`、`partitionId`、`snapshotId`、`epoch`、`snapshotSeq`、`committedStateSeq`、`committedStateEpoch`、`commitMarkerSeq`、`createdAt`。
- `marketVersions`：全市场键 `location\u001fmarketIndicator\u001fsecurityId` → 该书本的 `lastUpdateId`，确定性排序。
- `sha256`：字段及已排序市场键/版本的 UTF-8 长度前缀规范化摘要。**这只是内容完整性摘要，不是数字签名或可信来源证明。**
- `proofLevel="COMMITTED_SNAPSHOT_CHECKPOINT_ONLY"`、`promotionAuthorized=false`，拒绝没有市场、市场身份缺失/重复、市场序号无效、提交边界结构不合法等情况。
- 加入已落盘快照重读测试，证明生成清单不会改写快照文件。OrderSvr 本地全量 **305 个测试，失败 0、错误 0、跳过 1**。

**MDSvr**：[196ad18](https://github.com/bliplink/com.app.dc.mdsvr/commit/196ad18300e82888523add2eaf49c1c2bc96d402)，新增 `MdOrderSnapshotCheckpointContract.parseCheckpoint(json)` 解析/检查 OrderSvr JSON 合约，重算规范化摘要、校验提交边界、只允许 `promotionAuthorized=false` 的 CHECKPOINT 合约。`DepthBookFacade.compareOrderSnapshotCheckpoint(...)` **只读**调用分区全市场覆盖检查，将给定源版本与本机从完整快照+连续增量得到的市场水位逐一对比。MDSvr 的 `MdDepthReplayWitness` 改用与 OrderSvr 相同的 `location\u001fmarket\u001fsecurity` 路由键，原本内部 `security_market_location` 键仍只用于书本缓存。

两侧使用固定测试样例验证 `sha256=913fab4a79250a13d76a5b0f89d596dcf81d45f0d50cee80f4e83ee903dce216`，MD 端再验证所有市场匹配、单市场断档、修改市场版本与伪造哈希必被拒绝。MDSvr 本地全量 **84 项测试，失败 0、错误 0**。

## 尚未实现的跨服务安全协议

**本次完成的不是自动晋升，也不是生产业务 RPC 接通。** 目前两端都有生产代码可调用的合约方法，并有两套独立测试兼容性，但 OrderSvr **尚未通过具备鉴权、主体认证和重放保护的内部协议向 MD 分发 manifest**。因此不能说已在运行的 10 租户集群实现在线源水位传输。

更重要的是：持久化快照属于**历史 checkpoint**，不是当前写入主节点的 durable HEAD。单独从文件装载的快照没有独立的持久化 journal marker 重新读取确认，没有签名/请求主体证明，没有完整的市场全集原子性签名，也没有证明同一分区在快照后无新订单/成交。因此摘要校验合格**不能证明候选 MD 副本已经追上 OrderSvr 的当前状态**。

真正晋升前必须另外完成：

1. OrderSvr 经停写屏障、WAL 提交 marker、Projection watermark 验证后输出**当前**不可变市场全集和 durable HEAD，绑定发证主节点 fencing epoch、有效期与原子清单版本；签名或通过鉴权通道验证可信来源。
2. MD 候选节点对**所有**活跃市场重新核实完整 OrderSvr 快照+连续事件、时效、提交来源，提供跨节点可验证（而非仅进程内）的持久化状态哈希及水位；任何遗漏/断档拒绝。C 必须先从 learner 变成通过同步证明的 replica。
3. 带可写 ZooKeeper 控制器租约、唯一授权和版本 CAS 的 epoch 晋升与旧主强 fencing；新主 publish 前必须证明完整市场快照，不得将 READ_ROUTE_READY 当作发布许可。
4. 隔离三节点测试覆盖 10 租户持续交易、主节点 SIGKILL、旧主重新归队、角色反转、无双主、无丢单/重复成交及 Robot 订单状态对账；然后才可考虑再次在 Mac Demo 注入故障。

因此现网 MD 仍保留 `sha-48544e5` 镜像，10 租户继续正常运行；**MD 故障注入 P0 仍是 FAIL / OPEN，不授权再杀主节点或扩大 25/200 租户**。
