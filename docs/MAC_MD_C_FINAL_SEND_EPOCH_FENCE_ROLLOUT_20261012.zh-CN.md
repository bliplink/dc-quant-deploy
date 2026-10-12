# 2026-10-12 MD-C 发送前 Epoch 二次隔离：真实灰度上线记录

## 完成范围

**MD-C 新镜像已经真实滚动替换，MD-A/B 旧 Primary 未触动，现网 10 租户保留。MD 自动主切和真实业务归档 GC 未授权启动。**

| 项目 | 结果 |
|---|---|
| MD 源码仓库 | `bliplink/com.app.dc.mdsvr` |
| MD commit | `dff97ba95a4ae29062e9e353680c79e84d38e8f4`，`codex/md-auto-failover-disposable-gates-20261011` |
| 新镜像 | `dc-saas/mdsvr:cluster-dev-local-md-epoch-fence-dff97ba-20261012` |
| 镜像 SHA | `sha256:cccd5ef511c0ba9df8459dc9aab7d432e2e4346334d53936e3c6d988a7b0ab46` |
| Common GAV | `io.github.bliplink:com.app.common:3.0.17-dev3e1d45c620261011075101-SNAPSHOT`（本地版本，不是 Central 发布） |
| Common JAR SHA256 | `45ea321a89b44639310f6dd10ac043df144b2be05e8d8c087c0ccba2c01ea6c7` |
| 全量 Java8 Maven | `130 tests, 0 failures, 0 errors, 0 skipped` |
| 专项 `MdPublishQueuedEpochFenceTest` | `7/7 PASS` |

### 本轮修改

`MDPublish.publishMessage()` 与 `AsynSleepCacheMD.process()` 新增 **真正进入 Gateway 前的第二道本地 Epoch 检查**。此前只在 Serialize 前核验 queuedEpoch，但调用 `JsonUtils.Serializer` 可能耗时，允许在序列化期间发生 ZK 降级。现在在 Serialize 完成后再次与 watched assignment / 本地 epoch readiness 对比，不匹配立即拒绝发消息；只在 Gateway 接收调用后更新 published counters。保持全程仅查询**缓存的 assignment 和现有连接状态**，不增加每条消息 ZooKeeper RTT。

新增真实调度时序测试：让同一个 MD Publisher 第一次校验通过，第二次校验前变为非 Primary，分别确认盘口和 K 线两种异步消息 **Gateway send count=0**；连同之前所有 legacy、delta、queue reuse 测试共 7 项通过。

**明确限制**：MD Publish 的第二道本地校验只能缩短发送端的降级竞态。由于 Gateway 当前消费的 JSON 中还没有可信源 owner/epoch envelope 及接收端强制版本校验，因此 **仍不能宣称 Gateway 发布端已建立双主 Fencing**，不能用这项改动将 `md.cluster.failover.enabled=true`。

### 灰度发布记录

只升级名为 `dc-saas-mdsvr-c` 的 C 节点；ZK live preflight 执行前验证 **256/256 READY、MDSvrA/MDSvrB 各 128 Primary、MD-C=0 Primary**，同样有 3 个 ZooKeeper ephemeral live members。

候选镜像由 Java 8 Maven 本地编译，并严格核对现有 Common JAR SHA256 与 source revision。镜像仅灰度 MD-C，在 `release/candidates/md-c-epoch-fence-dff97ba-20261012.yaml` 中版本锁定，可复现：

```bash
ENV="$HOME/.opentradingcore/local-ha-zkfix-20261011-v1/artifacts/local-ha-runtime.env"
docker compose --env-file "$ENV" -f compose.yaml \
  -f release/candidates/md-c-epoch-fence-dff97ba-20261012.yaml \
  --profile md-cluster-c up -d --no-deps mdsvr-c
```

实际部署后 `dc-saas-mdsvr-c` 启动、0 OOM、0 Restart；MD-A/B 仍是 `dc-saas/mdsvr:cluster-dev-local-c3e1d45c6-20261011075101`，未触动 Primary。MD-C 仍只做 Learner，`md.cluster.replayWitness.enabled=true`、`auditMillis=30000`、**auto failover disabled**。

### 上线后真实检查（不是模拟）

- `tests/check-demo-tenants-readonly.py` 返回 **PASS_10_TENANT_SNAPSHOT**：10/10 Robot RUNNING，每租户 40 活动委托、双边盘口各 10 档。证据：`~/.opentradingcore/local-md-release-candidate-20261011/artifacts/md-C-dff97ba-after-tenant-audit.json`。
- `tests/check-projection-consistency-host.sh` 返回 **PASS**：`orphan_mutations=0`、Order/Trade `watermark_tail_mismatch=0`、`cross_partition_event_ids=0`。
- `scripts/check-md-recovery-shadow.py` 最新两轮均为 **10/10 Fresh + Contiguous、0 Stale、0 Gap**，返回 `PASS_LOCAL_OBSERVATION_ONLY`，不授权晋升。证据 `~/.opentradingcore/local-md-release-candidate-20261011/artifacts/md-c-dff97ba-shadow-audit.json`。
- 混合镜像的真实 ZooKeeper `scripts/check-md-failover-preflight.py`：`partitionCount=256`、`unreadyPartitions=0`、`primaryCounts={MDSvrA:128,MDSvrB:128}`，决策仍 **BLOCKED**，`canInjectMdPrimaryFault=false`，硬阻断项仍为 Order 全市场实时 committed HEAD、MD CAS/Safety、Ready_epoch publisher fence、promoted image 和 Robot post failover reconciliation。证据 `~/.opentradingcore/local-md-release-candidate-20261011/artifacts/md-c-dff97ba-real-preflight.json`。

