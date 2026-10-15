# OpenTradingCore 集群最终统一验收任务书（持续执行，优先级最高）

> 用户确认：2026-10-15。分支：各仓库 `saas-crypto`。统一验收对象：`Common / OrderSvr / TradeSvr / MDSvr`，加上真正交易链路的 Robot、Projection、Gateway 路由及业务对账。
>
> **这是当前执行任务书，不是新功能规划。直到整个 HA 方案真实验收完毕，不得改为反复编写设计、补宽泛新功能或只做空转预检。** 这里记录的是每轮可接续的工作目标；已通过的测试保留证据，镜像/环境改变后应进行必要回归，但不要无目的地重复同样检查。

## 一、用户不可偏离的目标和授权

1. **唯一目标：完成本轮 Common / Order / Trade / MD 整套集群实际验收。** 集中解决失败项；只做与验收失败直接相关的最小源码修复。不要扩大 Broker API、产品 Web、SDK 或其它功能开发。
2. **完整闭环，不要反复停在准备阶段：发现问题 → 快速定位根因 → 修复公共或服务代码 → 提交 `saas-crypto` → Mac 本地编译统一镜像 → 替换 Demo → 直接做真实故障/恢复验证 → 权威对账 → 决定 PASS/FAIL/BLOCKED。** 没有必要时，不重复搭建或重复执行已通过的静态测试。
3. **Demo 数据不重要。** 为推进机制验收，必要时可以清理、重新部署和重新注册租户；清理前仅检查操作对象是隔离 Demo 数据卷、保留源码和所需证据，并避免误删宿主机其它数据。不要为了兼容旧数据而无限追加迁移/恢复机制。真实节点切换仍必须先完成防双主、授权和提交边界防护；**清理数据不能绕过安全门禁**。
4. **本轮直接使用 Mac mini 本地编译/镜像/Compose 测试。** GitHub Actions 当前因费用问题暂不处理；不依赖 GHCR 构建来阻塞本地验收。Common 与 com.app.dc 和各服务必须对齐实际加载的 JAR SHA，源代码修复必须提交到对应仓库 `saas-crypto`。不要让本地修复只留在临时 worktree。
5. **架构不可改变：** Order、Trade 共用 Common 的状态机和恢复机制，业务各自实现 `apply(byte[])`、`snapshot(byte[])` 等适配；MD 的恢复机制也统一沉淀 Common 可复用接口，MD 行情来源是 Order 的完整 Image + 后续 Diff，不要求 MD-to-MD 复制业务 WAL。Gateway 保持透传，不因恢复改动 Gateway；不要求 TLS。
6. **风险原则：** 目标必须验证真实继续交易、无丢单、无重复成交、无双主；未满足旧发布者隔离、源 HEAD/提交 ACK、候选应用状态等证明前，不得把危险 Primary SIGKILL 写成 PASS。不能把 Learner 重启等同于 Primary HA。任何 BLOCKED 都必须给出明确的下一次实作修复/验收动作，而非长期停在文档研究。

## 二、统一最终验收矩阵（以证据而非日志口号判定）

