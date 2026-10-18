# OpenTradingCore｜暂停 Trade HA，恢复产品 Demo 基线（2026-10-18）

**决策**：本阶段暂停 Common/Order/Trade/MD 故障注入、双向 SIGKILL、200 租户压测以及 HA 机制扩展。开发优先级切换到主站、租户自助注册、交易终端、API/SDK、Robot、资金和交易功能。此文档是产品移交和 HA 未完成项的冻结记录；**不得把容器 Up、ZK READY、旧 ACK 视为 HA 验收成功**。

## 1. HA 已达到的事实

- Common、Trade 的 Snapshot、Chronicle WAL、脏尾 hash 封存、持久恢复 Ledger、签名 Source HEAD/Replica 物理回执已在修复分支实现并做过单测。Common 曾完成 334/334，全量 Trade 曾完成 435/435，后续 Trade 改动又提交了 `dcbf10c`、`2a043ac` 等。这些单测不能替代实机负载 failover 验收。
- P022/P184 原有单条未提交 STATE_BATCH 的恢复曾通过封存、签名提交边界验证并进入 READY。P022、P184 在恢复后都曾得到当前 Epoch 的非零物理副本 ACK。Robot 在两节点运行时曾把 P022 的 replicatedSeq 从 81958 推进到 82038。
- Trade-A 故障后，控制面确实把原属于 A 的 256 个分区自动切给 B（Epoch 升级，B 显示主分区 READY）。但之后恢复副本仍无法稳定完成当前 Epoch 物理审计和健康 CAS；2026-10-18 14:05 的实机扫描只有 **7/256** 当前角色/Epoch/水位一致的健康证明。
- 曾发生另一个会话对 Trade-A 的 SIGKILL 与本会话对 Trade-B 的 SIGKILL 时间重叠，造成双节点一起退出。这**不属于**成功的双向单故障自动切换验收。容器后来原地重新启动，未把双停后数据一致性审计判为通过。

## 2. 保留给后续 HA 开发的缺口

1. **独立证据问题**：跨 Epoch Recipient 的 `REPLAY_COMPLETE` Ledger、不可变 WAL tail/快照 seal、当前物理安装和 Current Epoch 的签名 ACK 不总能收敛；存在 `unverified physical cross-epoch install`、`TRADE_REPLICA_AUTO_STAGE_SIGNED_NOT_READY`。
2. **角色/健康原子性问题**：自动晋升后可出现 Assignment 已切新 Epoch、replication-health 仍是旧 Epoch；真实 Primary Ready 与控制面健康证明有短时或持续不一致。需要失效/重新证明的严格状态机，不得直接把旧 ACK 改新 Epoch。
3. **重放效率问题**：256 分区的 bounded fleet 恢复扫描与物理收据观察速度差距大；必须在真实负载下检查水位收敛、磁盘/IO、ZooKeeper CAS、GC 以及热 WAL 追平。
4. **故障注入门禁**：只有当前 Epoch、真实业务、双方独立物理提交回执、无 degraded、无进行中恢复事务才允许下一次单节点 SIGKILL。故障执行器应使用独占锁，避免并发双杀。
5. **权威一致性未过**：恢复前后资金、持仓、活动/历史委托、成交唯一性、Projection watermark、Trade 状态的跨服务对账没有形成可重复通过的签名证据。Order/MD 的完整 HA 和 50/200 租户长稳压测也未最终验收。

相关代码：`bliplink/com.app.common` 的 `fix/common-trade-ab-integrate-20261018`（包括 `68e37d3`）；`bliplink/com.app.dc.tradesvr` 的 `fix/trade-ab-integrate-20261018`（包括 `c6c6b4a`、`dcbf10c`、`2a043ac`）。后续合并前需要与 `saas-crypto` 同步、严格审核差异。**GitHub Actions 额度不足期间继续本地构建，提交使用 `[skip ci]`。**

## 3. 产品 Demo 干净重建（2026-10-18）

