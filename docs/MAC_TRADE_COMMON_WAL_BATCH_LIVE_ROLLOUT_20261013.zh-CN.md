# OpenTradingCore Mac Demo：Common 批量 WAL 真实双节点上线与 HA 验收（2026-10-13）

> 本报告记录当日 Mac mini Demo 的实际 Docker 操作与只读、受控故障注入证据。此集群为单机 Docker VM，**不等于多宿主机生产级 HA**。所有私有环境文件、恢复密钥、MySQL 密码、离线 WAL 和含私有数据的容器 inspect 证据均未提交仓库。
> **Gateway 没有修改，不启用 TLS，不放松同步 Replica ACK，不手工删除当前活跃 WAL。**

## 0. 已验收代码与候选镜像

- Common 源码：[bliplink/com.app.common](https://github.com/bliplink/com.app.common)
  PR [#10](https://github.com/bliplink/com.app.common/pull/10) 已合并至 `saas-crypto`，merge SHA
  `a2e4eb972b2a313b005bb08a649040dcdced4ca8`。
  可选 `WAL_BATCH=3`，每批最多 8 条、512 KiB，
  每条保留独立 MAC、Epoch、序号和完整状态提交证明。
  原始单条协议仍默认兼容。
- Java 8 Common 全量测试 **240/240 PASS**。
- Java 8 Trade 与候选 Common 隔离 Maven 依赖编译和全量测试
  **297/297 PASS**，无失败、无错误。
- 合成 WAL 的真实 Netty 2,000 条后缀下载在隔离容器中 PASS：
  250 次批量 RPC、约 445 ms（不是现网 TPS）。
  使用真实 P222 克隆的 346 条已提交 `STATE_BATCH/STATE_COMMIT`
  签名下载：**PASS**，最多 44 次 RPC、338 ms（不是现网 SLA）。
- Trade 候选源码
  [bliplink/com.app.dc.tradesvr](https://github.com/bliplink/com.app.dc.tradesvr/tree/codex/trade-safe-wal-archive-canary-20261012)
  最新 SHA `08cc6953fcaf3f0dca3f5677aa34e28357738dfe`，
  `trade.cluster.recovery.replica.walBatch.enabled` 显式 opt-in，
  `TradeRecoverySourceDataAdapter.readWalBatch` 使用 Chronicle
  bounded Reader generation 并严格校验分区、代际、序号和提交 HEAD。
- 本地候选 arm64：
  `dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261013-walbatch-08cc695`
  Docker image SHA256 `d0a524a6a989cc06d6b3c54304728fcf32ccf7db14f4fe2e4a7586210a24cce2`，
  Common JAR SHA256
  `2215a7dc34e86fe0deee82e5d4589ea2cafe8a17cfc5423bbc19524359517e68`。
  本地唯一验证用 Common SNAPSHOT **不是 Maven Central 正式版本**。

## 1. 受控双 Trade 冷切换（实际执行）

- 运行前 11/11 租户只读验收 PASS；
  `docker compose --env-file ... --profile trade-cluster config --images`
  确认 A/B 均指向候选镜像。
- 当前同步复制策略要求**全部 Replica ACK**，
  `trade_sync_replica_rolling_gate.py` 不允许逐节点滚动重启。
  因此执行受控**冷维护**而非绕过该门禁：
  暂停 Robot，停止 Trade A/B，APFS `cp -R -c`
  保存静止的两端 `data/TradeSvrA/B` 完整数据与配置、私有
  Docker inspect 规格；备份位置：
  `~/.opentradingcore/epochwarm-walbatch-cold-cutover-20261013/`
  （0700 权限，禁止上传）。
- A/B 分别新增：
  `trade.cluster.recovery.replica.walBatch.enabled=true`、
  `trade.cluster.recovery.replica.autoWarm.maxSessionWalSlots=2048`。
  其余签名 Epoch、Replica ACK 和 Snapshot guard 未放宽。
- `docker compose --no-deps --force-recreate tradesvr tradesvr-b`
  启动两个完全相同的候选镜像。
  对应 Docker 容器均为 Running、无 OOM。
- 冷切换之后 ZooKeeper **Trade 256/256 分区 READY**，
  `TradeSvrA` Primary 68、`TradeSvrB` Primary 188。
  恢复 Robot 后，11/11 租户 RUNNING，每户 40 个活动委托，
  盘口买卖各 10 档。
- Projection：批量只读孤儿 Mutation=0，
  Order/Trade 各 11 条 Projection watermark，
  watermark/event tail mismatch=0，
  跨分区 eventId 冲突 false。
  这些是在线抽样/水位验证，**不替代权威业务总账证明**。

## 2. P222 自动温缓存追平（实际在线）

- 旧版 Trade B 的 P222 Epoch1 Snapshot Seq 10464，
  新版冷切换之后，Trade B 通过**新 Common 批量 WAL 接收端**
  自动执行 `TRADE_REPLICA_WARM_CACHE_INSTALLED partition:P222`。
- A/B 都追平至 Epoch 1、Snapshot Seq 27866、
  Committed State Seq 27865，
  **完整 Snapshot SHA256 `91479ce9...` 双端一致**。
- 随后再次独立验证源端 `SOURCE_HEAD_SIGNATURE_VALID`、
  `SIGNED_MANIFEST_VALID`，示例：
  HEAD Seq 28742，Snapshot Seq 27866，后缀 876 <4096。
- 真实 P222 A→B→A 受控角色反转 PASS，
  双向目标 READY，
  Projection **22** 条基准水位不回退。
- 新 Epoch 恢复后：P222 A/B
  **Epoch 3、Snapshot Seq 28922、SHA256 一致**。

## 3. P012 带真实持仓 SIGKILL（实际在线）

- 用户授权的既存故障租户 `QGM88N`，
  使用已存在的 **0.0001 BTC 模拟多仓**；
  不重新注册、不开新仓。
- 在 SIGKILL 前 P012 A/B 可信 Snapshot
  Epoch4、Seq20866、Committed State Seq20865、
  SHA256 完全一致，ZK READY。
- 真正执行 `SIGKILL dc-saas-tradesvr-b`，
  Trade A **自动接管 Epoch 5**；
  持仓 MySQL 数量保持不变，READY 匹配。
  测试结果：
  `PASS_AUTOMATIC_TRADE_TAKEOVER_HELD_POSITION`。
- 故障后 Trade B 重启，`unless-stopped` 策略恢复，
  Trade A 曾记录短暂降级后
  `TRADE_REPLICA_RECOVERED`。
  最新 P012 A/B **Epoch5、Snapshot Seq21802、SHA256 一致**，
  Trade B 成功记录新代际
  `TRADE_REPLICA_WARM_CACHE_INSTALLED`。
- 11/11 Robot，再次盘口/委托通过；
  Projection 再次 0 孤儿 Mutation、0 watermark mismatch，
  无跨分区 Event ID 冲突。
- **待办**：故障租户测试仓位尚未通过 Trader API 确认平仓；
  此前执行环境阻拦恢复私人登录凭据，不强行绕过、不直接修改 DB。
  完整 WAL committed HEAD 与 Replica durable ACK
  **仍需独立联合签名交叉证明**，不能把 Snapshot SHA 一致当作充分条件。

## 4. 归档与物理删除

- 在**新建的临时 disposable canary** 中已实际执行
  `run-archive-retention-gc-canary.py --execute-canary`：
  **1 个安全 canary WAL 实际删除**、另一不安全目录保留，
  **8 项拒绝条件**（Replica、Projection、Snapshot、
  Reader、备份、源不可恢复、缺副本、超水位）全部被拒绝；
  备份恢复 SHA256 一致。
- 在线只读归档盘点：
  **526 个归档目录**、archive 文件分配
  **491,261,952 bytes**，
  0 个超出 48h 的目录，
  **0 个达到自动物理删除授权**，
  0 个未知/异常目录。
- Common/Trade 产出 Archive 不等于**独立定时分段+可安全物理清理**
  的生产机制完整上线。
  当期缺少持久归档 Seal ledger、全量 Replica/Projection
  durable watermark、Reader generation 与真实外部备份恢复证明。
  **禁止自动执行在线物理删除**，不要把 canary PASS 当作现网 GC PASS。

## 5. 发布链：状态依赖实时核对

- Common PR10 已合并 `saas-crypto`。
  标签 `com-app-common-v3.0.18` 已从 SHA `a2e4eb...`
  **真实推送**；GitHub Actions Run
  **38333032827** 已启动，Java8 build PASS，
  Maven Central publish job 正在进行
  （该事实记录于 2026-10-13 09:41 Asia/Shanghai）。
- `com.app.dc` Common 3.0.18 消费者 PR
  [#5](https://github.com/bliplink/com.app.dc/pull/5)
  已创建，**须确认 Maven Central 3.0.18 可用后才可合并**。
- Trade 正式发布 PR
  [#5](https://github.com/bliplink/com.app.dc.tradesvr/pull/5)
  已创建，须在 `com.app.dc` 正式使用 3.0.18 后合并，
  依赖其 `publish-saas-image.yml`
  构建并推送 GHCR `linux/amd64,linux/arm64`。
- **正式 GHCR 镜像尚未部署**；当前双节点仍为
  `dc-saas/tradesvr:cluster-dev-local-...-walbatch-08cc695`。
  验证过的本地 arm64 镜像不是正式发布产物。

## 6. 后续生产化门禁

1. 等待 Common 3.0.18 在 Maven Central 真实可下载；
   再合并 `com.app.dc` PR5 和 Trade PR5，
   跑 GHCR amd64/arm64 CI，核查 Common JAR 与镜像源码摘要。
2. 正式镜像替换之前重复备份与**冷维护门禁**；
   不能简单用逐 Replica rolling restart，除非增加可信
   多副本 quorum 策略、调整配置并完成严格故障验收。
3. 校验受控故障后的订单、执行、资金、持仓与
   Projection 的**权威总账**；测试仓位需要安全关闭。
4. 完成可证明的 WAL Seal/Reader/消费者水位和
   48h retain 后，单独 canary 验证真实 CQ 归档 GC；
   未通过则物理删除保持禁用。
5. 做 10/11 租户 Soak，随后 50→100→200 租户阶梯压测，
   真实交易 TPS 不等同于行情点价事件速率。
