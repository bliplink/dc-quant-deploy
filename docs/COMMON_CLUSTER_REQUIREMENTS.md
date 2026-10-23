# Common 集群统一功能及独立 Demo 验收基线

版本：1.0｜确认日期：2026-10-23

> 本文件为 Common 与独立 byte[] Demo 的开发/放行硬门槛；先全部完成功能、真实自动 HA 和性能压测，才开始 Trade / Order / MD 状态机集成。

> 必须区分模式：LOCAL_DURABLE_ASYNC 可用性优先，但 Primary 永久失效可能丢失未复制的已 ACK 尾部；QUORUM_DURABLE 在实际数据副本持久化证明与证书托管法定数不满足时，不得给严格成功 ACK。两种合同不可静默互换。


## 架构与扩展

- **C01** Common 是 Order、Trade、MD 和后续服务共用的有状态集群基础设施。
- **C02** Common 不理解委托、成交、余额、持仓、行情等业务结构。
- **C03** 业务只实现 byte[] apply、snapshot、restore 等状态机接口；集群与恢复逻辑不散落到业务层。
- **C04** 单节点可独立运行；实际 ACK 保证必须遵守所配置的 durability 模式。
- **C05** 按照 Partition 分配业务和拥有者，避免全量节点复制所有分区。
- **C06** 支持 1、2、3、4、5、20 及更多节点扩展。
- **C07** 每分区只向指定 RF-1 个 Replica 复制 WAL，不进行全节点广播。
- **C08** ZooKeeper 维护真实成员、分区配置、Epoch、Primary、Replica 与授权信息。

## 复制与持久化

- **C09** 状态变化记录可恢复 WAL，并规定 apply/ACK 与 fsync 的顺序。
- **C10** Primary 单向复制给 Replica；慢副本不能阻塞 Primary 的本地处理。
- **C11** 显式支持 LOCAL_DURABLE_ASYNC 与 QUORUM_DURABLE 两类确认合同。
- **C12** 严格 ACK 必须先验证法定数量的真实持久化证明。
- **C13** RF2 严格 2/2；RF3 严格 2/3 个独立数据副本证明；ZK 见证票不算 WAL 数据票。
- **C14** 验证 WAL 提交证书、独立 RSA 签名、Epoch、Hash 和 Membership。
- **C15** 所有已 ACK 的提交证书须由足够独立数据成员持久保管。
- **C16** 节点重启从 WAL/证书/快照恢复可证明的提交水位。
- **C17** 按分区顺序 apply；同一 requestId 重试不得重复应用。

## 自动 HA 与恢复

- **C18** 自动检测节点死亡、断网、超时、租约失效。
- **C19** 合格 Replica 在 Primary 故障后自动接管，不能由验收脚本代替选主。
- **C20** 验证 A→B 与 B→A 双向自动接管。
- **C21** 旧主 Epoch fencing；禁止双主、旧主继续提交或发布。
- **C22** 新主须证明完整覆盖旧 Epoch 最高已 ACK 水位后才能 READY。
- **C23** 旧 Primary 恢复自动降为 Replica，不得抢回主角色。
- **C24** 通过 Snapshot + WAL/Diff 自动追平 Replica。
- **C25** 新节点作为 Learner 追平后，再经授权成员变更进入正式数据副本组。
- **C26** Replica 故障/卡顿/重启不能拖垮健康 Primary；严格模式不满足数据法定数时拒绝严格成功 ACK。
- **C27** 切换期间允许有界暂停，恢复后数据必须正确。
- **C28** 自动定时生成可信 Snapshot。
- **C29** 支持快照之后的 WAL/Diff 增量重放。
- **C30** 恢复支持安全续传、完整性校验与重试。
- **C31** 恢复安装必须事务化；验证完成前不能 READY。
- **C32** 分叉 WAL 尾部隔离、保存与验证，不得覆盖已确认状态。
- **C33** WAL 自动归档，不能无界增长。
- **C34** 安全删除基于快照、恢复水位、副本证明及保留策略。
- **C35** Demo 默认约 2 天保留、可配置；不误删当前恢复所需证据。
- **C36** WAL fsync、证书安装、目录 fsync、快照、成员变更各崩溃窗口均安全恢复。

## 性能与可观测性

- **C37** 性能优先：避免不必要的逐笔序列化、全历史校验和磁盘操作。
- **C38** 支持 group fsync、批量 ACK、证书合并而不弱化严格确认。
- **C39** WAL/复制/验证/托管使用异步流水线，不堵塞 Netty IO 线程。
- **C40** 前缀校验采用可验证增量索引，避免每次 ACK 全历史 SHA。
- **C41** 稳态端到端请求→客户端 ACK P99 ≤30ms；保留完整测量口径。
- **C42** 报告有效业务 TPS、WAL TPS、网络吞吐与峰值能力。
- **C43** 慢副本/归档/快照/恢复必须有 CPU、内存、磁盘、网络背压和资源边界。
- **C44** 提供角色、Epoch、复制落后、提交水位、恢复状态、TPS、延迟及错误指标。

