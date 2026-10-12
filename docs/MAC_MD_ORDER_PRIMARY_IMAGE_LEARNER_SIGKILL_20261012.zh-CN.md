# Order→MD 主备恢复链路 + MD-C 真实 SIGKILL 验收（2026-10-12）

## 验收范围与结论

**Gateway 完全透传、未修改；不处理进入 Gateway 的历史在途消息。** Order 提供权威完整盘口，MD 利用现有 `subscribeWithImage` 和 `MdDepthGapRecovery` 恢复。今回完成了 Order/MD 业务接口的双端隔离场景、真实 Mac 上无 Primary 的 MD-C Learner 进程 `SIGKILL → 新建容器 → 再订阅 → 恢复`。**尚未执行 MD-A/B Primary SIGKILL 或真正自动晋升**，前置安全门禁仍 BLOCKED。

## 一、代码已提交

| Repo | 分支 | SHA | 内容 |
|---|---|---|---|
| Order `bliplink/com.app.dc.ordersvr` | `codex/order-durable-primary-common-source-20261011` | `b501f7c` | `OrderMarketImageHandlerTest.physicalOrderPrimaryHandoffGivesResubscribingMdOnlyNewCompleteImage`：A 停发、B 返回两市场全量 bid/ask 和合法空簿 |
| MD `bliplink/com.app.dc.mdsvr` | `codex/md-auto-failover-disposable-gates-20261011` | `f5a4ac6` | `MdGatewaySubscribeImageRaceTest.changedOrderPrimaryEventuallyRebuildsMdBookThroughExistingGapResubscribe`：源切换间断、阻断错误增量、旧有异步补镜像回调、恢复新 Delta、旧快照不回退盘口 |
| Deploy `bliplink/dc-quant-deploy` | `codex/mac-trade-sigkill-validated-20261011` | 本文对应提交 | 改正 Shadow 累计 gap 检查、补真实重启证据 |

订单业务代码、MD 订阅/生产业务代码均**没有改动**，本轮仅增加针对现有真实处理类的故障场景测试。Java8 Docker 全量回归：**Order 341 项（0 失败 1 跳过），MD 131/131 PASS**。

## 二、完整订阅路线不变

`MD MarketDeptInput.refreshSnapshotAfterPrimaryChange` → `OrderSvrClient.subscribeMarketDeptForOrder` → `BaseApi.subscribeWithImage` → `OrderMarketImageHandler.snapshot` 从物理 Primary 的当前 OrderBook 返回完整盘口，`DepthBookFacade.onSnapshot` 才安装镜像并按市场置 Ready。普通行情 Gap 调用现有 `MdDepthGapRecovery`，聚合一次重订阅并以 5–60 秒退避。既无 Gateway 变更，也**没有新增一个每 30 秒轮询订阅**。

这两侧新增测试是隔离真实业务类，**不是在实际 ZK 执行 Order Primary 交接**；目前真实 ZooKeeper 全面主切的独立 Safety 尚未完成。

## 三、MD-C 零 Primary Learner 真实进程故障注入

故障注入前现场读取 `scripts/check-md-failover-preflight.py`：256/256 READY，`primaryCounts={MDSvrA:128,MDSvrB:128}`，MD-C=**0 Primary**，3 个 ZooKeeper ephemeral members 在线。`decision=BLOCKED`（不允许注入 Primary 故障），原始证据：
`~/.opentradingcore/local-md-release-candidate-20261011/artifacts/order-to-md-handoff-preflight-20261012.json`。

只针对 MD-C 运行一次 `docker kill --signal=SIGKILL dc-saas-mdsvr-c`；实际容器停机状态确认为 `running=false`，随后用版本锁 `release/candidates/md-c-epoch-fence-dff97ba-20261012.yaml` 执行 `docker compose ... up -d --no-deps --force-recreate mdsvr-c`。原始版本 `dc-saas/mdsvr:cluster-dev-local-md-epoch-fence-dff97ba-20261012`，无 Primary A/B 重启、无 Order/Gateway 容器操作、无数据清理。原容器 meta 备份在 `md-c-learner-sigkill-before.txt`。

重启后来自真实 Order 全量订阅的 10 个市场重新产生 `MD_MARKET_READY`，角色均为 `LEARNER`；最后状态 `running=true, restartCount=0, OOM=false`。真实日志 `~/.opentradingcore/dc-saas-runtime-zkfix-20261011/log/MDSvrC.log`。

