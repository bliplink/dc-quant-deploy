# Mac mini SaaS 全集群冷部署与 10 租户验收记录（2026-10-14）

## 结论

**10 租户功能验收：PASS。Order 三副本快照一致性：PASS。Projection 数据库内一致性：PASS。Order/Trade/MD 真实 HA 故障注入：NOT AUTHORIZED / 未完成。**

这是 Demo 冷重部署验收，不是生产 HA 上线证明；不得把 READY、快照相等或数据库检查结果当作经认证的提交 HEAD + replica ACK + epoch fencing 证明。

## 部署及版本边界

- 通过 `deploy-saas-macos.sh --full-cluster --skip-pull` 在 Colima 执行全栈冷部署。受控 reset 将旧运行目录移入私有隔离区，当前运行目录是 `~/.opentradingcore/dc-saas-runtime-redeployfinal20261014`。
- **固定使用 19 种已缓存的镜像**，没有新发布 GHCR，也没有部署此前 Trade PR 中尚未合并/发布的 Common 3.0.20 新恢复实现。
- 当前 HA 基线镜像：Order A/B/C = `dc-saas/ordersvr:cluster-dev-local-c361e3e3d-20261012034946`；Trade A/B = `dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261013-walbatch-08cc695`；机器人 = `dc-saas/robotsvr:cluster-dev-local-robot-tape-precision-1a4aaae-20261012`。Gateway / Order / MD 镜像 Common revision 相同（`dev-361e3e3d-20261012034946`）。
- 容器 `24/24` 运行；一键部署退出码 0；Order/Trade 各 `256/256 READY`；Gateway TradeSvr、TDSvr 路由在线。MySQL 53 张表。
- 本地 HTTP 18088、18090、18092、18094 均返回 200；18096 API Docs 返回 302；公开 `https://opentradingcore.com/` 与 `https://trade.opentradingcore.com/` 返回 200（不代表页面的全部 JS/移动端功能已验收）。

## 真正发生的启动失败与修复

第一次从零初始化时 AdminSvr TrialLiquidityBootstrapWorker 的 CREATE_MAKER 因 `dc_tenant` 缺 `tenant_id` 与 `next_user_no` 报 `SQLSyntaxErrorException`，旧试验租户初始化失败。

修复：为全新 SQL 初始化和可重复执行的迁移加入自动递增、唯一的 `tenant_id` 及初始为 1 的 `next_user_no`；迁移连续运行两次均通过。随后基于修复后的初始化 SQL **再次冷重部署**，从 0 户重做正式验收，没有伪造用户或手动设置 Robot 状态。

