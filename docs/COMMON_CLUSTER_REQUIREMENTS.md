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

- **T35（2026-10-23：RF2 buddy 256分区本地规划合成基准 PASS）** Common现有PartitionBuddyPlacementPlanner按2节点每个128主、4节点A/B与C/D每个64主、8节点每个32主做单buddy复制；新规划只能PREPARING、不能自行READY；新增本地PartitionBuddyPlacementLoadProbe/ScaleTest，Common commit 786bdbc，40次256分区规划4节点median1.179ms/p99 4.867ms（仅Java规划CPU，不是交易p99/TPS）；Common本地全量423单测全部通过。
- **T36（未完成）** 实际4独立数据JVM、256分区ZK PREPARING和认证READY、两组buddy持续WAL、自动故障注入、10/50/200租户真实负载TPS与p99、2–3倍burst、最终资金/持仓/委托/成交/Projection一致性均需验收。目前Mac磁盘仅剩12–13GiB，虽已安全清理两个停止的旧实验Compose及未引用镜像，宿主空间未显著增加；高压前必须定量处理磁盘资源，不允许删除正式容器卷/当前严格Epoch9证据。

- **T37（2026-10-23：真实3ZK+4JVM的256分区catalog/WAL准备PASS）** 独立Docker 3 ZK、4独立JVM审计，共256 ZK PREPARING、epoch1、version0 assignments；A/B、C/D两组buddy，每节点64主+64备；四个独立WAL卷，每节点128个干净、未提交、无READY授权的WAL；停止重启全ZK后幂等bootstrap及四JVM重新审计通过。Demo189项测试188通过、1跳过、0失败；未运行实际复制或订单。
- **T38（尚未通过）** 去掉v19交易Harness/P000/A-B静态限制，接通动态(分区/节点/epoch)Netty WAL、认证Genesis/CommitIndex及A/B-C/D双custody，分区级ZK版本CAS授权READY；进行真正256分区同步持久ACK、4数据节点主切和恢复、10/50/200租户稳态/burst的真实TPS/p99及资金持仓委托成交Projection权威一致性。磁盘仅约12GiB，200租户高压前应清出真实宿主空间，不能删生产或Epoch9证据卷。

- **T39（2026-10-23：真实四个持续Netty数据JVM与512 RPC PASS）** 隔离3ZK+4JVM，A/B/C/D精确端口35411至35414各独占128本地WAL，实际256分区双目标共512 STATUS RPC，每节点128命中，物理空WAL前缀一致、ZK成员及version0、PREPARING/ready=false校验通过。真实二进制WAL ReplicationBatch到四节点以及COMMIT控制均拒绝。SIGKILL C导致全量探测安全失败，恢复C并重获本地文件锁后512 RPC全部恢复；当前0笔订单、0 READY。Demo193项测试192通过、1跳过、0失败。
- **T40（NO-GO：4节点真实交易HA与容量）** 必须抽象动态分区上下文，接入A/B、C/D各自认证Genesis、持久签名CommitIndex/Custody、ZooKeeper分区级CAS READY与旧主隔离、单分区真正双fsync交易ACK及失效后单节点自动续写，再扩展256分区、10/50/200租户持续下单撤单成交TPS/p99与资金持仓委托成交Projection权威对账。PREPARING不可对外发交易ACK；Mac当前磁盘98%应先保证压测空间。

- **T41（2026-10-23：P000 A/B和P128 C/D启动前RSA双节点证明PASS）** 4个持续Netty JVM各自持久存储2048bit RSA私钥、公钥只在独立ZK create-once绑定；两组真实分区分别以32B随机挑战和当前ZK assignment version0、节点/主备身份及各自clean/空WAL seq0 SHA独立签名并验证，两份证据写入不可覆盖的preflight-evidence ZK节点（读取还须version0），持久ZK重启、4节点重启后原签名重新验证通过。SIGKILL C时当前证明拒绝，恢复C再次通过。全Demo197项测试196通过、1跳过、0失败。真实Common WAL seq1/CommitIndex/双Custody和客户严格ACK尚不存在，不得发布READY。
- **T42（仍未完成）** 在上述A/B、C/D双签名PRECHECK上，接入真正分区级Epoch写入授权与可信空集群Genesis（不能用虚构订单或seq0冒充已提交证书），按旧主fencing与ZK CAS恢复事务写入真实fsync WAL seq1，产生Common验证过的2/2 WAL RSA quorum证书并在两节点独立fsync Custody；之后接入动态 PrimaryWriter+Netty持续复制/严格ACK，真实主切和恢复，最后扩大256分区/10–50–200租户、TPS/p99与资金持仓订单成交及Projection权威一致性。Mac约12GiB剩余，压力测试前需安全释放空间，禁止删正式业务及严格Epoch9证据卷。

- **T43（2026-10-23：P000/P128两组独立物理Genesis WAL和bootstrap双保管PASS）** A/B与C/D各自fsync 108字节非业务Genesis控制帧（epoch1、seq0、分区+成员摘要）；每组两个独立RSA签名及原始ZK证据create-only、各自WAL物理哈希相同。又在四个独立WAL卷fsync不可覆盖的bootstrap custody head.bin，两伙伴hash一致。完整ZK+JVM重启仍可验签和恢复；SIGKILL C期间拒绝，恢复C后通过；256分区512Netty请求仍PREPARING、未授权写拒绝。Demo205测试204通过、1跳过、0失败。
- **T44（NO-GO：Common真实双fsync交易ACK/4节点HA仍待验收）** seq0 Genesis metadata和其bootstrap custody并不等于Common seq>=1 DurableWalCommitIndex业务证书/两节点真正证书保管。须实现安全真实业务seq1、分区授权和旧主fencing、Common签名2/2 commit证书与独立双Custody、ZK CAS READY和客户端严格ACK，并真实杀主恢复及权威业务对账，方可扩至256分区/10-50-200租户TPS/p99/burst；本机剩约11GiB、98%磁盘占用，禁止损坏正式业务或Epoch9证据卷。