首次严格租户检查为 **FAIL**：10 Robot 都是 RUNNING 且盘口各 10 档，但 `TWLYHK` 在采样时 **39/40 单**。记录未改阈值、未抹去：
`~/.opentradingcore/local-md-release-candidate-20261011/artifacts/md-c-after-real-sigkill-10tenant-20261012.json`。
随后严格重新审计 `md-c-post-sigkill-recheck-10tenant-20261012.json` 得到 **PASS_10_TENANT_SNAPSHOT，10/10 Robot 均 40 单**。这可能是机器人正常成交补单时窗，无法仅凭短时采样证明连续十分钟长期稳定。

Projection 在注入后 `orphan_mutations=0`、Order/Trade watermark mismatch=0、cross-partition event IDs=0，状态 PASS；不代表真正 MD Primary 切换。

## 四、自动验收脚本 bug 修复：已恢复并不等于历史从未发生 Gap

实际 SIGKILL/重连后的 MD-C Shadow 最初记录 `trackedMarkets=10, contiguous=10, stale=0, gapMarkets=0, gapEvents=1`。其中 `gapEvents` 是**累积诊断计数**，不是当前未恢复的 Gap；此前 `scripts/check-md-recovery-shadow.py` 要求此值一直为 0，会让曾正确恢复过的节点永远无法通过。

现在保留两轮完整/新鲜/零当前 Gap 的硬要求，同时要求最新两轮 `gapEvents` **完全相等**（不允许周期内新 Gap 或跨重启归零），而非历史计数必须为 0。输出 `historicalGapEvents` 和 `newGapEventsInWindow`，始终 `promotionAuthorized=false, canInjectMdPrimaryFault=false`。新增测试验证稳定历史 Gap 能通过、新增 Gap/累积计数重置仍 BLOCKED，脚本 **9/9 PASS**。

真实 Mac 中最新连续两轮观测 `2026-10-12 08:27:08`、`08:27:38` 均为 **10/10 Fresh，0 当前 gap，历史 gapEvents=1 且无新 Gap**，脚本 `PASS_LOCAL_OBSERVATION_ONLY`，原始证据 `md-c-after-real-sigkill-final-recovery-gate-20261012.json`。这**不是**拥有 ZK CAS 或外部 Order commit HEAD 的证明。

## 五、故障后的 Order 三副本权威一致性

在真实 MD-C SIGKILL/重订阅后，使用现有 `tests/verify-order-cluster-state-host.sh` 对 Order 的三个物理节点做只读最终检查，实际 **PASS**：256/256 分区 READY、256/256 Snapshot 集合一致、0 Learner；Order A/C 分别 129/127 Primary，Order B 256 个 Replica；Epoch 计数 `{2:128,3:127,4:1}`，Order A/B/C 和 Gateway 容器 running、0 重启、无 OOM。此结果只证明 MD-C 故障没有破坏 Order 集群，仍不是 Order Primary 故障切换验收。

## 六、生产启用前仍待办（不得绕过）

1. Order 当前物理 Primary 的完整 tenant-market inventory 和最新提交水位、源断开/重连的可靠连续性证明。
2. MD 自动控制器使用真实 ZooKeeper CAS/旧主禁止继续新发与新主 RECOVERING→READY 验证，不能从 MD-C Learner shadow 直接授权真实 Primary 自动晋升。
3. 真正 MD-A/B Primary 故障，连续委托/盘口、旧节点重入 Learner、反向切换和长时间运行回归。
4. 业务 Archive GC 仍缺真实最小持久副本水位、Projection/备份/活动读取者与跨归档追平证明，尚未开启生产自动删除。

故障恢复后的真实 ZooKeeper 再核验（文件 `~/.opentradingcore/local-md-release-candidate-20261011/artifacts/md-c-post-sigkill-preflight-20261012.json`）：MD-A/B/C 三个 ephemeral member 全部恢复在线，256/256 READY、Primary 分配仍 A/B 各 128、MD-C 无 Primary。自动故障主切的 `decision=BLOCKED`、`canInjectMdPrimaryFault=false` 未变（本轮并未强行开放）。

**Gateway 仍完全不改；故障前已入 Gateway 的消息不处理，最终恢复正常并持续稳定是验收目标。**
