# MD 高可用故障验收门禁（2026-10-10）

## 实盘结果

十租户稳定观察 601 秒、11/11 样本通过；MDSvrB 负责 128 个主分区，进程中断期间 4/10 租户盘口不可用且 Robot 异常。恢复 B 后约 52 秒恢复十租户，之后连续 301 秒、11/11 样本通过。这证明恢复能力，不证明主节点故障下业务持续可用。详见 `TEN_TENANT_MD_PRIMARY_FAULT_OBSERVATION_20261010.zh-CN.md`。

## 自动晋升为何被禁止

ZooKeeper 实机扫描 256 个 MD 分区：A、B 各持 128 个 Primary；全部分区仅有一个指定 Replica，C 并非合法同步副本。通用 PartitionFailoverController 需要晋升后保留同步副本，还需要控制面租约、CAS fencing、候选同步进度证明。现有 MD 业务尚未实现独立的 durable market watermark、promotion safety proof 及完整 epoch 快照晋升协议。因此 ZK 的 READY 不足以授权自动晋升。

只读脚本 `scripts/check-md-failover-preflight.py` 将这些事实转换为机器可读的 BLOCKED 结果。无论分配是否已有两个 replica，它都禁止将静态信息当作安全晋升证明。所有操作仅查询 ZooKeeper 分配与 Docker 镜像，不修改现网。6 项测试覆盖真实拓扑、即使具备多个副本仍不能伪造证明、错误状态和异常节点。

## 已提交的基础机制

MDSvr `1b2ed12` 增加只读路由随角色和 epoch 变更的后台对账：旧 Primary 丧失权限时撤销对应 PartitionReadinessGuard；新 Primary 的合法只读路由建立在当前 assignment epoch，发布行情仍须先获得完整市场快照。共 48 项 Maven 单元测试通过。该补丁未加入 ZK 自动晋升，也未验证跨节点复制。

## 真正解决 P0 的顺序

1. 扩展为三节点真实同步复制；每分区需要两个经过完整 OrderSvr 行情快照、连续事件和 freshness watermark 验证的合法 Replica。不可把 C 的进程存活等同于同步完成。
2. 构建唯一领导者 ZK 控制器、主节点失联检测、基于已同步状态的 candidate proof、带版本 CAS epoch 晋升和过期主节点发布栅栏。控制面断开必须拒绝写入和过期行情发布。
3. 晋升时基于权威完整市场快照重新开放 publish；Robot 只有在 OrderSvr 挂单与账户/持仓核对后才能恢复，严禁重复单。
4. 隔离环境运行持续十租户流量下的故障注入、旧主归队、角色反转、双主检测与持久化成交/账户对账；通过后再进行 Mac 受控故障注入。当前不扩大到 25 租户，不继续触碰 Order/Trade 主节点。

## 适用范围

这是安全机制和可读门禁，并非完整的自动 MD 主故障接管。待真实晋升协议及其测试完成，才可将 P0 由未通过改为已通过。

## 冷部署的安全拓扑前置阶段

`deploy-saas.sh` 现在针对 **全新分区创建**且 `MD_CLUSTER_C_ENABLED=true` 的环境，将 C 节点标记为 `learners:["MDSvrC"]`，A/B 仍为原有 Primary/唯一指定同步 Replica。这样 C 才会按 `MdPartitionRuntime.shouldProcess` 接收 OrderSvr 行情流和完整市场快照；C 仍**不被计算为同步复制 quorum**，只有拿到可验证的事件连续性与新鲜度水位后，才能经独立审批转为真正同步 Replica。旧两节点部署保持原样。

对于已经存在的 256 个 ZK 分区，安装器保持原有幂等行为，不会直接覆盖已有主从分配，也不会在当前十租户系统中自动添加 learner。需要设计经过版本 CAS 的分区级在线迁移流程，验证 C 的同步进度之后才可晋升。这只是后续机制的**安全准备**，并非已经修复主节点故障期间 4/10 市场中断。

## Incremental depth gap fencing

MDSvr commit `5928ee5` invalidates the market-specific publish-ready epoch whenever a depth delta is missing or out of sequence. A fresh authoritative snapshot is needed to reopen publishing; other tenant markets remain unaffected. All 50 Maven tests passed. This is not automatic leader election and has not been deployed to the running ten-tenant cluster.

