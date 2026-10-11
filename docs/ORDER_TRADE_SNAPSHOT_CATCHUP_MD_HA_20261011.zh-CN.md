# Demo：Order/Trade 快照恢复、两天 WAL 归档与 MD HA 验收（2026-10-11）

## 本次实际交付

- OrderSvr `saas-crypto` [commit 6303989](https://github.com/bliplink/com.app.dc.ordersvr/commit/6303989)：加入**同一 Order epoch 下仅向前**的完整 Snapshot rebase 功能。`OrderReplicaReplicationHandler` 只有在显式配置 `order.cluster.replication.sameEpochSnapshotRebase.enabled=true` 且分区已有 GAP、收到合法 `SNAPSHOT_BEGIN`、快照 `snapshotSeq` 高于副本现有 Journal 末尾时才重建；Journal 增加对应严格校验的 `rebaseSameEpochForwardSnapshot`，沿用旧的 SHA-256/BEGIN/CHUNK/END 校验与后续连续序号约束。旧的跨 epoch 恢复、精确同 epoch rollback commit marker 修复不变。**默认 false，不会在线突然改变行为。**
- Order 隔离全量 Maven 回归 **322 tests / 0 fail / 0 error / 1 skip**；同 epoch、新 epoch、Learner coalesced GAP/原有 batch 复制专项 **26/26 PASS**。GitHub Actions [38100577121](https://github.com/bliplink/com.app.dc.ordersvr/actions/runs/38100577121) 编译新版 GHCR 镜像，正式部署必须另外核验 SUCCESS 和 ARM64 清单。
- `generate-saas-configs.sh`、`.env.example` 提供独立变量 `ORDER_CLUSTER_SAME_EPOCH_SNAPSHOT_REBASE_ENABLED`，默认 false，三个 Order 节点按同一配置生成；`tests/test-order-cluster-c-config.sh` 验证默认拒绝、显式 true 三节点同开。**不能在滚动版本混用时随意开启，先 fresh deploy 同版本再测。**

## 必须区分三个能力

1. **副本 Recovery：** 有最新可信完整快照以及它之后的连续业务提交日志，才可脱离更老的 WAL 恢复。新功能补齐了一个同 epoch 向前安装快照的接收端缺口，不代表任意来源的 Snapshot 都可直接安装。现阶段安装机制使用源 OrderSvr 已同步复制的 snapshot transfer 日志。
2. **周期完整快照：** Order/Trade 周期快照运行开关目前 Demo 仍为 false。盲目高频开启会在已同步复制的 Order Journal 中引入 snapshot chunk IO，不能假设单纯调高频率就能节省磁盘。未来应采用**只有已提交变更时生成，控制每轮分区数/最大字节/异步限流**的方案。
3. **WAL GC：** 目前仅 Demo date-only LaunchAgent `config/retention-demo.json` 已启用**按日期 2 天清理普通轮转日志和已关闭/未被映射的空初始化归档**。它不碰 Order/Trade 业务 CQ4 活动日志及带记录的 .archive。业务归档想在 2 天后删除仍需：来源 committed HEAD、后续增量连续、同步副本 SNAPSHOT 已完成、Projection durable watermark 覆盖、rollback marker 不依赖将删范围、已关闭文件和隔离恢复演练。没有完整证明就不能把业务 WAL 强行按日期裁剪。

## MD HA 同步验收

- MDSvr `saas-crypto` `bcdec88` 已交付 Order 与 MD epoch 隔离、空盘口及旧 image gate；ZK 独占租约和 CAS 控制器代码已经存在，但缺少可认证的旧 publisher 失权/共享 Gateway 下游 epoch fencing，以及**Order 当前整个分区全部活动市场的权威快照和连续增量证明**。
- 本轮 MD 单元专项 `MdAutomaticFailoverServiceTest`、`MdImageRecoveryFailoverControllerTest`、`MdGatewaySubscribeImageRaceTest` **16/16 PASS**。真实 Mac Mini 只读预检查 **256/256 READY、A/B 各 128 primary、三个 MD ephemeral membership 在线、0 分区缺失恢复候选**。结果依然 `decision=BLOCKED`，不启用自动主晋升；不能只凭静态 READY 或过时市场清单伪称故障注入成功。
- 下一步正确测试：在全新 Demo 同版本镜像注册 10 租户并启动 Robot；先核对 MD Web 深度/Trade history/Projection，然后解决 source HEAD 与 Gateway 旧 epoch publisher 防护，只有预检查通过后再在演示集群执行 MD primary 故障注入、恢复成员重入、Robot 对账。

## 正常环境发布与冷重置准备情况

- 已核验 `scripts/mac-saas-reset.py --mode plan`：仅当前 `dc-saas` 项目的 24 个容器和 `~/.opentradingcore/dc-saas-runtime-clean-20261010`，隔离保存的 P246 故障复现文件 SHA-256=`41ccc177...` 仍存在。用户允许 Demo 数据清空重部署。
- 新版 Order 的 GitHub Actions 完成并检查 ARM64 镜像前不得清理旧运行目录。**更新正式不可变发布镜像锁 `release/saas-crypto-images.env` 时，执行环境返回 policy_rejected**；没有改写或通过替代锁路径绕过。既然不能证明新镜像与发布清单、完整 Compose 一致，就**没有执行 stage/容器删除**，现网保留旧 Order `sha-7842df4`、MD `sha-48544e5`，业务仍可运行。
- 生产授权可以重置 Demo 数据不等于“允许在镜像锁被拒绝后先停 24 个服务”。待正规发布锁能更新并通过 Mac 安装器静态检查后，执行完整 cold reset → 一键部署 → Migration/Robot/10 租户 → Order/Trade/MD 逐层 HA 故障测试；若失败则保留现场与原始隔离证据。
