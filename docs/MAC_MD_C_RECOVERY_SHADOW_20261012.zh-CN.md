# MD-C 真实恢复连续性观测灰度（2026-10-12）

## 结论 / 线上范围

WebCodex 已恢复可操作 Mac mini；本轮在此前 MD-C 灰度的基础上构建并滚动部署了 **`dc-saas/mdsvr:cluster-dev-local-md-shadow-120d6c9-20261012`**，只替换 **`dc-saas-mdsvr-c`**，原 MD-A/B 的 Primary 和旧镜像不动。

代码：`bliplink/com.app.dc.mdsvr` 独立验证分支 `codex/md-auto-failover-disposable-gates-20261011`，提交 `120d6c9`。`mvn clean test` **128/128 PASS**。构建的镜像 ID：`sha256:c17e4d808a035d4381bf4178ca83f845f263657dca4d6bc7be7ead72afc4b7e6`。Common jar 使用与现网一致的 `3.0.17-dev3e1d45c620261011075101-SNAPSHOT`、SHA256 `45ea321a89b44639310f6dd10ac043df144b2be05e8d8c087c0ccba2c01ea6c7`。

仅 MD-C 的 Docker Compose Override `~/.opentradingcore/local-md-release-candidate-20261011/artifacts/md-c-shadow-only.yaml` 增加：

```yaml
services:
  mdsvr-c:
    image: dc-saas/mdsvr:cluster-dev-local-md-shadow-120d6c9-20261012
    environment:
      JAVA_TOOL_OPTIONS: "-Dmd.cluster.replayWitness.enabled=true -Dmd.cluster.replayWitness.auditMillis=30000"
```

MD-C 专用 log4j 配置 `~/.opentradingcore/dc-saas-runtime-zkfix-20261011/control/overrides/MDSvrC/config/log4j.ini` 添加 `com.app.dc.service.orderbook.DepthBookFacade=INFO,file,stdout` 与相应 `additivity=false`；修改前的备份位于 `~/.opentradingcore/local-md-release-candidate-20261011/artifacts/md-c-before-shadow-log4j.ini`。宿主机修改仅作用于 MD-C，不涉及 A/B。观测位于 `MDSvrC.log`，标签 `MD_RECOVERY_SHADOW_OBSERVATION`。

## 真正完成的场内验证

- 重启后 MD-C 是 **Learner**，独立恢复全部 10 个已有租户 `MD_MARKET_READY`；无 Primary、无 ZK assignment CAS。
- 首轮 30 秒观测（06:33:29）：`trackedMarkets=10, contiguous=8, stale=2, gapMarkets=0, gapEvents=0, promotionAuthorized=false`。保留**初次未达 10/10 的事实**；本地 stale 不能冒充签名源头证明。
- 后续连续两轮真实观测（06:33:58、06:34:28）均为 **`trackedMarkets=10, contiguous=10, stale=0, gapMarkets=0, gapEvents=0, promotionAuthorized=false`**，说明现有十个真实市场的 MD-C 本地 Full Image→Delta 观测已恢复正常且无间断。源端 Order durable watermark/Gateway publisher fencing 仍不可从本地观测推断。原始记录在 `~/.opentradingcore/dc-saas-runtime-zkfix-20261011/log/MDSvrC.log`。
- 第一次滚动后严格 `tests/check-demo-tenants-readonly.py`：**10/10 PASS**，10 个 Robot 全为 RUNNING、各 40 活动委托、双边盘口各 10 档；原始 JSON `~/.opentradingcore/local-md-release-candidate-20261011/artifacts/md-shadow-120d6c9-10tenant.json`。
- `tests/check-projection-consistency-host.sh`：**PASS**，Order/Trade watermark tail mismatch 均为 0、orphan_mutations=0、cross_partition_event_ids=0。MD-C 重启/ OOM 均为 0。
- 实际应用为 Java 8 Spring Boot 2.3；对 JVM 的 `jcmd VM.system_properties` 核对两个 observer 标志均按预期生效。早期无 INFO 日志是 MD-C log4j root=ERROR 过滤造成，非观测代码未执行；专门调整 C 的日志级别后已经有真实汇总记录。

## 自动化只读 Shadow 验收与故障注入阻断（本轮新增）

`scripts/check-md-recovery-shadow.py` 把原来的人工日志检查改成可重复机器门禁，只从 `MDSvrC.log` 中取**最新的两个** `MD_RECOVERY_SHADOW_OBSERVATION` 样本，严格要求采样间隔在 15–120 秒、日志未过期、两个样本都恰好 10/10 Fresh、无 Stale、无 Gap、无累计 Gap 事件，且 `promotionAuthorized=false`。不允许挑选很久前的成功记录；缺失、陈旧、缺市场或本地 Gap 均拒绝。**脚本没有源端市场身份清单和 Epoch/ZK 认证能力**，这些只能由后续独立证明来保障，不能用本脚本替代。

`tests/test_md_recovery_shadow.py` **6/6 PASS**（含伪造 promotion=true、最新样本失败、样本过期、缺失、出现 Gap 等反例）；`.github/workflows/validate-md-failover-preflight.yml` 将脚本编译和测试纳入 GitHub Actions。

2026-10-12 06:36 CST 现场运行：

