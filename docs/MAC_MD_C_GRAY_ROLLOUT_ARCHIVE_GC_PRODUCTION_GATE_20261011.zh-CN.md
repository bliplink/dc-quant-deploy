# MD-C 真实灰度上线与 Archive GC 安全门禁：2026-10-11

> **发布状态：MD-C 已真正运行新镜像；MD-A/B 未升级；MD 自动主切与真实业务归档删除未开启。** 后两项尚未具备最基本的跨服务权威证明，任何从 BLOCKED 改为 PASS 的假门禁均不可上线。

## 1. 实际已部署版本

| 组件 | 容器 | 当前镜像 |
|---|---|---|
| MD-A | `dc-saas-mdsvr` | `dc-saas/mdsvr:cluster-dev-local-c3e1d45c6-20261011075101` |
| MD-B | `dc-saas-mdsvr-b` | `dc-saas/mdsvr:cluster-dev-local-c3e1d45c6-20261011075101` |
| **MD-C 灰度** | **`dc-saas-mdsvr-c`** | **`dc-saas/mdsvr:cluster-dev-local-md-ha-a5f6063-20261011`** |

- MD-C 构建来源：`bliplink/com.app.dc.mdsvr` 提交 `a5f6063793e69ed2a585f9d98cb135a257e3b75b`（独立验证分支），Java 8 Maven `mvn clean test` **127/127 PASS**。隔离自动主切/反向切换专项 **17/17 PASS**。
- Java 8 依赖来源：当前 **与线上一致的** `com.app.common-3.0.17-dev3e1d45c620261011075101-SNAPSHOT.jar`，SHA256 **`45ea321a89b44639310f6dd10ac043df144b2be05e8d8c087c0ccba2c01ea6c7`**。不把本地开发 GAV 错报为 Maven Central 发布。
- 新容器 ImageId `sha256:b7a31c16e689f3d52d7a1af9eea372f5b265633f0bfe24c69bbee51920a5f0fa`，容器已重新创建并启动，`RestartCount=0`、`OOMKilled=false`。MD-A/B 均 0 重启、无 OOM。
- 隔离构建快照、源 SHA、日志：`~/.opentradingcore/local-md-release-candidate-20261011/{source,artifacts}`。
- 灰度镜像专属 Compose override：`~/.opentradingcore/local-md-release-candidate-20261011/artifacts/md-c-image-only.yaml`。本轮命令只执行 `docker compose --env-file <local-ha-runtime.env> -f compose.yaml -f <md-c-image-only.yaml> --profile md-cluster-c up -d --no-deps mdsvr-c`；其余 23 个服务未动。部署完成后第一次 MD-C 启动日志确认 10 个租户市场以 Learner 身份恢复 `MD_MARKET_READY`。

**MD 自动切换依然默认关闭：`md.cluster.failover.enabled=false`（无 Safety provider 时启用还会启动失败）**；MD-C 的 `md.cluster.replayWitness.enabled=false` 也未被改变。只上线了新的可验证代码，没有强开 HA 写 ZK。

## 2. 真正上线的灰度验收

- 第一次部署后严格租户审计 **FAIL**：`OET72U` 在一个 Robot 成交补单窗口 **39/40**，其余 9 租户 40；10/10 市场均有双边盘口；证据 `~/.opentradingcore/local-md-release-candidate-20261011/artifacts/md-c-rollout-10ten.json`。
- 紧接着严格完整重跑 **PASS_10_TENANT_SNAPSHOT**：10/10 Robot `RUNNING`、各 40 活动单、10/10 市场 10 档 bid 和 10 档 ask；证据 `md-c-rollout-retest-10ten.json`。保留首次失败证据，未放松 Robot 审计阈值。
- `tests/check-projection-consistency-host.sh` **PASS**：Order/Trade `watermark_tail_mismatch=0`，`orphan_mutations=0`、`cross_partition_event_ids=0`。
- MD-C 本地 `MDSvrC.log` 首次启动时记录所有 10 个原有租户市场 `MD_MARKET_READY`，角色为 LEARNER，启动日志最后 350 行 **0 ERROR/Exception**；最近内存约 **234 MiB / 640 MiB**。
- 所有 24 个 Docker 容器运行，A/B 仍服务原 128+128 MD Primary 分区，MD-C 无 Primary。

## 3. 现在已按新旧混合镜像验证真正的 ZooKeeper 状态

`scripts/check-md-failover-preflight.py` 新增精确参数 `--expected-md-c-image`：默认锁定 A/B 旧版本，C 可以显式验证新发布的不可变本地版本。11→**12/12 单测通过**，并在 Mac Docker+ZooKeeper 上真实执行：

```bash
python3 scripts/check-md-failover-preflight.py \
  --expected-image dc-saas/mdsvr:cluster-dev-local-c3e1d45c6-20261011075101 \
  --expected-md-c-image dc-saas/mdsvr:cluster-dev-local-md-ha-a5f6063-20261011 \
  --output "$HOME/.opentradingcore/local-md-release-candidate-20261011/artifacts/md-c-mixed-image-preflight.json"
```

