# 可复用集群底座：Order、Trade、MD 首批接入计划

更新：2026-09-29。按最新要求，近期主线调整为**集群底座、压测、异常与稳定性**；管理面与完整业务专项后排。集群测试仍必须守住订单、资金和行情一致性，不能为了 TPS 放宽安全门禁。

最新候选进度：Trade `d934291` 补齐显式混合非现金提交的现金索引覆盖连续性，全量 **65 类 / 320 项**通过；Projection `3122a8d` 的 **73 项**和 **45 项隔离 MySQL 一轮**复验通过。线上仍未接入候选或退出旧 SQL 写入；下一步先做全节点冷恢复/admission 容量及真实全事务后态核对，之后才是受控异常和 TPS。详见 [混合覆盖候选验收](TRADE_MIXED_STATE_COVERAGE_CANDIDATE_20260929.zh-CN.md)。

## 1. 当前实测与问题边界

- 本地 Colima 的 Trade A/B 当前各有 128 个 Primary，256 个 assignment 均为 READY；当前进程日志存在相应 epoch 的 READY 证据。该证据不等于已验证业务可写或 RPO。
- 最近一次启动到最后一个本地主分区 READY：A **128.802 秒**，B **79.969 秒**。包含容器启动和初始化，不是单分区重放时长，也不是自动故障切换 RTO。
- Trade A/B 各约 3.8 GiB journal，没有 `latest.json` 快照，定时快照配置为 `false`。A 的 P204/P122 journal 分别约 1.9/1.3 GiB；恢复需要从历史日志重建。A 原先 384 MiB 堆多次 OOM；调整为 768 MiB 后当前进程未再 OOM。B 尚不能因此被认定有能力接管 A 的大分区。
- Trade 恢复循环是单线程；大分区重放会延迟排在后面的空/小分区。流式恢复先验证再安装，不能为了缩短时间直接删除预验证或 committed-tail 门禁。
- Order A/B 各约 3.5 GiB journal、69 MiB snapshot；定时快照关闭。现有设计把快照传输块写入同一 journal，贸然打开会放大日志，必须先验证快照传输与保留策略。
- **故障语义不同：** Order 运行配置 `replication.required=true`、`SYNC_PER_RECORD`；Trade 是 `state.required=true`、`replication.required=false`，副本失败时允许本地主节点降级提交。Trade 的本地成功不能自动成为副本可证明的 committed prefix，切主前必须验证，不宣称当前 RPO=0。
- MD 已部署 A/B/C；只读核对 256 个 assignment 均为 READY，A/B 各有 128 个 Primary 与 128 个 Replica，C 当前没有 Primary/Replica/Learner 分配。C 是运行中的未分配节点，不是已经验证的第三副本。MD 必须与 Order、Trade 一起列为首批适配和验收对象；进程数为 3 不证明跨故障域或多数派提交。
- 本地 A/B/C 共用一个 VM 和磁盘，只能证明进程级行为，不能证明宿主机级 HA。

证据入口：`tests/trade_recovery_baseline_host.py`，只读采集当前进程 READY、启动耗时、快照、资源和 assignment 状态；不注入故障、不修改 ZooKeeper、不导出原始认证日志。本轮数据保存在本地 `.tmp-trade-evidence/recovery-baseline-20260929.json`。

## 2. 框架边界：在现有 Common 上演进

现有 `app-common` 已有 PartitionAssignment/Registry/Runtime、Router、epoch fence、ReadinessGuard、节点/placement 元数据及通用复制传输。保留这些能力，不再建立第二套注册、路由和 fencing 体系。

公共层负责：