源码已合并：[PR #22](https://github.com/bliplink/dc-quant-deploy/pull/22)，squash `6d056e43ca3bdc9faa75932b2f509ae32c27d583`。

## 10 个真实租户 E2E

逐户调用 ManagerSvr 公开申请/自动审批 API，等待独立 Maker、Tape 账户和 Robot 初始化，注册 12 位数字 user_id 交易员并登录，Demo 入金 1000；BTCUSDT IOC 买单 `0.0001 BTC` 成交、核对 MySQL execution 与持仓，再以 reduce-only IOC 卖单平仓，核验持仓为零，Robot 恢复 20 买 + 20 卖、公共盘口可见 10+10 档。

| 序号 | location | E2E |
| --- | --- | --- |
| 1 | EQZGMW | PASS |
| 2 | JML78R | PASS |
| 3 | FFKV0A | PASS |
| 4 | KAW4VQ | PASS |
| 5 | XZ9FO1 | PASS |
| 6 | ZEEPVJ | PASS |
| 7 | ZGH4H4 | PASS |
| 8 | IQKBDF | PASS |
| 9 | KLVOPR | PASS |
| 10 | UQ85QI | PASS |

连续观察到 **10/10 RUNNING、每户 40、合计 400 活动挂单**。正式 `tests/check-demo-tenants-readonly.py` 再次返回 `PASS_10_TENANT_SNAPSHOT`，十户盘口检查全部通过。

`tests/check-tenant-ramp-readiness.py` 返回 `BASELINE_READY_ONLY`、`nextRampAuthorized=false`、`enabledRobotsUnhealthy=[]`、近期 Order recovery signals=[]；不是 50/100/200 户 TPS 证明。

## 快照、投影和 HA 安全边界

- Order 定时快照在运行；前一小时若尚未生成则不能把启动时空 Snapshot 当成恢复能力。长时间运行后 `tests/check_order_md_market_snapshot_readonly.py` 对十户归属分区返回 `verifiedTriplicateSnapshots=10` 且 `snapshotIssues=[]`，**但仍为 `decision=BLOCKED`、`promotionAuthorized=false`**：未获得签名源端 HEAD/ACK、MD full image + delta 与旧发布者 fencing 证明。
- Trade 双向只读快照检查 `verify_trade_rollout_snapshot_headroom.py`：A→B 有 P136、P232、P240 三个目标完整快照滞后；B→A 有 P075、P155 两个滞后。**只说明 full-snapshot fast recovery 前提不满足，不证明 WAL 复制落后或数据损坏**。
- 旧 `projection_watermark_tail_gate.py` 在 10 户不断写入时，因不同 SQL 会话/查询时点曾误报水位与尾部差异。已改用**一个只读 REPEATABLE READ / WITH CONSISTENT SNAPSHOT 事务**同时读取 Order 和 Trade 的水位与索引事件尾部，3 次独立实时采样均 10/10+10/10 匹配；修改后工具返回 `PROJECTION_DB_TAIL_MATCH`。11 项单元测试和 GitHub CI 均通过。源码已合并 [PR #24](https://github.com/bliplink/dc-quant-deploy/pull/24)，squash `c6ef1a040951bc64a2e9fc707b49013384adebd0`。
- `scripts/check-projection-orphans-batched.py` 使用 bounded indexed live range 检查 `236,410` 个 Trade mutations、24 页，`orphanMutations=0`；`tests/check-projection-consistency-host.sh` 也通过事件/Mutation 主键、Order/Trade tail、跨分区 event_id 检查。**这是在线有界只读检查，不是不可变提交证明**。
- 正式 `tests/order_ha_rollout_gate.py --target OrderSvrA` 仍 `NO-GO`：Colima `SwapFree=0`（需 ≥256 MiB），以及未满足 50/50 RUNNING 和 2,000 活动挂单。这次**没有**进行任意 SIGKILL / Gateway 更改 / ZooKeeper 手动主切 / WAL 删除。
- Trade 恢复 P0 的可信 HEAD、完整 Snapshot + diff、epoch fencing、同代快照安装和副本持久水位证明仍需要在 Common 状态机协议及 Trade 业务适配层收口；参考 [Trade issue #7](https://github.com/bliplink/com.app.dc.tradesvr/issues/7)。

## 磁盘释放与证据保全

清理 Docker **未被使用的镜像**：`285 → 36`，Docker 报告回收 `17.01 GB`；未删除运行容器或数据卷。

按 `scripts/mac-saas-purge-quarantine.py` 精确清理已受控隔离的旧 Demo：
- `dc-saas-runtime-epochwarm20261013-20261014T085435Z`：约 92 GB apparent。
- `dc-saas-runtime-zkfix-20261011-20261012T121001Z`：约 66 GB apparent。

脚本校验 24 个现役容器、精确预审的六个关键镜像标签、现役挂载、健康 HTTP、所有 Docker 容器无旧根目录 bind、外部 P246 固定 SHA256、独占锁和确认令牌；本地 10 项回归测试通过；代码 [PR #23](https://github.com/bliplink/dc-quant-deploy/pull/23) 已合并。

宿主机 `/System/Volumes/Data` 从约 **95% / 23 GiB 可用** 降到 **73% / 120 GiB 可用**（最后观测 2026-10-14 18:26 CST）。仅清理受控旧隔离目录，未删除当前 Demo 或独立 `~/.opentradingcore/evidence/p246-reproducer-20261010/` 证据；其余约 77 GB 旧隔离文件继续保留。

## 后续 GO / NO-GO

1. **GO（已通过）**：10 户自动审批、入金、Robot、盘口、真实订单成交和平仓、数据库执行/持仓验证；Order 三副本 Full Snapshot 一致；数据库一致性快照及有界 mutation 孤儿检查。
2. **NO-GO（待开发/验证）**：Common 可信 committed source HEAD / replica ACK + 证实的完整 Snapshot/Diff 数据恢复、Trade 目标副本 full-image gap、MD 单一发布者 fencing、故障时 Projection authoritative watermark；配置层面 Colima swap 及更高租户负载门禁。
3. 在以上门禁满足前**不允许**对当前活动集群 SIGKILL Order/Trade primary，也不允许根据时间/年龄单独永久清除 WAL。需要先保证所有副本可从已验证的 checkpoint+diff 重建。
4. 50→200 户规模测试和真实 HA fault injection 单列验收，不能凭 10 户通过自动宣布上线。

## 证据位置（私有，不含测试用户密码）

`~/.opentradingcore/local-ha-redeploy-20261014/`：`final-deploy.log`、`final-tenant-01.log` 至 `final-tenant-10.log`、`final-10tenant-audit.json`、`soak-10tenant-audit.json`、`soak-10tenant-ramp.json`、`soak-10tenant-order-md.json`、`trade-ab-headroom-20261014.json`、`trade-ba-headroom-20261014.json`、`soak-projection-orphans.json`。私有 env/lock 文件不要提交仓库。
