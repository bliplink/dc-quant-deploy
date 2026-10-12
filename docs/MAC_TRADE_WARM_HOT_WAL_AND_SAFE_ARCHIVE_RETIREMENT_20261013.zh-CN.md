# 2026-10-13 Trade Replica 温缓存与 WAL 安全回收进度（Mac Demo）

## 当前集群真实状态（北京时间 06:03）

实机只读审计：`dc-saas` 24/24 容器运行，无重启/无 OOM。
10/10 租户 Robot `RUNNING`，每户有 40 个活动委托、
订单簿买卖各十档；这是机器人 Demo 交易基线，不是
200 户吞吐或真实带持仓 failover 的证明。

运行中的 Trade A/B 仍为：

`dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261012-archive-recovery-0e798cc`

**新的候选镜像没有热替换在线A/B，没有重启唯一同步副本。**
当前 `trade.cluster.recovery.source.enabled` 与
`replica.autoWarm.enabled` 尚未在现有进程启动时开启，
因此目前仍然不能声称 Replica 全量 Snapshot 自动追平。

最近的权威只读 ZooKeeper + Full Snapshot 门禁
（`tenants-morning-20261013.json`，
`trade-snapshot-role-gate-morning-20261013.json`）：
10/10 活跃租户分区存在落后/不含业务租户的 Replica
完整快照，`decision=BLOCKED`，
**不能执行持仓 SIGKILL、不能强制提升或盲重启 Trade A/B**。
WAL 最新提交尾部此前已作过主备字节一致性采样，
但这种采样不能替代副本持久可恢复快照证明。

## Trade 自动温缓存性能 P0 修复

源码：
`bliplink/com.app.dc.tradesvr`，
分支 `codex/trade-safe-wal-archive-canary-20261012`，
连续提交：

- `1c18a93aa533ef67060a999d7531a975d23c3ded`：
  已同步的 Replica Snapshot 不占用每轮唯一真实传输机会，
  同轮继续搜索需要恢复的分区，失败保持指数退避；
- `72e98ce9a64357118f4ea3edf91e017216bad40c`：
  利用本地已有的 `*.cq4` 日志段存在性**只读优先级提示**
  先扫描活跃业务分区，减少256个分区中空 WAL 的
  签名 HEAD 请求。只检查文件存在、不读正文、不解析
  业务状态、不修改 Chronicle；
  只有 `metadata.cq4t` 的空分区仍保留兜底扫描资格。

保留恢复传输上限：**每轮最多一次真实传输或失败尝试**，
没有并行IO、没有放松同步 ACK、ZK epoch 或签名检查。

实机文件目录确认：Trade A/B 每个都有256个分区
目录，大量空分区只有 `metadata.cq4t`，
活跃租户分区有实际 `*.cq4` 日志段；
这正是新优先级提示的依据。

使用本地固定的 Common `6b8fe7d` 依赖链，
Java8 `mvn -o clean test`：
**294/294 PASS，0失败、0错误、0跳过，72个测试类**。
其中真实 Netty 回环签名 HEAD/Manifest、分块快照、
STATE/STATE_COMMIT WAL 后缀、持久seal、快照缓存落盘、
不得提前 READY 的专项端到端测试均通过。
这些测试用隔离业务数据，不代表在线集群已替换。

候选镜像（仅 Mac 本地构建）：

`dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261013-hotwarm-72e98ce`

源码 SHA `72e98ce9a64357118f4ea3edf91e017216bad40c`，
Common JAR SHA256
`34a6ee05db748eb2990f68b1dc86188a41ca52c320e1838b9cd82fd3c77a0363`，
镜像 labels 已核对。
尚未用 GitHub Actions 发布 GHCR 多架构正式镜像。

## Common WAL 日志安全删除业务接入层

源码：
`bliplink/com.app.common`，
分支 `codex/common-wal-rotation-policy-20261012`，
提交 `5105ab1edb34af7e392d19bc401e757e996b8035`。

新增 `VerifiedLocalArchiveRetirementAdapter`，
连接以下已实现的通用功能：

1. `SnapshotRetentionFence`：必须完整验证
   full Snapshot、全部 Replica 的可恢复水位、
   Projection及其它消费者持久水位、最小保留期、
   文件句柄关闭、回滚历史完整性；
2. `JournalArchiveRetirementCoordinator`：
   `PREPARED → QUARANTINED → REMOVED` 持久事务，
   操作前后锁内再次检查权威水位；
3. `LocalArchiveQuarantineFileOps`：只允许
   `.archive` 下准确的
   `Pnnn-epochN-seqN-timestamp` 已封存目录，
   根据可信 `ARCHIVE_SEALED` ledger 中的 SHA256
   做实际文件校验、同盘原子迁移、fsync、
   确认持久证据后才物理删除；
   隔离目录必须是相邻的
   `.retirement-quarantine`，拒绝将活跃journal
   当成回收对象。

测试采用**真实文件与磁盘隔离/删除**，
而业务锁和持久水位使用测试双生实现：
错 SHA、消费者水位回退、重复事务、
隔离态崩溃等必须 FAIL CLOSED。
**Common Java8 全量252/252测试通过，
零失败，零错误，零跳过。**

这使得 Order/Trade 可以复用公共安全回收流程，
但它们仍需要提供自己的
`ArchiveAuthority/FencedLease`：
严格验证持久seal ledger、当前分区 ZK epoch、
关闭所有相关 Chronicle reader/generation，
Replica真正可恢复的full Snapshot，
Projection订单/成交/资金/持仓各消费水位。

**本次没有把这个 Adapter 以虚假水位接入在线清理线程，
也没有调用生产unlink。**

## 在线 WAL 审计（北京时间06:03）

`tests/audit_saas_wal_archives_readonly.py`：

```text
archiveDirectories             512
agedCandidateDirectories         0
archiveAllocatedBytes     67108864 (64 MiB)
activeAllocatedBytes   12921765888
deletionAuthorized               0
unsafeOrUnknownEntries           0
```

活跃 WAL 实际分配约12.0GiB，不是单一服务，
并且绝不可只按文件表观大小删除。
现网48小时保留期尚未满足，
Replica/Projection完整证明也缺失。
日志自动轮转和删除**仍未在线启用**。

## 后续严格的上线顺序

1. 使用隔离环境/受控停机窗口，将新 Trade 候选镜像
   与 `TRADE_CLUSTER_RECOVERY_WARM_ENABLED=true`
   的全链配置一起部署；
   本机host network只用127.0.0.1，不需要TLS。
2. 在至少一个真实活跃业务分区，验证签名HEAD、
   Manifest、WAL下行、Replica完整快照fsync、epoch
   与source物理身份、门禁从BLOCK到可靠证据；
   然后验证带持仓进程级故障接管、恢复节点和角色反转。
3. Order、Trade提供各自ArchiveAuthority
   可证明的真实Snapshot/Replica/Projection水位，
   完成同epoch物理WAL轮转与重启恢复。
4. 保留 `enabled=false` 直到旧归档达到保留期，
   并经过多次真实故障注入、历史查询、资金/订单
   对账，才为确切、可回滚证据的segment打开GC；
   其它候选继续保留。

Gateway纯透传机制不变；MD自动主切验证另外走
Order市场镜像恢复与epoch fence，不能以本轮Trade
测试替代。
