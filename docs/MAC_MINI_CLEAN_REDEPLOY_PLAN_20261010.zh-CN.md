# Mac mini：保留 P246 故障证据后的干净重建计划（2026-10-10）

**状态：镜像及完整配置已验证；尚未运行数据清理、停机或新容器部署。** 仅适用于用户明确授权可丢弃业务 Demo 数据的环境。实际执行必须使用经测试的 Mac/Colima 安装器，不能绕过服务器版脚本的安全检查。

## 现网与风险

- 现网共有 17 个租户（检查时的 MySQL 只读计数）；用户明确说明数据不重要、允许必要时清空重部署。清空会导致原账户、Robot、交易记录与演示状态失效，必须重新注册、初始化及验收，不可静默当作在线升级。
- OrderSvr A/B/C 仍运行 `ghcr.io/bliplink/ordersvr:sha-26b01eb`，P246 持续恢复失败；ZooKeeper 的 256 个分区全部标记 READY，但 3 节点快照只有 P246 不一致。即使重置，仍必须有真实故障恢复测试，不能将全新空库成功当作已修复 P246。
- 主数据根目录：`/Users/kong/.opentradingcore/dc-saas-runtime-fresh2-20261005`；系统盘检查时约 92% 已用、可用约 37 GiB。Docker VM 约 8 CPU、15 GiB 内存，不适合与现网**并行运行另一套完整** 22 服务集群。
- 线上运行的 Compose 来源标签指向旧 Worktree `/Users/kong/.webcodex-managed-worktrees/dc-quant-deploy-9ce2c171/compose.yaml`，并非当前 `/Users/kong/dc-quant-deploy/compose.yaml`。当前 `.env.prod` 内 `DEPLOY_ROOT=/data/dc-saas-runtime`、`ORDER_CLUSTER_C_ENABLED=false`，与现网 Mac 目录及正在运行的 C 节点不符。
- 服务器 `deploy-saas.sh` 限定 Linux `/data` 或 `/opt` 运行根目录、root/sudo、Linux 系统调用；Mac 当前 `sudo -n` 不可用。因此**不能为了省事调用 Linux 版 reset、修改其根目录允许列表，或直接用基础 compose up 覆盖现有站点**。

## 已保存的不可替代证据

P246 原始 Primary archive（含 seq 578109/578110）及 A/B/C P246 快照的压缩样本已保留在 Mac 私有目录（权限 0700）：

`/Users/kong/.opentradingcore/evidence/p246-reproducer-20261010/P246-primary-archived-commit.tar.gz`

- SHA-256：`41ccc17752734ed3731764de9c0ca4135452c7903e95dd47e6bf7db0ae79a707`
- 压缩大小：约 44 MB；配套三节点 P246 baseline 属性文件同目录保存（权限 0600）。这是故障复现材料，不是完整 MySQL 交易数据备份，也不是全局一致性快照；不包含当前活动副本日志的完整冻结副本。若要验证旧 WAL 恢复，使用隔离运行时加载这些材料，不要原位覆盖现网。

## 已完成的全栈 Compose 静态验证

使用 `.env.prod` 的私有副本，只修改新运行根目录及集群配置，在基础 compose 之上显式启用 Profile：

`COMPOSE_PROFILES=order-cluster,order-cluster-c,md-cluster,md-cluster-c,trade-cluster`

配置解析返回 **22 个服务**，其中必需的 Order A/B/C、MD A/B/C、Trade A/B、Projection、Robot、MySQL 和 ZooKeeper 全部存在。三个 Order 节点统一引用 GitHub Actions 新构建的不可变 GHCR 镜像，且共享新 Mac 路径 `/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261010/data`。

私有候选 env：`/Users/kong/.opentradingcore/evidence/p246-reproducer-20261010/.env.mac-clean-candidate`（0600，包含部署凭据；**严禁上传至 GitHub、复制到用户下载链接或写入日志**）。此文件是静态配置样本，不是可以直接执行的发布许可。新镜像需要 CI PASS 和 `linux/arm64` manifest 可用。

## 真正执行 clean redeploy 之前的硬条件