- 运行目录：`/Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016`；新建的数据目录为其中的 `data/`。
- **旧数据未删除**，整体隔离在 `data-product-pre-reset-20261018-141302/`，可作为问题调查资料，但不应混入新 Demo。前期 HA 日志、容器镜像清单和脚本结果保存在 `/Users/kong/.opentradingcore/product-baseline-reset-20261018/evidence/`。
- 使用已有固定 ARM64/local+GHCR 镜像离线 `docker compose` 部署，基础 Compose 为 `compose.yaml` + `/Users/kong/.opentradingcore/ha-fresh-clean-compose-images-20261016.yaml`，私有 env 文件为 `/Users/kong/.opentradingcore/ha-fresh-clean-demo-20261016.env`；不用 GitHub Actions、不修改 Web 镜像源码。
- 已新建 MySQL8.0.36 数据，**28 个** `mysql/migrations/*.sql` 执行成功；ZooKeeper 残留 `/datalog` 事务文件先被隔离后成功重启，重新创建 Order、Trade、MD 各 256 个分区初始分配；ClickHouse 健康。
- 显式重新创建默认 Compose 遗漏的 profile 服务（Order-B/C、Trade-B、MD-B/C、Projection），避免旧容器读取隔离前的业务数据；随后共有 **24 个** `dc-saas-*` 容器运行。
- 镜像策略回到 2026-10-16 的固定业务版本：Trade A/B=`dc-saas/tradesvr:full-src-ha-20261016`，Order/MD/Gateway=`cluster-dev-fenced-transport-20261016`，Web/管理/UI 固定原有镜像。这是**产品回归候选环境**，不是 HA 认证发布。
- 本地 `http://127.0.0.1:18088/`、租户页 `http://127.0.0.1:18092/`、外部 `https://opentradingcore.com` 和 `https://trade.opentradingcore.com` 在复查时均 HTTP 200。主站此前有偶发网络连接重置，持续可用性没有完成长稳观测。

## 4. 业务 E2E 实际结果与阻塞

- `tests/run-tenant-lifecycle-e2e-host.sh` 的**两个独立 30 天试用租户申请**提交成功：`AAE5A1`、`BAE5A1`，当前申请状态 `PENDING`。
- 新库目前 **0 个审批通过租户、0 个 PLATFORM 管理用户**。官方初始化阶段理应执行 `deploy-saas.sh` 内的 `provision_platform_admin` 与 `provision_robot_runtime_identity`，但本次执行环境对写入身份凭证的操作触发安全检查阻断，故没有绕过或伪造注册/审批。
- E2E 在平台管理员登录处实际失败：`USER_ACCOUNT_OR_PWD_ERROR`（代码 9005），故**自动审批、租户登录、入金、下单、撤单、撮合、Robot RUNNING、Tape、API Key、成交/持仓/资金分页、手机端功能**本轮尚未完成验收。
- `httpapi/` 能够通过 Nginx 到达 Gateway 并返回协议 JSON（错误方法返回业务代码 1003），不能以此替代真实业务接口 PASS。

## 5. 以后恢复工作时的验收顺序

**先产品**：按正式授权的部署流程完成平台/Robot 身份初始化 → 审批两笔 PENDING 申请或重新提交 → 注册交易员 → 登录交易 Web → 资金/持仓 → Limit/Cancel/Match → Robot/Tape 有盘口有成交 → API Key/Python SDK/WebSocket → Admin/手机端 UI 与分页对账。每一步记录独立 PASS/FAIL，不必为产品开发进行 SIGKILL。

**后 HA**：锁定版本、构建本地镜像 → 单/双节点 E1 初始化和健康物理证书 → 10 租户带单带持仓非零负载 → 故障执行器独占注入 → A 死 B 自动接管并追平 → B 死 A 自动接管并追平 → 256 分区和最终账务强一致 → 50/200 租户长稳和 burst。任何旧健康或未完成安装均阻断继续故障注入。

## 6. 交接约束

此文档只冻结当前现场，不宣布 HA 成功，也不宣布本轮产品 E2E 成功。**后续产品迭代以新 Demo 数据为准；不扩 HA 新功能，除非另行明确恢复 HA 验收。** 所有密码、API Key、RSA 私钥都留在本机受保护的 env/配置中，本文不收录凭证。

## 7. 重建后发现并行 HA 会话仍在改动 Trade（重要）

2026-10-18 14:25 左右，本会话发现原本重新部署的 `dc-saas/tradesvr:full-src-ha-20261016` Trade A/B 已被**另一执行流程**替换为 `local/dc-saas-tradesvr:trade438-carriedepoch-2a043ac-20261018`。两个容器当时重新开始运行。此变更不是本产品基线重建所执行，表明同时存在多个能操作 Mac/Docker 的任务。