- **T45（2026-10-23：双buddy Common正式seq1证书接口本地集成PASS）** P000(A/B)、P128(C/D)读取真实3ZK PREPARING签名RSA成员映射，取得各自2/2 Common Membership，均为同一Mac内JVM而非真实独立物理机。在两个本地独立临时WAL文件fsync相同Demo业务seq1，调用Common DurableWalCommitQuorum签名、DurableWalCommitIndex fsync证书、双Common DurableWalCertificateCustody独立持久化，并在释放/重新获取WAL锁后重新校验通过；缺失副本、WAL分叉和授权撤销拒绝。Demo209项测试208通过、1跳过、0失败。尚非四Docker实际业务复制或订单。
- **T46（仍NO-GO：真实Netty写入、严格ACK、4节点故障与性能）** 必须把已有Common正式双WAL/证书/双Custody机制接入两组四个真实常驻Netty数据容器和分区级真实ZooKeeper授权，验证签名Genesis后的同一seq1数据在两节点分别真实fsync，收齐RSA receipts、CommitIndex和两份真正Common Custody并在当前ZK水位/fencing复核后CAS READY、返回客户端严格2/2 ACK。随后SIGKILL主备、自动恢复以及256分区/10–50–200租户实测TPS/p99与Order/Trade/MD/Projection资金持仓委托成交权威一致性。现有全部真实Docker分区依然PREPARING，禁止把JUnit模拟交易认证当作已上线。

- **T47（2026-10-23：2组真实Netty WAL的Common提交及双正式Custody PASS）** 独立3ZK和4个持续Netty JVM中P000 A/B、P128 C/D分别真实fsync固定内部Demo seq1 WAL，分别独立RSA Common DurableWalCommitQuorum签名，主节点持久Common DurableWalCommitIndex，两个不同数据节点各自Common DurableWalCertificateCustody.install并signInstalled，经DurableWalCustodyQuorum.verify核实真正2/2双保管。两组独立WAL/Custody SHA一致，全量重启3ZK+4JVM后仍通过；SIGKILL C使P128当前复核失败，恢复C通过；256分区/512状态RPC仍通过，全部READY=false/0真实订单/禁止普通Binary WAL。Demo214测试213通过、1跳过、0失败。
- **T48（仍NO-GO：真实交易、自动主切及容量）** 真实Netty seq1是固定内部Demo指令且四节点都在同一Mac，尚未提供独立物理故障域。必须集成动态分区ZK Epoch/版本授权、旧PRIMARY fencing、已证实Common双节点持久提交与两正式Custody同ZK CAS READY/发布隔离，并执行真正Order/Trade下单撤单撮合严格客户端ACK、自动主切/单节点降级续写、恢复副本重新追平、256分区/4节点与10/50/200租户TPS/p99及资金持仓委托成交Projection一致性。内部DEMO_V19_FOUR_NODE_INTERNAL_SEQ1=1仅准隔离实验，不能用于生产；磁盘清理后可用55GiB，但Order A/B共76GiB正式WAL仍须按可信Snapshot归档水位谨慎回收。

- **T49（2026-10-23：四节点现有验收复测通过；Epoch Fencing 仍未完成）** 本次只读复测保留原三ZK、A/B/C/D四个Netty JVM、原有256个PREPARING assignment及物理WAL/Custody卷：P000 A/B、P128 C/D的Common RSA绑定成员均为2/2，且明确 ready=false/clientAck=false；全256分区512次真实TCP Status查询、按节点128次以及全部未授权binary WAL写拒绝再次PASS。原Demo Maven52 suites/214 tests，213通过、1跳过、0失败。全部实验容器随后停止，正式Order/Trade/MD未操作，剩余空间约54GiB。本轮尝试添加隔离ZK旧Epoch控制及只读准入审计代码均被平台安全检查拦截，核实未产生相关源码文件，**不能将Epoch Fencing/自动READY/主切标记为通过**。正式接入顺序仍是：(a) 分区旧主失权、独立ZK lease与CAS fencing真实注入通过；(b) 两节点持续业务WAL/双Common正式Custody与分区READY发布原子门禁、严格客户端ACK通过；(c) A/B及C/D主故障自动接管、单节点安全运行、重新同步与一致性对账通过；之后Order和Trade分别状态机业务验收，最后10/50/200租户及burst。Order/Trade业务状态机接口设计可与(a)-(c)并行，但正式部署验收不能提前放行。

- **T50（2026-10-23：四节点只读分区准入门禁新增并通过）** 新增 DemoV19FourNodeAdmissionVerdict 纯判断及专项JUnit，逐项检查 READY、Primary、Epoch、控制租约、旧发布者隔离、匹配双WAL水位、最新双Custody与独立物理故障域；接入 --common-membership 的只读ZK成员验收。真实隔离三ZooKeeper读回P000(A/B)与P128(C/D)两个2/2 RSA成员配置后，分别输出 FOUR_NODE_ADMISSION_DENIED，原因包含 NOT_READY、NO_CONTROL_LEASE、OLD_PUBLISHER_NOT_ISOLATED、FAULT_DOMAINS_NOT_INDEPENDENT，clientAck=false，未执行ZK写入。Demo全量53 suites/219 tests，218通过、1跳过、0失败。源码三文件快照 tests/patches/common-v19-four-node-readonly-admission-20261023.tar.gz 配套SHA256清单已逐字节核对。该纯判断不代表已实现ZK分区CAS写入授权、旧主物理隔离、生产READY/ACK或自动故障切换；仍须在真正逐请求fencing与恢复事务落地后才能开始正式Order/Trade HA验收。隔离ZK停止，证据卷和正式服务不变。