## ZooKeeper membership verification

Read-only preflight now requests the physical node path `get -s /MDTService/MDSvrX/MDSvrX` and validates its `ephemeralOwner` is nonzero. A live Docker container or a persistent parent folder is insufficient to attest membership. Live scan confirms all A/B/C ephemeral children currently exist. The preflight remains `BLOCKED` because 256 partitions still have only one configured replica each, and signed/durable market watermarks and promotion fences are missing.

## Latest verified MD safety changes (2026-10-10)

- [MDSvr c1be3b1](https://github.com/bliplink/com.app.dc.mdsvr/commit/c1be3b1ce53d4fa4f50d2363b93522c49b06a1e1): when the shared ZooKeeper client reports a disconnection, block publication from the local cached assignment and clear previously ready market epochs/read-route fences. A new complete market snapshot is required to regain publish readiness. All 54 Maven tests and CI passed. **Limit**: the common ZookeeperClient currently treats `ConnectedReadOnly` as connected; a future writable controller lease / fencing epoch protocol is still mandatory before claiming no split-brain across partitions.
- [MDSvr e70405e](https://github.com/bliplink/com.app.dc.mdsvr/commit/e70405eae178c376d9df44a84b5b38282c4d16cd): per-market local OrderSvr depth replay witness tracking full snapshot update ID, contiguous deltas, gaps, epoch and sample freshness, with epoch-aware rejection of stale rollback snapshots. Integrated real DepthBookFacade ingestion test. Full 63 Maven tests plus ARM64/AMD64 GitHub Actions successful. **Limit**: these volatile readings are NOT durable commits, do not prove source-wide state hashes or Trade/Projection consistency and may NEVER authorize promotion alone.
- [Deployment 0e2554e](https://github.com/bliplink/dc-quant-deploy/commit/0e2554e4664ad2bc8b61d157c2d27c297280725d): ZK failover gate now also checks nonzero `ephemeralOwner` for all three membership children under `/MDTService/MDSvrX/MDSvrX`. Live read-only scan confirms A/B/C ephemeral registration. Eight gate tests and CI passed; still `BLOCKED` on 256/256 insufficient configured replica slots and missing source commit/fence proofs.

Neither MDSvr commit has been deployed to the existing ten-tenant Demo (live pinned image remains `sha-48544e5`), and neither grants or enables automatic failover.

## 分区级全市场副本覆盖检查（2026-10-10）

[MDSvr 7f9cd83](https://github.com/bliplink/com.app.dc.mdsvr/commit/7f9cd830737e464669210a162ddc0a16b936d89a) 新增完整市场清单的本地连续前缀检查和 DepthBookFacade 只读入口，79 项 Maven 全量测试通过。它会拒绝分区内任意单个市场缺失、断档、epoch/序号/新鲜度不符、清单空缺及跨分区错配。但源清单仍没有 OrderSvr 持久化证明；无论单项检查匹配与否，`canPromote=false`。权威证明和 CAS 晋升协议仍待实现。详见 [分区级全市场追平阶段报告](MD_PARTITION_MARKET_COVERAGE_20261010.zh-CN.md)。

## OrderSvr committed-checkpoint market manifest → MD read-only comparer

[OrderSvr f2df4a9](https://github.com/bliplink/com.app.dc.ordersvr/commit/f2df4a97eb696cd85526bc6253eea41399302b47) adds a persisted-snapshot read-only market version manifest, with a canonical SHA-256 data-integrity checksum and structural commit boundary validation. [MDSvr 196ad18](https://github.com/bliplink/com.app.dc.mdsvr/commit/196ad18300e82888523add2eaf49c1c2bc96d402) parses the same JSON contract and compares the version map to locally contiguous per-market depth replay evidence. Order/MDSvr full local test runs: 305 and 84; CI builds pending at time of code commit. These are checkpoint-compatible code interfaces **without a running authenticated source→replica transport** and **cannot prove current durable HEAD or promote an MD primary**. See [full contract and missing guarantees](ORDER_MD_COMMITTED_CHECKPOINT_MANIFEST_20261010.zh-CN.md).