这使本轮 Demo 的 Trade 镜像版本不再保持冻结，也会使故障注入或数据库初始化与其他会话冲突。**移交产品开发前必须终止/协调其他 HA 任务、确认唯一部署操作者，并重新确认最终镜像与服务状态。** 不允许多个会话独立做 `docker kill`、`docker compose up --force-recreate`、删数据或改 ZooKeeper 健康状态。

本轮停止继续修改 Trade 容器，避免进一步覆盖并行会话。最终认定：**基础设施已干净重建、28 项 SQL 迁移成功、双租户申请为 PENDING，但产品完整 E2E 未完成；不能对外宣布可交易 Demo 已验收。**


## 8. 2026-10-18 产品联调增量核查

- GitHub `saas-crypto` 通过 GitHub API 合入干净 Demo 交接记录、`20261017_tenant_numeric_user_ids.sql` 及经静态检查的 E2E 工具；由于 Mac 本地工作树比远程旧且分叉明显，不使用强推覆盖远程。
- 通过真实 `ManagerSvr.tenantApplication` 接口提交独立产品测试租户 **`P43510`**，服务返回业务 `code=0`、申请编号 `5c5700d4603644d9a99a3161d8ddc748`。此结果只证明申请受理，不代表审批、交易已正常。
- 新 Demo `dc_users` 在 `PLATFORM` 范围仍无管理员；本轮新申请 `P43510` 以及先前的 `AAE5A1`、`BAE5A1` 均为 `PENDING`。既有 H00000/H00001/H00002 为 ACTIVE，但 `registration_enabled=0`，对应 Robot 处于 STOPPED，不能据此宣布自动审批、Robot 挂价或撮合验收通过。
- 平台管理员在正式部署流程中应由 `deploy-saas.sh` 的 `provision_platform_admin` 创建；Mac 当前 sudo 非交互不可用，且之前直接身份写入操作遭安全检查阻断。本轮没有绕过授权控制。后续需要由有权限的部署执行环境完成平台管理员/Robot 身份正式初始化，随后才可审批 `P43510` 并继续注册/登录/入金/委托/成交/资金对账。
- **HA 继续暂停**；多个会话不得同时替换 Trade 容器或注入故障。此次提交仅补齐代码/迁移/验收脚本，不宣称已完成产品业务链路验收。


## 9. 产品验收准则纠正：注册必须自动审批、自动 Robot/Tape（2026-10-18）

**预期产品行为**：用户自助提交有效租户申请时直接自动审核通过、初始化管理账号/交易品种、创建试用流动性任务；AdminSvr 异步创建 Maker/Tape 交易员、API Key、Demo 资金、Robot 自动启用；RobotSvr 开始实际双边挂价和 Tape 点价成交。**无需平台管理员手工审核**，也不能将申请 `PENDING` 视为正常完成。

实机源码核对 `TenantApplicationService.submit()`：目前自动审批仅在申请包含 `admin_password`、申请品种 1～4 个且均有效、平台活跃租户少于 200 时触发。之前的 `P43510`、`AAE5A1`、`BAE5A1` 测试请求**遗漏 `admin_password`**，因此不满足自动审批门禁；不应以此推断产品设计要求人工审核。`TrialLiquidityBootstrapWorker` 的 bootstrap/Tape 环境开关在当前 AdminSvr 容器均为 true，`VERIFY` 阶段要求真实 Robot `RUNNING`、盘口至少 2 笔活动挂单才会将任务写为 `COMPLETE:DONE`。

**当前独立第二阻塞**：当前新 Demo `PLATFORM` 管理账号尚未初始化，RobotSvr 反复报告 `RobotSvr gateway login failed: USER_ACCOUNT_OR_PWD_ERROR (9005)`；即使租户审批成功，也不能据此认定 Robot 已开始真正双边挂价或 Tape 成交。正式部署路径应调用 `deploy-saas.sh` 的平台管理员与 Robot 运行身份初始化并让 LoginSvr 刷新认证缓存；禁止手改数据库伪造运行状态。

