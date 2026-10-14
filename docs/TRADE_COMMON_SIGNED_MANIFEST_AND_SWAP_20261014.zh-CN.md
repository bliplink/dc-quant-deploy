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
