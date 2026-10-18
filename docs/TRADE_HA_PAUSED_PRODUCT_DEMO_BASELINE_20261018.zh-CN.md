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