- **T50（2026-10-23：纯函数RF2准入门禁边界单元测试PASS，实际ZooKeeper旧主隔离仍未通过）** 在隔离Demo中审查既存的 DemoV19FourNodeAdmissionVerdict（只读纯Java missingProofs），增加对非法RF2成员数量、主备节点同名、自引用、负数配置版本的拒绝条件；专项验证P000/P128现有PREPARING均缺少READY、租约、旧发布者隔离和独立物理故障域等关键证据；合成READY测试对象只验证纯函数边界，不读写真实ZK、不产生交易ACK。Demo Maven全量53 suites、219 tests，218 PASS、1 SKIPPED、0 failures/errors。对应两个Java/测试文件快照 tests/patches/common-v19-4node-pure-admission-verdict-20261023.tar.gz 和同前缀SHA256清单已解压逐字节比对。**该校验器不是动态ZooKeeper控制租约或CAS fencing的实现，也未挂到实际交易写入路径；不能据此放行Trade/Order生产HA。** 本轮对实际ZK Epoch Fencing及只读审计源码操作遭执行环境安全检查拦截，未创建那两个组件。剩余机制仍为真实分区Epoch旧主隔离、严格READY/ACK、自动主切/副本追平；之后Order/Trade权威业务验收及10/50/200租户负载。原正式服务、持久证据卷保持不变。

- **T51（2026-10-23：Common控制器租约同名碰撞与断线重授权修复PASS）** 检查 ZkPartitionFailoverControlPlane 发现旧 tryAcquireLease/hasLease 仅比较可复用的 ownerId 字符串，相同逻辑ownerId的不同控制器进程可能误认相同临时租约。本地Common Git提交 3d6fad0 改成每个控制器对象独立随机 leaseToken，只有亲自成功创建的ZooKeeper临时租约才允许通过 hasLease；观察到租约消失、被其他会话替换、ZK断连后，旧对象永久失权，不能直接重新获得原授权或删除替代者临时节点，需新的控制器对象及重新认证。新增两控制器同名竞争、替代租约、断网重连旧实例不可重获租约的专门JUnit负例。Common全量 **98 suites /426 tests、0失败0跳过**，本机重新安装Common 3.0.22-SNAPSHOT jar后Demo全量 **53 suites /219 tests、218通过1跳过0失败**；源码双文件及sha256清单快照 tests/patches/common-zk-controller-unique-lease-revocation-20261023.tar.gz 已独立临时目录逐文件验证。该修复属于Common通用ZooKeeper控制器级租约隔离，**尚不等价于真实P000/P128动态分区Epoch fencing、双物理宿主证明、分区CAS READY/严格客户端ACK及自动主切恢复**；四节点实验仍全PREPARING/NO-GO。未修改正式Order/Trade/MD/MySQL或任何WAL/ZK数据卷，不使用GitHub Actions/中央仓库发布。本轮本地测试生成构建缓存后Mac可用约50GiB，压力测试前继续关注。

- **T52（2026-10-23：真实三ZooKeeper同名控制器租约与失联替代验证PASS）** 为通用租约修复提交新增隔离 DemoV19ControllerLeaseSmoke，实际启动旧v19隔离项目三台独立ZooKeeper容器，由两个独立ZooKeeper客户端会话以同一逻辑ownerId创建/竞争唯一临时控制租约：第一控制器获取，第二控制器被拒绝；第二控制器关闭不会删除第一租约。随后实际关闭第一控制器背后的ZooKeeper会话，检查旧控制器已失权，新会话的新控制器获取租约成功，旧对象不能重新获取、也不能在关闭时删除新租约。输出 THREE_ZK_REAL_SAME_OWNER_CONTROLLER_LEASE_PASS，全部三ZK容器已停止并保留原持久卷。此测试仅在独立随机lease路径创建临时控制节点，未修改256个partition assignments/READY/WAL，正式业务Order/Trade/MD/MySQL均未操作。此项是控制器单租约防冒领及旧会话失权的真实ZK验收；**尚未验证每个业务分区独立Epoch CAS、旧业务Primary隔离、可靠自动主切、READY/客户端ACK**。新增单Java文件源码归档 tests/patches/common-zk-real-three-node-lease-session-failover-20261023.tar.gz 及SHA256校验清单，已独立解包逐文件字节核对。此前Common全量426测试及Demo219测试回归结论保持有效。

- **T53（2026-10-23：Common分区Epoch/ZK版本读栅栏及独立三ZooKeeper临时分区CAS实测PASS）** 新增Common PartitionEpochReadFence：真实数据Primary在已存在READY和本地状态恢复的前提下，从AssignmentStore取得绑定分区、ZK stat.version、Epoch、assignmentVersion、精确Primary与RF2唯一备份的不可变校验Ticket；每次需重新读取ZK版本/成员/READY/本地恢复状态，遇到版本变化、过期Primary、配置分叉、ZK断线、PREPARING/RECOVERING状态一律拒绝。本地Common Git branch feat/common-durable-wal-quorum-20261022 提交 5b30f4d；新增5项正反单测（ZK版本CAS、旧Epoch、备节点未恢复、缺ZK/本地READY/非法RF2）。Common全量 **99 suites /431 tests、431 PASS、0失败**；本地安装新版Common JAR后原Demo全量 **53 suites /219 tests、218 PASS、1 skipped、0失败**。此外通过Demo DemoV19EpochCasReadFenceSmoke 启动原隔离Docker的**3个真实ZK进程**、两个独立ZK会话，仅创建随机唯一临时测试root下的合成P000 READY/Epoch41/版本0，并真实CAS到Epoch42/RECOVERING/版本1。原Primary的旧Ticket拒绝，旧版本CAS冲突拒绝，新Primary RECOVERING阶段拒绝，本次真实256个P000–P255 assignments、原WAL、Cert/Custody均**未触碰**；最后隔离三ZK停机。快照 tests/patches/common-v19-partition-epoch-read-fence-20261023.tar.gz 及配套sha256包含两份Common源码/测试+一份Docker烟测源码，已安全解包逐字节核对。
  - **严格边界（NO-GO）**：本轮实现的是Common可复用、只读的过期Epoch和ZK版本拒绝前置门禁，且隔离真实CAS发生在**随机测试路径而不是现存P000/P128实际运行分区**；没有把栅栏挂到四个Netty数据写入者真正的持久化提交写屏障中，也不能保证简单ZK重读与WAL写入之间不会并发发生新的CAS。尚需控制器可信持有写入屏障/撤销事务，确保任何旧Primary在CAS转移后不能继续持久化/签名或发布，继而两副本真实Common CommitIndex和双Custody水位对账后分区CAS READY、严格客户端ACK及A/B C/D自动切换追平。正式Order/Trade/MD/MySQL未修改、不启动GitHub Actions、不发布中央仓库，保留旧Epoch9八卷和四节点十卷。

