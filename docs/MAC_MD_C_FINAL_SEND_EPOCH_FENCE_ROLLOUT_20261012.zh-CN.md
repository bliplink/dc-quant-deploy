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

### 回滚与后续上线门禁

立即回退至此前可用 MD-C Shadow 版本（仅 C，不动 A/B）：

```bash
ROOT="$HOME/.opentradingcore/local-md-release-candidate-20261011"
ENV="$HOME/.opentradingcore/local-ha-zkfix-20261011-v1/artifacts/local-ha-runtime.env"
docker compose --env-file "$ENV" -f compose.yaml \
  -f "$ROOT/artifacts/md-c-shadow-only.yaml" \
  --profile md-cluster-c up -d --no-deps mdsvr-c
```

真实 MD 故障注入前仍须补齐：Order 签名的当前 Primary committed full-market inventory + continuous delta、Gateway 在接收端拒绝旧 epoch、真实分区级 ZooKeeper CAS + RECOVERING/READY Fencing、机器人订单核对，以及实际 SIGKILL、rejoin、role reversal。不以本地 10/10 shadow 代替真实签名证据。

生产 Archive GC 也仍 **HOLD**，必须补齐合法双副本最小 Durable HEAD、Projection、远程冷备份恢复与 open reader/rollback fork 后才能开始限速删除。此次变更没有清理任何业务归档。
