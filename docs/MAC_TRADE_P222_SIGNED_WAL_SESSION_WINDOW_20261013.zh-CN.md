# Trade P222：签名恢复的 WAL 传输窗口诊断与低开销修复（2026-10-13）

## 结论及界限

针对 Mac mini 11 租户 Demo 的 P222 Trade Replica 自动温缓存积压，
本轮完成了 **隔离磁盘 WAL 克隆、真实源端签名挑战、隔离 VerifiedRecoveryStagingClient 下载对照**。
整个取证过程不修改正在运行的 Trade A/B、Gateway 或数据库。

- Trade A/B P222 使用 APFS Clone File 复制当时 `metadata.cq4t` 和
  两个 Chronicle `.cq4` 文件到私有目录；克隆前后检查原文件
  size/mtime 一致。所有解析都在离线 Java 8 容器上执行。
- Trade 自身 `TradePartitionJournal` 解析两份克隆：
  `Epoch=1`、`lastSeq=16632`、`baselineSeq=0`；
  从 1 到 16632 的全部 **16,632 条 WAL 均连续，编码整体
  SHA256 = `7336f8a7c1e29c1890cc3581751d2cd444472077ff069eacdc5d970b594bdeaa`，
  A/B 完全相同**。
  这是独立时间点的持久化内容证明，但不是在线最新 HEAD/ACK
  或全部分区的一致性授权。
- 使用 B 节点既有只读配置中的恢复密钥（密钥从未输出或保存到结果）
  与当前 ZK Version 0，向实机 Trade A 的
  `127.0.0.1:19221` 发起真实 Netty 签名 HEAD 与 Manifest
  挑战，**HMAC/Nonce/ZK/Primary 约束全部通过**。
- 一次签名 HEAD：`headSeq=17400`、`snapshotSeq=16880`、
  imageBytes=1,094,480、后缀 520 条，小于 Common 硬上限 4096。
- 使用隔离可写暂存目录运行真实
  `VerifiedRecoveryStagingClient.stage`，**没有调用真实 Replica
  的业务 apply、seal/install 或 READY**。
  第一次长窗口 `headSeq=17842, snapshotSeq=16880`，后缀 962
  条，WAL_SLOT 请求遭 `source refused authenticated recovery control request`，
  下层曾伴随 socket connect timeout；
  第二次更长窗口 `headSeq=18826, snapshotSeq=16880`，后缀
  **1946 条**，在请求 `WAL_SLOT seq=17268` 附近遭源端拒绝
  （已收到数百条帧）。
  第三次较短窗口 `headSeq=19364, snapshotSeq=19242`，
  后缀 **122 条**，真实签名 Snapshot 下载、WAL 传输、
  连续性与摘要核验**全部 PASS**。
- Common `RecoverySourceHeadControlHandler` 的 PIN 窗口为
  `25,000 ms`，`RecoverySourceDataControlHandler` 挑战有效期
  `30,000 ms`；接收端目前**逐条发送**并等待 WAL control RPC，
  源端对每个请求需要重新验证 HEAD、ZK/物理节点、签名并读取 CQ。
  对照结果高度符合 **长后缀持续时间超过稳定签名代际/请求窗口**
  的解释；但是源端返回统一 `UNSAFE` 而非内部阶段详情，
  所以**不能断言全部失败只由 TTL 造成**。
  数据面完整传输成功并不证明主备安装成功。

## Trade 调度低开销改动

Trade 验证分支：
`bliplink/com.app.dc.tradesvr/codex/trade-safe-wal-archive-canary-20261012`。

- 提交 `73e5ececb17512159c38c0fa3ff2961924d34891`：
  增加 `trade.cluster.recovery.replica.autoWarm.maxSessionWalSlots`
  （默认 **256**，必须在 `1..4096` 内，Common 硬限额不变）。
  后台从已验证的源端 Manifest/HEAD 计算
  `signedCommittedHeadSeq - signedSnapshotSeq`。
  对超过短窗口上限的缓存下载执行
  `TRADE_REPLICA_WARM_DEFER`，不下载大量 WAL、不增加失败指数退避，
  后续轮询等待源端下一次合法 Snapshot。
- 提交 `7c75beb115fcd8fb18a6c4733d49ad2ef520733b` 添加短/长窗口、
  无效窗口与边界测试；`27ac081552c0ab5a83bb757e7619e6d9448afb15`
  仅明确注释中「失败不一定是凭据超时」。
- 实机 Mac 上 Docker Java 8
  `mvn -o clean test` **296/296 PASS，0 失败/错误/跳过**；
  `mvn -o -DskipTests package dependency:copy-dependencies` PASS。
- 新本地 arm64 候选镜像：
  `dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261013-warmwindow-27ac081`，
  image digest
  `sha256:0123f2dc2a8ea4dff9ddcdba855dbac4a5b64001d2a9d092a464be2c0bae3048`，
  源码 label `27ac081...`，
  Common JAR SHA256
  `34a6ee05db748eb2990f68b1dc86188a41ca52c320e1838b9cd82fd3c77a0363`。
  此为本地开发依赖和缓存运行基础镜像构建，非 GHCR 正式双架构发布。

## 线上保留状态与后续门禁

- **尚未部署**此新镜像：Trade A/B 在线镜像仍为
  `firstsnap-e249f74`，不满足自动证明的滚动主切门禁，不能盲目
  重启带真实仓位的节点。
- 最近复查：Trade A P222 Snapshot Seq 19242，Trade B P222
  Snapshot Seq 10464，仍落后；不可声称已安装。
- 11/11 租户独立只读验证 PASS，所有 Robot RUNNING，
  每户 40 笔活动委托、买卖盘口各 10 档；
  Projection Order/Trade 各 11 条内部水位、事件尾部一致。
- 未来必须先在隔离节点或新的受控 Demo 环境证实
  `WARM_DEFER → 新签名 Snapshot → VERIFIED_STAGING →
  durable-seal/install → 双副本同 Epoch/Seq/SHA`，
  并独立校验源 HEAD/Replica durable ACK 后，
  才允许第二轮 SIGKILL、双向主切、GHCR 发布/线上替换。
  对 200 租户的性能评估还须研究 Common WAL 批量/流水线
  传输、端到端身份/时效防重放，不应靠无限延长签名 TTL
  或放松安全校验。
- `QGM88N` 测试交易员历史模拟多仓 0.0001 BTC
  尚未通过 API 确认归零；不得覆盖、重试不确定状态的交易。
- WAL 归档产生物理目录不等于周期归档自动运行。
  **48h + 持久 Seal/Replica/Projection/Reader 全门禁**
  未证实时，WAL 物理自动删除继续关闭。
- 全程不启用 TLS、不修改 Gateway，不在生产热路径添加
  额外 IO 或全分区扫描。

取证证据位于 Mac 私有工作目录：
`~/.opentradingcore/local-ha-clean-20261012-v1/forensic-p222-wal-clone/`，
`tenants-p222-recovery-probes-20261013.json`。
该目录含恢复诊断和隔离 WAL 克隆，**勿对外上传**。