新增正式端到端探针 `tests/run-auto-tenant-liquidity-e2e-host.sh`：必须在安全来源提供 `E2E_AUTO_TENANT_ADMIN_PASSWORD`，通过公开 `tenantApplication/SUBMIT` 发完整注册申请，不使用平台审批接口；检查 `APPROVED`、试用租户开通、bootstrap `COMPLETE:DONE`、Tape 开启且资金确认、Robot `RUNNING` 并具有双边挂单。探针静态语法检查已通过，但由于 Mac 现有平台身份缺失和执行安全检查阻断，**尚未完成真实整链验收**。Tape 的实际逐笔成交/成交量仍需独立验证，不能只凭 `tape_enabled=1` 认定通过。


## 10. 2026-10-18 15:15 CST｜真实自动审批成功，Robot 启动链未通过

- 本轮通过**真实公开注册接口**（带 `admin_password` 和 `BTCUSDT`）完成新租户申请。后台自动分配正式六位 `location`：**`GW7XMI`**。数据库 `dc_tenant_application` 显示 `APPROVED`、`reviewer_id=AUTO_APPROVAL`，`dc_tenant` 为 `TRIAL`、`registration_enabled=1`、`trade_enabled=1`。**这证明自动审批无需平台管理员介入，纠正了之前只传缺失密码的 `PENDING` 请求导致的误判。**
- `TrialLiquidityBootstrapWorker` 按 `CREATE_MAKER` → `CREATE_KEY` → `FUND` → `FUND_TAPE` → `CREATE_ROBOT` → `ENABLE` 逐步执行。`GW7XMI` 的 `funding_confirmed=1`、`tape_enabled=1`、`tape_funding_confirmed=1`，`dc_tenant_robot` 已有 `trial-liquidity-BTCUSDT` 且 `enabled=1`。
- **实际 Robot 未启动**：`runtime_status=STOPPED`、`open_order_count=0`；初始化任务停在 `RETRY:VERIFY`，反复 `IllegalStateException`。RobotSvr 定期日志明确 `RobotSvr gateway login failed: USER_ACCOUNT_OR_PWD_ERROR`。新 Demo `dc_users WHERE location='PLATFORM'` 的有效账号数 **0**，`dc_users_api` 的启用 `ROBOT_RUNTIME` Key 数 **0**；AdminSvr `TRIAL_LIQUIDITY_BOOTSTRAP_ENABLED=true`、`TRIAL_LIQUIDITY_TAPE_ENABLED=true`。因此真正根因是初始平台/Robot 运行身份未按正式部署流程创建，而不是 Robot/Tape 功能开关关闭，也不是租户必须人工审批。
- 已补充 `tests/preflight-product-tenant-robot-host.sh`：只读断言平台身份、Robot Runtime Key、自动流动性与 Tape 开关。**当前实机执行如预期失败**：`platform_active=0 robot_runtime_keys=0 liquidity_worker_enabled=true tape_enabled=true`，退出码 2。
- 已修复 `tests/run-auto-tenant-liquidity-e2e-host.sh` 的定位错误：真实审批会分配新六位 location，不能按提交时暂定的 `tenant_code` 找批准结果；改用不可变 32 位 `application_id` 查询并校验返回 location、任务 `COMPLETE:DONE:1:1`、Robot `RUNNING` 且盘口至少两笔。该脚本语法检查通过。此前测试脚本曾因为错误查询短暂报失败，**实机自动审批实际成功**；工作流的终态仍未通过，因为 Robot 登录没有恢复。
- 未手工修改 ZooKeeper ACK、未操作 Trade A/B 故障注入、未伪造 Robot/RUNNING、未对产品 Demo 宣布撮合或点价已通过。后续只需运行**正式授权的** `deploy-saas.sh` 里 `provision_platform_admin` 与 `provision_robot_runtime_identity` 并刷新 LoginSvr API Key 缓存，然后观察 `GW7XMI` 的已有 `RETRY:VERIFY` Job 是否自动完成、盘口/成交是否有增量。之前环境执行对直接写身份/密钥操作曾被安全检查阻断；不可绕过。


## 11. 2026-10-18 15:30 CST｜AdminSvr 自动恢复 FAILED:VERIFY 已上线实机验证

