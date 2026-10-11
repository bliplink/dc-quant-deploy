# Common 已认证 Snapshot / Committed WAL 网络读取、隔离 Staging 阶段验收（2026-10-11）

## 范围与生产安全结论

本轮补齐从 **Common SourceHead V2 → 凭来源证明读取真实 Order/Trade Snapshot 和 CQ4 WAL → TCP 传输 → 隔离 Staging → SHA + 业务 Commit Pair 验证** 的通用数据平面。实际使用独立 Mac 工作树和 Docker Maven Java8 编译，并通过真实 Loopback Netty、Order/Trade 本地 CQ4 文件联调。

**没有接管线上 10 租户运行版、没有 SIGKILL、没有把业务路由设 READY、没有删除 Journal/Archive，也没有发布新的正式 Maven Central 或 GHCR 镜像。** Common 接收端只产生 `VERIFIED_STAGING_NOT_READY`，不能等同恢复完成。只对源码/独立 JVM 测试负责。

源码推送确认：Common `8a1b440` 已更新至 `saas-crypto`；Order `1c0014c` 位于 `codex/order-durable-primary-common-source-20261011`；Trade `f3318d5` 位于 `codex/trade-durable-primary-common-source-20261011`。Order / Trade 独立验证分支是有意保留的发布门禁，避免依赖未正式发布的 Common 版本破坏 GitHub Actions。

## 1. 公共接口（供所有有状态服务复用）

- `RecoverySourceHeadControlHandler`：源端独立从 ZooKeeper 当前 Primary + Snapshot SHA + Committed HEAD 签名证明。默认不注册，旧服务兼容。
- `RecoverySourceDataControlHandler`：新增带版本号 `RECOVERY_READ_DATA_V2` 操作，复用现有 exact-node `DirectNettyReplicationServer`，不另开一条数据通道，不影响正常订单复制。Snapshot 数据从偏移开始，每帧最多 64 KiB；WAL 按指定序号发送实际记录，并把原始字节、Epoch、HEAD、ZK version、Challenge 绑定 HMAC。
- **请求方独立授权**：源码检查发现仅用“公开可获取的源端签名 HEAD”作下载凭证不安全，已升级 V2。每一个读请求还必须由持有节点私密 HMAC key 的副本对服务、分区、Challenge、signed HEAD、文件偏移/WAL Seq 签名。错误 key 时在源端实际扫描 ZK 或 Snapshot/Journal 前拒绝；篡改、跨节点、错 HEAD、ZK version、过期请求也拒绝。
- 原业务 `OrderRecoveryControlRouter` / `TradeRecoveryControlRouter` 在 opt-in disabled 下完全保持旧服务控制处理器/旧三参 Netty 构造。只有显式开启 `order.cluster.recovery.source.control.enabled=true` 或 `trade.cluster.recovery.source.control.enabled=true`，配置安全的节点专属密钥，且注入真实 `DurablePrimaryHeadAuthority`，才增加两条 recovery-only 控制操作。
- `VerifiedRecoveryStagingClient`：通过真实 TCP 获取带签 HEAD，经 HMAC 校验后按**显式可信的 exact Snapshot 长度**拉取 64KiB 分块；一边流式写临时隔离文件、一边检查帧 MAC、offset 连续及 SHA256，然后 fsync 并重新读取暂存文件 SHA。之后最多取 4096 条指定 committed WAL，使用服务注入的业务 decoder 验证每个帧的序号/Epoch 和 `CommittedWalPrefixVerifier` 累计 STATE/COMMIT 语义，并将长度帧写入独立 `committed-wal.frames`、fsync。
- 所有检查结束才创建 `VERIFIED_STAGING_NOT_READY`；失败时删除隔离未验证文件。未安装 state machine、未 ALTER/DELETE 在线数据，没有 READINESS/promotion 接口。调用方必须提供可信 `snapshotBaselineCommittedStateSeq/Epoch/Marker`，不能从物理 WAL 断言它们。

## 2. Order / Trade 真实数据读取

- `OrderDurablePrimaryHeadAuthority` / `TradeDurablePrimaryHeadAuthority` 实现 Common `SourceData`：使用 `RandomAccessFile` 定位读取实际 `snapshot.json` / `latest.json`；真实 `OrderPartitionJournal.readBatch` / `TradePartitionJournal.readBatch` 获取 CQ4 单个指定 WAL record，按真实 Epoch 和编码字节签署传输帧。
- SourceData 本身在 Common 数据读取 handler 的角色/HEAD 二次验证夹持下运行；原有来源适配会通过真实 ZooKeeper Stat Version、Epoch、隔离锁、Snapshot SHA、Commit Watermark 和 bounded cumulative WAL 做严格 HEAD 认证。流中源头变更则拒绝，不返回 READY。
- 专项集成测试真实写入 Order、Trade CQ4 `STATE→STATE_COMMIT` 并放置非空磁盘 Snapshot（超过 64KiB，拆成两块），通过真实 Loopback Netty 从业务适配器获取原始真实文件字节，再经 HMAC、SHA256、业务累计提交严格验收；错误序号不可读取。

