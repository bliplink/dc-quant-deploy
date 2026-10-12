# Mac Demo：全新数据一键部署和租户重建（2026-10-12）

> 本文件仅记录 **Mac Demo** 实际操作与证据，不代表生产集群 HA、WAL
> 自动 GC 或 200 租户压力测试通过。当前使用本地不可变镜像，尚非
> 全部通过 GitHub Actions 正式发布的 GHCR 镜像。

## 为什么选择冷部署

上轮 Trade 在两节点、每个分区唯一强同步 Replica 的部署中，
直接重启任一必需 Replica 会使 Primary 缺少持久 ACK，造成业务
降级和冗长 dirty-tail 恢复。原有 Trade A/B 快照缺口与
Projection 六处 archived WAL 历史水位也未完成线上追平。
Demo 业务数据没有保留价值，用户明确授权清理数据重新部署。
因此采取 **隔离旧数据 + 新 MySQL、ZooKeeper 和所有业务数据目录**
的策略，避免把旧历史状态混入恢复协议测试。

## 实施操作和持久回滚证据

1. `scripts/mac-saas-reset.py` 冷重置最初因非 Compose 的已停止
   `dc-saas-tradesvr-failed-2ed6095` 使用同一旧数据目录而拒绝，
   经实机核实它确是前轮失败留下、restart=no、非 Compose 的
   旧 Trade-A 候选容器后，只删除了该一个已停止残留容器。
2. 重新运行 `--mode plan` 确认恰好 **24 个 Compose 容器**、
   独立私有 P246 SHA256 故障复现证据完整，
   无其他 Docker 项目共享挂载。
3. 使用 `--mode stage --confirm STAGE_DISPOSABLE_DC_SAAS`
   停止并移除 24 个旧 Compose 容器，把约 **67 GiB** 旧
   Mac 运行目录原子移动至
   `~/.opentradingcore/.dc-saas-quarantine/dc-saas-runtime-zkfix-20261011-20261012T121001Z`。
   **没有执行永久数据 purge**；原有仓库、配置和独立故障证据保留。
4. 全新根目录：
   `~/.opentradingcore/dc-saas-runtime-clean20261012`，
   构建目录 `~/.opentradingcore/dc-saas-build-clean20261012`。
   当前私有 0600 配置及固定镜像锁：
   `~/.opentradingcore/local-ha-clean-20261012-v1/fresh-release.env`、
   `fresh-images.env`。**绝不能将该 env 文件提交到 Git**：
   内含数据库、管理员及服务 API 凭证。
5. 17 个固定版本镜像均确认已缓存；完整 Compose
   `--check --full-cluster` 通过。第一次启动前置安全门禁
   拒绝 Gateway/MD/Order Common 版本错配；通过修正
   `IMAGE_SOURCE=local` + `--skip-pull` 的不可变本地
   release lock，使 Gateway、Order、MD 使用已编译的
   同一 Common `361e3e3`，Trade A/B 使用新的
   `6b8fe7d` 开发包（它包含旧 V2 兼容协议及独立新 Manifest）；
   无需从网络重新下载应用镜像。
6. 使用原有 `deploy-saas-macos.sh --full-cluster --skip-pull`
   正式执行冷部署，退出码 **0**，日志：
   `~/.opentradingcore/local-ha-clean-20261012-v1/fresh-deploy.log`。
   经验证：
   - **24/24 Compose 服务 Running**；
   - MySQL、ClickHouse、ZooKeeper 健康；
   - **Order 256/256、Trade 256/256 分区 READY**，
     复制服务的私有端口正在监听；
   - GW 的 TradeSvr/TDSvr 路由 online；
   - 53 张 MySQL 表和 35 个 location 字段；
   - Trade Web、Tenant Web、Platform Web、Public Web、
     API Docs 的 Docker 健康检查通过；
   - `http://127.0.0.1:18088/` 可访问。
7. 固定关键镜像：
   - Gateway `dc-saas/gw:cluster-dev-local-c361e3e3d-20261012034946`，
     Gateway **业务透传逻辑未修改**；
   - Order A/B/C `dc-saas/ordersvr:cluster-dev-local-c361e3e3d-20261012034946`；
   - MD A/B/C `dc-saas/mdsvr:cluster-dev-local-c361e3e3d-20261012034946`；
     原先 MD-C 独立的 dff97ba epoch-fence 修复**尚未转移到新镜像**，
     后续必须单独验证；
   - Trade A/B `dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261012-archive-recovery-0e798cc`，
     包含新签名 Snapshot manifest、历史归档 GAP 修复、
     有界恢复优化，**并发恢复选项默认 1**，
     未通过在线主从切换/跨容器自动温缓存故障验收。
   - 其余核心服务使用缓存的固定 GHCR sha 镜像。

## 新租户业务回归

从新库 `dc_tenant=0`、`dc_tenant_robot=0` 出发，
调用现有 `tests/run-auto-tenant-trading-e2e.py` 走真实网关服务 API：
ManagerSvr `tenantApplication` 自动审批 →
tenant liquidity bootstrap、Robot 自动入金和报价 →
公有盘口买卖各十档 → 注册交易员 → 入金 →
BTCUSDT Limit IOC 开仓成交 → MySQL 成交/持仓核对 →
Reduce-only 平仓 → 状态为零及 Robot 自动补齐四十笔活动委托。