## 独立 Demo 必过测试 T01–T15

- **T01** 单节点读写、重启、恢复；两种 durability 合同均准确。
- **T02** RF2/RF3 分区成员、真实独立 WAL fsync、证书持久化及提交水位正确。
- **T03** SIGKILL Replica 后 Primary 不崩溃；严格法定数不足时安全拒 ACK。
- **T04** SIGKILL Primary 后无需脚本自动接管，已 ACK 完整。
- **T05** A→B→A 双向故障自动切换。
- **T06** 旧主恢复自动降为 Replica，并追平。
- **T07** 网络分区或租约失效时无双主、无越权 ACK。
- **T08** 恢复/安装中再故障后仍可安全重试，不误 READY。
- **T09** 新增/删除成员和 Learner 自动追平、授权迁移。
- **T10** 定时快照、WAL 归档安全回收，重启仍能恢复。
- **T11** 10/50/200 并发模拟客户端各稳态运行至少 5 分钟；区分模拟客户端与真实租户。
- **T12** 2–3 倍突发负载持续 5–10 分钟。
- **T13** 持续业务写入期间 SIGKILL 主/副本，并执行恢复追平。
- **T14** 逐 requestId 审计：无已 ACK 丢失、重复 apply、双主，水位一致。
- **T15** 端到端 P99 ≤30ms 并报告 TPS、资源、水位、异常与故障恢复窗口。

## 开发与验收约束

- 独立 Demo 必须使用真实多 JVM、多数据卷与实际 ZooKeeper 授权及 Netty 通信；同一 Mac 虚拟机仅提供进程隔离，不能冒充物理故障域验证。
- PASS 需有命令、时间、提交 SHA、运行环境、可审计日志与最终水位；单测通过不等于故障自动主切与负载通过。
- 先完成 Common + 独立 Demo，之后固定接口版本，再适配 Trade / Order / MD，最后做真实交易业务及 Projection 一致性验收。
- GitHub Actions 暂不使用；优先本地编译和独立测试容器，不破坏正式交易容器或在用 WAL/证书。
- P99 30ms 为当前目标，若真实性能不可达，必须报告 FAIL 和瓶颈，不得降低安全合同伪造 PASS。
- 任何测试数据清理须先确认无 Docker 容器及恢复流程引用。


## 2026-10-23 方案确认：轻量多节点选主与默认双节点互备（追加要求）

- **C45** 统一按 Partition 的 RF2/RF3 成员/Epoch/Fencing/恢复机制；A/B、C/D、E/F 配对只是一种默认 RF2 放置策略，不允许维护第二套私有 HA 协议。
- **C46** 全新 256 分区：2 节点各 128 主+128 备；4 节点按 A↔B、C↔D 成对各 64 主+64 备；每分区只向所属指定 1 个备复制；故障域彼此独立。
- **C47** 静态分区规划永远不得直接写 ZooKeeper、打开 READY 或重新分配已存在的业务分区。2→4 扩容必须先 Learner 追平，再完成授权变更、Fencing/水位校验、分批切换。
- **C48** 默认轻量选主仅在成员/租约变化时执行：ZooKeeper epoch CAS + 旧主隔离 + 候选本地可信已 ACK 提交水位覆盖；不能把 lastApplied 当 maxAcked，也不能仅凭网络存活或单节点只读旧证书直接升主。
- **C49** 常态数据单向批量 WAL，反向仅累计 durable ACK，业务写入热路径 ZooKeeper 同步 RPC 为 0；失败租约的可撤销授权视图必须 fail-closed，严格 ACK 保持 RF2 2/2、RF3 2/3，禁止静默降级。
- **T16** 初始 2/4/6 节点规划实际验证每节点主/备分区数、定向复制目标、不同故障域与异常输入拒绝；严格区分“生成 PREPARING 建议”和真实新 Epoch 已激活。
- **T17** 真正从 A/B 256 分区迁移到 A/B/C/D 64 主+64 备的运行时集群验证，故障中仍无双主/错路由/ACK 丢失/重复应用，分区完成迁移前旧分区不得被静态规划改写。
- **T18** 真实 RF2 SIGKILL A/B 后同一分区由对端取得新 Epoch；对端单数据节点仍不允许冒充严格 2/2 ACK。独立验证客户端恢复与所有已确认 WAL 水位。
- **C50** RF2 用户可用性要求（2026-10-23 修订）：A/B 一方故障后，另一方应在旧主可信 Fencing + WAL 已 ACK 提交边界检查 + 新 Epoch ZK 授权成立后，按**明确配置、可审计、向客户端标注**的 `AUTO_DEGRADED_LOCAL_DURABLE` 合同继续交易；不能长期停在 RECOVERING/503 等待旧副本恢复。故障期间仅 B 本地强制落盘的新 ACK 不得冒充 2/2 零丢失。
- **C51** 旧主回归后必须先作为 Learner 自动追平单副本期间全部已确认 WAL、校验去重与状态，之后安全恢复 2/2；ZK 多数丢失时单节点不能继续 ACK，恢复仲裁需要新合法 Epoch 而非重开已被撤销旧租约。
- **T19** 真实 Docker A→B failover 时，验证严格 2/2 的旧 ACK 全覆盖、自动降级本地 ACK 继续成功、请求幂等、B 持久化重启恢复、旧 A 写入拒绝、ZK 失去多数后的拒绝以及原 A 自动重入/追平；未完成环节不得标 PASS。
- 详细方案：`docs/COMMON_HA_LIGHTWEIGHT_BUDDY_STRATEGY_20261023.zh-CN.md`，本节为 C01–C44/T01–T15 的**补充**，不得减弱原要求。