1. 服务、节点、逻辑分区与放置策略；assignment 的 CAS/version/epoch 和控制面连接状态。
2. 统一恢复生命周期与 READY 门禁；有界恢复执行器、分区去重、可协作取消、重试退避与公平调度。重放不得堵塞 ZooKeeper 回调线程。
3. 可扩展的 journal、snapshot、commit proof、复制 transport 接口；存储格式与业务对象不进入公共生命周期代码。
4. 明确的一致性策略：本地提交、指定副本确认、多数派提交分别配置、分别验收。策略名称不能代替真实的选举、提交和 fencing 协议；没有实现多数派协议时不暴露“QUORUM 可用”开关。
5. 健康检测、drain、catch-up、promotion、回切、扩缩容和滚动升级操作；自动化切主必须有权威提交边界证明，不能只看到 heartbeat 消失就改 primary。
6. 统一观测：阶段耗时、snapshot age/delta、journal bytes、commit/replica lag、READY/DEGRADED 状态、失败原因、内存和恢复进度。认证信息不进入证据。

服务适配器负责：

| 服务 | 状态范围 | READY 前必须证明 |
| --- | --- | --- |
| Order | 活动单、撮合簿、幂等结果及相关提交状态 | 已确认 committed prefix、快照与增量一致、复制/epoch fencing 安全，不丢已确认订单、不重复成交 |
| Trade | 余额、持仓、保证金、费用/资金费效果、执行去重及配置 | 已确认资金效果可恢复、无未解释 dirty tail、降级提交的权威来源明确，不重复入账、不从落后副本静默回退 |
| MD | order book/ticker/recent trades/kline 与订阅序列 | snapshot + delta 连续、GAP 补齐、行情新鲜度与路由/epoch 正确；旧主不得继续以新主身份发布 |

MD 是序列状态服务，不简单按“无状态服务”处理。后续服务可以只接注册路由，或进一步接恢复/复制/快照能力；不能被迫引入交易专属字段。

## 3. 已落地的公共代码（尚未接入部署）

`app-common/PartitionRecoveryCoordinator` 提供泛型适配接口：

```text
prepare（只读、锁外）
  -> 分区业务屏障内 install
  -> 服务 verifyPromotion
  -> adapter closePlan 释放准备资源
  -> 复核控制面、primary、epoch、assignmentVersion、副本/learner 集合
  -> mark READY 后再次复核
```

失败或旧 token 不开放 READY；旧恢复不能清掉新 epoch 的 READY。服务仍须用相同分区屏障保护 mutation/recovery/readiness，并在业务入口检查当前归属与 epoch。当前为公共恢复协议和调度原语，不含自动选举、持久多数派或三个服务的完整接入；这些是下一阶段明确交付项。

### 有界调度原语增量（2026-09-29）

- app-common 本地提交 `e95850b` 增加 `PartitionRecoveryExecutor`：有限并发/队列/估算资源预算、同分区去重与新旧 generation 串行、协作取消后保留资源占位、有限小任务旁路和严重错误停止接收。自动 retry/backoff、实际 heap/IO 限额和角色变更协议仍由后续适配补齐。
- Coordinator 增加显式 `closePlan` 钩子，READY 前释放计划输入，stale/install/verify 失败也关闭一次；prepare 部分失败资源由 adapter 自行清理。关闭失败不能开放 READY。默认 no-op 不代替具体服务的资源关闭实现。
- 全量 24 个测试类 / 83 个用例通过；30 个契约用例重复 8 轮通过。未发布/替换任何运行依赖，MD 仍与 Order、Trade 一起属于首批服务适配范围。
- 详细 API、取消/预算边界、版本差异和服务接入门禁见 [可复用恢复调度说明](REUSABLE_RECOVERY_SCHEDULER_20260929.zh-CN.md)。

Trade 数据来源补充：权威模式不能从数据库 Projection 恢复余额/持仓/用户交易配置；本地文件缺失保持 NOT_READY。候选代码、未迁出的 SQL 事务和历史基线门禁见 [Trade 本地文件权威恢复](TRADE_LOCAL_FILE_AUTHORITY_20260929.zh-CN.md)。