```bash
python3 scripts/check-md-recovery-shadow.py \
  --log "$HOME/.opentradingcore/dc-saas-runtime-zkfix-20261011/log/MDSvrC.log" \
  --markets 10 --max-age-seconds 180 \
  --output "$HOME/.opentradingcore/local-md-release-candidate-20261011/artifacts/md-c-two-sample-shadow-gate-20261012.json"
```

实际 `decision=PASS_LOCAL_OBSERVATION_ONLY`，两个样本分别在 **06:35:55、06:36:25**，`tracked=10, fresh=10, stale=0, gapMarkets=0, gapEvents=0`。验收 JSON **始终**带 `promotionAuthorized=false, canInjectMdPrimaryFault=false, hasSignedOrderDurableHead=false, hasGatewayOldPublisherFence=false`。因此通过只读观测**不构成真正的 MD 自动主切发布授权**。

## 当前真实 ZooKeeper / Order 与租户最后验收

已用混合版本锁重新运行 `scripts/check-md-failover-preflight.py`，A/B 锁旧镜像、C 锁 `120d6c9`。ZooKeeper 与 Docker 结果：**256 个 MD 分区全部 READY、MD-A/B 各 128 Primary、A/B/C ephemeral member 全在线，容器镜像版本都精确匹配**。但工具实际 `exit=2, decision=BLOCKED, canInjectMdPrimaryFault=false`；阻断原因为 `ORDER_CURRENT_FULL_MARKET_IMAGE_PROOF_MISSING`、`MD_PROMOTION_FENCING_AND_CAS_CONTROLLER_NOT_CONFIGURED`、`MD_RECOVERING_TO_READY_EPOCH_PUBLICATION_FENCE_UNATTESTED`、`MD_PROMOTED_EPOCH_FULL_MARKET_IMAGE_NOT_ATTESTED`、`ROBOT_POST_FAILOVER_ORDER_RECONCILIATION_NOT_ATTESTED`。原始 JSON：`~/.opentradingcore/local-md-release-candidate-20261011/artifacts/md-c-shadow-preflight-20261012.json`。

结束前执行全部现网只读检查：`check-demo-tenants-readonly.py` **PASS_10_TENANT_SNAPSHOT**（10 Robot RUNNING、每租户 40 活动单、双边盘口 10 档）；`check-projection-consistency-host.sh` **PASS**（Order/Trade tail mismatch=0、orphan_mutations=0、cross_partition_event_ids=0）；`verify-order-cluster-state-host.sh` **PASS**（**Order 256/256 READY，256 组 snapshot 一致，0 Learner，Order A/C 129/127 Primary，B 为 256 Replica**，各 Order 无重启/OOM）；共有 **24 个** `dc-saas-` Docker 容器运行。文件 `~/.opentradingcore/local-md-release-candidate-20261011/artifacts/md-c-shadow-final-tenants-20261012.json`。这些在线服务仍以旧 Order/Trade 镜像为主，不等于新 HA 正式接管。

## 严格区分观察与真正自动切换上线

**仍保持自动 failover closed**：`md.cluster.failover.enabled=false`。虽然 shadow 可观察完整 Order 全量 image 与 delta 的本地连续性，它从未声称证明 Order durable committed HEAD、网关 Publisher Fencing、ZooKeeper 旧主隔离、跨全市场 signed inventory 或跨重启 ledger，不允许拿 `contiguous=10` 直接置 READY。

先决未完成：
1. Order 与 Common 绑定的当前 Primary/ZK Stat/Committed HEAD/全市场原子 Image 的可认证证明。历史 manifest `COMMITTED_SNAPSHOT_CHECKPOINT_ONLY` 不具备晋升效力。
2. Gateway 与 MD 的旧 Epoch 强制禁止发布机制在所有旧 publisher、断线重连和延迟队列中实际证明生效。
3. MD-C 按被接管 epoch 接受确切的全市场 Snapshot/delta 水位，然后由外部 CAS gate 再次验证；Robot 委托/盘口对账。
4. 真实的 MD 主节点 SIGKILL、重入 Learner、逆向接管测试通过，再扩大灰度到 MD-A/B。
5. 归档 GC 仍不可碰现有业务 WAL，直到跨副本持久水位/Projection watermark/真实远端备份恢复与所有 reader/fork 明确证明，并通过单 segment 的 Archive→Active 全恢复。

## 仅回滚 MD-C

将灰度回退到上一已验证 MD-C 镜像：

```bash
ROOT="$HOME/.opentradingcore/local-md-release-candidate-20261011"
ENV="$HOME/.opentradingcore/local-ha-zkfix-20261011-v1/artifacts/local-ha-runtime.env"
docker compose --env-file "$ENV" -f compose.yaml -f "$ROOT/artifacts/md-c-image-only.yaml" --profile md-cluster-c up -d --no-deps mdsvr-c
```

需要再回退到最早旧镜像：`docker compose --env-file "$ENV" -f compose.yaml --profile md-cluster-c up -d --no-deps mdsvr-c`，请先核对 `compose.yaml` 和运行容器标签。仅撤销 C 的专用 INFO logger，则从 `md-c-before-shadow-log4j.ini` 恢复到上面明确的 override path 并重新部署 C，不要改动 MD-A/B。

**这不是完整 MD HA 或生产 Archive GC 上线报告。** MD-C 新镜像和只读 shadow observer 已真实部署，源端/发布者权威验证仍 BLOCKED。