- **T20（2026-10-23）** RF2 A故障B自动降级继续 ACK 后，A恢复必须自动以 Learner 身份安全追平 B 的全部已 ACK WAL，检查旧已确认历史不分叉、镜像/增量传输与重放、ZK 成员身份、脏尾隔离与重启回放。当前隔离 P000 镜像追平和重启验证 PASS；增量 Diff/256 分区/多物理节点仍未通过。
- **T21（2026-10-23）** Learner追平以后必须在新 Epoch 与配置事务中恢复 A/B 双副本复制、正确持久 ACK，然后 B SIGKILL → A 自动接管，继续交易并多轮 A/B 故障切换。此项仍 FAIL/未完成，不能仅凭 WAL 水位相同宣布 HA 完成。

- **T22（2026-10-23，P000 隔离试验 PASS）** A/B 两数据节点、真实 ZooKeeper 三协调进程、两独立 JVM/WAL，经 SIGKILL A、B、A，自动获得 Epoch2/3/4 唯一主及可持续本地持久化写入，双向 Learner 追平与重启回放一致、旧主 Fencing、ZooKeeper 仲裁丢失时拒绝写入。单机降级 ACK 明确标记 quorumDurable=false，不是零丢失严格双副本提交。
- **T23（未完成）** Learner 已追平之后需自动、原子地把它纳入新配置中的同步 Replica，建立随 Epoch 动态切换的严格 RF2 2/2 WAL 持久复制与真实签名/累计 ACK，并执行多轮故障、重新授权、256 分区/4 节点及业务权威一致性验收。

- **T24（2026-10-23：部分 PASS）** 经 A/B 单节点故障恢复并进入新 Epoch 后，真实远程读取两个不同 JVM 的洁净 WAL、committedSeq、hash、业务 stateDigest 和原双签名证书，复验 ZooKeeper 的 Epoch、Assignment 版本与成员身份。现阶段 P000 read-only preflight Docker PASS（Epoch5/seq16），不构成严格 2/2 ACK 及成员切换完成。
- **T25（2026-10-23：Common 单测 PASS，动态生产接线未完成）** 可在新的 Epoch 双签名成员下，对已存在的 WAL 水位签出新的两物理数据节点持久 Genesis，连续认证后续序列并在重启后验证；必须拒绝单签名、旧签名、失效授权。真实 Order/Trade 数据接线、恢复同步 Replica 的 ZK CAS/数据屏障/新 Epoch 2/2 TCP RPC 和故障注入仍 NO-GO。

- **T26（2026-10-23：Demo 接线/负向验收 PASS，自动切回严格复制未完成）** 新 Epoch 独立物理 WAL RSA Receipt 服务从 ZooKeeper Assignment 固定 Primary、2 数据成员、Epoch/config、旧已确认签名边界和拟发布 Genesis；仅当 RECOVERING/STRICT_REJOIN_GENESIS_PREPARE 或 READY/QUORUM_DURABLE 的严格门禁真实成立才能签名，每次签名前后再核实 ZK，拒绝降级模式冒充严格 ACK。当前隔离 Netty B/旧降级 READY 的错误签名请求正确拒绝，7 新单测通过；仍需自动切换事务、双签名证书保管以及真实客户端 2/2 ACK 验收。