## 3. 必须保留的阻断门禁

1. **网络连接保密/鉴权仍不足以对外开放**：HMAC 请求方证明并不对明文 TCP 内容加密，也不防本地网络嗅探/重放；正式部署前需对来源控制端口实施网络白名单、TLS/mTLS 和请求方节点身份授权，安全管理每物理节点密钥与轮换。Demo 目前保持 SOURCE/DATA control flag 为 false。
2. **未真正安装 Replica**：Staging 已实现传输与校验，但**没有**把已验证数据与 `StateMachineRecoveryCoordinator.recover`、`DurableRecoveryTransactionControl`、`install→restore(byte[])→apply(byte[])→finishReplay` 打通，并独立证明不可逆状态/安装前后 Fencing 或 READY/Projection/Gateway 联合安全性。
3. 当前 HEAD 为易变业务状态：持久化 Snapshot 和 WAL 在新写入时可能更新，来源端在每次网络调用前后重新证明同一 HEAD，合法的快速写入可能使整个传输失败；生产需实现只读、固定 Session 的**不可变 Snapshot + 已提交 WAL pinning**，避免锁主业务热路径和恢复期 O(n²) 反复计算 SHA。失败安全拒绝不等于性能可用。
4. Staging Receipt 是“已验证传输”而非可信永久不可修改 WAL。启动正式 `recover` 前还需再认证已暂存 WAL 的整体哈希/只读不可变元数据（或持久化逐记录 MAC），同时接入跨重启完整 ledger，防止恢复过程中备份文件被重写或错误重放。
5. 当前单次增量最多 4096 条，跨多段 Archive→Active 的序号/镜像/租户余额持仓 Projection 权威核验尚未端到端执行；任何自动 Archive 删除仍保持 HOLD。
6. MD 自动主切门禁持续 **BLOCKED**（Order 全市场权威镜像、旧 Publisher Fence、MD READY 前第二次验证、Robot 对单），不得为求通过而跳过强制安全门禁。
7. GH Actions 发布链（新的 Common Maven Central -> com.app.dc -> Order/Trade ARM64/Linux）仍待对齐；Order/Trade 的 Common 新 API 修改继续只存放独立验证分支，不破坏 `saas-crypto` 正式镜像编译。

## 4. 本轮构建及证据

- 通用 Java8 Maven 本地隔离依赖链：`~/.opentradingcore/local-common-protocol-20261011/source/{common,dc,ordersvr,tradesvr}`，生成测试 GAV **不可当作 Maven Central 正式版本**。
- Common 全量 **199/199 PASS**（SourceData V2、Staging、HMAC 源端/请求端授权）。
- Order 全量 **336 tests, failures=0, errors=0, skipped=1**。
- Trade 首轮全量发生 **1 个测试失败**（旧 `RECOVERY_READ_DATA_V1` static-final 操作常量残留）；`mvn clean -Dtest=TradeSourceDataReadTest,TradeRecoveryControlRouterTest test` **4/4 PASS**；随后重新执行 **`mvn clean test`，Trade 全量 240/240 PASS、0 失败、0 错误、0 跳过**。Order 同样执行 `mvn clean test` 全量 **336 项、0 失败、1 跳过**。这说明问题由同 GAV 的旧字节码缓存造成，正式编译时必须 clean 或升级依赖 GAV。
- 真正做了 Java8 **`mvn clean test`** 完整重编译验证，共计 **775 个测试执行，0 失败、1 跳过**（Common199 + Order336 + Trade240）；此前同 GAV 缓存导致的 Trade 1 项失败已明确保留记录，并在 Clean 全量中消除。
- Mac 原在线 Docker 容器未重启。最终 `check-demo-tenants-readonly.py`：**PASS_10_TENANT_SNAPSHOT**，10/10 Robot `RUNNING`、各 40 活动委托、10/10 双边盘口各 10 档；`check-projection-consistency-host.sh`：`order_watermark_tail_mismatch=0`、`trade_watermark_tail_mismatch=0`、`orphan_mutations=0`、`cross_partition_event_ids=0`；`dc-saas-` Docker 容器 **24**。巡检 JSON：`~/.opentradingcore/local-common-protocol-20261011/artifacts/final-v2-staged-auth-10tenant-20261011.json`。
- `verify-order-cluster-state-host.sh` 最终只读核验：**256/256 分区 READY**、`snapshot_sets_equal=256`、无 Learner，A 129 Primary、C 127 Primary、B 256 同步 Replica，Order A/B/C 无 OOM、无容器重启。既有 Order 镜像仍为 `dc-saas/ordersvr:cluster-dev-local-orderepoch-4c7df72-20261011`。