| 顺序 | 验收项目 | PASS 必须满足 |
| --- | --- | --- |
| A | Fresh/Clean Demo、镜像版本、业务 Smoke | 本地编译并部署的 Common/Order/Trade/MD 镜像依赖一致，ZooKeeper/DB/Projection/Robot 正常；真实注册、登录、入金、下单、撤单、撮合、平仓成功。 |
| B | Common 状态机 Snapshot + WAL + Diff | Order/Trade 按同一 Common 恢复契约正确安装 Image、续传完整原始 WAL、提交标记/哈希/日志边界核对，重启中断必须 fail-closed。 |
| C | Order 稳态与真实 HA | 256 分区分配与完整业务快照一致；真实下单/撤单/撮合过程中 SIGKILL 当前 Order Primary，合法自动 promotion，业务恢复；故障节点归来追平为 Replica；再次主备角色互换，验证无双主、无丢单、无重复成交。 |
| D | Trade 持仓主切 | 有真实余额、持仓、委托、成交时 SIGKILL Trade Primary；先证明真实副本 WAL 已到已提交 HEAD、必要 ACK 和可信隔离，再 promotion + 持仓状态恢复；恢复节点追平；与 Order/Projection/DB 权威账本对齐。 |
| E | MD 主切 | MD 从 Order 获取各分区全部市场 Image + Diff；候选节点实际应用全量且无序号空洞；旧发布者隔离和新 Epoch CAS/fence；真实 MD Primary SIGKILL 后盘口/实时成交/Robot 持续正常。**仅 MD-C Learner SIGKILL 成功不等于本项通过。** |
| F | 全链路权威一致性 | MySQL orders/executions/balances/positions/open orders、Order+Trade WAL committed HEAD、Projection watermark/事件、Trade 内存状态及 MD 可见盘口对应相同已提交业务边界，0 不明订单、0 重复成交、0 双主。 |
| G | 自动归档、定时快照、WAL 归档删除 | Order/Trade 正确生成快照、归档、安全清理；按日期建议保留 2 天，仅在接收端/副本/Projection 等回放水位以及打开文件引用满足条件后删除；重启及日志清理后仍能恢复。MySQL binlog 按既定 1 天策略检查。 |
| H | 租户规模与性能 | 先 10，再 50，最后 **200 租户**持续 Robot 下单/撤单/撮合；完成主切和权威一致性后做 2–3 倍 5–10 分钟 burst，测 TPS、p95/p99、CPU/GC、IO、内存、磁盘；无系统级错误。 |

**顺序原则：先证明恢复正确且能真实主切，再做 50/200 压测；不要为性能优化牺牲 WAL 提交、Quorum 或接收端门禁。** Demo 是 Mac mini 同一物理宿主的 Docker 节点，单机实验可验证进程故障恢复，但**不能冒充不同物理机的生产容灾/quorum 证明**。

> **最新实际角色切换证据（2026-10-16 Mac Demo）：** [Trade P000/P020、Order P000/P228 在线双向切换与对账记录](CLUSTER_HA_REAL_ROLLOUT_EVIDENCE_20261016.zh-CN.md)。切换项目已有 PASS；真实 Primary SIGKILL 自动接管、Trade 客户资金持仓 API 对账、MD Primary 故障切换及 200 租户压测仍未通过，禁止重复将已完成的角色切换当作全部 HA 验收。

## 三、2026-10-15 当时可核实的运行状态（历史快照，接续前复查）

- 当前 Mac Demo 23 个容器在运行；Order A/B/C、Trade A/B、MD A/B/C 运行，Docker OOM=false。
- Order ZK 256/256 READY，A/B 各 Primary 128，C 为所有 256 分区的副本；已有三副本 Order 快照对齐的只读校验 PASS。
- Trade ZK 256/256 READY，A/B 各 Primary 128；六个真实租户 Primary Snapshot 含业务状态。但同步 Replica 的 `latest.json` 为初始零快照，`*.cq4` 中有连续原始 WAL 且可见尾部常落后 Primary；**这不代表已证明 committed HEAD、完整 ACK 或业务可恢复**。须从真实 Common/Trade 提交水位、原始 WAL 原封续传与独立认证 ACK 确认，再执行 Trade 主切；不要简单基于旧快照错误下结论。
- ZooKeeper Trade `controller/replication-health` 记录 `degraded=false`，但 `replicatedSeq` 非持续刷新，**不能当作实时提交 HEAD**。现有 Trade Primary→Replica WAL 原始记录共存内容大多一致，但不同时间的文件扫描尾部有差异，需要有界的同一提交点交叉证明。
- MD A/B 各 Primary 128，C 为所有 256 分区的 Learner。2026-10-15 实际对 C 执行一次 SIGKILL、手动启动，C 从 Order 恢复六个活跃市场的 Image，原分区和 Primary 分配未改变：**MD-C Learner 恢复 PASS，MD Primary 自动故障切换仍 BLOCKED**。
- Projection 最近校验 Order/Trade 7/7 watermark 与事件尾一致，孤儿 Mutation=0、跨分区重复 Event ID=0；Robot 六租户 RUNNING、总共 240 挂单，租约/心跳持续有效。
- 已抽查八个运行中的 Order/Trade/MD 容器：Common 均为 `3.0.21-devcombined-20261015-SNAPSHOT`，JAR SHA-256 完全相同；com.app.dc `0.0.5-devcombined-20261015-SNAPSHOT` 同样一致。仅证明基础包同源，不证明 HA 验收通过。
- `tests/run-core-trading-acceptance.sh` 调用了与三副本 Order 拓扑不兼容的旧恢复脚本；业务规则 E2E 的 FOK/IOC/PostOnly/撤单/TP-SL 等通过，但后续浏览器步骤默认向 Mac 宿主机只读 `/data` 写测试产物失败。**修复验收脚本/路径并隔离 HA 故障场景，再补真实交易 E2E**；不要让普通 Smoke 自动重启 Primary。
- Order 当前 A/B 既是 Primary 也是同步 Replica，C 是全部分区副本；直接滚动停止 A/B/C 的预检均 NO-GO，**先正确处理同步副本耐久和切换边界，不能强行关闭安全门禁**。
- MD Primary 自动主切预检缺乏独立验证的 Order 当前签名 HEAD、候选 Image+Diff 接收状态、旧发布者 epoch fence 与 CAS 授权。已有镜像锁脚本过时，不应把脚本识别不了新本地镜像等同于节点不健康。
- Order/Trade WAL 占用需要监测：只读审计活跃 allocated ~1.83 GB；512 个 Order archive 初始化元数据目录约 64 MiB，尚无超 48 小时应删的归档；未证明的 WAL 不允许删除。
- 最近一次 MD-C SIGKILL 后复测：23 个容器、Trade 256 READY、Projection 7/7、Robot 6 RUNNING/240 挂单均 PASS；未执行 Order/Trade/MD Primary SIGKILL。
- **本仓库该文档属于任务交接，不是验收完成声明**；历史数据随 Demo 清理或镜像更换作废，PASS 要有对应镜像 SHA、测试命令、日志/JSON 证据和时间窗。