- **T27（2026-10-23 隔离 P000 部分 PASS）** 经 A/B 初始 8/8 严格 ACK、SIGKILL A、B 单节点本地继续 ACK seq9、A Learner 追平后，按真实 ZK CAS 冻结旧授权进入 Epoch3/RECOVERING，等待旧租约隔离并重验两物理 WAL/旧双签名历史前缀，CAS 进入新双副本签名 Genesis 准备；两台 RSA 独立 Netty Receipt 对新 Epoch3/seq9 一致，Common CommitIndex fsync 证书落盘（B 主节点 1035 字节）。仍不应发布严格 READY 或新客户端 ACK。
- **T28（未完成）** 新 Epoch 严格 Genesis 的完整证书须再由第二数据节点独立 fsync 保管并验证真实两节点 Custody ACK，随后接通动态双节点 WAL 复制与 2/2 交易 ACK、READY 事务及失败自动降级回单节点正常交易。当前禁止在正式 Demo 开启自动严格恢复试验开关。

- **T29（2026-10-23：独立 P000 新 Epoch3 双物理数据节点证书 Custody PASS）** B 的 Common CommitIndex 已 fsync Genesis seq9，经真实 Netty 发送给 A/B；两份独立真实 WAL 重新验签并执行本地 certificate fsync/原子安装，各节点 signed custody receipt 由 Common 验证双保管；A/B JVM 全部重启后，通过各自 Netty HEAD_READ 再次验证真实 head.bin（各 1018 B）的一致签名、Seq 和 membership。该过程不发布客户端 READY，实验期写入 503 正确。
- **T30（未完成）** 接入新 Epoch 动态严格写入、同 Epoch B→A 的持久 WAL 复制、每笔客户端 2/2 ACK 与双保管证书更新，成功后原子 ZK READY；随后 SIGKILL 单数据节点自动降级继续交易、恢复节点自动追平并切回严格 2/2，才算完整 Common HA。生产和正式 Demo 禁止启用停在 RECOVERING 的严格切换实验。

- **T31（2026-10-23：隔离 P000 动态 Epoch 严格 ACK→单节点→严格 ACK 闭环 PASS）** 真实 Epoch5 B/A seq13 新交易 code0/appliedCount1/QUORUM_DURABLE，A/B 两独立 WAL hash、CommitIndex 证书与 2 个 Custody head.bin 对齐，重复 requestId 不重复执行；SIGKILL A，B 自动 Epoch6 单节点续写 seq14 code0/quorumDurable=false，A 自动追平；随后 Epoch7 自动 ZK Freeze/双签名 Genesis/双保管/READY，seq15 新交易 code0/quorumDurable=true，A/B 同 WAL hash 和 custody。Demo 181 项测试：180 pass、1 skipped、0 fail。
- **T32（未完成）** 仍需实际不重启 JVM 的多轮重复重新武装测试、Epoch7 严格 B Primary 故障时 A 自动接管和恢复、移除隔离 Demo Epoch8 上界并在更长 Epoch 链持续故障注入、多物理机器故障域、256分区与4节点扩展、10/50/200 租户长期负载 TPS/p99/2-3倍 burst、Order/Trade/MD/Projection 权威资金与成交一致性。未通过前禁止标记完整 Common 生产 HA 完成。

- **T33（2026-10-23 隔离单分区反向主切/严格 ACK PASS）** 在 Epoch7 A备/B主真严格 seq15 后 SIGKILL B，A 由真实 ZK 自动晋升为 Epoch8 主并本地继续真实新交易 seq16 code0/appliedCount1/quorumDurable=false；B 恢复自动追平 A 的 seq16 且 SHA一致，A 自动完成 Epoch9 新签名 Genesis、双证书保管和严格 READY。恢复就绪检查 Epoch1-8 限制后，A 作为严格主的 seq17 首次 TCP 超时，但同 requestId 重试 code0、appliedCount1、无重复；全新 seq18 code0/quorumDurable=true，A/B WAL epoch9/seq18 SHA 一致，两个独立 head.bin SHA 一致，CommitIndex 证书落盘。Demo 全量 181 测试：180通过、1跳过、0失败。
- **T34（仍未完成）** 评估更多真实 Epoch 滚动故障与不重启 JVM 的重复 rearm、完整不同物理故障域、256分区/4节点拓扑的 ZooKeeper 授权规模和负载、10/50/200 tenants TPS与p99、签名及证书双保管批量优化，消除高延迟/客户端 TCP 超时、验证安全重试、订单成交去重和权威资金/持仓/Projection 一致性。隔离 v19 Epoch 上限已统一提升至128，仅验证 Epoch9，不得视为更高 Epoch 或生产 HA 都已验收。