### Gateway 继续透传：MD 最终恢复正常即可（2026-10-12 架构修正）

按当前验收目标，**不改 Gateway，也不要求拦截或撤回已经进入 Gateway 的旧行情消息**。此前将 MD→Gateway 消息签名及 Gateway 接收端校验列为上线前置条件，是对架构边界的误判，现明确撤回。Gateway 只传输 `topic/content`；不需要理解 MD 主备、Order 或业务 Epoch。

正确的实现位置是 **MD 发送端 + ZooKeeper 分区所有权 + Order 完整行情恢复**：旧主失去 READY/Primary 时停止新的发布，新主保持 RECOVERING 和禁发，从 Order 重新订阅最新完整盘口并应用连续增量，验证后再 READY 并正常发布。已经进入 Gateway 的在途消息允许按现有通道自然发完，不为它们增加接收端去重要求；验收重点是故障后**最终恢复并持续正常**，而非故障窗口零旧消息。

**已确认存在完整的按需重订阅链路，不增设新的周期性重订阅**：`MarketDeptInput.refreshSnapshotAfterPrimaryChange()` 先向 BaseApi 取消原 listener，再调用 `OrderSvrClient.subscribeMarketDeptForOrder()` → `BaseApi.subscribeWithImage()`，由 Order 的 `OrderMarketImageHandler.snapshot()` 根据真实物理 Primary 当前内存订单簿生成完整市场镜像。MD 的 `DepthBookFacade.onSnapshot()` 校验并安装镜像才标记该市场就绪；发生增量 gap 则由原有 `MdDepthGapRecovery` 聚合一次请求并按 5～60 秒退避继续重订阅。不能把 `subscribeWithImage` 的调用成功当成业务镜像安装成功，尤其 Order 正在切 Primary、市场未被追踪或 3 次一致性读取失败时，Order 可能暂时不返回某个市场的镜像。真正排查这类现象应先看 Order 的 Handler 和 Primary/订单簿状态，而不是增加 MD 定时订阅。此前未提交的 30 秒循环代码已经撤回。

#### 重新检查 Order 实际订阅响应的验证证据

- MD 的 `MarketDeptInput.refreshSnapshotAfterPrimaryChange()` 实际取消原 `subscribeWithImage` listener，再通过 `OrderSvrClient.subscribeMarketDeptForOrder()` 重新发起。Order 侧服务端 `OrderMarketImageHandler.snapshot()` 正是这次订阅的初始 Image Handler；从当前物理 Primary 的内存 `OrderBook` 读取全量 bid/ask，包含合法空簿，使用前后两次深度读核对 3 次重试，并再次检查物理 Primary 身份。只有当前源数据不稳定/非本节点 Primary/没有被跟踪的市场才可能漏发某市场快照——应排查 Order 而不是新增 MD 独立轮询。
- MD `DepthBookFacade.onSnapshot()` 在校验并安装完整镜像后，才对本市场标记 READY；序号 gap 已由 `MdDepthGapRecovery` 异步聚合并以 5–60 秒指数退避请求新的 `subscribeWithImage`，正常路径无额外订阅负担。此前拟增加的统一 30 秒 RECOVERING 订阅循环未提交且已撤回，它曾使 `MdReadRouteFailoverReconcileTest.failedImageRefreshRetriesWithoutAnotherEpochBump` 的预期同步重试变化，不应替代已有机制。
- 回退后 Mac Docker Java 8 全量 MD **130/130 PASS**；Order `OrderMarketImageHandlerTest` **7/7 PASS**；MD 三个订阅/恢复专项 **18/18 PASS**。实时只读日志中 OrderSvrA/B/C 的 `ORDER_INITIAL_MD_IMAGES_SKIPPED_UNSTEADY` 均 **0 条**，MD-C `MD_DEPTH_IMAGE_RECOVERY_SUBSCRIBE_RETRY` **0 条**；这不等于真实故障切换已经验收。Gateway 源码和镜像未改。

### 回滚与后续上线门禁

立即回退至此前可用 MD-C Shadow 版本（仅 C，不动 A/B）：

```bash
ROOT="$HOME/.opentradingcore/local-md-release-candidate-20261011"
ENV="$HOME/.opentradingcore/local-ha-zkfix-20261011-v1/artifacts/local-ha-runtime.env"
docker compose --env-file "$ENV" -f compose.yaml \
  -f "$ROOT/artifacts/md-c-shadow-only.yaml" \
  --profile md-cluster-c up -d --no-deps mdsvr-c
```

真实 MD 故障注入前仍须补齐：Order 当前权威 full-market inventory + continuous delta、**MD 自身的旧主停止发布与真实分区级 ZooKeeper CAS/RECOVERING→READY Fencing**、Robot 行情/订单核对，以及实际 SIGKILL、重订阅、rejoin、role reversal。**不要求改 Gateway 或清除 Gateway 内在途旧消息。** 不以本地 10/10 shadow 代替真实签名证据。

生产 Archive GC 也仍 **HOLD**，必须补齐合法双副本最小 Durable HEAD、Projection、远程冷备份恢复与 open reader/rollback fork 后才能开始限速删除。此次变更没有清理任何业务归档。