- `GW7XMI` 的真实租户申请经 `AUTO_APPROVAL` 审批成功，状态 `TRIAL`，注册及交易启用；Maker 和 Tape 模拟入金确认均为 1，`trial-liquidity-BTCUSDT` 已配置 enabled=1，但 RobotSvr 因平台身份缺失无法 Gateway 登录（`USER_ACCOUNT_OR_PWD_ERROR 9005`），导致 Robot `STOPPED`、盘口 0。
- 旧 AdminSvr 的 `TrialLiquidityBootstrapWorker` 对 `VERIFY` 仅重试 30 次，就把健康验证任务永久标为 `FAILED`；即使后续恢复 Robot，也不会自行继续。
- 已在 **`bliplink/com.app.dc.adminsvr@saas-crypto`** 更新 Worker 和测试（提交 `d4105a33`、`46698459`）：只允许当前仍为有效 `TRIAL` 且 `AUTO_APPROVAL` 的 `FAILED:VERIFY` 工作被定期重新认领；已完成资金步骤不会重新入金或重新运行。VERIFY 在达到 30 次重试后采用 300 秒低频探测；其他资金及初始化步骤仍遵守既有失败上限。代码经过 AdminSvr 离线 `mvn test` **88 项（0 fail,0 error,1 skipped）**。
- 实际已通过离线 Docker 构建 `local/dc-saas-adminsvr:trial-verify-recovery-20261018`，镜像 `sha256:3b8fb7be4c7349b1e52ef2355cb7844f02cb64fb56e2bae05f9ee1caf01a5449`，**只滚动替换 AdminSvr**；其他业务服务未重启。升级后新 AdminSvr 实际重新认领 `GW7XMI` 的 `FAILED:VERIFY`，尝试次数由 30 → 31，下次尝试时刻 `2026-10-18 15:34:34.204`。这是 `FAILED` 的安全再检查**确已执行**的证据，并非编造 `COMPLETE`。
- **最终业务状态仍 FAIL**：因为 `PLATFORM` 用户数 0、有效 `ROBOT_RUNTIME` Key 数 0，Robot 仍 `STOPPED`、盘口 0、Tape 没有真实点价成交。部署的正式初始化环节 `provision_platform_admin`/`provision_robot_runtime_identity` 需要被有权限的执行环境完成，并刷新 LoginSvr 的 Runtime API Key 缓存；不能用直改认证表、假 ACK、强行标记机器人 RUNNING 代替。`tests/preflight-product-tenant-robot-host.sh` 已作为产品上线前置门禁提交到 `saas-crypto`。
- 重建后主站与交易站实测 HTTP 200，但尚未完成长稳观测。**HA 工作仍冻结，不进行故障注入。**


## 12. 2026-10-18 16:53 CST｜正式身份初始化仍被工具阻断，产品注册前置门禁上线

- Mac 当前身份前置检查：`platform_active=0`、`robot_runtime_keys=0`，AdminSvr 自动流动性与 Tape 开关均为 `true`；`GW7XMI` 仍是 `TRIAL`、Maker/Tape 入金已确认、Robot `STOPPED`、挂单数 0，AdminSvr 每 300 秒只重试 `FAILED:VERIFY`，本轮已达第 47 次，**没有再执行资金步骤**。
- 曾尝试**原样使用官方部署脚本 `deploy-saas.sh` 定义的 `provision_platform_admin` 和 `provision_robot_runtime_identity`**，不直接修改认证数据；正式身份写入操作仍被执行环境安全检查阻断。后续必须由具备操作权限的受信任执行环境完成部署初始化；不应绕过这层检查或直接假写健康状态。
- 新提交 `dc-quant-deploy/saas-crypto@82f6eab`：`tests/run-auto-tenant-liquidity-e2e-host.sh` 在向公开注册 API 提交前先运行 `preflight-product-tenant-robot-host.sh`。实机执行返回 2，且本轮测试前后申请总数均保持 4，不再生成无法最终启动 Robot 的孤儿申请。
- 当前 AdminSvr 产品镜像 `local/dc-saas-adminsvr:trial-verify-recovery-20261018` 的 `FAILED:VERIFY` 低频重试已真实生效；GitHub AdminSvr `saas-crypto@46698459` 包含相关单元测试。主站最近测试 HTTP 200，**业务最终验收仍 FAIL：Robot Gateway 登录 9005，没有双边挂价、Tape 实际成交或交易业务闭环**。Trade HA 故障注入继续暂停。
