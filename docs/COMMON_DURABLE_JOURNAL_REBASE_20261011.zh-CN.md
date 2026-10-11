# OpenTradingCore Common HA：恢复事务流水账与真实 CQ baseline 验证（2026-10-11）

## 本轮实现和实际意义

在现有 Common 的 `apply(byte[])`/`snapshot`/`restore`、`StateMachineRecoveryCoordinator` 和 `DurableRecoverySnapshotSeal` 之上，新增了 Common **`DurableRecoveryInstallLedger` 和 `DurableRecoveryTransactionControl`**：

1. 对从当前合法 Primary 收取、SHA 已验证的完整镜像做不可变封存；SHA 和快照提交边界都写入持久元数据。
2. 以临时文件 → fsync → 原子 rename → 目录 fsync 的方式，**在任何业务 CQ rebase 前**写入按分区隔离的 `INSTALLING` 记录。记录包括分区、镜像 epoch/seq、最新 committed HEAD epoch/seq、digest。
3. 委托 Order/Trade 注入的业务 `JournalBaseline.install(request, sealedImage)` 持久化 **同一份**业务快照并调用原有 Chronicle Queue `rebase` / `rebaseSameEpochForwardSnapshot`；Common 不解析订单/资金对象，不自行改写 CQ 文件，也不引入一套新的复制选举协议。
4. 业务 `JournalBaseline.attest` **从磁盘重新读取**业务快照 metadata、CQ baseline，严格匹配 snapshot id、epoch、seq、commitMarker 等，才能进入 `BASELINE_DURABLE`。
5. Common 对返回的独立封存文件再次验证并调用业务 `restore`；从 snapshotSeq+1 连续应用已提交业务增量，并让控制日志只推进 seq。完成权威来源二次核验和业务 `finishReplay()` 后记录 `REPLAY_COMPLETE`。
6. 所有阶段只表示**恢复内部进度**，绝不授权分区 READY。业务/仓位/委托/资金、Projection、水位、Robot、旧主 publisher fencing 均需各自验收。未完成 `INSTALLING` / `BASELINE_DURABLE` 或损坏 ledger 在重启时必须 fail-closed。正常业务热路径不写 ledger；仅恢复或可选生命周期首次注册/epoch 更换时检查。

### 不复用单一通用业务快照格式

- **Order**：`OrderDurableJournalBaseline` 解析本业务已有 JSON 镜像、复用 `OrderPartitionSnapshotStore` 和 `OrderPartitionJournal.Baseline`，分区镜像先 fsync/atomic rename，然后按照合法 same-epoch-forward 或跨 epoch 路径 rebase；再读取实际保存的快照和 CQ baseline 做完整校验。Order snapshotStore 保存逻辑加强了文件和父目录 fsync（仅快照低频路径）。**Order 的 STATE_COMMIT 是累计提交证明，不得假设与 STATE_UPSERT 紧邻。**
- **Trade**：`TradeDurableJournalBaseline` 只按流读取封存文件 metadata；`TradeSnapshotStore.installSealedImage` 用 64KiB 分块复制、sha256 校验和原子 rename 安装整份余额/持仓/挂单/执行去重镜像，避免 50MiB+ 快照被一次性装进内存；之后调用 Trade 自己的 Journal rebase，再读 snapshot metadata+baseline 双重核验。修复 Trade 旧版本拒绝**跨 epoch 快照序号超出副本本地 WAL 尾部**的问题：跨 epoch 的权威完整镜像可以直接成为新基线；同 epoch 的非前进式 rebase 仍受约束。这是“副本落后 → 最新快照恢复”的必要条件。
- **Order/Trade 可选 binding**：新增不同的 `recoveryLedgerDir` 配置，默认指向各自 `data/<Service>/commonRecoveryLedger`。当且仅当 `commonBinding.enabled=true` 时，真实 assignment 生命周期在第一次注册分区或 epoch 发生变更时读取 ledger；未完成/损坏状态拒绝本机注册。对每笔订单、每个业务请求不增加磁盘 IO。上线前必须确保该路径与恢复事务使用的 ledger 目录一致。

## 验证方式及状态

