# T278｜Common 高 Epoch 自动 Replica 重加入：真实双向故障验收（2026-10-29）

## 完成内容

**阶段 PASS，整体 P0 仍 NO-GO**。本轮实际开发了两个业务无关的 Common 公共组件：

- `CommonCertifiedReplicaRejoin.installHigherEpochReplica`：只有 E3+（或已认证更高 Epoch）ZK READY 赋予当前节点明确 Replica 角色、签名旧 Epoch 转换验证成功后，才通过既有 Common `LocalReplicaCatchup` 读取当前主节点签名的不透明 `byte[]` WAL，逐帧 fsync 到本地，生成独立 RSA Replica 回执，验证两个物理签名者同一 WAL 头，最后将不透明 bytes 交给业务状态机 `apply/finishReplay`。**这不是新的复制协议，也不会授予 Primary、发布 READY、对客户端发 ACK、或把旧 LOCAL ACK 追认为 QUORUM。**
- `CommonCertifiedReplicaRejoinWatch`：一个冷控制线程；每次尝试重新要求最新认证 ZK Manifest/版本以及存活 Primary 租约。授权未到位时拒绝并重试，成功才对启动方报告已安装；任何缺证书、错误身份、错配 Epoch、错误策略或分叉 WAL 都必须拒绝。失败后不覆盖已存在的物理 WAL 尾部。
- 原 `CommonDemoRejoinedBProcess` 测试节点不再自己逐步组织签名 WAL 下载、物理签名、回放，而是启动并等待 Common 通用重加入 Watch。测试的业务状态机仍只解析自己的 `byte[]`。
- 新增 `CommonCertifiedReplicaRejoinTest`：没有签名 Stage、错误恢复策略和未认证旧 Epoch 时，都不能创建副本 WAL 或调用业务 `apply`。

Common 源码：`~/.opentradingcore/t177-common-saas-crypto-integration-20261027`，本地分支 `codex/t177-common-saas-crypto-integration-20261027`，提交 `a925626`（**尚未合入所有业务仓库 saas-crypto 的正式构建**）。本轮候选 Common Jar SHA256：`77bd923109490f91d300d7b843c4404a019a1a2f2be5eba8591f7c1cb364b51d`。

## 全部真实测试结果

- 测试使用现有 A/B/C RSA 密钥（只读）、三个真实 ZooKeeper、两个真实 Netty 节点、多次实际 `SIGKILL`，并在一个新的 B JVM 上启动 Common 重加入控制线程。原始证据路径 `~/.opentradingcore/t124-live-kill-runs/20261029130214`；本轮全流程日志 `~/.opentradingcore/p0-20261029-evidence/t278-auto-rejoin-watch-real-sigkill.log`；**脚本退出 0**。
- `T275_COMMON_WATCH_THREAD_VERIFIED_E2_RSA_READY=PASS`、`T276_COMMON_WATCH_THREAD_VERIFIED_E3_RSA_READY=PASS`：两次真正主故障后 Common 控制线程恢复 READY。
- `T278_COMMON_AUTOMATIC_E3_REJOIN_WATCH_SIGNED_RSA=PASS` 与 `T277_COMMON_GENERIC_E3_REPLICA_RSA_INSTALL_PASS head=2 applied=2`：B 的新 Common 控制线程确认 E3 原始签名 WAL 安装完成、物理前缀等价、两个不透明业务命令回放。
- B 之后通过 Common 控制获得 E3 Replica 角色；A 在 B 回归后通过 Common TCP+RSA 复制新业务，`T272_REAL_A_E3_NEW_BUSINESS_TO_REJOINED_B_TCP_RSA_FSYNC=PASS`，双方最终总值 **85**、去重请求 **7**、E3 seq **3**。**旧 E2/E3 写入均为 LOCAL_DURABLE_ASYNC，保留 RPO 风险**。
- 本轮使用现有 RSA 执行 Common 全量 Maven 回归，退出 0：**140 套件，621 项 PASS，0 skipped，0 errors，0 failures**。仍有旧项目 `./control/ATSConfig.ini` 查找日志，但未导致测试失败。

## 完整 P0 尚不能 GO

1. B/A 进程的创建和重启在此次隔离验收仍由测试环境负责；**Common 已负责启动后的认证重加入控制线程和 WAL 恢复，但生产订单/交易服务启动接线、各分区 Snapshot/状态机完整恢复门禁及持续自动订阅仍须真实验证**。不可用测试脚本的外部编排替代完整生产自动 HA。
2. 新写入恢复严格 **2/2 QUORUM_DURABLE ACK** 仍未实现/验收：现阶段 E3 复制虽有新 RSA Replica fsync，客户仍按 `LOCAL_DURABLE_ASYNC` ACK。必须先验证主、备原始 WAL 物理 HEAD/签名、旧 Epoch 撤权和无分叉尾，然后通过 Common 认证的较高 Epoch 重新授权 STRICT，才允许**此后**新业务经两副本物理 ACK 作为 QUORUM_DURABLE 返回。历史 LOCAL 客户端 ACK 永不改变分类；不能删除 `Common newer Epoch replica certified recovery required` 门禁绕过认证。
3. 最终仍需在持续业务写入下验证自动 A→B→A、双向重启追平、无双主、无重复应用、Snapshot/WAL/CommitIndex/业务状态一致。以上完成后 P0 GO，才能将同一个 SHA Common Jar/Bootstrap/Watch/恢复接口直接用于 Order/Trade，业务只提供 `byte[]`。

本轮未更换现有 Order/Trade 容器，未调用 GitHub Actions，未清除 Demo 原有数据或上传原始 RSA/WAL。
