# Common 统一 Replica Durable ACK 接口与三层版本链（2026-10-14）

## 目标

复制成功 ACK 必须代表本次认证的 WAL 前缀已经完成业务 Journal 的同步落盘；不能仅凭 Chronicle `writeText()` 追加返回就称为持久 ACK。Common 负责安全门槛和 Epoch 复核，Order/Trade 负责自己的 WAL 操作与业务状态机，Gateway 始终不变。

## 已完成（仅开发/隔离测试，尚未部署）

- **Common PR [#11](https://github.com/bliplink/com.app.common/pull/11)**：`DurableReplicaAckGuard.acknowledge(OK|DUPLICATE, partition, epoch, requiredSeq, Storage)`。要求角色 Epoch 一致、记录序号范围有效、`Storage.requireDurableThrough()` 成功、同步后 Epoch 和序号仍有效。**重复 ACK 也必须重新校验持久性**；不得对磁盘同步失败发成功 ACK。Java 8 全量 271/271 测试通过；GitHub [CI 38523475670](https://github.com/bliplink/com.app.common/actions/runs/38523475670) PASS。
- **com.app.dc PR [#6](https://github.com/bliplink/com.app.dc/pull/6)**：沿用最新远端 saas-crypto 的 MySQL JDBC8 依赖排除设置，暂存 `com.app.dc:0.0.5-SNAPSHOT → io.github.bliplink:com.app.common:3.0.21-SNAPSHOT`，未发布。
- **Trade PR [#9](https://github.com/bliplink/com.app.dc.tradesvr/pull/9)**：基于 Chronicle 恢复 [PR #8](https://github.com/bliplink/com.app.dc.tradesvr/pull/8) 叠加，共用上述 Common 门槛：Trade 的 `TradeReplicaReplicationHandler` 在每个 Netty 复制批次（不是每条 record）追加后，以 `TradePartitionJournal.syncJournalThrough()` 做同步并复核 ZooKeeper 的真实 assignment/epoch；`DUPLICATE` 也同步。失败返回 ERROR，不会对异常报告成功 ACK。新增 4 个 Trade 适配测试：成功/重复、磁盘同步失败、同步中 epoch 改变、Gap 禁止超前 ACK。Java 8 全量 235/235 PASS；独立 runner 从两个特定新分支安装 Common 与 com.app.dc，再构建 Trade，[GitHub CI 38523702302](https://github.com/bliplink/com.app.dc.tradesvr/actions/runs/38523702302) **PASS**。
- GitHub Main 与运行中 Trade-A/B 没有替换。上面三个 PR 均是**未合并、未正式发布的 Draft**，不能当做 Maven Central 或 GHCR 正式成果。

## 版本与构建风险

曾存在 Mac 本地过时版本：Trade 的旧工作树依赖 `com.app.dc:0.0.4-SNAPSHOT`，解析到 `3.0.17-dev...SNAPSHOT`；GitHub 最新 `com.app.dc saas-crypto` 实际已引用 `3.0.20`。不要把本地旧 POM 直接覆盖远端，也不要发布同一 Maven artifact version 的不同二进制。

当前仅准备下一个**未发布的** `Common 3.0.21-SNAPSHOT → com.app.dc 0.0.5-SNAPSHOT → Trade` 版本链。要正式上线，先确认源端 HEAD 认证及完整快照恢复，评估 ACK 落盘延迟，之后才由固定 Release 流程发布新版 Common、固定 com.app.dc 版本、由 GitHub Actions 构建 Order/Trade GHCR 镜像并逐节点滚动。

## 仍然 NO-GO（严格不降级）

1. **Trade 9 分区，474 个剩余快照尾部序号**：双节点当前物理 WAL 均未覆盖快照后缀，未完成权威 committed HEAD + epoch fence + Snapshot/Diff 业务完整恢复。不能手动 READY、清理归档或归因“必然丢 474 笔”。
2. **Order 源码对 `ChronicleQueue.lastIndex()` 的依赖**：Order 的 `OrderPartitionJournal.open()` 当前把 `lastIndex()` 当尾部；Trade 已证明该索引在 rebase + 崩溃后可能停在第一条。必须先为 Order 建真实或合成复现测试与安全尾部识别，并将 DurableReplicaAckGuard 适配到 Order 副本，而不能直接全量滚动。
3. 性能：当前 Trade 同步一次/Netty 复制批次。必须测量 10/50/200 Robot 时的 fsync p50/p95/p99、每个分区业务 TPS/延迟、macOS Docker VM I/O；如有开销，统一在 Common 做有上界、按 Epoch/分区隔离的 group-commit 并验证断电失败，而不是放松 durable ACK。
4. 原有 Trade Snapshot 写前 WAL 映射区 msync 只覆盖快照持久化顺序；新 ACK 门槛单独覆盖副本复制承诺。**二者互不替代**。
5. 现网仍需核对权威 MySQL/Projection/Order/Trade 状态及恢复后的机器人 11/11 RUNNING，完成故障注入、恢复、追平、角色反转；运行盘 95% 需安全归档证据方可清理。

## 逐阶段推进

A. Common PR #11 中的接口稳定后，对 Order 的 Journal 真实恢复尾部和新 Durable ACK 做同样测试；Trade 借助 PR #9 做独立压力性能基线。

B. 用 Common 已有的 `RecoverySourceHeadControlHandler`、`StateMachineRecoveryCoordinator` 和 `SnapshotDiffStateMachineAdapter` 接入 Order/Trade 对应的已认证源端 HEAD、Snapshot(byte[])、Diff(byte[])、Epoch fence 和可逆完整安装，并形成真实故障恢复验收报告。

C. 正式 Common 新版本经 Maven Central 成功可见后，更新 com.app.dc，再通过 GitHub Actions 统一构建全部 `saas-crypto` 服务；禁止依赖 Mac 本地镜像。先只读 preflight → 非主节点 canary → 业务 READY/机器人 → 主备滚动 → 200 租户压测 → 日志自动归档删除。