- **T54（2026-10-23：4个真实Netty节点严格客户端写入入口 fail-closed PASS，正式Epoch写屏障仍NO-GO）** 承接 T53 的Common PartitionEpochReadFence（绑定真实ZK stat.version、Epoch、Primary、RF2成员关系、本地READY），本轮在隔离 Demo 的 DemoV19FourNodeLiveRuntime 真正加入独立新Netty STRICT_CLIENT_WRITE_ADMISSION_V1 入口，使用真实ZookeeperClient和ZkPartitionFailoverControlPlane读取分区赋权，核验精确服务/分区/32字节请求、当前物理成员、Common ReadFence/local recovery及独立控制器租约。当前全部256个实际ZK assignment均PREPARING、不具备真正controller lease和local READY，入口一律明确拒绝；即使未来这些只读检查通过，该入口也仍显式拒绝直到真正严格客户端写入者和原子化Epoch发布屏障接通，**不会凭一次ZK检查返回成功**。只限内部模拟指令的旧 INTERNAL_SEQ1_* Netty试点保留在另一路径，继续严禁任何真实Order/Trade业务绕过严格准入。实际隔离Docker启动三ZK及A/B/C/D四数据JVM，P000的A/B、P128的C/D共四次真实Netty严格客户端写入请求全部拒绝，原每节点物理WAL seq1/hash前后一致、ready=false、没有订单客户端ACK。256分区/512次物理Netty角色状态RPC再通过，未经授权binary WAL批次仍全部拒绝。新增 DemoV19FourNodeStrictWriterGateTest 请求白名单、错服务/错分区/错长度/内部opcode冒充与PREPARING角色测试；Demo全量 **54 suites/221 tests，220 PASS、1 SKIPPED、0 failures/errors**。归档 tests/patches/common-v19-4node-strict-client-writer-admission-20261023.tar.gz 与配套SHA256清单含准确三份Java源码及JUnit测试，安全解包逐字节验证通过。隔离三ZK+四数据JVM全部停止，十个四节点数据卷和旧Epoch9另八卷保留，生产Order/Trade/MD/MySQL正常，Mac约49GiB空闲，无GitHub Actions。**尚未完成正式生产Order/Trade状态机适配、跨节点原子CAS写屏障、动态旧主fencing后的真业务持续写入、READY和严格2/2 ACK，更未完成自动主切恢复/负载；完整四节点交易HA仍NO-GO。**

- **T55（2026-10-23：Common单JVM分区Epoch提交与协作式CAS互斥屏障PASS；跨节点真实业务Fencing仍NO-GO）** 承接T53分区只读Epoch Fence与T54真实Netty客户端准入拒绝，新增通用Common PartitionEpochCommitBarrier，要求单分区在同一Java进程内的WAL/证书/Custody提交函数和协作式控制器撤权CAS共享公平写锁。提交动作前后分别验证当前ZK stat.version、Epoch、assignmentVersion、当前Primary及RF2成员、本地READY与控制租约；异常/旧CAS/掉线即本地永久撤权，不提供客户端成功结果。控制器 drainAndCasRecovering 等待进程内所有已有提交完成，之后不可逆关闭旧主本地READY，再按原ZK stat.version CAS新Epoch RECOVERING，不发布READY、也不自动接纳新主。并发JUnit验证CAS无法超越正在执行的本地提交；外部非协作ZK CAS在提交中途修改版本时，提交后检查会拒绝客户端成功并保留需后续恢复的未确认写入；额外验证控制租约丢失、无效继任Epoch、CAS版本冲突等全fail-closed。Common本地Git commit 0151eed，**100 suites/435 tests，435通过、0失败**。Demo保持兼容，**54 suites/221 tests，220通过、1跳过、0失败**。
  - 在独立的3个真实ZooKeeper容器、两个真实ZK会话上运行 DemoV19EpochCommitBarrierSmoke --test-only，两种场景均PASS：(1) COOPERATIVE：在随机临时测试assignment下，CAS等待被延迟的模拟提交结束，随后由epoch41/zkVersion0升为epoch42/RECOVERING/zkVersion1，旧主对象失权，新主RECOVERING不READY；(2) EXTERNAL：非协作第二控制器在模拟提交期间完成真实ZK CAS，旧主体在返回前的二次版本检查拒绝成功，后续不能再次写入。仅使用测试模式/模拟工作步骤，**没有真实业务WAL写入或交易ACK**，没有修改原256份P000–P255实际assignment或真实P000/P128 WAL/CommitIndex/Custody；实验三ZK停止、证据卷保留、正式Order/Trade/MD/MySQL未变。三份阶段Java源码（Common屏障+JUnit，Demo三ZK冒烟）归档至 tests/patches/common-v19-local-epoch-commit-barrier-20261023.tar.gz 及sha256清单，独立安全解压逐字节核验。
  - **未达准入**：该锁只覆盖共享同一Barrier对象的本地JVM线程，无法序列化远端控制器的ZooKeeper CAS或四个不同物理数据节点。外部CAS后旧端可能已有未确认持久WAL副作用，只能拒绝客户端ACK并走确定恢复；仍须补跨进程物理节点确认的old-primary撤权/独占发布屏障，禁止CAS切换后旧主写入/签名，绑定真正双节点Common证书/Custody水位再行严格READY/2/2客户端ACK、自动主切追平。四节点真实业务HA仍NO-GO，未使用GitHub Actions。