Projection 事务增量：本地提交 `0a8ccfe` 修复不确定事务连接复用和重复消费锁升级死锁，增加 InnoDB/完整唯一键启动门禁。48 个单元用例、18 个真实 MySQL 隔离用例连续 3 轮通过；四项业务表物化仍默认关闭，未覆盖资金流水/历史基线，不等于异常切换或 TPS 验收。旧 Projection 候选依赖不同，不能晋级复用。见 [事务验收与下一步门禁](TRADE_PROJECTION_TRANSACTION_20260929.zh-CN.md)。

现金/流水后续增量：候选 Trade 增加显式请求身份、稳定流水 ID/请求指纹与同批余额/流水构造；恢复在安装前验证 POSTING。候选 Projection 的流水切片默认关闭，同 ID 在新的提交坐标出现会拒绝整批，不覆盖旧账。Trade 242 / Projection 56 个用例及 26 项隔离 MySQL 演练通过，**旧现金入口未接入、原结果持久去重与快照恢复未完成**，不能直接关闭 SQL 或当成切主验收。见 [候选协议与接入门禁](TRADE_CASH_POSTING_CANDIDATE_20260929.zh-CN.md)。

同时为 Trade 增加恢复阶段和快照阶段的耗时日志，保留已有 READY 日志格式以兼容验收工具。未构建/晋级镜像前，运行环境不会产生这些新日志。

### F1 当前增量（2026-09-29，代码已验证，未晋级运行环境）

- Trade 的恢复入口改为固定打开的快照文件描述符；去重记录逐条预验证、逐条安装，不再构造完整去重 DTO 列表。保留完整预验证、分区锁、epoch 复核和 committed-tail 门禁。
- Trade 源码已本地提交 `083e1c8`，候选镜像 `local/tradesvr:recovery-stream-083e1c8` 已构建；镜像内断网执行 27 个关键用例通过。没有推送/部署镜像，没有修改当前节点的运行配置。
- 补上低频分区首个快照的年龄触发：从首次观察到待快照提交开始计时，达到 `maxAgeMillis` 即进入候选；失败不重置年龄，丢失本地主角色清除计时。仍需所有本地主分区 READY，且每轮只处理一个候选，不能把候选年龄门槛当作所有分区完成快照的硬期限。
- 修复恢复同名去重键后旧淘汰队列记录可能提前淘汰新值的问题；未缩小去重缓存，未改现有全局容量限制。
- 合成 79.4 MiB 快照在独立 `-Xmx64m` 子进程中对比：旧整份加载 OOM，新读取方式通过 1 万条记录两遍扫描。Trade 全量 191 个测试通过。**这是解析内存测试，不是完整状态容量、快照捕获峰值或异常切换验收。**
- 余额/持仓/配置/活动单仍保留在恢复计划中，最终运行去重表仍需足够内存；下一步验证真实规模捕获、加载、安装和增量重放，再决定周期快照晋级。详细边界见 [F1 验证记录](TRADE_SNAPSHOT_RECOVERY_F1_20260929.zh-CN.md)。

## 4. 按顺序交付

### 真实日志副本实验增量（2026-09-29）

- Trade 已增加近尾 seek，P204 单分区快照增量恢复由约 8.34 秒降至 2.06 秒，完整状态摘要一致；属于隔离副本恢复，不是故障 RTO 或 TPS。
- P204 + 常驻 P122 在 768 MiB/1 GiB 堆预算下均恢复一致；GC 后仍占约 439–477 MiB，因此 B 当前 384 MiB 堆未通过大分区接管容量门禁。完整节点容量仍待验证。
- 发现完整提交历史中的 49,819 条缺状态 Trade 成交片段被留作订单镜像，推导剩余量为零；已经补新交易路径的镜像回归和 authoritative 重连保护。历史订单/资金权威对账先于快照晋级，不自动重写旧记录。
- 当前服务镜像、assignment 和周期快照配置均未改动。最新实测、镜像/源码差异、实验复现与晋级门禁见 [真实日志副本恢复验证](TRADE_REAL_JOURNAL_RECOVERY_LAB_20260929.zh-CN.md)。

### F0：测清现状并统一故障语义

