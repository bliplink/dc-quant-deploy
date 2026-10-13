# Mac Demo：Trade P222 自动温缓存积压与 Epoch 验收门禁修复（2026-10-13）

## 在线基线（11 户，原系统保持运行）

- **24/24** `dc-saas` 容器运行。Trade A/B 的在线镜像均仍为
  `dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261013-firstsnap-e249f74`，
  未发生新镜像替换或新一轮 SIGKILL。
- 11 租户只读审计 **11/11 PASS**：Robot `RUNNING`、
  每户活动 Robot 委托 40、公开订单簿双边各 10 档。
  私有审计结果：
  `~/.opentradingcore/local-ha-clean-20261012-v1/tenants-epochwarm-11-after-audit-fix.json`。
  输出字符串 `PASS_10_TENANT_SNAPSHOT` 为遗留脚本固定名称，
  本次 `expectedTenants=11`。
- P012 历史 SIGKILL 后自动接管并恢复至 Epoch 4，A/B
  完整 Snapshot Seq 3152、stateSeq 3151 和 SHA256 匹配；
  这是 Snapshot 恢复证据，不等于完整 WAL HEAD/ACK 权威证明。
- 测试租户 `QGM88N` 的测试交易员此前持有
  0.0001 BTC 模拟多仓。私有恢复凭据访问被执行安全检查阻挡；
  未曾擅自修改数据库或重发不确定状态的订单。

## 发现：P222 Replica 的完整快照仍落后

- ZK assignment/在线快照只读门禁在 11 户中检测到 P222
  `REPLICA_FULL_SNAPSHOT_BEHIND`，正确返回
  `snapshotPreflight=BLOCK`、`walCommittedHeadAndAckProof=NOT_CHECKED`；
  不授权滚动重启或再次 SIGKILL。
- 同 Epoch 1 的 A/B 文件：Trade A Snapshot Seq 14704，
  Trade B Snapshot Seq 10464；尚未追平。
- Trade B 的温缓存此前安装过 P222 seq 8232、seq 10464，
  随后有 `TRADE_REPLICA_WARM_RETRY`：
  约 08:14:41 attempt 1、08:16:28 attempt 2、08:19:29 attempt 3，
  原日志只记录 `IllegalStateException`，
  退避重试分别 60/120/240 秒。
- A/B 的 P222 Chronicle WAL `.cq4` 文件均存在；
  **文件存在、文件大小相同均不代表 WAL commit HEAD 和每条 ACK 相同**。
  当前尚不能确定失败发生在 HEAD/Manifest、bounded window、
  signed staging 还是 durable install，更不能认定业务 WAL 丢失。

## 已提交的安全修复

1. 部署/验收脚本提交
   `0a83849`，分支 `bliplink/dc-quant-deploy/saas-crypto`：
   `verify_trade_rollout_snapshot_headroom.py` 和
   `check_trade_live_snapshot_role_preflight.py` 均拒绝跨 Epoch
   序号比较，旧 Epoch 高序号也必须 BLOCK。
   回归 **11/11 PASS**，实际 P222 暂时落后会继续 BLOCK。
2. Trade 诊断补丁提交
   `eb7eb4767176a0380182d75e7bede2d0e8d7e1e0`，
   验证分支 `bliplink/com.app.dc.tradesvr/codex/trade-safe-wal-archive-canary-20261012`：
   在自动温缓存失败日志中加**阶段枚举**：
   `peer`、`signed-head-manifest`、
   `bounded-window`、`verified-staging`、
   `durable-install`。不记录异常 message、Node Key、
   签名响应、WAL 内容或业务账户信息。
   **Trade Java 8 全量 295/295 PASS**。
3. 在 Mac mini 离线构建调试候选镜像：
   `dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261013-warmphase-eb7eb47`，
   image sha256
   `f4584d202617dd29dbeacb19bb3821ed3e8bfeecb3a033f3652e7f95867cda8e`，
   `linux/arm64`。
   标签记录源 commit `eb7eb47` 与 Common JAR 校验值
   `34a6ee05db748eb2990f68b1dc86188a41ca52c320e1838b9cd82fd3c77a0363`。
   **未上线**。构建复用本地已缓存运行镜像、离线 Java 8 Maven
   依赖链，与正式 GHCR 多架构发布不同。

## 后续上线门禁

- 先在隔离实例或受控冷部署条件下运行新诊断镜像，取得 P222 的实际
  失败阶段，修复其真正根因；不能简单提高下载并发或放松签名/ACK。
- 再以认证签名 HEAD、ZK Epoch 和 Replica durable ACK 对比
  WAL commit suffix；Snapshot 一致不是充分条件。
- 目前 WAL 归档目录存在，但 Trade 的自动物理封段调度、
  48h 保留期 + 读者/快照/消费者持久水位安全回收尚未闭环；
  自动删除授权继续为 0。不得直接打开垃圾回收开关。
- 不启用 TLS，不修改 Gateway，优先低 IO、低 CPU 的后台方案。