- **T56（2026-10-24：真实四JVM跨节点旧Epoch持久撤权及RSA双签名证明PASS；新Epoch恢复/READY仍NO-GO）** 在此前P000(A/B)、P128(C/D)的两真实物理WAL seq1 fsync、Common双RSA提交收据、CommitIndex及两份正式Common Custody基础上，新增独立DemoV19FourNodeRemoteRevocation。仅对两个已有非业务试点分区：先核对真实ZK成员、各节点seq1物理WAL hash/双Custody，再在ZK old-epoch1-revoke-intents create-only登记不可覆盖撤权意图，两个独立Netty JVM在各自独占WAL FileLock下同步原内部seq1签署路径、验证本地Common Custody证书/双签名及同一WAL水位，分别fsync不可覆盖本地.pilot-old-epoch-revoked-Pxxx/head.bin后对(分区,节点,旧epoch1,成员摘要,certified WAL SHA,本地撤权head SHA,nonce)独立RSA签名。协调者用ZK原始公钥验两个不同签署者的2/2证明，再create-only持久化old-epoch1-revoke-proof到三ZK。ZK意图产生后原内部WAL fsync、RSA提交签署/CommitIndex和旧Custody安装请求都拒绝；即使ZK证据缺失但本地撤权文件目录还在，也拒绝恢复旧签署权。所有256个业务ZK assignments仍为epoch1/version0/PREPARING，没有伪造新的epoch2/READY或真实订单ACK。
  - 实际隔离Docker 3ZK+4个独立数据JVM：SIGKILL C测试中P000的双节点撤权证明通过，但P128因缺C节点未能形成有效双票，系统fail-closed；恢复C后原P000证明可再验，P128得到2/2 RSA签名、两份fsync旧主撤权证明。完整停止/重新创建四JVM后，两组原始ZK不可覆盖RSA证明及本地文件继续复核，四个物理节点的旧FSYNC、CERTIFY、CUSTODY这三类Netty写入口共12请求全部拒绝，WAL seq1及hash无改变。A/B旧撤权文件SHA256均为57a0bdfd8abc8f8850f4d76ad0805599d8e49df19c94bc682959436d7f1b537e；C/D均为7efbf3fa6c301b7f589c2b81c429abf6be445243e9e13bb540188df191fd5488。之前256分区512真实Netty只读状态检查继续PASS、全部PREPARING；Demo Maven **55 suites/226 tests，225 PASS、1 SKIPPED、0 failure/error**，涵盖修改、伪造、残留pending、永久失权即使head缺失等负面用例。源码4文件快照tests/patches/common-v19-four-jvm-dual-epoch-revocation-20261024.tar.gz及同前缀sha256清单，独立安全解压逐文件字节相同。
  - **仍NO-GO**：本轮为单Mac Docker VM内两个非交易试点P000/P128的旧source epoch1撤权证明，四JVM物理故障域并不独立；并未将真实业务动态分区ZK assignment CAS提升到epoch2、未让新Primary从Snapshot/WAL recovery至安全水位、未完成新epoch2双Custody/原子READY和真实交易客户端严格ACK/自动主切。因此不得报告正式Order/Trade集群完成或订单TPS数字，也不启动200租户压测。下一步必须把已完成的双撤权证明引入真实分区Recovery事务、epoch2版本CAS/可信Image安装/双节点追平，隔离旧发布者，最后才是READY及ACK、自动故障与业务权威对账。实验三ZK/四JVM均停止，四节点10卷与旧Epoch9八卷保留，正式Order/Trade/MySQL正常，Mac余49GiB，未使用GitHub Actions。

- **T57（2026-10-24：真实四Netty节点Epoch2双恢复候选镜像与RSA ZooKeeper证明PASS，仍未CAS激活）** 在T56已完成P000（A/B）、P128（C/D）的旧Epoch1源WAL seq1、双Common CommitIndex证书与双正式Custody及两物理JVM fsync、2/2 RSA撤权基础上，新增DemoV19FourNodeEpoch2Image与隔离Netty受限OP：必须先重新验证真实ZK的旧Epoch撤权intent及两份RSA签名原件、本地旧撤权head.bin与当前认证WAL前缀字节一致，读取各自独占文件锁的已提交旧source WAL、从DemoStateMachine生成二进制Snapshot并由新的StateMachine恢复校验stateDigest/total/请求唯一性；两JVM在自己卷内分别create-once fsync新的epoch2候选镜像candidate.bin，独立RSA签名成员摘要、旧wal SHA、image SHA、候选文件SHA与随机挑战；控制端两签名核实后ZK create-only保存不可覆盖的双镜像恢复证明。镜像仅为FROZEN状态来源，无新业务写入、无二次应用。初次SIGKILL C时P000可完成但P128缺C票拒绝，C恢复后P000/P128均通过。整个3ZK+4JVM停机后使用原卷再启动，重新校验两镜像文件、两独立RSA签名和ZK证明，P000 A/B候选镜像文件SHA256均c046c8753cb89b38ae5e036e2732bae796f2000d6ccee530a561d5688c8aee82、镜像数据SHA256均a7f6beb08b5645b07405d0412b299b7d74c15ffaf612d7360d0651e970e7e296；P128 C/D候选文件SHA256均ce55bc8339b51e2b75b1e9d9ecc59e2d181e389fea293d746e57361e239、镜像数据SHA256均dfcfe1900be5956e6bb1b1bd41944c4de8cfe2626838206ba09dc4efe2bedf1b。旧FSYNC/CERTIFY/CUSTODY四节点共12拒绝与256分区/512真实Netty TCP只读检查仍PASS。Demo Maven **56 suites /229 tests，228 PASS、1 SKIPPED、0 failures/errors**，新增不可覆盖候选文件、篡改/pending防护、WAL精确seq1和Snapshot replay单测。四份Java源码与JUnit测试快照为tests/patches/common-v19-four-jvm-epoch2-recovery-image-20261024.tar.gz及sha256校验文件，独立目录安全解压字节完全一致。实验容器全部停止，10个四节点卷及旧Epoch9的8证据卷保留；正式Order/Trade/MySQL/MD运行，Mac磁盘余约38GiB（使用率92%），不使用GitHub Actions。
  - **准确未完成/NO-GO**：本轮仅准备好两份Epoch2恢复候选和可信2/2证书，真实原256份ZooKeeper assignments仍旧是epoch1/version0/PREPARING，没有执行P000/P128到epoch2 RECOVERING的受控ZK CAS，也没有新epoch恢复事务安装至交易状态机、旧Primary原子发布隔离、READY或真实交易ACK。下一关要验证候选证明及本机不可篡改镜像之后，安全地CAS变更所选分区到新epoch2/RECOVERING、让ZK bootstrap/本地WAL/status在完整停止重启后识别合法新epoch并拒绝旧签名，再依完整恢复/双Custody水位考虑READY；自动故障切换与Order/Trade一致性及租户压测仍尚未执行。

