# OpenTradingCore 统一协作与发布要求

## 页面与手册必须同版（强制）

以后修改主站、交易 Web、租户管理 Web、平台对客页面或 API Docs 的任何**用户可见功能、文案、交互、布局、权限、入口、移动端页面**，必须在同一批次：

1. 核对影响的用户手册章节，更新操作说明和实际功能名称；
2. 用 Playwright 在当前真实界面或隔离部署版本重拍受影响的 PC/手机、登录/匿名截图，严禁假截图、旧截图、密钥与密码；
3. 更新源文档和对应中文/英文 PDF（已发布双语的产品必须双语核对）；
4. 跑各 Web 仓库 `qa/check-user-manual-sync.py` 门禁及 PDF 视觉/页数检查；
5. 与 UI 源码一同提交并发布，检查公网 PDF MIME/链接/版本后才能报告页面交付完成。

**禁止先发布 UI、后补手册；缺少手册同步证据，发布与验收为未完成。**

完整规定：`docs/FRONTEND_USER_MANUAL_SYNC_POLICY.zh-CN.md`。交易、租户、主站和 API 文档仓库各自也有对应的 `AGENTS.md`。

Common/Order/Trade/MD 的 HA、资金、订单一致性必须独立验收，不能被手册/页面测试替代。

统一图文 PDF 一键生成：`./scripts/generate-user-manuals.sh`，详见 `docs/USER_MANUAL_ONE_CLICK_GENERATION.zh-CN.md`。

## Demo 快速修复与最新代码归档（2026-11-01，用户确认）

- **失败就优先全新部署**：Mac Demo 是开发验收环境，旧 WAL、Snapshot、残留分区、旧租户数据若阻碍修复与验证，不得反复纠缠。先明确失败根因并保存最小可核验日志与代码后，直接选全新独立部署命名空间、空数据目录和新安装，重新注册租户走自动审批、Robot 报价/Tape 点价、订单成交与 A/B 故障切换全链路。
- **不得复用旧 Epoch 证明**：重新部署可以丢弃 Demo 业务数据，但不可把旧 RSA 出生凭据、旧 Quorum/READY 或旧 WAL 假装为新数据。仍须通过 Common 的真实 ZooKeeper 会话、双物理签名、WAL/快照、状态认证及业务验收。
- **目标是系统持续向前**：优先修真正机制和业务问题，严格保持 Common 通用、Order/Trade 业务专注；反复失败时直接重建 Demo，而不是长期维护旧数据兼容性或引入新框架。运行镜像可以彻底替换，但先保留必要证据和可回退镜像。
- **最新源码统一归档**：在 `saas-crypto` 研发基础上，可将当前已验证的各仓库最新源码分别提交并推送至其 `saas-crypto-latest` 分支；主仓统一记录各仓库 SHA、Common JAR SHA、构建镜像及 GO/NO-GO。不能把 Docker 运行产物、私钥、密码、数据卷、巨型临时目录提交进 Git；不得使用 GitHub Actions，除非用户明确要求。
- **真实交付门禁**：镜像已构建/容器 UP 不代表新部署 PASS。必须核对实际自动审批、Robot 持续挂价、真实成交、MD 成交时间、Order/Trade A/B 自动切换和持久业务状态一致，结果未完成时如实标记 NO-GO。

## Common / Order / Trade 部署防回归门禁（T534，强制）

**每次新部署、新服务接 Common 或升级 Common，先阅读 [长期部署故障手册](docs/COMMON_ORDER_TRADE_DEPLOYMENT_RUNBOOK.zh-CN.md)**；不能仅看最近一轮 PASS 日志。