结果：`partitionCount=256`、`unreadyPartitions=0`、`primaryCounts={MDSvrA:128,MDSvrB:128}`、MDSvrA/B/C 都有真实 ZooKeeper ephemeral membership，三个镜像锁与真实部署**精确匹配**。但仍旧 `decision=BLOCKED`，`canPromote=false`、`canInjectMdPrimaryFault=false`，主要有 5 个安全阻断：

1. `ORDER_CURRENT_FULL_MARKET_IMAGE_PROOF_MISSING`
2. `MD_PROMOTION_FENCING_AND_CAS_CONTROLLER_NOT_CONFIGURED`
3. `MD_RECOVERING_TO_READY_EPOCH_PUBLICATION_FENCE_UNATTESTED`
4. `MD_PROMOTED_EPOCH_FULL_MARKET_IMAGE_NOT_ATTESTED`
5. `ROBOT_POST_FAILOVER_ORDER_RECONCILIATION_NOT_ATTESTED`

尤其 Order 的 `OrderMdMarketManifest` 主动声明 `promotionAuthorized=false`，只是历史 Snapshot 的 SHA，**不是当前 Source HEAD 的加密签名**；MD 的 `MdDepthReplayWitness` 也明确只有诊断能力，不能取代完整的源与 Gateway Fencing 证明。直接打开 MD-A/B 的自动主切会让缺失 Safety bean 的服务启动拒绝，或者诱发双主风险；不得强行执行。

## 4. Archive GC 仍是隔离执行成功，线上业务归档保持

- 本轮已运行 `scripts/run-archive-retention-gc-canary.py` 物理删除**程序自己创建**的测试归档 1 份、保留不安全目录 1 份，备份 SHA 和恢复通过；新守卫补充了**拒绝空目录/未知目录成员/零长度 CQ 文件**的特殊情况，**6/6 单测 PASS**。
- Order 的真实 Chronicle Queue 测试已经在临时目录进行实际的 `STATE→COMMIT→Archive→文件移除→备份恢复→读出同一 COMMIT`，Order **339 项，0 失败、1 跳过**。它并不授予现网删除权限。
- 现网只读数量：Order A/B/C 的 Archive 分别 **384/385/513** 份（约 **168/194/112 MiB**）；Trade A **12** 份（约 **83 MiB**），Trade B 0。没有删除任意现有租户历史 WAL。跨副本、Projection、正在运行的 reader、跨 Archive→Active 追平和实际远端备份恢复证据尚未聚合成可信的自动 GC 允许书，因此生产 GC 仍 **HOLD**。仅凭 7 天时间、filename epoch/seq 不允许删除。

## 5. 一步回退 MD-C（只动 C，不改业务数据）

需要回滚时，保持主机当前 `dc-quant-deploy` 仓库 `compose.yaml` 和既有 `local-ha-runtime.env`：

```bash
ENV="$HOME/.opentradingcore/local-ha-zkfix-20261011-v1/artifacts/local-ha-runtime.env"
docker compose --env-file "$ENV" -f compose.yaml --profile md-cluster-c up -d --no-deps mdsvr-c
docker inspect dc-saas-mdsvr-c --format '{{.Config.Image}} {{.State.Running}} {{.RestartCount}}'
```

此命令使用环境变量里锁定的**旧 MD 镜像**，仅回退 C。回退后再运行 `tests/check-demo-tenants-readonly.py`、`tests/check-projection-consistency-host.sh` 并查看 `MDSvrC.log`。若本地实际主部署 compose 文件不是当前仓库，先核对 `docker inspect` 里的 compose project 标签。

## 6. 下一阶段真正开启条件（尚未完成，不得报已上线）

**MD**：Order 每市场现时 committed HEAD（绑定物理 Primary、Source ZK version 和当前深度版本）可信凭证；MD 根据当前 Epoch 完整收到所有合法活跃市场 Image+无间断 delta；Gateway 和旧 MD publisher 共同证实旧 Epoch 禁发（含断联后重连）；CAS 后二次验证；隔离现网测试分区实际 SIGKILL、复入、反向切换和 Robot 对单。然后才能开 `md.cluster.failover.enabled=true` 并逐步滚 A/B。

**Archive**：真实 Snapshot 可恢复及至少两个合法副本最小 Durable HEAD、Projection persistent watermark、所有可能 Archive reader 关闭、远端备份可恢复和 rollback fork proof，跨 Archive→Active 恢复到 READY 后，才能在业务外独立后台线程开启限速 GC。

**可断言的完成状态**：新版 MD-C 镜像**真实上线灰度完成**；生产自动主切和业务日志定时删除**尚未达到安全上线条件**。本轮没有重部署 10 租户、没有故障注入实际主节点、没有动用业务数据恢复或删除历史。