- **T58（2026-10-24：两个真实隔离分区Epoch2/RECOVERING版次CAS与完整服务重启验收PASS；READY仍NO-GO）** 接续T56两个分区旧epoch1物理双撤权RSA证明及T57 A/B、C/D各自fsync的两份冻结Snapshot+两份恢复RSA证明，本轮新增隔离 DemoV19FourNodeEpoch2Transition，依据旧ZK不可变撤权2/2签名、两个本地镜像候选2/2签名、成员公钥与旧WAL SHA重新完整校验，构造恰好一个安全后继：P000原主A->恢复主B、P128原主C->恢复主D，epoch1->2、assignmentVersion0->1、ZK stat.version0->1、state仅RECOVERING。由真实ZK控制器唯一租约及compare-and-set执行原隔离256分区Assignments的受控写入，只改P000和P128两份记录，其他254保持原PREPARING/version0。任何READY、非两个试点分区的CAS、签名或配置不匹配均拒绝。
  - 使用隔离3 ZooKeeper+4数据JVM真实执行，两条输出FOUR_NODE_EPOCH2_CAS_RECOVERING_PASS：P000 A->B 与 P128 C->D，分别真实CAS成功。立即核验256分区/512 TCP status RPC，准确识别新主和恢复状态、无写入、客户端ACK为0。再**完整停止全部三ZK和四JVM**并用原持久数据卷重启，bootstrap与每个JVM启动时要求检查恢复ZK双RSA证明、当前old source WAL seq1/哈希与本机epoch2候选镜像文件哈希完全一致（缺镜像无法进入服务）；重试CAS两个分区返回idempotent=true且version仍为1；全部256分区512 Netty状态检查再次PASS；四数据JVM旧epoch1的FSYNC/CERTIFY/CUSTODY合计12个请求仍拒绝，WAL未变化。所有恢复镜像、撤权ZK签名与原WAL数据卷保留；整个隔离服务组最后停止。
  - Demo全量Maven **57 suites/231 tests，230 PASS、1 SKIPPED、0 failures/errors**；四份本轮增改Java与JUnit源码 tests/patches/common-v19-four-jvm-epoch2-zk-cas-recovering-20261024.tar.gz 和配套sha256清单已独立临时目录安全解包逐文件核对。
  - **边界仍NO-GO**：当前两个分区仅有epoch2 RECOVERING ZK授权与两个已签名恢复镜像，尚未将image安装为真正新epoch2可写业务WAL状态/权威Snapshot+WAL恢复事务；未建立新epoch2真实双Common CommitIndex/双Custody的后继认证、控制器自动升主、旧发布者绝对隔离下的原子CAS READY/严格2/2客户端ACK。因此不得作为完成Order/Trade生产HA，也未运行任何真实交易TPS或200租户压测。其余254分区仍PREPARING。四节点同处一台Mac不构成独立物理故障域。本轮不修改正式Order/Trade/MySQL/MD，不删除4节点10卷和旧Epoch9八卷，不使用GitHub Actions；磁盘余约38GiB，使用率92%，需要继续关注日志归档回收但不得误删生产WAL。

- **T59（2026-10-24）**：隔离四JVM完成P000/P128两份Epoch2快照WAL的持久恢复安装、独立节点2/2签名校验及ZooKeeper证明持久化。完整三ZK+四JVM重启后仍验证通过，旧Epoch请求12/12拒绝、256分区512次Netty状态请求通过。JUnitCore全量233 tests通过。归档：tests/patches/common-v19-four-jvm-epoch2-recovery-install-t59-20261024.tar.gz及SHA256。尚未完成新Epoch Common CommitIndex/双Custody、READY/真实交易ACK与自动主切，完整HA继续NO-GO。

- **T60（2026-10-24）**：对已安装的P000(A/B)、P128(C/D) Epoch2 Snapshot WAL，实际使用Common DurableWalCommitQuorum进行两个独立RSA提交签名；新Primary B/D分别持久化DurableWalCommitIndex，两位Custodian各自安装/签名DurableWalCertificateCustody，并通过DurableWalCustodyQuorum独立验签（两分区均seq1、双票双Custody，PASS）。源数据、成员摘要及签名写入不可覆盖的三ZK证明。完整三ZK+四JVM停机重启后，所有节点从本地Common存储重新认证通过；旧Epoch请求12/12拒绝、256分区512 Netty状态RPC PASS。SIGKILL C后P000保持证明有效、P128因缺C拒绝重新认证，恢复C后两分区重试PASS。JUnitCore全量233 tests通过。源码归档：tests/patches/common-v19-four-jvm-epoch2-common-cert-custody-t60-20261024.tar.gz及SHA256。仍为RECOVERING、routable=false、clientAck=false。此结果是两试点的真实Common认证，**不是READY、真实交易ACK或自动主切**；完整Order/Trade HA仍NO-GO。

- **T61 第一阶段（2026-10-24：跨JVM READY发布前的严格运行时屏障PASS；READY/交易ACK仍NO-GO）** 新增DemoV19FourNodeReadyPreflight及Netty独立OP：只允许P000(A/B)、P128(C/D)处于真实ZK Epoch2/version1/RECOVERING的两个分区，分别让两个JVM重新检查本机独立恢复WAL、旧Epoch源WAL seq1、原始旧主永久撤权文件完整字节、Common Epoch2 CommitIndex及双Custody的不可覆盖证明，挑战nonce签名后用ZK固定RSA公钥验两位不同JVM的响应。真实隔离三ZK+四JVM两分区各2/2 PASS；SIGKILL C时P000不受影响而P128无法通过，未产生READY，恢复C后重试正常；随后整组三ZK+四JVM持原证据卷重启，P000/P128双节点预检继续PASS、旧Epoch12/12请求拒绝、四客户端入口拒写、256分区512次Netty状态查询PASS。JUnitCore全量233 tests，0 failures。源码及SHA256：tests/patches/common-v19-four-jvm-epoch2-ready-preflight-t61-20261024.tar.gz。**注意**：本阶段仅是发布前运行时准入，不是CAS READY；现有严格客户端写处理器仍硬拒绝，即使控制器发布READY也不能安全声称ACK成功。四JVM同一Mac，不能作为跨宿主故障域证明。尚缺与READY原子隔离的真实新Epoch业务写入/ACK、自动主切/角色反转，完整HA仍NO-GO。