- 锁定镜像 digest、拓扑、资源、快照和 journal 基线；Order/Trade/MD 分开记录。
- 对齐单节点故障后的可用性目标和成功响应的持久性要求。优先保住已确认状态，不为测试绕过 ACK、epoch 或 READY。
- 检查 B 接管 A 的容量，不以 B 自身 128 个分区正常推断大分区 promotion 安全。
- 补齐恢复阶段计时，明确慢在初始化、快照加载、验证、重放、复制追平还是路由刷新。

### F1：先降低恢复成本

- Trade 先在隔离副本数据上验证大快照捕获/加载的峰值内存，再恢复定时快照；不能只打开开关就宣布问题解决。
- 为活跃与低频分区建立首个快照的最大等待期限，限制 snapshot delta 和最大恢复工作量；快照既要新鲜，也要有经过验证的 committed prefix。
- 快照 payload 流式加载/安装，去重状态保留策略有明确重试窗口与持久幂等保证，不通过随意缩小去重缓存来换内存。
- Order 分离快照传输与业务 journal 放大问题；归档/保留由已确认快照及消费者 watermark 驱动，禁止直接清空 journal。
- 恢复执行器使用小的可配置并行度、内存/IO 预算和公平调度；保留逐分区业务屏障与完整预验证，不做无限并发恢复。

### F2：三服务适配与受控异常演练

- Order/Trade/MD 接入公共恢复状态机、指标与统一验收入口；先保持现有业务语义和存储兼容，再替换重复实现。
- MD C 先经受控 learner/catch-up 接入，再验证分区迁移、接管与回退；当前运行但未分配的 C 不能算扩容通过。
- 使用隔离目录、独立端口与 ZooKeeper namespace，先测空/小分区，再测当前规模的大分区；带业务数据的测试同时核对已确认订单/资金效果和 MD 序列。
- 注入进程退出、暂停/网络隔离、复制迟滞、控制面失联、脏尾和快照不可用。每次记录：检测、fence、生效归属、恢复、Replica ACK、首次成功业务响应、投影/订阅收敛、回切时间。
- 验证旧主拒写/拒发布、无双主、落后副本不能静默接管、重试不重复成交/入账、MD GAP 可补齐。正常 role reversal 不等于异常切换，日志 READY 不等于业务可写。
- 单宿主机验证通过后，再做独立故障域演练。三节点 ZooKeeper/MD 并不能自动解决 Order/Trade 双副本可用性。

### F3：分级压测与稳定性

- 先按 300/16 的有界小量基线校验；安全门禁发现旧活动单时退出，不删库重置。
- 依次量测入场、撤单、撮合完成、复制提交、投影可查与 MD 发布/订阅；只有 shadow probe 的结果不能称为系统交易 TPS。
- 再增加负载，在受控负载中做故障/恢复，分别报告正常容量、故障降级容量和恢复积压清空时间。
- 各轮保留 p50/p95/p99、成功/拒绝/超时、commit/replica/projection lag、MD freshness/GAP、CPU/内存/OOM、快照开销与订单/资金一致性。
- 短测门禁通过后做 24 小时观察与 72 小时候选长稳。时长是计划门槛，不是当前成绩；通过与否以持续记录和不变量判定。

### F4：复用产品化

- 交付按需启用的配置、服务适配模板、公共契约测试、故障注入 harness、版本升级/回滚手册。
- 用 Order、Trade、MD 三种状态适配证明可复用，再以一个最小新服务证明无需复制集群代码就能接入。
- 发布不可变 Common 与服务镜像；兼容旧 snapshot/journal/metadata 的升级门禁通过后再晋级，不混用未验证的底层版本。

## 5. 当前未宣称完成

现金恢复后续切片：Trade `40ae10c` 已加入候选原结果持久索引、STATE_BATCH v2 与 snapshot v3、容量不淘汰和恢复/快照覆盖门禁；全量 270 项通过。Projection `d4cd054` 的 27 项隔离测试验证旧格式物化与新 v2 整批拒绝，**不表示支持新协议**。旧现金入口未接入，原 SQL 写入保留；下一步为明确 API 身份、纯计算与坐标感知提交/安装、消费者升级、冷留存/可信历史门禁。前面“原结果持久去重与快照恢复未完成”描述的是上一切片；此次已完成候选记录/恢复部分，未完成线上原子现金流程。详见 [原结果候选验收](TRADE_CASH_REQUEST_RECOVERY_CANDIDATE_20260929.zh-CN.md)。

