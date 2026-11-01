# T401｜Common 原始 WAL 前拒写安全重试与 16 Home 并发恢复验收（2026-11-01）

## 本轮目标
与 T390 串行 Home 切回不同，T400/T401 要证明：P001..P015 真正进入 ZooKeeper RECOVERING 时，原先 READY 的 P000 等分区还能使用相同 A/B 长存物理 JVM、活跃 Netty TCP、副本 WAL 真实 strict 2/2 持久提交。Common 负责证书与恢复，Order/Trade 不新增选主/WAL 逻辑。

## 先前失败与证据
- T389 Common（SHA256 `6b4418f7b1373bb68a9fac4c79aa4406001e1699ec6d9dd080c83323110e2eae`）的 T400 2、4、8 Home 间隙写入 PASS，第三 JVM 物理 WAL/Custody 审计 PASS；但那时写入在下一个 shard 开始恢复之前，不能当作 RECOVERING 交错成功。
- 把额外提交移至 `CommonCertifiedFailoverWatch.awaitStage` 返回并经真实 ZK 核实目标处于 RECOVERING 后，首次 P000 在 P001 恢复时遇 `control snapshot not READY`；Common Watch 先撤销旧 node grant，控制线程重新取得认证 CAS。不得跳过真实 Quorum 签名。随后只在 WAL append 之前有界等待新的有效授权，P000/P001 真实交错与第三 JVM 审计 PASS；8/8 Home 同样 PASS，13 次额外 strict ACK，认证等待最大 21ms。
- 旧 T389 16 Home 测试在 P002 的 P000 seq3 处失败，原始异常为 `Common Netty peer did not fsync exact batch`，并有 `COMMON_COMMIT_PHASE ... phase=INDEPENDENT_WAL_FSYNC_RECEIPTS walWriteStarted=true`。物理卷证明 A 原 WAL 已写 seq3，而 A CommitIndex 和 B WAL 都仅到 seq2；**没有虚构 seq3 成功 ACK**，未按未知结果重试。原始日志 `target/t376-isolated-zk/t378-signed-auto-home-1f3aa0e8.log`、独立物理卷 `otc-t400-1f3aa0e8-{a,b}`。

## T401 实际 Common 变更
- 在 `DirectNettyCertifiedBusinessTransport`，严格限制本地 WAL fsync 后的 TCP 再发资格：只有来自**同一物理分区、Epoch、确切 seq-1 水位/seq 预期值**且远端明确错误为 `COMMON_PHYSICAL_REPLICA_NOT_AUTHORIZED`（副本 `checkAuthority()` 在任何 WAL append **之前**拒绝）才可在 500ms 有界窗口内，按 20ms 间隔**重发同一原始物理 frame、同 seq、同 bytes**，同时每次验证原 Common Epoch authority。不经过 ZK 热路径，也不接受未经签名的成功 ACK。
- 任何 unknown outcome、timeout、错误 Epoch/分区/序号、`COMMON_PHYSICAL_REPLICA_FENCED_AFTER_FSYNC`、不匹配 physical ACK、无签名 fsync/Custody 仍 **立刻失败并永久栅栏不确定 WAL**；不得重试业务命令、放宽严格确认或伪造 Quorum。
- 新增 `DirectNettyPreWalGrantReproofTest`，真实 Maven 离线 JUnit 结果 **3 tests，0 failure，0 error**。该类覆盖允许精确前置零写拒绝，以及禁止重试的失权、未知、超时形状、错 Epoch/分区/水位等。
- T400 测试夹具在独立 JVM 内保留所有已回切分区的实际 CommonCertifiedPartitionRuntime、真实 TCP、授权状态，使用不同端口并在**下一个 shard 已进入 RECOVERING 时**要求原 shard 成功 `QUORUM_DURABLE`。只在 `requireCertifiedPrimaryWriter()` 前有界等待认证刷新，绝不自动重放已开始的 WAL。完成后第三 JVM 按原 WAL + 双 custody 独立验收各 seq。

## 最新真实 PASS
- 新 Common 本地独立 JAR：`.work/t374-demo-common-ha/target/t401-common-safe-prewal-reproof.jar`，SHA256 **`135ec1c31d15b3992aa3fb69ae10b733aa0e48ab762928db236f55831f9b87bb`**，与旧 T389 SHA 不同。
- 同一真实独立 3-ZK + A/B JVM + 128 Home Watch 下，T401 三分区 P000..P002 真实交错 + 第三 JVM 审计 PASS。
- 扩大至 **16/16 Home** P000..P015：ZK RECOVERING/READY 与 epoch stage 严格签名、A/B 长会话、独立 WAL/CommitIndex/Custody、真实 TCP 2/2 ACK 和第三 JVM 物理磁盘检查 **全部 PASS，脚本退出码 0**。执行日志 `.work/t374-demo-common-ha/target/t376-isolated-zk/t378-signed-auto-home-21d69545.log`。
- 数量：原 shard 每个新 E3 strict ACK 16 次，**另加 29 次**已 READY shard 在别的 shard RECOVERING 时严格持久提交，**15** 个 RECOVERING 交错窗口。P000 A/B 原始业务 WAL 最终各 16 条、CommitIndex/Custody 均确认 16；P001–P014 A/B 各 2 条，P015 A/B 各 1 条；第三 JVM 16/16 全部对账。
- 认证刷新等待观测 0–21ms，7 次 pre-WAL 授权被暂时拒绝后取得真实重新认证；此观测**不是**交易 P99，也不保证所有客户请求绝不收到暂时错误。A/B 两个物理 JVM 整轮执行约 100590ms/101627ms（包含慢签名测试开销，非故障客户端停顿）。
- 运行脚本入口：`tests/run-t376-isolated-common-zk-stage.py --mode home256-signedwatch --continuous-writes --all-home-watch-pressure --home-partitions P000,...,P015 --candidate-jar-name t401-common-safe-prewal-reproof.jar --expected-sha256 135ec1c31d15b3992aa3fb69ae10b733aa0e48ab762928db236f55831f9b87bb --worktree .work/t374-demo-common-ha --base /Users/kong/.opentradingcore/t177-common-saas-crypto-integration-20261027`。第三 JVM 原始检查仍由脚本自动完成。

## NO-GO 与下一步
- 这是同一台 Mac 中隔离容器/JVM、独立 Docker volume 与真实 ZooKeeper 会话；**不是**真实不同物理机器。完整 **128/128 Home 持续并发客户端写入、真实 A/B SIGKILL 双向接管与回 Home、Order/Trade 数据一致性**仍需验收，不可把 16/16 当完整集群完成。
- 正式 Demo 目前仍为 T399 业务服务使用 T389 Common，不应把 T401 在隔离验收通过误报为 Order/Trade 已切换。新租户自动审批依赖完整管理员注册请求，当前仍为 NO-GO；Robot Runtime API Key 新 Login 会话已恢复，但无自动审批的新租户报价/成交证据。
- 继续将 Common 集群机制收敛在 Common，不增加 Order/Trade/Gateway 的自定义复制/选主。仅通过 Mac 本地 Maven 与 Docker 验证，不调用 GitHub Actions；保存原不确定 WAL 失败卷供审计。