- **T62（2026-10-24：真实非交易Epoch2 seq2双节点物理提交/签名Common CommitIndex/双Custody PASS，READY/正式业务ACK仍NO-GO）** 隔离四 JVM P000(A/B)和P128(C/D)均从已认证seq1恢复Snapshot WAL生成独立active WAL，实际通过Netty依次在两个JVM fsync PREPARE(epoch2,seq2)，再分别fsync COMMIT(epoch2,seq2)并apply状态机（两个独立持久commit；只使用固定非交易requestId和测试delta，无订单），共同确认物理WAL/状态哈希相等后分别产生Common DurableWalCommitQuorum RSA签名、新主B/D的DurableWalCommitIndex，以及两份物理DurableWalCertificateCustody；保存两分区不可覆盖ZK证书。重启时根据ZK签名反查各节点自身active WAL、状态摘要、Common提交索引和本机Custody；与安装的原始Epoch2 seq1可信镜像分开持久化，旧Epoch1源WAL保持原样。P000 seq2 SHA256=7b1f524c22e61a72606ed14ae930aa8f1b9d1c87b30071d90a3cfde5058c4807，P128=d4e80e01e99baa90acf5829c60863d9afca57816c6906970b708c37ed1887825。三ZK+四JVM全部停掉再使用原卷重启，四节点通过自身Common/seq2恢复验证，幂等重跑两个分区均PASS且没有重复生效；SIGKILL C使P128不能完成2/2重新认证、P000不受影响，恢复C再重试通过。旧Epoch fsync/CommitIndex/Custody 12/12拒绝，严格客户端4/4拒写、256分区512 Netty status PASS。新增的JUnit精确覆盖PREPARE后进程退出及恢复COMMIT、相异requestId劫持拒绝；全量59类235 tests PASS、0 failures。源码快照 tests/patches/common-v19-four-jvm-epoch2-real-seq2-commit-t62-20261024.tar.gz 与sha256逐文件匹配。本轮虽然实现了真正的demo状态机写入/两份持久Commit，但仍仅限内部隔离非交易操作：**ZK仍RECOVERING、没有真实用户交易ACK、没有与READY的原子发布/写入绑定、也没有自动主切与角色反转**。这些属于后续T63+，不应报告200租户TPS或生产HA GO。

- **T63（2026-10-24：真实Epoch2 seq1→seq2单链Common CommitIndex及四节点Custody水位修复PASS，READY仍NO-GO）** 发现T62使用不同的seq1/seq2提交索引及Custody目录，不能证明权威连续提交链；本轮改为复用同一Common DurableWalCommitIndex目录，seq2必须有已认证seq1作前序，由Common链条重放校验前序哈希，不能单独从空索引认证seq2。四个节点各自的Custody也从Common seq1账本安装/持久化seq2水位，签名和证书仍严格复核现有ZK双物理JVM证明、WAL/State哈希。真实隔离3ZK+4JVM停机后进行有界离线证据迁移：P000新主B、P128新主D两份Common连续索引PASS；A/B/C/D四份Common Custody从seq1推进到seq2 PASS，源Epoch1 WAL及旧证据卷未改写。四数据JVM启动、全部3ZK+4JVM停启后的本地恢复验证PASS；两个分区seq2复验及幂等重跑PASS；SIGKILL C时P000可继续验证而P128缺第二节点确认拒绝；旧Epoch12/12拒绝、严格客户端4/4拒绝、256分区512Netty状态查询PASS。JUnitCore全59类235项PASS、0失败；3份源码SHA256存档tests/patches/common-v19-four-jvm-epoch2-contiguous-index-custody-t63-20261024.tar.gz。**仍仅内部非交易写入，ZK仍epoch2 RECOVERING/ready=false，真实交易ACK、自动双向切换、单节点降级与Order/Trade一致性均未通过；全量HA仍NO-GO。**

- **T64（2026-10-24：最新Epoch2 seq2双JVM在线签名与真实控制器租约发布屏障PASS，READY/ACK尚未发布）** 继T63统一Common CommitIndex/Custody后，发现T61发布预检RSA仍锁定旧seq1，不能授权新seq2提交头。本轮新增DemoV19FourNodeEpoch2ReadySeal，严格要求当前ZK分区Epoch2/version1/RECOVERING，2个独立JVM各自重新验证本地Epoch1永久撤权完整字节、本地可信Epoch2 active WAL seq2及真实State Digest、seq1→seq2 Common CommitIndex、各自Common seq2 Custody、ZK不可覆盖2/2 WAL认证和可信RSA身份，再对fresh nonce + seq2 SHA + state SHA + membership + 证书SHA做RSA签名；控制器在确实持有活跃ZK ephemeral lease期间收集和验签两份响应，保存不可覆盖的ZK READY发布前证据，验签结果本身明确ready=false、clientAck=false。真实3ZK+4Netty两个分区P000(B/A)、P128(D/C)均2/2 PASS；SIGKILL C后P000仍能重新验证、P128不可获取第二节点签名并拒绝，而不是虚假READY；3ZK+4JVM完整停启后双分区再次PASS，旧Epoch12/12拒绝，严格客户端4/4拒绝、256分区512次Netty status RPC PASS。新增3个针对旧seq1/篡改nonce、member/伪造READY或ACK位的负向JUnit，现共60类238 tests PASS、0 failed。归档tests/patches/common-v19-four-jvm-latest-epoch2-ready-seal-t64-20261024.tar.gz及SHA256，逐文件安全解包byte compare通过。本轮不是自动READY：还没有完整动态交易提交/ACK和原子撤权机制，不应因为已获双签发布预检就修改ZK READY，生产HA及200租户压测仍NO-GO。