首户 `HCQE6R` 和随后九户均在真实 HTTP API、Robot、
Trade A/B 和 MySQL Projection 下完整运行，**10/10 E2E 通过**：
`B5LS9L,G8Q69U,HCQE6R,IUWE6C,KA8K49,MTU9UC,RSE3WJ,RTBIXY,WCOYY6,YVFBBX`。
每户均在 40 笔 Robot 买卖挂单仍然有效时，用新的
交易员执行 BTCUSDT 0.0001 的开仓成交与 Reduce-Only
平仓，且逐户核对数据库中的实际成交记录与交易员仓位归零；
没有跳过写 API 直接将数据库改成成功。

日志保存在私有
`~/.opentradingcore/local-ha-clean-20261012-v1/tenant-first-auto-e2e.log`
和 `tenant-e2e-{2..10}.log`。
批量最终输出：
`TEN_TENANT_FULL_BUSINESS_RECREATION_ALL_PASS`。

再使用只读
`tests/check-demo-tenants-readonly.py`
审计独立验证 10/10 租户 `TRIAL/ACTIVE`、
Robot `RUNNING` 且 `open_order_count=40`、
每个租户买卖各10档、盘口无交叉；
`PASS_10_TENANT_SNAPSHOT`，共 **400 笔活动 Robot 委托**。
`dc_order_projection_watermark` 与
`dc_trade_projection_watermark` 均各有 10 个分区水位；
`dc_orders` 的业务验收用户订单 20 笔，
`dc_orders_execorders` 的对应成交 20 笔
（Robot Demo 委托通过服务内存维护，不能误以为
MySQL 只有20个订单就是 Robot 下单失败）。
证据：
`~/.opentradingcore/local-ha-clean-20261012-v1/tenants-fresh-10-all-readonly.json`。

严格 Order 256 分区只读核验：
`partitions=256 ready=256 epoch=1`，
128 个 Primary 在 Order A、128 个在 Order B；
Order C 有 256 个同步 Replica，
`snapshot_sets_equal=256`、无 Learner、
容器无 OOM、无重启。路由到达认证门禁；
由于无会话凭证，跳过需要认证的逐分区 HTTP 查询，
不能把这个检查说成全量下单路由测试。
证据：
`~/.opentradingcore/local-ha-clean-20261012-v1/order-256-strict-verify.log`。

## 10 户资源瓶颈与调参

首次只读 `check-tenant-ramp-readiness.py`：
10 个 Robot 全部健康、5 分钟 Market Trade 有 516 条，
但 `CPU_PSI_HIGH=41.25% (>25%)` 且 Robot
`0.2 CPU` 配额使用率 `101.55%`，
返回 `NOT_READY`。
Mac Docker VM 为 8 CPU、16GiB；
发现 ZooKeeper 只允许 `0.1 CPU`，
在其 `cpu.stat` 已观测的 14440 个调度周期中
有 13496 次节流，远超其他主服务。
即使提高 Robot CPU 到 0.75，CPU PSI 仍然高。

在**不重启任何容器**的前提下通过 `docker update`
并更新私有 0600 `fresh-release.env`：
- `TRADESVR_MEMORY_LIMIT=3072m`、
  `TRADESVR_CPU_LIMIT=2.00`（Trade A）；
  Trade B 保持 3584m/2 CPU；
- `ROBOTSVR_MEMORY_LIMIT=1024m`、
  `ROBOTSVR_CPU_LIMIT=0.75`；
- `ZOOKEEPER_CPU_LIMIT=0.75`、
  `GW_CPU_LIMIT=0.75`、
  `APSSVR_CPU_LIMIT=0.75`。

再次只读资源验收：
`gate=BASELINE_READY_ONLY`，`reasons=[]`，
CPU PSI 降至 **20.78%**（低于25%）；
Robot 配额使用率 **25.39%**；
10/10 租户仍然活跃，Order B
full GC 3 秒观察为0。
`nextRampAuthorized=false` 是工具明确返回的结果，
**这并非 50/100/200 租户负载测试授权或 TPS 保证**。
`marketRowsPerSecondNotOrderTPS=2.54667` 不能
冒充权威订单 TPS。
证据：
`~/.opentradingcore/local-ha-clean-20261012-v1/tenant-ramp-10-after-core-cpu-headroom.json`。

## 当前明确未完成

- 10 租户初始 E2E、单次综合审计和 CPU 基线已通过；
  **长时间运行稳定性和真实故障注入仍未完成**，持续审计仍需进行。
- 同机两节点 Trade 同步复制不能直接零停机滚动替换唯一
  Replica；新版本已通过冷部署安装，**但真实 Trade SIGKILL、
  反向角色切换、权威资产一致性仍未完成**。
- 本轮不启用 WAL 自动删除或 MD 自动主切；需要额外
  的 retention fence、Replica/Projection 持久水位校验。
- 不以 256 分区 READY 或全量单元测试取代 200 租户压测；
  先确保 10 户稳定、IO/CPU/内存满足门禁。
- MD-C 原有 `dff97ba` 的 epoch fence 优化在新的统一
  MD baseline 中还需补齐并独立验收，不应声称已发布。

旧数据仅隔离，**未彻底永久删除**，保留了出错回滚空间。