- 一律由 `generate-saas-configs.sh` 针对**真实目标模式**生成 Gateway / 业务配置：单机就单机，A/B 就生成完整 A/B。生成器自动执行 `tests/preflight_saas_cluster_config.py`，检查节点 A/B、RegType、Partition LB、ZK 注册地址和端口；失败立即停止部署。
- ZooKeeper 已经运行时，执行同一预检的 `--zk-container` 检查；Common 阶段配置存在时加 `--runtime-root` 检查 ZK、namespace 和节点端口。不允许把 `STANDBY` 单机发现目录误作 A/B 的 `ALL`。
- Order/Trade/Projection 等消费者必须锁定**相同、已审核的 Common JAR SHA256**；发布前执行 `tests/check-common-jar-consumer-parity.sh`。只替换 Order/Trade 而忽略 Projection 不算完整升级。
- APS 的 Colima host-network 执行 `tests/check-host-network-dns.sh`；DNS 通过不能代替外部 WebSocket 连接或真实行情收包，不得以 `subscribe active` 当成功报价。
- 恢复顺序：Birth → 原始业务 Snapshot/WAL/Ledger 安装 → 双 Home RSA → E2 CAS → 业务 READY → Gateway；旧临时租约等待自然撤销，禁止伪造认证、跳步或混用旧资金/Projection。
- **检查 PASS 只是部署预检**：真实租户审批、入金、订单成交、资金/持仓与 Projection、物理 ACK 和自动 A→B→A HA 必须独立证明。执行安全检查阻塞时保留 NO-GO，不能绕开。

## Common 升级连续性强制门禁（2026-11-06，T528）

**先选择唯一模式，不得混用：** `UPGRADE`（保留旧数据，实际滚动升级）或 `FRESH`（开发环境全新业务数据源）。部署脚本、验收记录必须显式写明模式。不得将 `T398` 旧 MySQL/Projection/Robot 水位与 `T523` 全新 Common WAL/Snapshot 当作同一个可恢复的业务状态。

- **UPGRADE：** 原 Order/Trade A/B 四份 WAL、Snapshot、业务状态、ZooKeeper 授权及对应的数据身份必须保持可验证的连续性；新节点 Common SHA 必须一致；先检查旧分区和新分区真实物理数据根是否对应。不允许静默换到新空卷又发布旧租户 Gateway READY；若更换物理路径，必须有独立的已认证数据迁移和恢复证明，不能强行改此门禁。
- **FRESH：** 新 ZooKeeper/数据根/业务状态、旧 Robot/旧 Projection/历史消费水位必须隔离；用新租户自动审批、新资金入账、Robot 和新 SQL 投影作全量验收。不能保留旧消费者不停从新 Common 的 seq=0 数据源读取历史 seq=数万的提交水位。旧业务数据只读保留或明确清理，禁止假装已经迁移。
- **读写分离的部署检查：** 执行 `python3 tests/check_common_upgrade_continuity.py --mode upgrade|fresh ...` 检查运行容器真实 JAR SHA、Gateway 发布、WAL/Snapshot 物理数据根及 Projection 卷身份。任何 `NO-GO` / exit 2 均停止**后续替换、旧节点停机和公开 READY 宣称**；该工具仅读取 Docker 配置，不改变持久数据、不能签发 RSA、不能替代真实业务 E2E。
- **先恢复交易，再单独验收 HA：** 已存在 Common/Demo HA 阻塞时可以报告“基础交易恢复验收”，但绝不能把容器启动或 Gateway 注册称为真实资金、成交或严格自动 HA PASS。资金冻结、业务 Replay、订单/成交/持仓/Projection 及真实签名 WAL 都要逐项可核验。
- **边界不变：** 这只是部署层防误切换检查，不在 Order/Trade 或 Common 额外实现 Watch、投票、第二套 WAL/恢复子系统；Common 不理解业务账户类型。

详见 [T528 升级连续性与现场审计](docs/T528_COMMON_UPGRADE_CONTINUITY_20261106.zh-CN.md)。

## 集群开发优先级（P0 强制门禁）

**2026-10-31 A/B 最终架构强制决定：** [Common A/B Home Primary 自动切回](docs/COMMON_AB_HOME_PRIMARY_AUTO_FAILBACK_ARCHITECTURE_20261031.zh-CN.md) 为最新版分区选主、回主和验收标准。默认 256 分区 A/B 各 128 主、128 备；A 故障 B 自动接管，A 追平后无人工干预地将其 128 主分区自动切回 A；B 同理。禁止把“重启后只能永远当备”误读为目标，也禁止把“重启立刻抢主”当自动切回。必须先追平、后升 Epoch/CAS 切回，保持所有安全证明及明确的单节点持久化合同。

**先 Demo+Common，再 Order/Trade，最后业务验收。**

