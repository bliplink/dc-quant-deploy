# Common/Trade 可信 Manifest 协议与 Colima Swap 验收（2026-10-14）

## 现网事实及变更隔离

当前 Mac mini Demo 仍为 **24 个服务、10 个 Robot RUNNING、400 活动挂单**；Order/Trade 业务 E2E 10/10，Order 三副本快照和 Projection 只读审计通过。现网仍运行 2026-10-12/13 缓存的 Order、Trade 镜像，**没有合并或部署以下 Common/Trade Draft PR**。

**Colima Swap 环境门槛已现场解决**：在运行中的 Colima VZ Linux 创建 mode 0600 的 `/swapfile`（1 GiB）并 `mkswap` / `swapon` 在线启用；`/proc/meminfo` 报 `SwapTotal=1048572 kB`、`SwapFree=1048572 kB`、已用 0，并向 VM `/etc/fstab` 写入唯一的 `/swapfile none swap sw,nofail 0 0` 挂载项。无容器重启。**尚未重启 Colima 验证持久化**，重启前须复核。

重新执行 `python3 tests/order_ha_rollout_gate.py --target OrderSvrA`：不再出现 Swap 不足；**仍 NO-GO**，剩余 `50/50 RUNNING` 和 `2000` 活动挂单负载门槛。不要修改此门禁直接强制测试。磁盘此前已降至约 73%，其余约 77 GB 历史隔离目录继续保留；独立 P246 故障证据不动。

## 恢复协议：统一 Common，不新造一套

先检查出旧 `VerifiedRecoveryStagingClient.stageWithBatch` 需要从客户端预先传入确切的 `exactImageBytes`；不能猜长度。验证过程中新增的 `SNAPSHOT_SIZE` 小协议原型虽然通过了 Common CI 和 Trade 的 250/250 测试，但复查整个 Common 源码发现它早已定义了**更完整的、独立签名的** `RecoverySourceManifestControlHandler` + `RecoverySnapshotManifestAttestation`，涵盖镜像字节长度、SHA256、Snapshot epoch/seq、已提交基线状态 seq/epoch 和 commitMarker。为了遵守统一 Common 状态机协议的架构要求，**重复的签长度协议两个 Draft PR #12 已主动关闭、从未合并或发布**。

