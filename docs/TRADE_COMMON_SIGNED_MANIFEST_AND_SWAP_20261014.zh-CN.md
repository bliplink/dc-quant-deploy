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
