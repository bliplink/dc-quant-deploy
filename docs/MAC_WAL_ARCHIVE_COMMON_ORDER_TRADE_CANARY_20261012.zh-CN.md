# Mac WAL 自动归档下一阶段：Common / Trade / Order 验证结果（2026-10-12）

## 功能分层结论

1. **周期快照：已在 Demo 开启**。Order A/B/C、Trade A/B 五个服务
   启用低频调度；Trade-B 曾多次真实生成快照，
   具体现场证据见 `MAC_PERIODIC_SNAPSHOT_ENABLEMENT_20261012.zh-CN.md`。
2. **恢复时归档：已存在并验收过**。已提交的业务 journal rebase/恢复
   可以归档旧 Chronicle Queue，保留快照后的新写入。
3. **正常交易期间同 epoch 自动封段：尚未上线**。仅有 Common 纯决策
   门禁，以及 Order/Trade 历史读取与拒绝危险重入的验证。
4. **真实 WAL 自动删除：仍关闭**。`SnapshotRetentionFence` 已在 Common，
   但没有完整下游水位 + 文件句柄 + 快照恢复证明，不能直接使用。

## 2026-10-12 本轮已提交代码

| 仓库 | 分支 | 提交 | 结果 |
| --- | --- | --- | --- |
| `bliplink/com.app.common` | `codex/common-wal-rotation-policy-20261012` | `bf6415bf9d7a42a0a4da4e4d77141e07e7c4bd92` | 公共 O(1) 轮转判定 `HOLD/SNAPSHOT_REQUIRED/SEAL_ALLOWED`，Common **214/214** 单测通过 |
| `bliplink/com.app.dc.tradesvr` | `codex/trade-safe-wal-archive-canary-20261012` | `be17fb85c240cc733f84c9c42adc81f6e503fbfb` | 仅缺口时扫描历史归档，活跃 WAL 热读取跳过旧目录，Projection 跨 archive GAP 补齐；Trade **231/231** 全量单测通过 |
| `bliplink/com.app.dc.ordersvr` | `codex/order-wal-archive-read-canary-20261012` | `77b0d8e9cad78e61b7b1b79504fb05ff8a604456` | 同 epoch 错误调用 `rebase` 被保护，跨 epoch 历史 Projection 可回放，发现原始 Replica readBatch 无归档桥接；Order 全量 **327 项，0 失败，3 跳过** |

**均已推送 GitHub 验证分支，不是发版分支；没有触发 Common Maven Central
发布、GHCR/容器替换或 Gateway 修改。** 之所以没有直接上线新的物理
封段控制器，是因为目前运行的 Chronicle Queue `rebase` 包含关闭
Queue、移动目录以及恢复安装行为，同 epoch 背景执行的 reader 生命周期、
Writer 屏障、掉电期间 manifest 状态和副本归档读取尚未打通。

## 关键性能与正确性发现

- Trade 过去在每次正常读取副本追平区间前都枚举、排序全部
  `.archive` 并加载 baseline，归档增加会形成不必要的线性 IO 开销。
  现在通过 `fromSeq > activeBaselineSeq` **O(1) 快速路由活跃 WAL**。
  历史场景仍按证据读取 archive；最大条数限制同时约束扫描上界。
- 隔离 Trade 测试证明：从 fully committed snapshot 边界进行原有
  `rebase` 后同 epoch 继续写入，Projection、Replica 有界读取
  可跨旧 archive + 当前 WAL，重新打开 Chronicle Queue 后仍可读。
- Order 的 `rebase` 正确拒绝 same-epoch，不能简单修改 epoch
  校验绕过；Order 的 `OrderProjectionCommittedReader` 能补归档历史，
  但低层 `OrderPartitionJournal.readBatch` 只读取当前 WAL，
  还需要正确的 Replica catch-up/完整 image 安装桥接。
- 后台 Common 门禁只可做判断；真实封段需要外层持有权威 writer
  barrier，二次检查 epoch/committed HEAD、持久化封段 manifest、
  读者句柄安全交接，最后才能发布新 WAL 基线。
  安全删除是完全独立的后续操作，不能以封段成功等价于可删除。

## Mac Demo 只读验收

本轮验证分支提交后，未重启 Demo，执行
`tests/check-demo-tenants-readonly.py` 返回 `PASS_10_TENANT_SNAPSHOT`：
10/10 Robot RUNNING、每租户 40 笔活动委托、双边各 10 档盘口。
Order A/B/C、Trade A/B、Robot 均 running，OOM=false，restartCount=0。
Trade-B 实测内存约 **1.535 GiB / 2 GiB**，仍应持续观察峰值。
证据（Mac 私有目录）：
`~/.opentradingcore/local-md-release-candidate-20261011/artifacts/tenants-wal-archive-read-canary-20261012-final.json`。

## 继续开发的最小安全工作包

**不重写 Common 状态机，不改 Gateway、不重新部署无关服务。**
设计并开发 Common 的可持久化 `SEAL_PREPARED / ACTIVE_SWITCHED /
ARCHIVE_SEALED` 封段事务，以及关闭句柄、重启修复和恢复链验证。
先在 Order/Trade 的临时 journal 目录做 SIGKILL/断电中断窗口测试，
再接 Common Gate 与实际物理封段；只有完整历史、日志回放、
Projection/Replica 追平和 TPS/P99 性能达标，才允许在 Demo 灰度开启。