- Common `saas-crypto`：[`f03d191`](https://github.com/bliplink/com.app.common/commit/f03d191)；Maven 全量 **158 tests / 0 failures / 0 errors**；GitHub Actions **38115728059 SUCCESS**。测试包括有效/无效阶段跃迁，安装前崩溃、已落盘 baseline 后崩溃、业务 finishReplay 异常、损坏 ledger、错误快照来源等。
- Order **[`6eb0f55`](https://github.com/bliplink/com.app.dc.ordersvr/commit/6eb0f55)**，Maven 全量 **337 项、0 failures、0 errors、1 skipped**；Trade **[`997548c`](https://github.com/bliplink/com.app.dc.tradesvr/commit/997548c)**，Maven 全量 **249/249 PASS**；MD **125/125 PASS**。Order/Trade 代码已推到 `ha-common-state-machine-validation-20261011` 验证分支，正式 `saas-crypto` 未合并。新真实 CQ 文件测试各自使用私有临时目录和注入的隔离/权威测试证明，绝不操作 Mac 当前十租户数据。
- Mac 最新**成功**的独立开发镜像组：`~/.opentradingcore/local-ha-ledger-verified-20261011`；Common GAV `3.0.17-devf03d191920261011054522-SNAPSHOT`，三服务 Common JAR SHA-256 **`feca5a0e30507c3a7add8df24dff411227c30af7f690ded0f32af94289c8795f`** 完全一致，均编译成功。唯一的 UTC build ID 避免不同开发 JAR 覆盖。前一批有 Java 泛型编译错误的 `local-ha-ledger-final-20261011` 不算成功镜像，错误已修复且重新全量回归。没有替换现网 Primary，也没有发布 Maven Central / GHCR 正式镜像。
- GitHub Actions/Common Maven 构建与本地真实 CQ 全量回归结果以该轮 CI/日志为准。本轮不是 GHCR 正式发布，更不是 HA 故障注入的结果。

## 现网只读验收（本轮未重启业务）

Mac mini 上 `dc-saas-ordersvr{,-b,-c}`、`dc-saas-tradesvr{,-b}` 仍是原 GHCR 镜像；MD-A/B 仍是稳定 GHCR 镜像，MD-C 为先前本地金丝雀。`https://opentradingcore.com`、`https://trade.opentradingcore.com` 均 HTTP 200；本轮磁盘检查剩余约 **225GiB**（49% 已使用），此数值仅是观察值，不应把磁盘用量变化归功于本次代码改动。

MD HA 预检查：**256/256 READY；MDSvrA 128、MDSvrB 128 Primary；`decision=BLOCKED` / `canPromote=false` / `canInjectMdPrimaryFault=false`**。阻断保持为 `MD_NODE_UNHEALTHY_OR_UNREVIEWED:MDSvrC`、`ORDER_CURRENT_FULL_MARKET_IMAGE_PROOF_MISSING`、`MD_PROMOTION_FENCING_AND_CAS_CONTROLLER_NOT_CONFIGURED`、`MD_PROMOTED_EPOCH_FULL_MARKET_IMAGE_NOT_ATTESTED`、`ROBOT_POST_FAILOVER_ORDER_RECONCILIATION_NOT_ATTESTED`。因此本轮没有执行 MD SIGKILL、自动晋升、旧日志删除或 Demo 冷重建。

## 尚待完成的 P0 安全门禁

**关键限制：本轮提供并单测了真实业务 CQ baseline 的持久化适配器，但生产级恢复入口尚未真正提供下面这些机制，也没有默认开启开关：**

1. ZK 及复制控制面带版本的当前 Primary 权威完整镜像来源证明、epoch/fencing/来源通道/commit HEAD，且对应业务 partition 恢复期间持续保持真正排他屏障；不能拿本机老 WAL 冒充上游权威。
2. 快照传输和 committed tail 跨网络验证，与 Ledger 使用同一个固定 recovery identity，允许 crash 后幂等 retry；真机重启后区分完整/不完整事务。
3. 业务 `JournalBaseline` 只在已证实为 **非 routable 的 Replica/Learner** 下触发（当前单元测试通过注入 guard 模拟）。**任何 Primary 禁止触发此路径**。
4. 完整业务对账（Order open orders/executions、Trade balances/positions/execution-dedupe、Projection watermark 和 Robot 对账）通过后，再单独开放 READY。
5. 2 天 WAL 归档回收仍必须通过 Common `SnapshotRetentionFence` 的完整快照覆盖、消费者/复制 durable watermark 和文件句柄门禁；仅文件过期不自动授权删除。MD 仍从 Order 权威市场镜像恢复，旧 publisher fencing/CAS、提升后全镜像及 Robot 对账未齐全则 MD HA 不允许 SIGKILL。
6. 正式发布顺序：在 Mac 隔离故障恢复验收通过后统一发布 Common Maven Central、更新 com.app.dc 依赖版本、合并 Order/Trade 的验证分支、GH Actions 生成 amd64/arm64 GHCR 镜像，最后按预检查做安全滚动部署或 Demo 冷重建。

不要把 ledger `REPLAY_COMPLETE` 视为系统已经 READY，也不要在未实现上述 P0 前宣称自动 HA 已完全上线。