- **T65（2026-10-24：复用Common双Custody严格业务ACK Gate接入4JVM请求入口，RECOVERING正确拒绝，READY/新请求写入仍NO-GO）** 不再重复独立签名预检，新增DemoV19FourNodeEpoch2StrictAck并在P000/B及P128/D的真实Netty Control入口部署现有Common `DurableWalCertificateCustodyAckGate.requireDurableBeforeAck`与`DurableWalCommitAckGate.requireDurable`，用实际已写入Epoch2 seq2 WAL、单链CommitIndex、两份有RSA签名Custody及最新ZK Epoch2 READY seal逐一验证。严格从客户端payload取`requestId`、`delta`、`epoch`、`sequence`，借助物理`DemoDurableJournal.requireForcedCommitted`校验精确序号对应的请求及数额，不允许单纯复用签名水位对未提交请求、被篡改delta或旧Epoch返回成功ACK；调用`PartitionEpochReadFence`进行ZK当前PRIMARY/READY/本地READY版本核验。当前原ZK仍为epoch2/version1/RECOVERING，因此实际双分区通过Common双Custody验证后，在最终授权检查阶段返回`EPOCH2_STRICT_ACK_NOT_READY`、`PARTITION_EPOCH_FENCED`，四JVM均不发业务ACK；伪造requestId、变动delta、旧Epoch与无效payload分别在适当阶段拒绝。真实隔离3ZK+4Netty两分区在线探测PASS；SIGKILL B后P128仍独立完成上述拒绝验证，P000无法通过B的RPC且不产生伪ACK；B恢复后全3ZK+4JVM停止/保留原卷重启，再次P000/P128 PASS。新3项JUnit覆盖非法epoch/seq、空req、小数/越界金额、错误partition/空payload，61类241项JUnit PASS、0失败。源码快照`tests/patches/common-v19-four-jvm-exact-client-common-ack-gate-t65-20261024.tar.gz`及SHA256字节比对PASS。**真实Strict ACK底层已连接，但没有真正新业务写入动态seq3、没有READY CAS或源端写入原子撤权，仍然没有任何成功交易ACK、自动双向主切或单节点降级**；这个里程碑只能叫ACK拒绝边界正确，不能叫完整HA GO。

- **T66（2026-10-24：真正的 Common RF2 单分区 A↔B 双向自动主切、双Custody READY、成功客户端ACK、完整重启及去重 PASS；正式业务集成仍NO-GO）** 这轮不再继续四节点预检，直接复用现有 `DemoV19Rf2AutoStage` / `DemoV19Rf2StrictCutoverCoordinator` / `DemoV19Rf2StrictAckRuntime`，以 `compose.v19-rf2-strict-cutover.yaml` 在隔离的真实3ZooKeeper＋两个独立Netty JVM、独立持久WAL中验证 P000；首次真实业务等价测试命令在Epoch1返回 `QUORUM_DURABLE_SINGLE_HOST_TEST`，双方WAL fsync一致。直接 `docker kill --signal=SIGKILL` A后，无脚本写ZK，B控制器自动将Epoch1切至Epoch2 `RECOVERING`→`AUTO_DEGRADED_LOCAL_DURABLE READY`，客户端B序号2获得local-ACK，明确`quorumDurable=false`且提示possibleDataLossIfPrimaryPermanentlyLost=true。恢复A后，系统自动catch-up、冻结老写权限、生成Epoch3可信双物理提交证书、两份Custody并CAS发布严格READY，B客户端seq3获得真实`QUORUM_DURABLE`且A/B完全一致。反向SIGKILL B后A自动Epoch4 degraded READY、seq4 local-ACK，B恢复后自动Epoch5双Custody严格READY，A的seq5返回`QUORUM_DURABLE`且A/B一致。完整停止3ZK+2JVM并使用原8卷重启，自动恢复Epoch5 READY；第一次seq6请求出现客户端Netty超时，但后台两个WAL实际均已提交seq6；用完全相同requestId重试成功返回`QUORUM_DURABLE`，seq和distinctRequests仍为6且A/B SHA一致（无重复执行）。随后补充自动化脚本`tests/run-common-rf2-ab-auto-e2e.py`，它使用随机Compose project独立创建网络与数据卷、真正SIGKILL及检查READY/ACK并自动停止进程但不删除证据卷；首次从零复跑因日志匹配判定错误被脚本拒绝，修正后再次全新卷全流程 **`AUTO_HA_T66_RF2_TWO_WAY_PASS`**，最后A/B Epoch5 seq6、6独立请求，WAL SHA=`8e42fa6ba5dcd301f2abc2602134fc992143738c0f0fcb7e63f9b8e7341544eb`、State SHA=`9ea74e3c9377861314fc61ea19ed68e8735babe3b849038aba10718e7e156e56` 完全一致。证据日志`tests/patches/common-rf2-automatic-ab-t66-20261024.log`；独立Java源码与Compose快照`tests/patches/common-rf2-automatic-e2e-t66-20261024.tar.gz`及SHA256。**验收边界**：仅单分区P000的Common RF2，两数据JVM共用单台Mac硬件，不覆盖四节点256分区；degraded local-ACK可能有RPO>0，不能称它等同严格零丢失；真实Order/Trade没有通过业务failover或资金/持仓/撮合一致性，完整Demo HA仍NO-GO。**进入业务接入的真实阻塞**：Order当前`OrderClusterAdapter`配置为非required时复制/日志异常允许传统业务继续（严格场景必须设强制并保持源端栅栏）；Trade配置回归测试`tests/test-trade-cluster-config.sh`要求`trade.cluster.replication.required=false`用于备用掉线时Primary继续，但Trade源码`TradeFailoverController.configurationBlockReason`对任何`replicationRequired=false`拒绝自动选主启动。必须把严格2/2已认证前沿与本地降级ACK的RPO契约明确隔离、接入可信副本水位，不能简单删除这个安全门禁后声称零丢失。后续按Order→Trade开展真实tenant资金/订单/成交/持仓权威一致性和10/50/200租户压测；GitHub Actions不运行，真实Demo未替换。