## 四、下一次接续立刻做（拒绝原地空转）

1. 基于真实运行中的 `saas-crypto` 代码和容器复核 Trade/Order/MD **为何当前安全门禁无法通过**，查 Common 接收端恢复授权、WAL 逐条验证、ACK 提交边界、Epoch 和快照。找出可复现的真实失败，立即做最小代码修复；不是继续堆新的恢复准备阶段或设计说明。
2. 本地 Java 8 / Maven 编译 Common + com.app.dc + 三服务，构建 ARM64 Demo 镜像，验证实际 JAR SHA；GitHub Actions 先不处理。**每一处有效源码变更先提交对应服务 `saas-crypto`，Demo 镜像要可对应提交。**
3. 需要简化现场时，按用户授权进行**受控 Demo 数据清理 → fresh 部署 → 自动审批新租户/Robot 启动**，但不触及宿主非 Demo 数据；该动作后立即完成 Smoke，不再纠缠上一轮测试数据。
4. 完成 Order SIGKILL → 自动主切 → Replica 追平、Trade 持仓故障 → 自动主切 → 资金持仓对账、MD Primary SIGKILL → 全量行情恢复与发布隔离；每项每次只验收一个明确边界，并记录精确证据。
5. 只有以上通过，再执行日志归档/自动删除和 10→50→200 租户压力与 burst 验收；如失败直接修复、替换 Demo、重新跑该项的必要回归。
6. 每轮结束在此文档或单独 `docs/evidence/` 中更新 `PASS/FAIL/BLOCKED`、代码提交 SHA、Demo 镜像 SHA、故障触发/恢复窗口和最终对账数据。**下一会话先读本文件，从第一个 FAIL/BLOCKED 继续，禁止重复介绍计划取代操作。**

## 五、禁止误判和不可偏离的要求

- 不动 Gateway 业务逻辑，不启用 TLS；也不改产品、Broker API、Python SDK/API docs 等旁支工作。
- 不能以 ZK READY、容器 Up、零 OOM、Learner 快照恢复、原始 WAL 文件大小、旧健康标记替代真实 Primary 自动切换证据。
- 不能因为 Demo 数据可重建就允许旧主继续发布、未取得 quorum/提交证明直接 READY、或者未验证后删除 WAL。
- 不要反复问用户是否可以重新部署或清理 Demo；此授权已给出。遇到必须外部补充的生产物理 quorum 条件，清晰标注生产环境限制，继续完成单机能独立验证的进程级 HA。
- **任务结束标准：以上 A–H 全部有真实验收证据，所有故障已修复并已部署，权威账本通过，服务在恢复后持续交易。未达此标准就不得宣布“整轮完成”。**
