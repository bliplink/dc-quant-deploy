# Mac mini Demo｜直接更新、干净重建、10 租户验收（2026-10-15）

> **本页是实际执行记录，不是 50/200 租户容量证明，也不是 HA 主切授权。** 详细候选版本基线见 [MAC_CERTIFIED_WAL_QUORUM_LOCAL_CANDIDATE_20261015.zh-CN.md](MAC_CERTIFIED_WAL_QUORUM_LOCAL_CANDIDATE_20261015.zh-CN.md)。

## 当前 Demo（已运行）

- 按用户要求采用**直接 Demo 更新**，没有逐节点灰度；为避免新旧 WAL 物理字节冲突，最终使用全新持久化根目录 `~/.opentradingcore/dc-saas-runtime-ordered-20261015`。此前两份数据 `dc-saas-runtime-redeployfinal20261014` 与 `dc-saas-runtime-freshcert-20261015` **完整保留**，未删除、未覆写，包含最初复制分歧与错误部署证据。
- 24 个 `dc-saas-*` 容器运行，公网站本地 `/` 返回 HTTP 200。
- 统一 ARM64 候选：Order A/B/C `dc-saas/ordersvr:certified-v2-local-20261015`、Trade A/B `dc-saas/tradesvr:certified-receiver-v3-local-20261015`、MD A/B/C `dc-saas/mdsvr:certified-v2-local-20261015`、Gateway `dc-saas/gw:certified-v2-local-20261015`。这些仍是**Mac 本地测试镜像，不是正式发布 GHCR 的统一授权恢复镜像**。对应 Common JAR SHA-256 为 `af14b091151feba2caf384ae8652065fa1b12de8ef27af57b57fe955187d71de`。
- AdminSvr `dc-saas/adminsvr:trial-completion-fix-local-20261015` 从 `saas-crypto` 源镜像 `sha-4d4092f...` 仅替换 `TrialLiquidityBootstrapWorker.class`。修复已合并到 [AdminSvr PR #4](https://github.com/bliplink/com.app.dc.adminsvr/pull/4)，合并 SHA `06cf491e66f6e70b5d7b8229163a84da216dc802`；Java 8 本地 87 项测试、0 失败/错误、1 跳过。尚未产生与此补丁一致的正式 GHCR 镜像。

## 冷启动事故与正确顺序

- 初次直接 Compose 替换后，原 Trade WAL 同一 seq 在主、副本上出现 `duplicate WAL physical record differs`。新校验**正确拒绝**该重复 ACK；**没有关闭字节校验、覆盖 WAL、或强制 READY**。
- 第一次切到空数据时直接 `docker compose up`，绕过正式部署入口前置阶段：ZooKeeper 768 个分区未预创建、MySQL 缺少增量 `dc_tenant_liquidity_bootstrap` 表、平台与 Robot API Key 尚未初始化。后补数据时，Trade 首次 ZK `NoNode` 已被栅栏；LoginSvr 缓存未加载新增 Robot Key，导致自动审批 `PENDING`、资金结果待对账、Robot `API_NOT_EXIST` 等链式故障。该次数据作为证据保留，未通过手动伪造资金/审批状态来修复。
- **真正干净且通过的顺序：** ① 基础设施 MySQL/ZooKeeper/ClickHouse 健康；② 对 Order、Trade、MD 各写入 256 个 ZooKeeper partition assignment；③ 应用已提交的 26 项 MySQL migration（未应用本机尚未提交的数字 user ID 实验）；④ 在业务服务启动前创建平台管理员与独立 Robot runtime identity；⑤ 最后整体启动 24 个容器并等待 LoginSvr 载入 Key、Order/Trade/MD READY；⑥ 逐租户真实 API E2E 与独立盘口、数据库、水位检查。
- **不要把直接 `docker compose up` 当作冷部署入口。** 项目标准 `deploy-saas.sh` 及 macOS 包装器 `deploy-saas-macos.sh` 已按上述 pre-bootstrap 顺序执行。对本地离线候选的直接部署，应在不暴露私有环境变量的情况下显式完成等价前置步骤。重建前先保留可回滚配置和旧数据目录。

## 10 租户实测

- 10 次独立 `tests/run-auto-tenant-trading-e2e.py` 全部退出码 0；每次含租户自动审批、Maker/Tape 独立账户资金初始化、Robot 挂单、真实交易员入金、限价成交 `0.0001 BTC`、Position/Execution 一致、reduce-only 平仓、最终净持仓 0 与无剩余交易员活动订单、Robot 自动补单。
- 租户：`HRESWU`、`CL8EEN`、`WPSQVQ`、`TS99FH`、`LP3BG2`、`BRUDXK`、`B75WXC`、`PB7G7G`、`S3YEKU`、`PZGR4M`。
- 后置 MySQL：10 `TRIAL`；10 条 Trial 流动性任务 `COMPLETE/DONE`；10 Robot `RUNNING`，合计 **400 条报价**；公开盘口审计 10/10 有 **10 bid + 10 ask**。
- 修复了 Trial `VERIFY` 曾失败又重试成功后仍保留旧 `last_error_code/message/attempts` 的问题；上线原子完成 SQL 后，对**仅限已 COMPLETE/DONE、无租约、已入金、对应 RUNNING 且 40 挂单 Robot**的 10 条历史元数据做一次 guarded cleanup。残留错误 10→0、过时重试计数 10→0；未更改资金/持仓/订单/成交/WAL。
- Order：256/256 ZK assignment READY，A/B 各 128 primary、C 256 sync replica，256 个三节点 Snapshot 一致；Order/Gateway 无重启、无 OOM。
- Projection DB tail：Order 10 行、Trade 10 行匹配（`PROJECTION_DB_TAIL_MATCH`），**不等于源 WAL committed head、资金/持仓最终权威对账**。
- `check-tenant-ramp-readiness.py`：`BASELINE_READY_ONLY`、0 阻断原因、`nextRampAuthorized=false`。某次 5 分钟采样为 469 行 market-trade、0 不活跃租户、CPU PSI 9.27%、Order B 三秒 Full GC 0、老年代仅占最大容量 6.6%；**market-trade 不是下单 TPS**。
- 重新部署 AdminSvr 后，`check-demo-tenants-readonly.py` 10/10 PASS；Order、Projection 和 ramp gate 复查再次通过；主站 HTTP 200、容器无退出/不健康。

## 尚未通过／下一步必须做

1. **Trade 真实主切仍 NO-GO。** `check_trade_live_snapshot_role_preflight.py` 对 10 个活跃分区全部 `snapshotBlocked`；实测主、副本的 `latest.json` 仍为初始 `snapshotSeq=0`、`committedStateSeq=0`、`locations=[]`。目前 Trade periodic snapshot **已开启**，但配置为每 60 秒轮询、最大快照年龄 1 小时、2 万次提交变化触发；不可用初始快照代替真实 WAL committed-range/certified 恢复证据。先修复活跃分区快照可恢复性、接收端完成事务，再核实真实复本状态。
2. **接收端认证恢复未上线。** ZooKeeper `Mode: standalone`，没有多独立物理投票成员和 Quorum 证明；Common/Trade 可信源端 + signed full WAL candidate 尚未闭环到生产接收事务的外部权威 READY。需要保留旧 publisher fencing、重复 WAL 物理字节核验，不得强制提升 READY。
3. **没有做 SIGKILL / 对 10 租户以上的负载宣称。** 尚未完成故障后资金/持仓/委托/成交/Projection 与权威 WAL 源的总对账；50/200 租户持续负载、突发 2–3 倍、HA Order/Trade/MD 故障切换、WAL 安全归档/删除也仍待验收。先构建证据链再执行故障注入，不因 Demo 可交易就自行跳过正确性约束。

## 本机回溯材料（敏感环境文件不入库）

- 配置与回滚元数据：`~/.opentradingcore/otc-demo-direct-20261015/` 下的 `demo-ordered-20261015.env`、`demo-ordered-adminfix-20261015.env` 与原版本 env（权限 0600）。**这些 env 含私密值，不要提交 Git。**
- 测试记录：同目录 `acceptance-evidence/` 中的 `tenant-2-e2e.log` ～ `tenant-10-e2e.log`、`ten-tenant-after-admin-update.json`、`ten-tenant-final-ramp-gate.json`、`trade-role-readonly-gate.json`、`admin-completion-metadata-cleanup.txt`。第一个租户的完整 PASS 保存在执行会话日志。
- 源码：[Common PR #25](https://github.com/bliplink/com.app.common/pull/25)、[Trade PR #26](https://github.com/bliplink/com.app.dc.tradesvr/pull/26)、[Order PR #11](https://github.com/bliplink/com.app.dc.ordersvr/pull/11) 仍需发布栈整合；Admin 修复 PR #4 已合并。
