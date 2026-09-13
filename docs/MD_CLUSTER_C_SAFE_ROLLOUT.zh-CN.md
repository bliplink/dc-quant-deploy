# MDSvrC 安全扩容与滚动升级

## 目标

在不直接重启当前 MDSvrA/MDSvrB 主分区的前提下，把 MDSvrC 先作为热 learner 加入，确认活跃市场已经追平后，再按小批分区迁移 primary。所有 ZooKeeper 更新必须使用 znode `dataVersion` CAS；禁止盲写整个 assignment 目录。

当前阶段仍使用 legacy `P000..P255` assignment。Placement 继续保持关闭；按 BTCUSDT 独立节点、其他品种普通池的 namespaced placement 在三节点兼容版本完成滚动升级后再灰度启用。

## 不变量

- MDSvrC 启动时使用与线上 A/B 相同的旧 MDSvr 镜像，先完成 learner 预热，不混用业务协议。
- 加 learner 不改变 epoch、primary、replica 或 READY 状态。
- primary 切换必须是 `READY(old epoch) -> RECOVERING(new epoch) -> READY(new epoch)`。
- 目标节点必须已经在原 assignment 的 `replicas[]` 或 `learners[]` 中。
- 活跃市场按 `location + marketIndicator + securityID` 逐条检查 `MD_MARKET_READY`，不能只看端口或容器状态。
- 每次只迁移小批分区；任何 CAS 冲突、容器重启、日志证据缺失都会停止本批。

## 工具

`tests/md_cluster_transition_host.py` 默认只生成计划，不修改 ZooKeeper。实际写入必须同时提供 `--apply` 和与目标根路径完全一致的 `--confirm-root`。工具默认每 16 个分区执行一次批量预读、逐条版本 CAS 和批量回读；可用 `--batch-size` 调小故障域。

活跃路由文件使用 JSONL，例如：

```json
{"location":"WEB_E2E","marketIndicator":"4","securityID":"BTCUSDT"}
{"location":"WEB_E2E","marketIndicator":"4","securityID":"ETHUSDT"}
```

路由清单应从当前启用租户、交易品种和 Robot 配置生成，放在运行主机临时目录，不提交用户或凭据数据。

## 执行顺序

1. 暂停自动更新，确认 A/B、GW、ZooKeeper 健康，保存镜像和 assignment 快照。
2. 拉取部署仓库，但不执行全量 `deploy-saas.sh`。
3. 生成 MDSvrC 配置，使用线上当前 `MDSVR_TAG` 仅启动 `mdsvr-c`，确认端口、注册和零重启。
4. 生成 learner 计划：

```bash
sudo python3 tests/md_cluster_transition_host.py stage-learner \
  --learner MDSvrC \
  --plan /data/dc-saas-runtime/evidence/md-c-stage-learner.json
```

5. 人工审阅计划后，以 CAS 应用同一操作：

```bash
sudo python3 tests/md_cluster_transition_host.py stage-learner \
  --learner MDSvrC \
  --plan /data/dc-saas-runtime/evidence/md-c-stage-learner-applied.json \
  --apply --confirm-root /dc/cluster/mdsvr/partitions
```

6. 等待 MDSvrC 对所有活跃路由记录 `role:LEARNER` 的 `MD_MARKET_READY`。切主工具会再次强制检查这些证据。
7. 每批最多 8 个原 A 主分区进入 RECOVERING：

```bash
sudo python3 tests/md_cluster_transition_host.py drain-recovering \
  --from-node MDSvrA --to-node MDSvrC --limit 8 \
  --active-routes /tmp/md-active-routes.jsonl \
  --target-container dc-saas-mdsvr-c \
  --since 2026-09-13T00:00:00Z \
  --plan /data/dc-saas-runtime/evidence/md-a-to-c-batch-001-recovering.json
```

8. 审阅后用相同参数增加 `--apply --confirm-root /dc/cluster/mdsvr/partitions`。
9. 目标节点在新 epoch 收到完整市场图后，生成并应用 READY 计划：

```bash
sudo python3 tests/md_cluster_transition_host.py promote-ready \
  --recovery-plan /data/dc-saas-runtime/evidence/md-a-to-c-batch-001-recovering.json \
  --active-routes /tmp/md-active-routes.jsonl \
  --target-container dc-saas-mdsvr-c \
  --plan /data/dc-saas-runtime/evidence/md-a-to-c-batch-001-ready.json
```

10. 每批验收行情最新价、盘口、成交、K 线和 WebSocket 连续性，然后继续下一批。

单分区灰度通过后，可使用 `tests/md_cluster_roll_drain_host.py` 自动重复同一套门禁，按批排空一个节点。它仍要求精确确认 ZooKeeper 根路径，并为每批分别保存 RECOVERING/READY 证据：

```bash
sudo python3 tests/md_cluster_roll_drain_host.py \
  --source MDSvrA --target MDSvrC \
  --active-routes /data/dc-saas-runtime/evidence/md-active-routes.jsonl \
  --target-container dc-saas-mdsvr-c \
  --learner-since 2026-09-13T12:38:42Z \
  --evidence-dir /data/dc-saas-runtime/evidence/md-a-to-c \
  --batch-size 8 --ready-timeout 60 \
  --confirm-root /dc/cluster/mdsvr/partitions
```

## 版本滚动顺序

MDSvrC 用旧镜像预热并承接 A 的 primary 后，先升级 A；A 在新镜像下作为 replica/learner 追平后承接 B，再升级 B；最后把 C 的 primary 排空到已升级节点并升级 C。最终三节点使用同一不可变镜像和相同 Common JAR SHA，再进行均衡与 placement 灰度。

若任一步失败，保留当前 assignment 和数据，不删除 OHLC、快照或 ZooKeeper 节点。已经完成的单分区 CAS 是显式状态，不需要回滚整棵树；修复目标节点后从实时 assignment 重新生成下一份计划。