没有新增故障注入或压测；没有接管/修改现有 assignment；没有启用快照或清理日志。初版框架与计时代码尚未部署。自动切换、持续 TPS、业务 RPO=0、跨宿主机 HA 和长期稳定性均需后续实测，不由本计划或单元测试推导。

### 后续增量：候选现金提交/安装闭环

Trade `64acf8e` 已将纯计算、真实容量预留、严格协调器提交、安装校验、原结果索引/覆盖推进与发布/响应串成**显式隔离候选**。不确定提交会撤销 READY，容量保留到可信恢复完成；新增 25 项后全量 **64 类 / 295 项**通过。真实合成主副 Chronicle 文件和实际恢复/快照类验证并发重试、ACK/纪元/安装/发布异常及关闭重开；没有线上/TCP/进程强杀或真实 promotion。

Projection 源码未变，56 项单元与 27 项隔离 MySQL **一轮**复验通过，仍整事务拒绝新 v2，不是消费者升级完成。下一步先补消费者协议，再做真实 API/admission、全事务覆盖、投递/冷留存及全节点容量门禁；旧现金入口、SQL 写入、运行镜像和 assignment 均不变。混合旧交易的覆盖跟踪、业务推送补齐及可信历史仍未完成，故不开始 TPS 晋级。详见 [提交/安装候选验收](TRADE_CASH_COMMIT_INSTALL_CANDIDATE_20260929.zh-CN.md)。

### 后续增量：新现金格式投影消费者候选

Projection `3122a8d` 增加**默认关闭**的 v2 消费者，整批校验余额/流水/首次结果，原结果在同一 SQL 事务中普通 INSERT；新增身份二进制比较、结构/容量/精度与 UTF-8 门禁。全量 **73 项**通过，实际 Trade 生产器全附加字段互通的 **45 项隔离 MySQL 连续 3 轮**通过，Trade **295 项**重新回归通过。前文“只拒绝 v2”属于上一切片/当前线上：关闭开关仍拒绝，未升级线上镜像或改表。

下一步回到混合交易覆盖坐标与异常恢复/业务重试门禁，并落实真实 API/admission、全节点容量、投递/冷留存/历史对账。新结果表不是核心恢复来源；原 SQL writer 仍在，尚不能启用双写或做 TPS 晋级。公共 Order/Trade/MD 框架接线、大分区接管与受控故障仍待验证。详见 [v2 消费者候选验收](TRADE_CASH_V2_PROJECTION_CANDIDATE_20260929.zh-CN.md)。

### 后续增量：混合交易覆盖连续性候选

Trade `d934291` 在严格分区屏障/primary/epoch/READY/复制 ACK 下为已知 v1 非现金提交推进现金索引覆盖；冻结协议、拒绝旧现金/未来效果、匹配原覆盖且无本分区预留，可信 adapter 安装核对后才推进。旧 `record` 未自动接入，不能跳过未观察的旧提交；安装/发布后的权威和日志尾变化会封住分区。新增 **25 项**，最终全量 **65 类 / 320 项**通过；Projection 源码不变，**73 项＋45 项隔离 MySQL 一轮**复验通过。

当前仍是显式隔离候选，不是全线上业务后态/风险核对或完整 TCP 投递链路。下一步优先全节点冷恢复容量：未恢复分区不能被当成零占用，再补真实全部 adapter、可信历史与留存/GAP 门禁。无部署、重启、assignment/SQL/历史变更或压测，故不宣布 RPO/RTO/TPS/HA。详见 [混合覆盖验收](TRADE_MIXED_STATE_COVERAGE_CANDIDATE_20260929.zh-CN.md)。