- **P0**：仅在 Demo+Common 修复和验证全部通用集群机制；真实 A SIGKILL → B 自动 READY/继续写 → A 自动追平 → B SIGKILL → A 自动 READY/继续写 → B 自动追平，并检查旧主隔离、WAL/快照/水位/状态一致性；脚本手工切换、只到 RECOVERING 或仅容器 UP 均不算 PASS。
- **P1**：P0 通过才允许 Order/Trade 集成；与 Demo 使用相同 Common Jar SHA256、启动入口、常驻 Watch、复制/提交、降级写入和恢复机制，业务只提供自己的 byte[] 状态机及必要成员/路径配置。Order/Trade 禁止自建或各自修补 HA。
- **P2**：P1 通过后验证 Robot 报价/Tape 成交、资金持仓、MD 最近成交、SQL 投影和业务 A/B 自动互切。P0 不通过时 P1/P2 保持 NO-GO。

强制执行规范：`docs/COMMON_AB_HOME_PRIMARY_AUTO_FAILBACK_ARCHITECTURE_20261031.zh-CN.md`、`docs/ARCHITECTURE_SIMPLE_COMMON_BOUNDARY_20261029.zh-CN.md` 和 `docs/T266_DEMO_COMMON_ORDER_TRADE_PARITY_FIRST_20261029.zh-CN.md`。

## Common / Order / Trade 简洁集群架构（强制）

Before changing Common, OrderSvr, TradeSvr, MDSvr, deployment or HA, read:
`docs/ARCHITECTURE_SIMPLE_COMMON_BOUNDARY_20261029.zh-CN.md`.

Non-negotiable rules:
- Common is a business-opaque `byte[]` WAL/replication/snapshot/recovery/failover library. It MUST NOT branch on order types (GTC, IOC, FOK, PO, DAY, GFD) or domain balances, positions, executions, settings.
- Order/Trade own their state machines, validation, serialization, apply/replay/snapshot and financial correctness. All business state writes use one generic Common persistence path, not type-specific WAL or parallel cluster implementations.
- Keep the cluster **simple**. Do not add recovery workflows, certificates, second ledgers, specialized outboxes, business-specific gates, helper services or configuration toggles without an explicit necessity approved by the project owner.
- Preserve essential safety: an uncommitted WAL tail must not be acknowledged or replayed as committed; a former Primary must not write; no fabricated ACK/READY. Recovery should use existing committed high-water mark, WAL, and peer replication, automatically.
- ZooKeeper is control plane only; TCP one-way replication, minimal hot-path I/O; a healthy Primary should continue with clearly signaled local durability if a standby is down.
- Work directly on the Mac Demo and `saas-crypto` branches; avoid GitHub Actions unless requested; do not discard uncommitted user changes.
- Real acceptance: auto-approved tenant, Robot live quotes, real Tape trades, auto A/B failover, and exact business consistency. Do not claim PASS from tests or container UP alone.

## P0/P1 Common-only contract — 2026-10-29 (mandatory)

- Demo, Order and Trade MUST NOT implement cluster Watch, Epoch election, READY publication, replica networking, WAL recovery, failover orchestration, or separate cluster persistence. They only supply business validation, opaque `byte[]` encode/apply/replay/snapshot and call the SAME Common runtime APIs.
- Common MUST remain domain-opaque: no order-type/TIF (GTC, IOC, FOK, PostOnly), execution, balance, position, leverage, or funding-type filtering in signing, WAL, replay or replication. Signatures authenticate Common node/epoch/WAL/commit evidence, never authorize a particular business category.
- ALL business mutations (new/cancel/mass or batch cancel/replace, fills, balances, positions, settlements, settings) MUST pass through one Common durable commit path before external success. Removing a legacy type gate is forbidden unless its operation is actually connected to durable WAL + after-commit apply; otherwise fail closed. Domain legality checks remain solely in business services.
- P0: Demo+Common must demonstrate unattended production-runtime A→B→A SIGKILL, both former primaries rejoin online and catch up, with identical Common bootstrap/Watch/recovery/READY semantics and explicit local-vs-quorum durability. Only after proven P0 GO, P1 installs the exact same Common Jar SHA256/startup contract into Order/Trade. No bespoke Order/Trade HA fixes.