1. **业务边界**：通知演示站点会短时中断；停止外部订单写入、Robot、定时任务和重试队列，取得所有容器状态与进程清单。不要使用修改 ZooKeeper READY、关闭 SYNC_PER_RECORD 或强制 WAL 删除来“快速”完成。
2. **镜像与配置**：所有镜像固定 GHCR 不可变 SHA，架构匹配 ARM64；正确传入完整 5 个 Profile。Mac/Colima 运行目录必须是实际可挂载的绝对路径。平台/Robot 登录身份、tenant bootstrap、GW 分区路由及迁移必须在重建启动程序中明确定义。
3. **停机备份**：先关闭网关写入，按依赖关系停 Robot、Trade、Order、Projection、基础设施；检查所有 `dc-saas-` 容器停止且源数据不再被进程引用。保留 P246 样本和旧版镜像。不要清理代码仓库、`common` Maven 包、X/GitHub/Cloudflare 凭据和当前 `.env.prod`。
4. **清理边界**：仅删除当前 SaaS Demo 运行数据根下已明确列出的容器业务数据与匹配的 ZooKeeper `datalog`、ClickHouse 数据。禁止遍历用户主目录、其它 Docker 项目、Cloudflare Tunnel 状态。不得在用户级权限不足时借由 Docker root 私自绕过原有 root/路径保护。
5. **启动与恢复**：必须一次性拉起完整 A/B/C 拓扑及 DB/ZK，用 migration/bootstrap 初始化平台管理员、租户自动审批、Robot 身份；确认所有浏览器入口、API Docs、Trade Web 对外可用，且三副本一致性验证通过。
6. **业务验收**：注册真实隔离租户 → Robot 盘口/主动点价 → Trader API Key 余额/下单/撤单 → Broker 代客权限 → Order HA SIGKILL（在专用隔离验证环境）→ Trade HA → MySQL/Projection 的订单执行、持仓、资金、历史水位一致。逐批扩容 10、25、50、100、200 租户，按资源门禁决定是否继续。
7. **日志容量**：按归档清单和独立备份水位进行安全 GC；只有跨副本 committed proof + Projection durable watermark + 可恢复的远端备份均满足，才允许删除 WAL。空库重启本身不会实现此机制。

**当前决策：** 已具备新版代码、完整 Compose 静态配置和 P246 证据，但尚缺 Mac 原生 root-guarded 安装/清理执行流程、集群全量停写，以及内存/磁盘容量门禁。故现在不直接停止在线 Demo。该缺口不能通过擅自解除保护解决；需要继续实现并验证 Mac 的受控重建执行器后才能实际应用。

## 2026-10-10 验收结论：Mac mini 冷重建成功，旧数据已回收

Mac mini + Colima **真实执行**了以下步骤（不是仅静态验证）：

1. 使用 `deploy-saas-macos.sh reset --mode stage --confirm STAGE_DISPOSABLE_DC_SAAS`，成功停止并移除 24 个旧 `dc-saas` Compose 容器与经镜像/挂载验证的浏览器测试 Runner，把约 120 GB 逻辑大小的旧环境移动至私有隔离区；P246 WAL 和 A/B/C 快照先独立打包，SHA-256 固定为 `41ccc17752734ed3731764de9c0ca4135452c7903e95dd47e6bf7db0ae79a707`。
2. 使用**独立私有环境文件**、新根目录 `~/.opentradingcore/dc-saas-runtime-clean-20261010` 和完整五组 Compose Profile 执行 `deploy-saas-macos.sh --full-cluster --skip-pull`；全部 19 个镜像引用事先缓存。首次流程因独立 API Docs 容器名称冲突失败，已将旧 Docs 改名后保留为停止的回滚容器，并将 Compose Docs pin 到已上线的 `sha-ca814ce...`。随后幂等续装 **成功（exit 0）**。
3. 安装器完成 MySQL 迁移及 Robot 专用身份初始化；**24 个预期容器全部运行**、MySQL **53 张表**、Order **256/256 READY**、Trade **256/256 READY**、GW `TradeSvr/TDSvr` 路由在线。OrderSvr A/B/C 使用 `sha-7842df4`，Trade A/B 使用 `sha-e5cebdd...`，Robot 使用 `sha-5941ee...`，Docs 使用 `sha-ca814ce...`。
4. 新环境验证 18088、18090、18092、18094 四个 HTTP 入口全部 **200**，清理后最近 2 分钟 P246 恢复失败日志 **0**。**新环境 MySQL 租户数 0、Robot 记录数 0**；实际申请租户、Robot 自动报价、Trader/Broker API Key、Order/Trade 故障注入和 200 租户压力验收 **尚未通过，不应误报为成功**。
5. 旧隔离运行目录已经通过 `deploy-saas-macos.sh purge --mode execute --confirm PURGE_ONLY_QUARANTINED_OLD_DC_SAAS` **永久清理**，GitHub Actions [38033344146](https://github.com/bliplink/dc-quant-deploy/actions/runs/38033344146) SUCCESS，工具的全部范围/镜像/健康/挂载/证据检查通过。清理后宿主机磁盘由约 **93% / 31 GiB 可用**改为 **87% / 60 GiB 可用**，实际释放约 **29 GiB**。逻辑文件大小不等于实际分配块/可回收空间。旧环境的完整数据回滚已不可用，但独立 P246 证据和源代码仍保留。

**剩余发布门槛：** Broker E2E 的镜像审核闸门拒绝了新 RobotSvr (`BLOCKED_UNREVIEWED_BROKER_RUNNER`)，因此没有创建测试租户或绕过保护签名下单。后续须完成正式镜像代码及不可变摘要审核，或通过经过审核的 Runner 正常进行代客交易验收，不能为了报告通过而绕过控制。OrderSvr 的基础写入排空尚不是完整跨节点分布式维护协议；自动 WAL GC 仍缺 Replica/Projection 提交水位与远端恢复证明，本次冷重置不等于上述机制均已完成。
