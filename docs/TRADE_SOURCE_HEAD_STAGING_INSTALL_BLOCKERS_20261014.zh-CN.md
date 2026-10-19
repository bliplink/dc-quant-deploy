# Trade 可信源端恢复 → 分块 Staging → 安装事务验收（2026-10-14）

## 已交付并验证的代码（均是 GitHub Draft，未合并）

- [Common #11](https://github.com/bliplink/com.app.common/pull/11) 统一 Replica Durable ACK 与已有源端 Recovery HEAD/分块源数据验证、累计 STATE_COMMIT 审核、`StateMachineRecoveryCoordinator`、`DurableRecoveryInstallLedger`。
- [com.app.dc #6](https://github.com/bliplink/com.app.dc/pull/6)：新 Common 3.0.21-SNAPSHOT → com.app.dc 0.0.5-SNAPSHOT 的**仅开发暂存版本链**，正式 Central / GHCR 尚未发布。
- [Trade #8](https://github.com/bliplink/com.app.dc.tradesvr/pull/8)、[#9](https://github.com/bliplink/com.app.dc.tradesvr/pull/9)：已修复 Chronicle lastIndex 不可信（cold-open 校验完整连续前缀、倒序从真实物理尾部索引定位）、Snapshot 写前 WAL 同步、Common 同步 ACK（含 DUPLICATE 及 Epoch fencing）。
- [Trade #10](https://github.com/bliplink/com.app.dc.tradesvr/pull/10)：生产服务源端只读接口`RECOVERY_SOURCE_HEAD_V2` 和 `RECOVERY_READ_DATA_V2` 已接入**现有** DirectNetty 复制端口，HEAD 双检新鲜 ZK version、Primary/READY/committed marker、WAL msync、真实 Snapshot SHA256；DATA 以 Common HMAC 身份鉴别读取真实持久文件（64KiB Snapshot 分块及认证提交前缀 WAL）。纠正过一次真实 loopback 发现的 `SERVER.TradeSvr` 与 `TradeSvr` 规范化不一致。**HEAD/DATA 两个开关均默认关闭**，无 Gateway 修改。
- [Trade #11](https://github.com/bliplink/com.app.dc.tradesvr/pull/11)：真实 Trade STATE_BATCH + STATE_COMMIT 编码适配 Common 累计提交审计，使用 Common 受认证 Snapshot+WAL 的 Netty loopback staging；`TradeRecoveryStateMachine` 暂存完整业务镜像+已提交增量并最终调用现有 `TradeRecoveryApplier`；`TradeRecoveryInstallGuard` 检查 Common 持久化安装事务，**只要存在恢复安装事务标记（包含 REPLAY_COMPLETE），普通 Trade READY 通道一律不自动放行**；Trade Replica ACK 在 ZK 会话丢失时拒绝成功。
- [Order #10](https://github.com/bliplink/com.app.dc.ordersvr/pull/10)：复用 Common Durable ACK 和冷启动 Chronicle 连续前缀机制，独立 GitHub CI 通过。

### 已通过的测试

1. Trade 新接口：真实 `127.0.0.1` DirectNetty 主/从 Source HEAD HMAC + DATA 分块、完整 Snapshot SHA + committed WAL `STATE_BATCH / STATE_COMMIT` 真实内存源 staging 测试 **PASS**。`VERIFIED_STAGING_NOT_READY` 收据不会授权安装或 READY。
2. Common `StateMachineRecoveryCoordinator` 与 Trade business adapter、模拟封锁控制面、独立密封 Snapshot、Common ledger `INSTALLING → BASELINE_DURABLE → REPLAY_COMPLETE`、业务单次应用 Test Double 验证 **PASS**。此处 **ZK 与 journal baseline fsync 是模拟控制面**，不能称生产事务已完成。
3. Trade 全量 249 项 Java 测试通过，后续新增 ZK 会话断开副本 ACK 测试单独通过；[最新 #11 Actions](https://github.com/bliplink/com.app.dc.tradesvr/actions/runs/38532956563) 成功（全量测试 + Docker 候选镜像构建，无 GHCR 发布）。
4. Order 全量 372 项测试 0 failed 0 error 3 skipped，[Actions](https://github.com/bliplink/com.app.dc.ordersvr/actions/runs/38525430682) PASS。
5. 真实故障分区隔离物理 WAL 恢复验证：P200 的 lastSeq 284052 vs 最新 Snapshot 284088，P071 lastSeq 311962 vs Snapshot 312034；9 分区剩余快照/双侧 WAL 差额共 474 序号，**不是 474 笔丢单的证明**。

## 真正上线前尚需完成（不可用测试双桩冒充生产功能）

A. 生产 Replica **可信源发现及恢复会话**：独立信任的最新 ZK Primary 身份/version、持久且**每个物理节点独有**的 256bit+ 源端 HMAC 密钥安全分发；Common 目前签名的 SourceHead **没有携带 Snapshot 的确切字节长度**。必须在服务端增加已认证的 Snapshot 大小/清单，或明确从另一独立权威来源取得；`VerifiedRecoveryStagingClient` 不允许猜大小（需要 `exactImageBytes`）以免截断或无限传输。DATA 裸 TCP 不提供保密性，服务只能在受控私网/隔离网络验证（生产加密/ACL 设计须明确），不可公网上开放。
B. 与 Common `StateMachineRecoveryCoordinator.Control` 相连的**真实 Trade Replica 接收端**：业务写入与状态机变更共用的独占分区锁、`markNotReady` 与旧节点 fencing、`requireSourceAttested` 在每阶段获取新鲜 HEAD/role/version、落盘原子密封快照和原子业务 latest 快照、实际 `TradePartitionJournal.rebaseSameEpochForwardSnapshot()` baseline fsync、不可更改的 install ledger、失败后的重启重新认证与回滚/重试、重放后业务状态/执行去重核对、外部独立 READY 放行。不能单靠 Common test fixture 的假 ZK、假 journal baseline 操作。
C. 单/双副本崩溃注入：WAL fsync 跨 Chronicle roll 文件证据、ack/p95/p99/吞吐，断开 ZK 下 Epoch 双重隔离、snapshot 后 crash、SIGKILL 恢复追平、角色反转无双主、无人机 robot 10/50/200（含 2000 挂单）稳定验收。
D. **现有 9 个 Trade 分区无可签署的合法 Source HEAD**（Snapshot 比双节点 WAL 物理记录新），必须有第三份证实的权威快照及 Quorum ACK 保证，或者走用户已经允许的 Demo 环境**清理重建**路径，在健全的新机制上重新创建测试租户并验证。绝不能凭 474 序号差额手动推进 WAL 基线、直接复制 latest.json 或标记 READY。
E. 正式发布 Common 至中央仓库 **新唯一版本** → com.app.dc 引用 → GitHub Actions 编译发布 Order/Trade/MD/Main 等一致分支 arm64/amd64 镜像 → 只读预检 → Replica canary → READY/财务一致性 → Primary 轮换 → Robot/HA 与归档删除后安全水位验收。

## 最新线上门槛（只读，2026-10-14）

`python3 tests/order_ha_rollout_gate.py --target OrderSvrA` 实际返回 **NO-GO**：

- VM SwapFree **0 KiB**，门槛 262144 KiB。
- Robot 尚未达到 **50/50 RUNNING**。
- Robot open orders 尚未达到 **2000**。
- Mac 宿主约 **94% 磁盘使用率，剩余 26 GiB**；Live Robot **2 RUNNING / 9 ERROR**。

这不是 CI 失败，而是线上容量和业务恢复预检不通过。没有替换现网订单/交易镜像、修改 Gateway、删除归档、强制 READY 或清空数据。本记录是复现证据和下一轮执行标准，不是已部署证书。