已改成 canonical 方案：
- [Common PR #13](https://github.com/bliplink/com.app.common/pull/13)：`stageWithSourceManifest` 首先认证挑战绑定的 Source HEAD，再用**现有 Common Manifest** HMAC 认证完整镜像长度、baseline state/epoch/commit marker 与 HEAD 一致。随后复用 Common 原有的 64 KiB 分块下载、全镜像 SHA256 与连续 committed-WAL 审计，结果仅生成 `VERIFIED_STAGING_NOT_READY`。不引入重复 wire opcode，不授予 READY。
- [Trade PR #13](https://github.com/bliplink/com.app.dc.tradesvr/pull/13)：Trade SnapshotStore 从经过 SHA 核验的最新持久化 Snapshot 获取文件长度；Trade 只实现 `RecoverySourceManifestControlHandler.ManifestSource` 业务适配；原有 Netty control 端口统一路由 HEAD/DATA/Manifest，仍**全部默认关闭**。DATA 在 Manifest 未启用时不对外开放。真实 Netty loopback fixture 用上述 Common `stageWithSourceManifest` 完成全 Snapshot + WAL 的隔离 NOT_READY staging。
- 已有 Common [durable replica ACK PR #11](https://github.com/bliplink/com.app.common/pull/11)、Trade [replay/ledger PR #11](https://github.com/bliplink/com.app.dc.tradesvr/pull/11) 均仍为 Draft/staged，未发布。
- 独立 CI：Common canonical Manifest [Actions](https://github.com/bliplink/com.app.common/actions/runs/38553262544) 成功；Trade 首轮 canonical [Actions](https://github.com/bliplink/com.app.dc.tradesvr/actions/runs/38553476191) 成功、`250/250` Java8 测试 + Docker 候选镜像。Trade 后续增加了大快照 SHA 缓存优化及“原子替换同 ID/seq 必须重新签名”回归，**最终 CI 应以分支最新 HEAD 为准**，不得以旧 run 代替。
- 为降低签名 HEAD 每分块重复 SHA 整份快照的 I/O，Trade 候选分支新增限定在 inode+unix:ctime+mtime+size+snapshot identity 不变时缓存源文件 SHA；缺少可靠文件身份/ctime 时仍完整计算，接收端最终重新校验整个镜像。新镜像分支仍禁发布。

## 尚未完成、不能绕过的生产接收端步骤

1. **生产接收节点会话**：认证源端身份、共享密钥安全供应、独立确认最新 ZooKeeper 角色/版本、Source HEAD + Replica durable ACK 与一致的 Quorum committed head。不能只签单节点内存/本地 WAL。
2. 在实际 Trade Replica 上运行 Common `StateMachineRecoveryCoordinator.Control`：先持久化 NOT_READY、独占业务分区 barrier、保全原始镜像/本地日志回滚状态，fsync Snapshot/目录和 Journal 真实基线；安装过程可在 SIGKILL、磁盘写失败及 Epoch 变化后拒绝普通 READY 并重新认证重试。
3. 完整 Snapshot 和已验证 committed Diff 经 Trade 业务状态机单事务 restore，并经过 MySQL orders/executions/balance/position、Projection watermark、Trade 状态、open order 权威对账与旧主隔离后，才允许外部 READY。
4. MD 还需独立的全市场 Snapshot/Diff、旧行情发布者 fencing；Order/Trade 共享 Common 模式，Gateway 不改业务。
5. 容量及真故障注入按门禁执行：50/50 Robot、2000 活动挂单、资源、持续下单、SIGKILL 当前 Primary、权威提交水位、无丢单/重成交/双主、恢复节点追平与主备反转，后续 200 户。

**当前许可结论：GO 10 户功能与独立 read-only 验证；NO-GO 主节点 SIGKILL、归档不可证明段删除、GHCR 新镜像替换。** 

## 追加进展：接收端真实持久化恢复最小安全子集（19:30 CST 后）

在原 [Trade PR #13](https://github.com/bliplink/com.app.dc.tradesvr/pull/13) 的完整签名 Manifest + Netty NOT_READY staging 上，继续形成 [Trade Draft PR #14](https://github.com/bliplink/com.app.dc.tradesvr/pull/14)：

- `TradeRecoveryReplicaFence`：持有真实 ZooKeeper assignment 的物理源 Primary、目标 Replica/Learner、ZK version 与 epoch；先证明接收者不是 Primary 才撤销其 READY；进入和业务写入共用的 Trade 分区锁后再次检查相同证据。版本/源节点/epoch/成员关系改变或断线时拒绝。
- `TradeSnapshotStore.installVerifiedRecoveryImage`：仅在上述排他锁内、已有 Common `INSTALLING` 保护的情形下使用；检查完整 business Snapshot 的字段、SHA 和 bounded length，按原始字节写入 temp + fsync，要求 `ATOMIC_MOVE`，再 fsync 父目录并核对原始文件 SHA。
- `TradePartitionJournal.saveBaseline`：从旧的“temp 文件 fsync + 普通 rename”升级为 **temp fsync + 强制原子替换 + 父目录 fsync + 落盘全字段回读验证**，不能在重启后丢失已宣布持久的基线。
- `TradeRecoveryReplicaJournalBaseline`：注入到 Common 已有 `DurableRecoveryTransactionControl.JournalBaseline` 的真正业务适配器，执行同 epoch 前向快照重建，确认真实 Chronicle 基线 cold-reopen 后的 snapshotId/epoch/snapshotSeq/committedStateEpoch/Seq/commitMarkerSeq 全部匹配；若失败则由 Common durable ledger 阻止普通 READY。
- **重要限制：目前仅支持源端 committed HEAD 恰好等于完整 Snapshot commit marker 的情况**。如果 Snapshot 后存在任何 WAL 后缀，安装器明确失败；不能用“只内存 apply 后缀”替代真实 Chronicle 持久化写入。更不能把该分支当作可做主切的完整恢复。
- 最新 [Trade Actions 38556910459](https://github.com/bliplink/com.app.dc.tradesvr/actions/runs/38556910459)：**260/260 Java8 测试通过，真实 Chronicle 文件和 cold-reopen 验收通过，候选 Docker image 构建通过**。没有合并到 `saas-crypto`、没有发布 GHCR、没有替换演示集群。

另一个在线审计修复已完成：[dc-quant-deploy PR #27](https://github.com/bliplink/dc-quant-deploy/pull/27)。在 10 租户持续交易下，Projection 旧水位检查因 MySQL 相关子查询 `Using filesort` 超过 1500ms，报错误 3024；并**非已证明数据不一致**。新版先只读发现 bounded partition catalog，再在**同一个 REPEATABLE READ、READ ONLY consistent snapshot 事务**里重新读取 watermark catalog，并对每个源分区使用常量分区键的复合索引倒序 `LIMIT 1` 检查事件尾部；catalog 变化、缺尾或超时仍 NO-GO。**13/13 单测和当前 10 Order+10 Trade 分区的真实 MySQL `PROJECTION_DB_TAIL_MATCH` 通过**；PR GitHub CI 通过，已合并，不授权 HA。

**剩余不可绕过的 P0：** 通用 Common 源端 committed HEAD 需要真实副本 durable ACK 认证；Trade 还要完成带 WAL 后缀的持久导入、崩溃恢复闭环、接收端受控启动，并完成 Order/Trade/Projection 的权威资金、持仓、成交、挂单对账和旧主隔离。MD 的 Snapshot/Diff 与旧发布者 fence 也未完成。Order HA 注入仍受 50/50 Robot 和 2,000 单真实负载门禁阻塞。Swap 当前在线但尚未经过 Colima 重启持久化实测。

## 继续推进：Common/Trade 原始 WAL 持久化 + 中断安全续传（20:15 CST 后）

依赖关系：**Common 已有完整 Manifest/Durable ACK [PR #11](https://github.com/bliplink/com.app.common/pull/11) → Common Canonical Manifest staging [PR #13](https://github.com/bliplink/com.app.common/pull/13) → [Common PR #14](https://github.com/bliplink/com.app.common/pull/14)**；Trade 对应 **recovery base PR #11 → Manifest PR #13 → Role/CQ PR #14 → [Trade PR #15](https://github.com/bliplink/com.app.dc.tradesvr/pull/15)**。均为未合并的 Draft 层叠候选；不可只拿最后一层 commit 冒充现网部署。

本轮新增机制：

1. **Common 保存原始认证 WAL 字节**：原来的 `CommittedRecord.protocolControl` 严格不允许 `STATE_COMMIT` 进入业务状态机，这一点不变。新增独立 `originalJournalWire()` 用于恢复时物理保存完整控制帧。由 `VerifiedRecoveryStagingClient.committedLogSource` 在 HMAC/Source HEAD/Manifest + 累积 committed prefix 通过后构造；普通无认证记录不能作为磁盘导入证据。
2. **Trade 真实 Chronicle WAL 导入**：接收端先完整检验所有 WAL 帧的序号、epoch、分区、真实业务事件类型、累积 `STATE_COMMIT` 和签名 HEAD 的最终提交水位；所有证据全部通过后，才持久化同 epoch 完整 Snapshot、原子重建 CQ baseline，并原样写入每一条 `STATE_BATCH` 和 `STATE_COMMIT`。需要最后一个 WAL 页完成 `msync`，再校验持久化 Chronicle 的实际最后提交标记与源端 HEAD。严格限制每次最多 4096 个 WAL slot、总 64 MiB。普通业务 `apply()` 永远跳过控制帧。
3. **Common durable ledger v2**：原先只持久化镜像/HEAD 边界；现在额外固定 Snapshot 基线与最终提交 StateSeq/Epoch/Marker，防止出现相同 HEAD 序号、同一快照 SHA，但不同最终提交证据的跨事务续传。旧版 v1 ledger 不作为 v2 完整恢复证明，会 fail closed。
4. **崩溃后安全续传**：Trade `appendRecoveredVerified` 遇到重放的已有 CQ 序号，必须从物理 Chronicle 读回并与可信源的**原始字节逐字节比对**，不能采用普通 `appendReplicated` 的“seq≤lastSeq 直接跳过”优化。仅在 Common `requireAuthenticatedIncompleteRetry` 证明同一未完成的持久安装事务、存储基线和完整 Snapshot SHA 再次匹配时，才允许补齐缺失的 WAL suffix；否则保持 NOT_READY。恢复成功也只是 `REPLAY_COMPLETE`，仍不授予 READY。
5. **测试用例**：在写入第一条 WAL（STATE_BATCH）后注入 `IOException`，确认 Common ledger `INSTALLING` 保留，冷启动仍拒绝 READY；重新使用**逐字节相同**的认证 WAL 事务补全 `STATE_COMMIT`，在重开的真实 Chronicle 校验末尾 102、Snapshot 基线 100。单独测试同序号而物理字节不同必须拒绝。另有完整 **真实 loopback Netty 认证 Source HEAD + Manifest → Snapshot 分块 → WAL prefix → Trade recipient Chronicle 恢复 + 关闭后重新打开** 的集成测试，隔离使用模拟 ZK/外部 Authority。
6. CI 证据：Common [Actions 38561322780](https://github.com/bliplink/com.app.common/actions/runs/38561322780) **通过**；最新 Trade [Actions 38562227580](https://github.com/bliplink/com.app.dc.tradesvr/actions/runs/38562227580) **263/263 Java8 测试、候选 Docker image build 通过**，不发布 Maven Central / GHCR，也未替换现网容器。

**本轮明确没有验收成功的能力**：源端 quorum commit HEAD 与多副本 durable ACK 的强一致绑定；生产真实 ZooKeeper Receiver 受控启动/重试自动调度、源端 HEAD 在接收期间继续写入时的协议快照一致性、跨 epoch/主备反转、多副本丢失/网络分裂的双主隔离、Order/Trade/Projection 权威资金/持仓/成交/挂单对账、MD 全行情 Snapshot/Diff + 旧发布者 fencing、50/100/200 租户和真实 SIGKILL HA 故障注入。**CI 263/263 不是故障切换 PASS**。

维护约束：本轮未删除现网 WAL、未重启 Mac Docker 或更改 Gateway 业务逻辑；变更保持候选 Draft、默认禁用。

## 继续推进：独立物理副本的持久化提交签名凭据（2026-10-14 晚）

- [Common Draft PR #15](https://github.com/bliplink/com.app.common/pull/15) 增加只读 `RecoveryQuorumCommitAttestation`、`RecoveryDurablePrefixControlHandler` 和 `VerifiedRecoveryQuorumClient`。签名受独立 HMAC domain、原始 32-byte challenge、真实物理节点 ID、ZooKeeper 版本、分区、epoch、提交头序号、累计状态 seq/epoch 和本地 **原始 STATE_COMMIT 标记 SHA256** 约束。客户端在独立物理 Netty endpoint 逐台拉取凭据，前后重新验证完整 ZK 投票成员/版本；Primary 单节点汇总的普通 `ReplicationAck` 不再被当作独立法定人数证据。必须有 Primary 证明 + 过半数真正投票成员；Learner、过期/重放挑战、签名伪造、密钥混用、异常角色、分区/epoch/版本不同全部失败关闭。所有投票节点必须使用**不同的 256bit+ 密钥**，集群共享 HMAC 密钥不能认证独立副本。
- [Trade Draft PR #16](https://github.com/bliplink/com.app.dc.tradesvr/pull/16) 只实现业务侧源证据适配器：利用实际 Trade 业务分区锁、独立读取的 ZooKeeper assignment、源/投票 Replica（排除 Learner）角色验证，`syncJournalThrough()` 保证本地 Chronicle WAL 已持久化，`TradeCommitWatermark.scan` 核对目标水位为完整累计 `STATE_COMMIT`，读取本地 CQ 的**原始物理标记**并计算 SHA256，fsync 前后两次检查 ZK role/version/epoch。Common 完全不解析 Trade 业务事件。仍通过原来内部复制 Netty Control port，可单独配置 `trade.cluster.recovery.quorumReceipt.enabled:false`（**默认关闭**），不增 Gateway 逻辑，不授权 READY。
- 测试：Common 真实双独立本地 TCP endpoint 的签名凭据获取和双边 ZK membership recheck、原始 challenge/MAC/epoch/物理 identity 重放与篡改、孤立主节点、非投票 Learner、全局共享密钥拒绝；Trade 自身提交标记/非投票源业务校验 + Java8 候选 Docker build。**只当最新的 Common/Trade 分支 CI 明确成功时计入完成**，此前旧版本 CI 不可代替。
- **特别强调：当前证明只认证同一个完整提交标记与状态水位，不验证该提交标记之前所有 WAL 字节逐一相同。** 这不是完整 committed WAL prefix hash；更不是跨故障源端绝对权威提交。真实 HA 仍必须逐字节核对 Common 已认证的 Snapshot + 累积 Diff，交叉认证投票成员，重放后执行资金/持仓/成交/挂单/Projection 权威一致性与旧主 fencing。
- 独立投票凭据属于 Common 状态机通用读协议，Order/Trade/MD 可以各自提供业务侧 WAL 持久水位，并通过公共验证器复用，禁止再增加 Trade 私有法定人数算法。当前仍**不合并到正式 saas-crypto、不发布 Maven Central 或 GHCR、不替换现网、不进行 SIGKILL**。

## 继续推进：完整 Snapshot 锚定 WAL 前缀的独立副本多数签名（2026-10-14 夜间）

已在 [Common Draft PR #16](https://github.com/bliplink/com.app.common/pull/16) 和 [Trade Draft PR #17](https://github.com/bliplink/com.app.dc.tradesvr/pull/17) 完成独立候选实现，**仍未合并发布**。

1. **原协议缺口与版本替换**：上一版多数节点签署相同 `STATE_COMMIT` 原始标记及累计 state/epoch，这仍不能证明**中间 WAL 字节完全相同**。Common 因此将物理副本凭据改成互不兼容的 **`OTC-RECOVERY-COMMIT-QUORUM-v2`**，拒绝 v1 协议。签名额外绑定完整 Snapshot 的序号与 SHA256，以及从该 Snapshot 到提交 HEAD 的**全部物理 STATE / STATE_COMMIT WAL 帧摘要**；snapshotEpoch 必须和 commitEpoch 一致，当前不允许跨 epoch 推断。
2. **Common RecoveryWalWindowDigest**：SHA-256 按固定 domain、分区、epoch、Snapshot seq+sha、签名 HEAD、每条 WAL 的物理序号、原始字节长度和原始数据计算；任何缺口、重复、乱序、错 epoch、截断或长度超限立刻 NO-GO。恢复挑战最多 **4096 个原始 WAL 槽/64 MiB**，无法审计更老历史时明确拒绝，绝不凭最后一次 `ReplicationAck` 或只比较末尾 marker 放行。
3. **Common 认证期望来源**：新增 `RecoveryQuorumWindowFromStaging.requireFullWindow`，必须先从经过真实 Netty HMAC、源端 HEAD + Manifest、完整 Snapshot SHA、累积已提交 WAL grammar 和 immutable staging receipt 验证的**接收端数据**，独立重新计算期望的完整区间摘要。 `VerifiedRecoveryQuorumClient` 再用独立可信的 Source HEAD 绑定 Snapshot/HEAD，向由 ZooKeeper 完整指定的物理投票副本各自获取签名凭据。不能让源 Primary 随意提供“预期 WAL 哈希”。
4. **Trade 只提供状态机业务适配**：源端按 Trade 业务分区锁、真实 ZooKeeper 角色、持久化 Snapshot 和 Chronicle Journal 物理内容导出；读取区间通过恢复专用 `readRecoveryBatch` 在解码后与原始 CQ 文本逐字节核对，**普通复制/catch-up `readBatch` 不承担额外重编码开销**。每个已提交 STATE/STATE_COMMIT 包括控制帧都参与摘要；快照错配、归档段未覆盖或超过上限时禁止签名。
5. **集成测试**：Common 负向测试涵盖篡改中间 STATE 而保持最后 STATE_COMMIT 不变、Snapshot SHA 改动、缺口、乱序、epoch/version、前缀超限、错误 HMAC、错误投票者或共享密钥。Trade 真实 Netty 源端认证、Manifest+WAL staging、真实 Chronicle CQ 安装及关闭重开的**完整区间摘要一致**测试通过。
6. **CI**：[Common 38570204457](https://github.com/bliplink/com.app.common/actions/runs/38570204457) 成功；最终 [Trade 38570596966](https://github.com/bliplink/com.app.dc.tradesvr/actions/runs/38570596966) Java8 **265/265** 测试、程序打包及候选 Docker 构建均成功（CI 只在工作目录本地安装 Common 3.0.21-SNAPSHOT 和 com.app.dc，不发布中央仓库/GHCR）。

**尚未得到生产授权：** 真实物理副本 ZooKeeper 独立投票成员发现和带有效期的接收端 recovery authority 还没有真正挂到 Trade 生产状态机/启动流程；不同副本若使用不同 Snapshot 版本，则当前严格拒绝，未来需要可信统一快照版本或可验证归档前缀。还缺旧 Primary fencing、跨 Epoch role reversal、完整金额/持仓/委托/执行/Projection 数据权威一致性对账、MD 旧发布者隔离以及 50 Robot/2000 挂单与 200 租户负载和真实 SIGKILL。**CI 全绿仅能说明隔离候选代码正确，不能推断线上 HA 已安全。**

发布顺序仍是 Common/Trade 各层叠 PR 按依赖验证、发布统一版本、冷部署候选隔离验证、负载门禁后才执行主切；Demo 当前不可据此放开故障注入。

## 恢复 Quorum 凭据的请求认证加固（2026-10-14 晚）

**遵守 Common 统一协议的架构约束**：此前 [Common PR #16](https://github.com/bliplink/com.app.common/pull/16) 与 [Trade PR #17](https://github.com/bliplink/com.app.dc.tradesvr/pull/17) 已完成比只签末尾 commit 更强的、**完整 Snapshot SHA 锚定 + 全部原始 WAL diff 字节**的签名 Quorum；不要额外部署或合并重复实现。已关闭误生成的重复 Draft Common #18、Trade #19，保留原正确的统一机制。

额外发现源端副本凭据的内部 Netty Control 查询原来只携带 unsigned challenge + committed seq，任何能访问私有复制端口的网络客户端都可能频繁触发 Chronicle `syncJournalThrough` + 最多 4096 WAL slots/64 MiB 的 SHA 扫描，造成恢复接口放大负载。为保障系统**性能优先**，新增一个只针对现有协议的增量保护：

- [Common Draft PR #19](https://github.com/bliplink/com.app.common/pull/19) `fix/common-recovery-quorum-query-auth-20261014`：换成不兼容旧 unsigned 请求的内部 `RECOVERY_DURABLE_PREFIX_SIGNED_QUERY_V2`，要求先计算并验证目标物理节点 256-bit 独立密钥的 HMAC，覆盖 challenge、序号、标准化服务名、分区及物理目的节点。**HMAC 比对发生在读取任何业务文件、执行 fsync 或窗口哈希之前**；错误节点密钥、篡改请求均 fail closed。保留已经完成的 Common full Snapshot/WAL signed quorum，无新业务协议、无 Gateway 修改。
- Common 真 Netty 及单元测试新增：伪造 HMAC 或使用别的物理节点密钥访问端口时，源端读盘回调**0 次**；合法查询可以继续。Common Java8 CI [Actions 38587400503](https://github.com/bliplink/com.app.common/actions/runs/38587400503) SUCCESS。
- Trade 不新增业务代码。仅从已经通过 265/265 的 canonical Trade PR #17 创建私有 CI 分支 `ci/trade-quorum-auth-integration-20261014`，在构建期使用上述 Common Candidate 运行全部 Java8 测试、依赖解析和候选 Docker 镜像构建。[Actions 38587566054](https://github.com/bliplink/com.app.dc.tradesvr/actions/runs/38587566054) 已确认 **SUCCESS：265/265 项 Java8 Trade 测试通过、Trade package 与候选 Docker build 成功**；不会发布 Maven Central/GHCR 或替换 Demo。
- **线上继续禁止 HA SIGKILL**：实际 ZooKeeper voting members 与恢复服务独立授权、完整源端提交 ACK 的生产绑定、外部财务/委托/持仓/成交/Projection READY 对账、MD 旧发布者 fencing、50/200 租户压测和主备反转还未验收；不能把测试中可签名的 Quorum 直接视为生产合法促主。

本次只读观察：2026-10-14 23:08 CST，Mac Demo 为 **24 容器运行、11/11 Robot RUNNING、440 活动挂单**，在线 MySQL 的 Order 和 Trade Projection 各 11 个分区返回 `PROJECTION_DB_TAIL_MATCH` / exit 0，macOS 磁盘约 71%。新增第 11 租户不是本次开发操作创建。本轮没有重启服务、删除 WAL、清理证据或替换任何现网镜像。

## 追加验收：投票凭据必须覆盖完整 Snapshot/WAL 原始区间（2026-10-14 23:47 CST）

之前 Common [PR #15](https://github.com/bliplink/com.app.common/pull/15) 的物理副本 HMAC 凭据只包含最终 `STATE_COMMIT` 的原始 SHA 和累计提交状态，**无法单独证明最后提交标记之前的所有 WAL 字节相同**。这个安全缺口现在在两个层叠 Draft PR 中作出了代码级修复：

- [Common Draft PR #20](https://github.com/bliplink/com.app.common/pull/20)：新通用 `RecoveryWalRangeDigest` 对同一分区、epoch、`snapshotSeq`、完整 Snapshot SHA、`committedHeadSeq` 及区间内**每条原始物理 WAL 的完整字节（含所有 STATE、STATE_COMMIT 控制帧）、序号、epoch 与帧长度**做确定性流式 SHA-256。限制单次 ≤4096 帧/64MiB，任何中间缺帧、乱序、跨 epoch、Snapshot 锚点不一致、只匹配最终 COMMIT 都不能认证。独立物理投票 HMAC 凭据线格式升级至**尚未发布的 V2**，签名绑定 Snapshot 和整个 WAL 区间 SHA；缺少完整 V2 内容即拒绝，不接受旧 V1 提交标记签名作为 Quorum。新增 `VerifiedRecoveryQuorumClient.requireHeadBoundPhysicalQuorum` 将完整 WAL 区间与另一条**已通过签名验证的源端 HEAD**的 Snapshot 序号/hash、提交 head、state、epoch 和最终 commitMarker 显式绑定。各节点独立密钥、可信 ZooKeeper voters、角色/版本/nonce 二次检查仍保持。
- [Trade Draft PR #20](https://github.com/bliplink/com.app.dc.tradesvr/pull/20)：`TradePartitionJournal.digestDurableRawRange` 在业务读 barrier 下，从真实 Chronicle *raw* 文本字节读取受限 WAL 区间，要求物理最后索引、连续 seq/epoch、包含完整区间，并同时使用 Common `CommittedWalPrefixVerifier` 检查 **STATE/STATE_COMMIT 累计提交语义**，不得只凭文件中的最后一条 marker。Trade 的恢复投票凭据只能从本地 fsync 过的 Journal、当前同 epoch 完整 Snapshot hash 和签名物理标记构造；如果源端 Archive 已删除该 WAL 或 Snapshot 太旧（>4096 帧），**明确 NO-GO**，不得省略历史帧来签名。
- Common [Actions 38591856028](https://github.com/bliplink/com.app.common/actions/runs/38591856028) **SUCCESS**；Trade 最新 [Actions 38592198601](https://github.com/bliplink/com.app.dc.tradesvr/actions/runs/38592198601) **SUCCESS，266/266 Trade Java8 测试通过，候选 Docker 编译成功**。加入真实 Chronicle 冷重开 SHA 不变、相同最终 COMMIT 但早期 STATE 字节被修改必须产生不同 digest 的回归。
- CI 初始发现测试模拟 SHA 写成 60 位而非 64 位，正确被协议拒绝。修正测试夹具后 Common/Trade 最新 CI 均绿。记录初次失败并不意味着生产数据损坏。
- 2026-10-14 23:47 CST 现网最新**只读**状态：24 个 SaaS 容器、**11/11 Robot RUNNING**、440 活动挂单、Order/Trade 各 11 个 Projection 水位均 `PROJECTION_DB_TAIL_MATCH`；Mac 约 72% 磁盘使用率/124 GiB 可用，Colima Swap 可用。与之前 10 户不同，新增第 11 户不是本次 Quorum 开发操作创建的，不能据此声明压测达到 50 户。

### 尚未完成的生产授权闭环

1. 在真实被动接收者启动流程中串起 `Source HEAD → source Manifest → 完整 WalRange quorum V2 → 真实 ZooKeeper voters → Chronicle 安装/中断续传 → 外部 READY`，中途源端/epoch/voter 成员变化即撤销凭据。
2. 50 个 Robot/2000 挂单条件、MD full Snapshot/Diff 与旧发布者 fencing，及恢复后资金/持仓/委托/成交/Projection authoritative 对账，均未验收。
3. V2 单次认证被**4096 帧/64MiB**严格约束。旧归档删除或快照未及时更新造成无法证明的区间必须被报告为阻塞，不可放宽到跳过校验。可能需要按性能情况进一步设计滚动持久 prefix digest/checkpoint，不应把全量重复扫描放进交易热路径。
4. 本轮未合并 Draft Common/Trade、未发布 Maven Central 或 GHCR、未更换现网镜像、未执行 SIGKILL/删除 WAL。**CI 成功不代表生产 HA 通过。**
