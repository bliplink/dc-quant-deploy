# T554：跨 Epoch 的交易、结算与 SQL 连续性验收

原 Mac Demo 的现役 `mac-demo-20261110-141838` 使用 Common `ef3fcf1` 恢复常规模拟交易。Trade A/B 双向正常替换、单节点客户及 Robot 业务、原卷自动归位与账务对账均通过。Order 和带 Robot 持续写入的强杀演练仍在进行。

## 已查明的两个业务缺口

1. `FetchCommittedTradeProjectionEventsHandler` 把游标序号传给只读当前 Epoch 的 Common 接口。当前 WAL 的序号会从零开始；不能把旧 Epoch 的序号当作新 Epoch 的游标。现役 `CertifiedTradeFinancialReadModel` 也会明确拒绝 Epoch 变动。需要按 `(Epoch, sequence)` 顺序读取有认证的旧区间，旧区间追到已确认头后再进入新区间。旧区间未验证、途中有缺口或当前权限失效时应拒绝推进。空区间要由同一认证链证明为空。
2. `TradePairSettlementDurability` 将原单副本属性和坐标保留在已有幂等记录中。`TradeSignedOrderMatchAdmission` 重试时仍返回原单副本收据；`OrderSignedMatchDeliveryWorker` 不会用该收据关闭待结算记录。返场后需要另外证明**同一笔**原提交已经被两端实际保管，不能重写原收据为双副本。核验记录至少应锁定原分区、原 Epoch、原序号、业务标识及实际认证过的副本水位。Order 取得该证据后，继续使用已有待结算记录和现有持久终结路径，不重复过账。

## 可复用的已有边界

- Common 已保留原始严格 WAL、独立见证签名、LOCAL 两端追平及退役证明、后继严格基线。跨 Epoch 读取或核对后来双副本证据应在 Common 内认证；接口返回不透明帧及坐标。Order、Trade、Projection 不自行验证选主或从运行数据推断授权。
- 现有投影传输已经带有 `previousEpoch`、`previousSeq` 和当前坐标；Trade 的事件归档在一个 SQL 事务内锁定前游标、写入事件和变更，再推进游标。消费端用同一套有序坐标物化资金和持仓，不能简单地清游标、只重扫新 Epoch 或把旧序号复用为新区间起点。
- LOCAL 原始回执保留 `quorumDurable=false` 及风险标记。原确认与返场后的追加证据是两个时间点。若旧数据节点在返场前也失去且无法核验原已确认数据，不把待结算记录认定为最终成功。

实现与验收均以现有 Common 证据为准：对旧严格区间使用原签名提交前缀，保留未认证尾部但不投影；对旧 LOCAL 区间使用返回副本与原主各自的物理退役签名、共同前缀和后继严格安装，等返回副本真实追平后再读取。当前发布者仍须持有现任授权；历史证明不能给旧主写权限。每次以有限条数及字节量读取，在同一分区内跨过签名链认可的空区间。不要把 `CommonCertifiedE2ReplicaHistory` 的冷恢复读取直接当作跨 Epoch 在线读，它只验证指定的一个 Epoch，且不会授予对外读取或写入许可。

## 原 Mac 上应采集的证据

- 每套服务先核对运行的 Common SHA256、A/B 各 128 主与 128 备。正常滚动替换一次只退出一个节点；验收程序只注入进程事件、读取状态及发业务请求，分区接管、追平及归位全部由 Common 完成。整轮记录实际停顿、各分区新旧 Epoch、确认策略和物理提交水位。
- 双向硬故障每轮覆盖旧主和幸存节点原有主位置。故障前、单节点期间、返场后使用可追踪的幂等请求。真实交易记录提交策略、成交执行 ID、订单终态、每次资金变动、持仓数量、MD 最近成交及投影游标。资金和持仓以同一认证坐标逐项对账。
- 为故障期间的单副本成交留出一条旧 Epoch 未消费记录，再延后返场及投影追赶。返场后重复提交相同请求，检查原确认属性不变、后续物理认证生效、每个成交恰有一对资金分录、待结算记录终结一次、MD 无重复或缺失、旧和新 Epoch 的 SQL 记录均齐全。
- 纯撮合与资金结算分别验收。纯撮合应有两侧真实执行记录及 MD 成交，资金和持仓不变。带资金的成交、撤单、平仓应与对应账本和 SQL 视图一致；不能以纯撮合结果替代资金验收。

`tests/check_certified_trade_financial_cursor.py` 以同一个 MySQL 只读快照检查 SQL 事件范围与两级游标，再逐项核对金额、持仓与最新认证变更。未对应变更的非零余额和任何多余持仓会导致失败；租户初始化时全零的余额单独计数。它能发现同一 Epoch 的缺号、游标缺头或不同步；旧 Epoch 的真实终点和空 Epoch 必须由 Common 的物理证据证明，SQL 自己不能证明。

## 首次现场演练和恢复证据（2026-11-10）

- Common `8eb55f2` 的同一已验证 JAR 部署在 `mac-demo-20261110-051948`，Order 与 Trade 各为 256 个严格 E2 分区、A/B 各主 128 个。两种撮合模式分别通过：Order-only 两条执行记录且资金、持仓不变；签名有资金的成交两条执行，卖方余额 999.98200000、买方余额 999.94600000，持仓量均为 0.001。Robot/Tape 有真实成交；SQL 两个认证游标、四条余额及四条持仓差异均为零。证据：`~/.opentradingcore/mac-demo-20261110-051948/verification.NmujpK`。
- Order A 正常停止后，Order B 用 1048.513 秒达到全部 256 个独立见证的 LOCAL 分区。ZooKeeper CLI 以非零码表示旧租约已按预期消失，旧脚本误判并自动拉起旧 A。A 的第一个严格返回阶段已经签名并落地，Gateway 却把尚未追平时的拒绝发现当成进程启动错误，导致进程退出。故障后的清单是 P000 严格 E4 RECOVERING、其余 255 个 E3 LOCAL。没有改清单或绕过物理确认。这轮现场滚动未通过。
- 保留新一代所有卷及原容器，按容器 ID 恢复原一代 `mac-demo-20261109-174426`。原 Trade 的冷启动采用整段读取，超过有界上限后按规则拒绝服务；用只替换 Trade 分段回放接线的恢复镜像重新启动两端，同一 Common JAR SHA256、同一物理卷、同一配置、同一签名身份，旧容器保留。新的现场验收结果以实际启动、业务与 SQL 日志为准。
- `19a0008` 加入有认证的跨 Epoch 旧区间读取；`a270e66` 增加严格返场阶段被打断后的独立演练和恢复入口。候选仍须通过同 JAR 的真实独立演练，再用于现场滚动及交易验收。

- 06:13，原代 Trade A/B 均完成原有签名历史校验并注册到网关。新建测试租户的 Order-only 两条执行未改变资金和持仓。另一测试租户的签名资金成交产生两条执行和两条匹配的资金分录，公共行情有一条对应成交。Robot/Tape 验证 24 个唯一执行 ID、24 个资金事件、48 条分录及零配对异常。独立 SQL 对账通过，四个游标对齐，12 条余额和 10 条持仓零差异。证据在 `~/.opentradingcore/mac-demo-20261109-174426/verification.wgEXCT`。
- `19a0008` 的反向返场在测试时限内推进到 P225，结果为 NO-GO。`a270e66` 演练实际杀掉已进入严格 E4 RECOVERING 的返场 A，证明清单保留，随后 A 重启因监听器仍强制 256 个 READY 而退出。候选 `4e3757f` 仅允许由签名 Stage 明确解释的分区退出监听器的 READY 集合，仍核对所有应当 READY 的分区 ID，并保持该分区无写权限。
- `./mac-colima-saas.sh verify-common <Common Git 提交>` 生成候选目录与同包物理证据。`./mac-colima-saas.sh fresh-verified <候选目录> <物理结果目录>` 使用同一个通过中断续接演练的 Common JAR 构建四个节点，校验镜像内原始字节，在原 Mac 切换现役代并跑业务基线。已实测未通过的物理结果会在构建和现场切换前被拒绝。
- `./mac-colima-saas.sh roll-voter <现役目录> <order|trade> <A|B> --fault <term|kill> --signed-business` 在同一测试租户中先挂单。Order 演练在见证 LOCAL 阶段发出对手单。Trade 演练要求在 LOCAL 阶段完成对手单的保证金冻结和成交结算，从幸存节点核对双方资金和持仓并记录真实单副本提交坐标。严格归位后，SQL 必须保留相同的原 Epoch 和序号。两条路径都验证物理文件哈希、逐笔分录、行情成交和认证 SQL 水位。`--order-only-business` 在 Order 单节点期间核对纯撮合的成交和行情，归位后检查没有重复成交，资金和持仓保持原值。现场滚动发生失败时保留被隔离的旧容器与签名阶段。

- 06:32 独立演练证明 `4e3757f` 的 A 在签名 LOCAL 转严格阶段被杀后，从原阶段续接，P000 两端物理 WAL 与快照一致，全部 256 个分区完成重建与 Home 归位。后续反向和再次接管仍在运行。
- Trade 单节点交易纳入验收。普通开仓和平仓的预留、撤单及单笔执行都使用 Common 的实际策略，受独立见证和原主隔离约束。单副本回执保存原分区、Epoch、序号并显式标示风险，返场后重试仍是原回执。签名匹配的最终确认继续要求真实返场双副本证据。14 项 Trade 和 16 项 Order 定向回归通过。Order 的查询保留原 Trade 冻结提交坐标和风险，恢复后仍能读回。现场单节点交易仍待验收。
- 06:46 独立候选 `4e3757f` 已完成双向强杀及 Home 归位，256 对 WAL 和 256 对快照逐对一致。首次接管 218.372 秒，含中断的首次返场 530.552 秒。反向接管 337.745 秒，返场 557.726 秒。第三次故障及再次归位仍在独立演练中。验收脚本将在该候选通过、部署后正常业务基线通过时优先开始 Trade A 的现场正常替换。
- 06:59，Common 候选 `4e3757f` 完成第三次故障和再次归位，256 对物理 WAL、256 对快照一致，历史严格记录和 LOCAL 记录可以跨 Epoch 按原坐标读取。整轮 `OK (1 test)`，共 2462.998 秒。封存 SHA256 为 `03e0e1d562d52ddc3bfce230ec3d403e5b19348c8df71817464155e501294866`，证据 `~/.opentradingcore/t554-common-verifications/20261110-061728-4e3757f`。此结果放行同包 Mac Demo 部署，现场单节点业务仍须独立验收。
- 07:10，原 Mac 新一代 `mac-demo-20261110-070227` 使用上述原 JAR 完成正常交易基线。纯撮合与资金成交各两条执行。Robot/Tape 可交易。两个认证 SQL 游标和 4 条余额、3 条持仓均无差异。证据在 `verification.xW9uZQ`。
- 首次 Trade A 现场正常退出，退出码 143。Trade B 在 303.766 秒内接管全部 256 个分区。定向测试挂单在 Trade 形成真实单副本冻结回执 `P137/3/1`，但实际部署的 Order 回调没有保存回执，客户端未能读到风险字段，因此定向用例失败。已修复真实回调并通过 16 项 Java 回归。两端已开始原卷返场。同一次演练的 Robot 在 Trade B 上产生 7 条实际 LOCAL 原子成交，证据 `ha-trade-a-term-tk_878h9/observed-local-trade-commits.json`。返场后按原 Epoch 和序号核对投影。
- Trade A 用 999.613 秒自动完成严格 Home 归位。实际比对 256 对已退役 LOCAL WAL 及 256 对严格恢复快照，差异为零。七笔成交在 `P131/E3` 的序号为 3、6、9、12、15、18、21，原始回执标记单副本风险。首次 SQL 核对没有读到这些分录。原幸存进程 B 在严格接续完成后仍持有旧 WAL 和保管记录的只读锁，归档校验遇到 `OverlappingFileLockException`，影响 P131 及 P137 的补账。证据 `ha-trade-a-term-tk_878h9/evidence.json`、`observed-local-trade-sql.json`。
- Common 候选 `69e3a01` 仅在严格后继实际安装后释放原退役读句柄，并串行执行同分区并发归档读取，保留物理文件锁及原有认证流程。独立进程演练增加由原幸存 B 同时服务投影和结算历史读取的用例。原 Mac 反向演练让 Trade B 正常退出，由 A 接管；B 原卷返场后再次按原始坐标核对七笔成交。
- 07:52，候选 `69e3a01` 的独立演练通过首次中断续接及原幸存 B 的并发归档读取，投影和结算均取得原 LOCAL 帧。整轮双向及重复返场仍在运行，尚未封存放行。另一次镜像构建在验证 Order 的 93 个和 Trade 的 79 个非项目依赖逐字节一致后复用原层，两个构建上下文分别为 3.2 MiB 和 3.5 MiB，镜像校验通过，Order 新镜像包含保证金回执写入。
- 08:08，现役 Trade B 的反向正常退出为 143，Trade A 在 1774.151 秒完成全 256 分区的独立见证 LOCAL 接管。B 用原卷和原镜像启动后开始追平。反向接管明显慢于首次的 303.766 秒，线程采样见串行的签名快照核验和 ZooKeeper 授权读取；现场本轮保留原资源限制以继续记录完整耗时。
- 08:20，候选 `69e3a01` 完成全部独立物理验收，双向及第三次接管、Home 归位、256 对 WAL/快照、原 LOCAL 帧读取全部通过。整轮耗时 2545.261 秒，SHA256 为 `edde3af5857f6dd08f0300e5eb71d8c91ca9827ec930d57b1db5a6f7deb746b7`。证据在 `~/.opentradingcore/t554-common-verifications/20261110-073748-69e3a01`。镜像构建使用此原包。
- 当前现场返场的线程采样还发现历史校验重复编译清单的正则。Common 提交 `8c20a50` 复用原校验表达式，256 分区清单的本机解析样本从 0.51–0.61 毫秒降至 0.24–0.28 毫秒，36 项定向回归通过。现场整轮耗时未用该提交复测。
- 返场已启动后若验收观察超时，`roll-voter --resume <此前的 evidence.json>` 可继续观察同一容器及租约，并完成原 LOCAL WAL 与严格快照的逐对核验。定向测试证明续验不触发容器变更，拒绝自动重启过的替换节点和变化的幸存租约。
- 08:27，反向返场过程中，原本堵塞的 `P131/E3` 七笔成交全部进入原 MySQL，各自保持序号 3、6、9、12、15、18、21 和同一事件的两条资金分录。P137 同时补至 E3/1。只读快照核对 3 个游标、7 条余额、6 条持仓、94 条前序链接，差异为零。阶段性证据 `ha-trade-a-term-tk_878h9/observed-local-trade-sql-during-b-return.json`。此前锁错误和初次 SQL NO-GO 保留，严格 Home 全量核对继续运行。
- 08:36，Trade B 在 1699.429 秒内完成严格 Home 归位，256 对 WAL 和 256 对快照差异为零。七笔资金分录和 SQL 游标在归位后复核仍通过。原成交是 Robot Demo，现配置排除这类公开执行历史，改为按原撮合事件和其独立签名结算终态核对。五笔已找到原撮合帧且两侧执行标识一致，两笔的原撮合帧尚未补入 Order 投影，七笔尚无返场签名终态。证据 `observed-local-trade-order-terminal-v20.json`，整体业务仍为 NO-GO。
- 返场后的实际短时 JFR 显示旧 Trade 结算在读取历史 LOCAL 帧时仍遇到 `OverlappingFileLockException`，并为每次请求重开全 256 个原始 Genesis。候选 `b3f16d2` 改为复用启动时已认证的全量签名基线，对选中的分区仍重新校验原物理文件。该独立演练随后由包含下一项死锁修复的候选接替。
- Order A 仍持有独立有效租约，Gateway 登记和监听端口可见。实际 Java 线程证据 `/tmp/mac-t554-order-a-route-0848.jstack` 显示 `common-certified-business-snapshot` 先持业务边界锁再等分区运行时，物理复制线程反向持锁并等待读取中毒状态；Order P062 结算回调和 Gateway 工作线程也在等待。候选 `5acd3ff` 将中毒状态改为无锁可见读，在物理水位返回前再次检查，保留物理校验。11 项 Java 8 定向测试通过，包括持业务锁时跨线程读到中毒状态，整包独立物理演练已启动。
- 08:52，确认 Order B 无 Java monitor cycle 后，使用 Common 现有接管路径强制退出已死锁的 Order A，退出码 137。沿用原租约、见证和数据卷，计划以含已验证保证金回执回调的同 Common 镜像返场。证据 `ha-order-a-kill-dax91ges`。未重启 Projection。
- Order B 用 1165.908 秒接管全部 256 个分区，Gateway 认证了单节点路由。Order A 按原卷启动。观察脚本因一次只读 ZooKeeper CLI 超时退出，但两个容器均继续运行；新观察 `ha-order-a-kill-7adeqnpx` 以同一替换容器和独立租约继续，不再注入故障。定向验证已覆盖查询超时后继续。
- 09:26，旧版 Order 在 P015 的签名严格 E4 Stage 卡住。A/B 分别生成 2461 字节的真实候选快照，SHA256 不同，Common 正确拒绝签名归位。逐字段比较只有两条 `clientOrderReservations.createdAt` 使用了进程本地回放时间。已将初次持久创建及终态时间改为原签名 WAL 帧时间，并排除排队前的临时去重占位。保留旧两端原卷、快照与签名 Stage，证据 `ha-order-a-kill-7adeqnpx/p015-snapshot-mismatch.json`。
- 09:33，Common `5acd3ff` 全套独立验收通过，三轮真实故障接管和归位均核对 256 对 WAL/快照，跨 Epoch 的结算及投影归档读仍通过。整轮 2280.868 秒，SHA256 为 `b2fea76db33d062149112a9d9b79e3a30cc3768d096f86720de47a5cea1a2bb0`。Order `ae086dc` 回放保留签名帧时间的 10 项回归通过。
- 09:37，已用 191 秒构建同版 Order/Trade 镜像。部署检查发现旧 Trade A 在 09:16 被容器内存限制终止（137、`OOMKilled=true`）；旧 B 仍在运行，最新只读清单中 117 分区已取得见证 LOCAL。原检查因旧 A 停止而拒绝切换，未改变现役服务。修复后以 Gateway 和 MySQL 的同一代标签锁定四个原容器，保留已停止的 A，回退按切换前运行名单恢复。切换前旧七笔 Trade 分录及资金读模型通过，Order 签名终态仍缺失，全部旧证据随原卷保留。
- 镜像依赖复用后，宿主机编译工具改用同一构建的完整 Maven 依赖，避免从精简后的 Docker 上下文取库。编译用同包 Common、共享业务 JAR 与 93 个依赖通过。09:41 在同一台原 Mac 切换至 `mac-demo-20261110-094143`，原部署全部容器和卷留存。
- 09:49，现役完成实际交易基线。Order-only 两侧各一条执行，余额与持仓不变。资金成交双方各 0.001 持仓，余额分别 999.98200000 和 999.94600000；Robot/Tape 两个真实执行 ID，三笔资金事件六条分录，异常配对为零。只读 SQL 对账四条余额、四条持仓、两个游标均零差异。启动及验收共 474 秒，其中业务 103 秒。证据 `~/.opentradingcore/mac-demo-20261110-094143/verification.dVYfA4`。随即开始 Trade A 客户签名滚动。
- 09:55，现役 Trade A 正常退出为 143，B 用 327.512 秒接管全部 256 个分区，Gateway 认证单节点路由。签名客户保证金冻结与本地风险回执检查通过；撤单返回 0 后仍停在 New，验收退出，未发对手成交。旧单笔撤单入口走旧异步队列，认证模式实际拒绝后续旧写入。已接到既有认证撤单 Saga，保留原会话和参数校验，先写待撤状态、等真实 Trade 保证金释放、再写终态并确认。15 项 Java 回归通过。现场证据 `ha-trade-a-term-dphm_8wq`，物理返场仍在运行。
- 10:20，两端仍运行且无自动重启。真实清单为 88 个严格双副本和 168 个 LOCAL，主均在 B。现场日志定位 P088 的另一笔 Robot 撤单已落盘并应用，最后确认遇到控制许可短暂撤销。旧 Common 把写入器永久隔离，返场读不到可信日志头。原 LOCAL WAL 仍在原卷，长 1491591 字节，记录和实际哈希见 `ha-trade-a-term-dphm_8wq/physical-blocker-P088.json`。
- Common `00d1840` 保留确认前的许可复核，并把它与落盘或业务应用未完成的隔离逻辑分开。24 项 Java 8 定向测试通过，包含许可恢复后读取原物理头和继续写入。独立真实进程验证使用原包 SHA256 `b6d47f5d7cb72dd6c4c12477ba908550da50751709b2831920ba4fa64a52d1ac`，证据目录 `~/.opentradingcore/t554-common-verifications/20261110-101730`。
- 10:24，定向清理 7 个已退役且不在 13 份回退记录中的旧测试容器，保留日志尾部、挂载卷和镜像。Colima 物理空闲由 0.40 GiB 增至 16.20 GiB，扣除文件系统预留后可用 8.68 GiB。49 个运行容器的 ID 前后完全一致。新部署和新故障演练要求至少 2 GiB 可用，新 Demo 的投票与见证进程使用与 Compose 相同的日志轮转上限。
- 10:28，通过 Colima 的磁盘回收将约 16 GiB 归还给宿主机，并清理了八份 10 月 24 至 27 日的已轮转应用日志，释放 25.63 GiB。宿主机可用空间约 62 GiB。本次无需停机扩容。真实演练继续按 Trade A、Trade B、Order A 纯撮合、Order B 资金成交顺序执行，每轮须通过双端物理和业务核对才开启下一轮。
- 10:29，现役只读复查仍无 Robot 双边活跃报价及最近 15 分钟 Tape 成交，资金投影无新进展。证据 `ha-trade-a-term-dphm_8wq/runtime-after-storage-cleanup.json` 和 `robot-trade-after-storage-cleanup.json`。独立 Common 验证已跨过首次 LOCAL 至严格双副本回归，正在进行首轮 Home 归位。
- 10:44，Common `00d1840` 已通过独立双向强杀接管及归位，256 对 WAL、256 对快照一致。首次接管 224.075 秒，含返场中断续接的归位 486.414 秒；反向接管 220.678 秒，归位 458.417 秒。第三轮重复故障仍在验证，整包尚未放行部署。
- 10:54，Common `00d1840` 第三轮再次归位、256 对物理记录和跨 Epoch 原始帧读取全部通过。独立验证耗时 2144.487 秒，原包物理验收状态 `PASS`。按部署门禁使用同一 Common 包构建 Order、Trade 及见证进程。
- 11:08，原机现役 `mac-demo-20261110-105606` 完成启动和交易基线。镜像构建 190 秒，启动加业务验收 513 秒，其中业务 115 秒。纯撮合两条执行，资金和持仓不变；资金模式两个账户分别结余 999.98200000 和 999.94600000，双方各 0.001 持仓。Robot 40 条报价订单，两笔唯一 Tape 执行。四条余额、三条持仓和两个认证游标零差异。证据 `verification.2bFz7Y`。随即启动 Trade A 正常替换 `ha-trade-a-term-syz25xkg`。
- 11:15，Trade A 正常退出 143，B 用 376.127 秒取得 256 个见证授权的单节点分区。真实客户 `ITBBHO` 的冻结使用 `P024/E3/1` 单副本回执，冻结保证金 8.99990000，撤单后余额字段恢复原值。随后双方成交持仓和资金在 A 缺席时已从 Trade B 读回，原始结算坐标 `P024/E3/4` 带单副本风险。A 已用原卷返场，终态、行情与原坐标对账仍在验证。
- 11:24，已查到原 `P024/E3/4` 两条资金分录，两侧订单均为 Filled、各有唯一执行，撤单终态为 Cancelled。真实 Robot 持续写入的 P138 则在 WAL 完成 fsync、业务尚未应用时遇到其他分区控制许可刷新。现役返场停在 138 个严格双副本、118 个 LOCAL。P138 原 WAL 哈希和竞争时点见 `ha-trade-a-term-syz25xkg/physical-blocker-P138.json`，两个 JVM 和原卷继续保留。
- Common `440bfb3` 在原 WAL 强制落盘后短时等待同分区、同 Epoch 的有效许可。等待期间不应用、不确认，持续撤权仍保持原隔离。Java 8 定向测试通过 26 项，独立原包 SHA256 `cf440050d344f975aa28742d968fa35d57d287ecffb05d03ecfc1cffd662253d` 正在 `~/.opentradingcore/t554-common-verifications/20261110-112659` 验证。
- 新增 `roll-voter --robot-traffic`，从故障前已在运行的实际 Robot 取样，同一个进程覆盖正常退出、强杀、单节点与原卷返场。记录真实报单到达、Tape 执行及 Trade 单副本结算，返场后按原 Epoch 和序号验证每个资金事件两条分录。用上一轮真实单节点时段回放，识别 25 笔新报价请求、18 笔 Tape 请求和 17 笔 Trade 单副本撮合，Robot 循环最大间隔约 30.4 秒。
- 11:50，再次只读核对 `ITBBHO` 的两侧 Order 执行、原 `P024/E3/4` 两条资金分录及唯一 MD 成交 `Edc134f43443ee55dddfc5c333038e5`，全部一致。证据 `ha-trade-a-term-syz25xkg/controlled-local-match-readonly.json`。该笔独立业务证据与 P138 全量返场阻塞同时保留。
- 12:02，Common `440bfb3` 的独立进程验收 `PASS`，耗时 2048.978 秒。双向接管分别为 223.374、216.032 秒，归位 448.140、441.016 秒，256 对 WAL 与快照一致。第三轮归位和原 Epoch 归档读取通过。开始原机同包构建和真实 Robot 持续写入验证。
- 12:13，原机 `mac-demo-20261110-120202` 常规交易和资金对账通过。启动加验收 479 秒，其中业务 107 秒。证据 `verification.5KHCmd`。首次现场替换前 Robot `VXT97E` 已有 43 个不同的双边报单请求和 3 个 Tape 执行。Trade A 正常退出；B 用 333.037 秒接管全部 256 个分区。接管期间同一 Robot 运行 12 轮，最大间隔 30.873 秒。只剩 B 时核对真实 Robot 结算 `P130/E3/96`，签名客户成交 `P154/E3/4` 和保证金原值退回。12:23，Robot 分区已恢复严格双副本，全量已恢复 144 个。证据 `ha-trade-a-term-ze5r5fka`。
- 12:32，Trade A 在 753.905 秒内完成全部 256 个分区严格归位，256 对 LOCAL WAL 和 256 对严格快照均一致。Gateway 未得到 Trade B 当前严格路由认证。P130/E4/14 在两端 WAL、原提交索引、两份保管签名已经落盘后被隔离，证据 `ha-trade-a-term-ze5r5fka/strict-gateway-blocker-P130.json`。可复核到双端持久化阶段，首次严格失败的内部具体调用未在服务日志中保留。客户 `P154/E3/4` 的两侧执行、两条分录和唯一 MD 均通过只读复核。同一 Robot 返场期间循环 25 轮，最大间隔 30.442 秒，`P130/E3/96` 两条资金分录可读回。新 Tape 与完整业务验收仍待复测。
- Common `a4ee3b4` 复用同一短时许可等待处理严格保管完成后的复核与应用前检查。业务已经应用时最后撤权仍拒绝 ACK，保留已完成前缀；缺少真实副本、保管或业务应用失败仍隔离。39 项 Java 8 定向测试全部运行并通过，含独立签名、真实 Netty 和双端 WAL。原包 SHA256 `fb74dbef9f983f4430d65f43a6e4e90bf7b2739729a78c1b88b9b076d6763464` 正在 `~/.opentradingcore/t554-common-verifications/20261110-124150` 做完整物理验证。
- 13:19，Common `a4ee3b4` 整包独立物理验收通过，耗时 2070.617 秒。构建同包镜像 122 秒，原 Mac `mac-demo-20261110-131659` 启动和真实业务基线共 434 秒。Trade B 用 295.004 秒在真实 Robot 持续活动下接管全部 256 个分区；Robot `Z779XR` 的主分区 P039 从 A 切到 B，接管期间运行 10 轮，最大间隔 33.13 秒。现场单节点客户 `P084/E3/4`、Robot `P039/E3/135`，证据 `ha-trade-a-term-ylom17u5`。
- 13:34，真实 Robot `P039/E4/22` 在提交索引落盘后进入保管阶段，原主的控制许可暂时不可读。两端 WAL 均有 22 帧且哈希一致，原保管证据只到 21，22 未得到客户确认。现场停在 167 个 Home 归位，P039 原 WAL 和容器保留。证据 `ha-trade-a-term-ylom17u5/strict-custody-blocker-P039.json`。
- Common `ef3fcf1` 将等待限制在可以重新认证的许可刷新，覆盖原写入链的双端 WAL、保管和签名复核。已换角色、已升 Epoch 或会话真正撤销时继续拒绝。63 项定向测试通过，包含实际 Netty 主端在提交索引后与副本在保管请求到达时分别遇到许可刷新，双端仍只写同一原帧、获得严格签名。原包 SHA256 `26b3d15c847782d1c6c5916b18d7a2c41cb45736aed3eb9704e9ae16213bd101` 在 `~/.opentradingcore/t554-common-verifications/20261110-134347` 独立验证。
- 14:18，Common `ef3fcf1` 独立整包验收 `PASS`，耗时 2047.307 秒。原 Mac `mac-demo-20261110-141838` 构建 124 秒，启动及基线验收 424 秒，业务 98 秒。Trade B 接管 307.537 秒，期间 Robot `SB9KAK` 同一进程循环 11 次，最大间隔 30.325 秒。单节点期间 37 笔报价请求、7 笔 `P133/E3` 实际结算；客户原成交 `P251/E3/4`。14:40 已恢复 202 个双副本，活跃 Robot 所在分区已严格返场。证据 `ha-trade-a-term-y1wsiocs`。
- 14:47，Trade A 首轮现场验收完整通过。原卷返场归位 743.194 秒，256 对 WAL 和 256 对快照零差异。原 Robot 在返场期间循环 24 轮，最大间隔 32.064 秒；7 笔原 LOCAL 成交均按原序号补齐两条资金分录，归位后新增 Tape 成交和对应分录。客户 `P251/E3/4` 两侧执行、原资金分录和唯一公开行情一致，SQL 核验 802 条前序链接零差异。随即启动 Trade B 正常替换 `ha-trade-b-term-ttut7ny3`。
- 15:09 前，Trade B 反向现场验收完整通过。A 单节点接管 327.372 秒，B 原卷严格归位 828.945 秒，256 对 WAL 与快照一致。实际 Robot P133 从 B 切到 A，单节点四笔成交按原坐标补齐分录；返场期间同进程循环 27 轮，最大间隔 36.089 秒，归位后又新增 Tape 成交及对应资金分录。签名客户原成交 `P114/E6/4`、订单、资金和行情一致。随后开启 Order A 纯撮合 `ha-order-a-term-insj2i0d`。
- 15:21，Order B 接管 255 个分区。P102 原双端 WAL 一致，严格认证到 E2/5313，主节点已有封存快照 4711，B 的已验证副本快照仍为 160，回放差值 5153 超出 4096。JFR 定位原崩溃写入窗口的帧数校验，证据 `ha-order-a-term-insj2i0d/order-P102-stale-replica-snapshot.json`。原 HA 用例未通过。使用现有混合返场入口启动原 Order A 容器及原卷，Common 验证后对 P102 按 64 帧窗口回放；15:40 Order A 已实际启动并开始其余分区严格归位。
- Common `d3887c5` 将副本快照尝试阈值从 2048 帧提早至 512 帧，并使用现有最多 8 帧的签名传输；较大的独立帧仍可通过原单帧路径重新认证。Mac 新代快照巡检为 60 秒。保留原 4096 帧恢复界限。14 项定向 Java 测试及部署回归通过，原包 SHA256 `e5b5539b1a662e43ec36dbfb5d84c68f367f908bd57ab2e6a04a9409ea2091a5` 进行独立验证。下一代先观察真实 Robot 流量下副本快照前移，再做 Order A/B 正常替换。
- 15:57 复核原 Order A 的实际退出码为 1。Spring 打印 `Started` 后进程仍因 `ORDER_COMMON_CERTIFIED_BUSINESS_STARTUP_DENIED` 退出，原代最近五分钟无新 Robot 报价或 Tape 成交。见 `ha-order-a-term-insj2i0d/original-a-restart-exit.log` 和 `robot-recovery-followup.json`。真实清单 517 保留 P102 的严格 E2，其他分区有 252 个 LOCAL、3 个已严格 READY、P002 在签名严格返场阶段，原卷和签名位置保留。
- Common `7b2152f` 复用现有认证位置校验，让启动时可读取已经安装的写入表，同时对只持有签名预约的分区继续拒绝写入。独立 JVM 在旧代码确实复现 `Common certified node contains uninstalled partition`。修复后 254 个物理位置正常启动，两个被隔离的位置无写入权限，追平后各自取得真实双副本确认。Java 8 定向回归实际运行 5 项并全部通过，13 项因已有测试条件跳过。证据 `/tmp/mac-t554-mixed-return-before-fix.log`、`/tmp/mac-t554-mixed-return-after-fix.log`。
- 16:07，经回退清单、容器写层及挂载核对，清理了四个已退出的 T488 演练容器。其输出日志合计约 4.1 GiB，回收日志和容器临时写层后 Colima 可用空间从 4.52 GiB 增至 11.09 GiB。两份原数据卷、镜像和日志尾部已复核保留，运行容器清单前后哈希一致。证据 `/tmp/mac-t554-storage-followup.eVlYMq`。本轮清理没有扩容或重启 Colima。
- `./mac-colima-saas.sh verify-ha <现役目录> <term|kill> [先演练的 Order 侧]` 逐侧复用原 `roll-voter` 入口。两侧 Order 分别走纯撮合和资金交易，两侧 Trade 走签名资金交易，全部要求同一个 Robot 进程持续报单并核对实际成交和分录。前一轮失败后退出，保留现场证据，避免连锁注入故障。脚本回归 `/tmp/mac-t554-verify-ha-wrapper-tests.log` 已通过，现场整轮另行记录。
- 16:19，`d3887c5` 完整独立物理验收 `PASS`，2377.158 秒。A 强杀接管 236.347 秒、含一次中断续接的归位 509.079 秒，反向接管 394.703 秒、归位 490.591 秒。两次都比对 256 对 WAL 和 256 对快照，第三次接管、归位和跨 Epoch 原前缀回读也通过。原机按此证据开始 `fresh-verified`。包含混合返场修复的 `7b2152f` 使用独立新包 SHA256 `3e453fe0a62e8fbd0b189e4dbd62efb05e2f934b5aacd9ee57919d1bf884be2c` 在 `~/.opentradingcore/t554-common-verifications/20261110-161927` 验证。
- 17:00，`7b2152f` 独立整包验收 `PASS`，2403.999 秒。A 强杀接管 229.494 秒、含中断续接归位 541.582 秒，反向接管 322.343 秒、归位 469.375 秒。第三次接管和归位以及跨 Epoch 原始历史回读通过，两轮各 256 对 WAL 和快照一致。
- 17:01，`d3887c5` 原机镜像已成功构建并从镜像内核对 Common、共享 JAR 和投影类。构建执行期间修改 Bash 脚本导致最后写发布清单时读断，已按完成的镜像记录、原包哈希和独立验收封条重建清单。由既有 `fresh` 入口校验并部署 `mac-demo-20261110-170107`，原数据卷用于回退。之后的精简构建仅在镜像实际完整类文件清单和新编译产物逐字节一致时复用类目录。
- 17:08，`mac-demo-20261110-170107` 的四节点、独立见证、签名 E2 清单和投影启动通过。首次 HTTP readiness 读取遭遇 `ConnectionResetError`，原探针未捕获裸 TCP 连接重置，按流程回退，候选原卷保留。`verify-mac-demo-fresh.sh` 在原 240 秒内重试连接类异常，仍要求 Manager、Login 返回各自精确的只读响应。本机受控 TCP 第一次实际断连后两条探针均通过。17:09，用原镜像及验收封条部署 `mac-demo-20261110-170946`。
- 17:13，回退后的旧代四个交易节点已退出，原部署门禁要求每组至少一台运行，因此第二次尝试在任何现场变更前退出。已将全停恢复限制在带完整物理验收封条的精确版本，仍核对同一代四个保留容器和签名挂载，保留原卷，回退恢复各容器记录的运行状态。
- 17:22，原机 `mac-demo-20261110-171345` 从全停的旧代恢复，新代启动、物理检查和业务基线 483 秒，其中业务 120 秒。纯撮合两条执行、资金和持仓原值不变；资金交易两条执行，余额 999.98200000 和 999.94600000，双方各 0.001 持仓。Robot 40 笔真实报价请求、2 个唯一 Tape 执行，四条余额、三条持仓和两个认证游标无差异。证据 `verification.JElLP0`。
- 17:26，修正原机四个已运行的前端代理，将旧网关 43002/43001 改为当前 49502/49501，验证配置并热重载，四容器启动时间不变。`THK220` 的三个本地 Web 入口读到盘口、最近成交和 1M、5M、15M、1H K 线，交易页 `/gateway` 返回 101。原配置和证据在 `frontend-route-repair`。
- 17:30，持续 Robot `THK220` 的 Order A 主分区 P050 在 B 原盘的已验证快照从 124 前移到 1312，证据 `robot-replica-snapshot-advance.json`。开始原机 Order A 正常退出，独立签名的纯撮合与持续 Robot 演练 `ha-order-a-term-4xprxq8q`。
- 旧 Trade 双侧回退后的冷启动错误已定位到既有磁盘布局选择。同主重建的 P000/E7 原账本在 `target/install`，恢复 Home 的 P128/E7 原账本在 `install`，两侧记录都存在且原序号与 SHA 一致。证据 `ha-trade-b-term-ttut7ny3/cold-restart-ledger-layout.jsonl`。Common `72d613f` 选择对应目录，保留原镜像、Epoch 和全量签名验证，Java 8 编译通过。新增断言使用两个真实 JVM 原盘验证两种布局，候选 SHA256 `8ac01eb692af7a5201afce96763e55933cc9d1d2ff9be9d772d30d63ea30d673` 在 `~/.opentradingcore/t554-common-verifications/20261110-171841` 独立验证。
- 17:41，`d3887c5` 的 Order A 演练未通过全程。A 退出码 143，B 用 449.637 秒接管全部 256 个分区。真实 Robot `THK220` 的 P050 由 A 切至 B 后，B 单节点见到 42 个新报价请求和 26 个唯一 Tape 成交，26 笔结算各有两条分录。纯撮合测试客户 `DZQGVY` 的两个 Filled 执行及两条 SQL 执行投影在 B 单节点期可读，公开行情无该成交。A 原卷替换进程在 255 个分区仍为 LOCAL 时退出，退出码 1。证据 `mac-demo-20261110-171345/ha-order-a-term-4xprxq8q`。验收脚本现以原幸存节点的两条执行回报证明 LOCAL 撮合，在严格归位后核对同一组 SQL 执行及同一条行情成交。
- 17:53，`72d613f` 整包独立物理验收 `PASS`，2052.060 秒。A 强杀接管 207.028 秒、含中断续接的归位 463.350 秒，反向接管 218.114 秒、归位 438.437 秒。两轮 256 对 WAL 与快照一致。第三次强杀、接管、归位、跨 Epoch 原始回读及两种冷启动账本布局均通过。完整证据在 `~/.opentradingcore/t554-common-verifications/20261110-171841`。
- 18:02，原机现役 `mac-demo-20261110-175459` 使用上述包通过启动、物理检查和业务基线。构建 54 秒，启动及业务验收 446 秒，其中业务 112 秒。纯撮合两个执行，资金和持仓保持原值；资金模式两笔执行、双方各 0.001 持仓，余额 999.98200000 和 999.94600000。真实 Robot 40 个报价请求、3 笔唯一 Tape 成交。余额、持仓和认证游标一致，证据 `verification.ZfSLc2`。
- 18:04，仅替换现役 MDSvr，原容器已退出并保留。新旧进程的配置、资源限制和原挂载一致，其他交易容器继续运行。修复让成交行情订阅跟随两个认证物理节点的连接，保留 Common 的角色和写入权限，由同一市场的最近成交队列过滤重复执行 ID。Java 8 三项定向测试通过，镜像内四个编译类逐一核对 SHA256。证据 `mac-demo-20261110-175459/md-execution-sources/replacement.json`。
- 18:06，MDSvr `1f273de` 的 203 项 Java 8 测试通过。原机通过两笔独立的纯撮合业务验证物理来源。A 产生的 `BLYFJ1` 成交 `E2ee7804d9f6410a28fcf7c0f9a6504`、B 产生的 `TNND0Z` 成交 `Ee707f596b1f08a70ff03b3058d6813` 各在公开行情出现一次，并与对应物理 Order 日志的执行 ID 一致。两组测试各有两条执行，资金和持仓不变。证据 `mac-demo-20261110-175459/md-execution-sources/both-physical-sources.json`。
- 18:10，现役 Robot `RLN7VT` 的 Order 主分区 P006 在 B 原盘的认证快照由 180 前移到 713。证据 `mac-demo-20261110-175459/robot-replica-snapshot-advance.json`。整轮故障验收从该热分区的 A 正常替换开始，第一轮明确选取同一 `RLN7VT` Robot；其后依次演练 Order B、Trade A、Trade B。正常轮全部通过后进入强杀轮。
- 18:16，A 正常退出 143，B 用 309.309 秒接管全部 256 个分区。P006 已由 A/E2 切到 B/E3。接管期间同一个 Robot 运行 10 轮，最大间隔 32.129 秒；全量单节点阶段见到 2 个新报价请求及 3 个唯一 Tape 执行。原 A 退出且替换进程尚未启动时，实际 B 执行 `E0bd2d1bde684a4e20b9e747cc36e5d` 在公开行情恰好出现一次。纯撮合客户 `E41PFJ` 的两条执行及唯一公开行情 `E7572d289dbda51cc349fca93629d62` 同时通过。证据 `mac-demo-20261110-175459/ha-order-a-term-rt8_ulzb`。
- 18:16，A 替换进程第一次返场退出 1，整轮验收仍为 `NO_GO`。`replacement-exit.log` 显示物理节点已经启动，第二次应用就绪检查 `OrderClusterAdapter.startLifecycle` 遇到 `NodePartitionGrantTable.GrantRefreshPending`，由 `requireCertifiedCensus` 拒绝正在刷新的认证清单。当时 P000/P001 已是严格 READY，P002 正在签名恢复。18:19，确认旧进程退出、A 无租约、B 仍运行后，用同一个替换容器与原卷做一次受控启动。18:22，已有 70 个分区恢复严格双副本，热分区 P006 已进入 E4。该受控恢复单独记录。
- Common `a0aab07` 复用已有的 2 秒许可刷新等待，仅当原认证检查返回可刷新的临时异常时重跑整个就绪检查。硬撤权、丢失会话及写入隔离仍拒绝。定向测试先以旧代码复现与现场相同的异常，再通过 23 项 Java 8 测试，证据 `/tmp/mac-t554-v31-refresh-red.log` 和 `/tmp/mac-t554-v31-refresh-green.log`。原包 SHA256 `61a0073103fa940f1666ab11cddd696584e46688079e98e809dcf2e7d6d94a86` 已开始独立物理验收，目录 `~/.opentradingcore/t554-common-verifications/20261110-182427`。
- 一键部署的业务基线增加了公开成交核对。纯撮合与资金模式必须各有两个唯一 SQL 执行，公开行情必须恰有一条来自这两个执行的成交。读回现役的四个客户样本均能精确关联 SQL 执行与公开行情。故障验收也支持在第一轮锁定已经前移认证副本快照的原有 Robot 租户，避免由无关分区的流量代替热分区验收。
- 18:47，受控返场已有 237 个严格双副本、109 个达到最终 Home。Trade 对账仍通过，12 条余额、12 条持仓和 9,216 条前驱链接一致，证据 `ha-order-a-term-rt8_ulzb/financial-cursor-during-manual-return.json`。18:49，B 的原 JVM 在 `common-witnessed-return` 中反复报 `Common LOCAL catchup head is outside the configured replay bound`。独立只读扫描 P197/E3 确认 B 的连续 5,865 条 CRC 正确，A 已复制的 4,055 条与 B 原始字节完全一致。证据 `ha-order-a-term-rt8_ulzb/P197-local-replay-bound.json` 和 `rearm-errors-order-b.txt`。P197 属于持续活跃的 Robot `R7EV7U`，旧版返场继续保留现场。
- 新的 LOCAL 追平预算与 STRICT 快照后的 4,096 帧窗口分开。LOCAL 原 WAL 直接按原字节拷贝并核对整体 SHA256，保留原主的签名、返场节点独立 fsync 与签名、退役及双侧恢复快照核验。返场扫描在未尝试的分区之前不会反复重试同一个较早失败分区。新增定向回归使用 4,100 条实际 WAL，完整独立故障用例也使用 4,100 条真实 LOCAL 写入，核对两端原 WAL 以及回放后的快照。
- 19:04，`a0aab07` 整包独立物理验收 `PASS`，2305.399 秒。A 强杀接管 236.505 秒、含中断续接的归位 487.174 秒，反向接管 230.176 秒、归位 452.353 秒。各 256 对 WAL 和快照一致。第三次强杀、归位和跨 Epoch 回读通过。保留 `20261110-182427` 的精确包及验收证据，现役部署继续等待包含长前缀修复的新版。
- 最新 Common `003446f` 的 20 项 Java 8 定向测试全部运行通过，证据 `/tmp/mac-t554-v32-final-tests.log`。生产 LOCAL 整段上限为 65,536 条和 64 MiB，STRICT 原后缀上限仍是 4,096。精确包 SHA256 `b4634b689dc767cefd6e6255964e19859359cda39a4c7f3ca41e6be9f52f9f7c` 在 `~/.opentradingcore/t554-common-verifications/20261110-190316` 完成额外长前缀的完整物理验证后，才允许原机更新。
- 19:12，`003446f` 已完成 4,100 条真实 LOCAL 写入，首个返场方向在尝试构建后续严格 Home 阶段时因错误传入 LOCAL 帧数预算而拒绝，独立结果 `NO_GO`。`8b6fcf4` 分离了两项预算，并在失败分区确实抛异常后才轮到其他候选。3 项 Java 8 定向测试均通过，精确包 SHA256 `3834b6f31ade734a2f4cf14e121dd13c70265196520a8b62d3f31f52b413c970` 在 `~/.opentradingcore/t554-common-verifications/20261110-191512` 完整复测。
- 19:12，原机在部分返场状态下取得 5 分钟真实业务样本。4 个活跃租户产生 450 个报价请求、301 个 Tape 请求及 289 笔 Tape 成交，约 0.963 笔/秒。按同租户和同客户订单 ID 关联 289 组 Trade 收到请求与 Order 发布 Filled 的时间，P50 912.397 ms，P95 2795.535 ms，P99 3504.148 ms。Order B 当次资源样本 CPU 76.43%、内存 805.5 MiB。证据 `ha-order-a-term-rt8_ulzb/observed-robot-performance-during-partial-return.json`。稳态负载和客户端往返延迟另行测量。
- 19:22，原机 `RLN7VT` 的 WebSocket `/gateway` 握手返回 101 并核对接受签名，三个本地 Web 端口可读取行情，盘口双边各 10 档、200 条最近成交、1M/5M/15M/1H K 线均可读。证据 `ha-order-a-term-rt8_ulzb/market-live-after-long-local-bound.json` 和 `websocket-current.json`。
- 19:25，`8b6fcf4` 的独立返场中断已恢复 P000/E4，但 P001/E4 在 A 进程返回后新进入签名 RECOVERING，旧进程已在 A 盘落下 P001/E3 的复制 WAL 和独立回执。新进程持有 P001 认证预约，但启动时尚无 P001/E4 记录，返回循环因此没有重建该分区任务。证据 `20261110-191512/fixture-manifest-after-interrupt.log` 和 `P001-durable-return-receipt.json`。停止了该独立用例，保留 `NO_GO`；原机现役未参与这次故障注入。
- `6c67ddf` 允许已认证预约的返场节点，从当前精确同主、高一 Epoch 的签名 STRICT 阶段重建追平任务。现有路径继续校验原见证、双方现役租约、阶段签名及真实本地 WAL 和复制回执。新包开始完整独立验收，目录 `~/.opentradingcore/t554-common-verifications/20261110-192641`。
- 19:38，`6c67ddf` 精确包 SHA256 `e195c2b4d47e4da13987fbcfc5494c50136c635be26425ca8cd1be820ead96ac` 的独立首轮已越过 P001。P042 两侧 LOCAL WAL 都含 4,100 条记录，SHA256 同为 `5633b0f7cf6479655ed45681fdf63c5e0196dbb1e2cc20f2c77b3f32f40252cc`，已有 192 个分区打开新的严格 E4 WAL。归位快照及后续故障仍在验证。
- 20:05，`6c67ddf` 的独立整包验收 `PASS`，耗时 2287.666 秒。首轮接管与额外 4,100 条真实 LOCAL 写入合计 386.876 秒，归位 579.174 秒。反向接管 214.806 秒，归位 408.925 秒，两轮各 256 对原 WAL 与快照一致。P042 两端归位快照完整重放 4,100 条记录，返场中断续接、两种冷启动账本布局、第三次强杀归位和跨 Epoch 历史回读全部通过。现役发布从该封条直接构建，64 秒完成镜像，原 Mac 新代为 `mac-demo-20261110-200523`。旧代及数据卷保留，业务基线和现场双向验收仍在进行。
- 20:15，新代 `mac-demo-20261110-200523` 启动、物理核对与业务基线通过，耗时 464 秒，其中业务 98 秒。纯撮合 `CCZXZE` 与资金交易 `AJKDT8` 各有两个唯一 SQL 执行，公开行情各有一条匹配成交。资金账户余额分别为 999.98200000、999.94600000，双方各有 0.001 持仓。Robot 有 40 个报价请求和两个唯一 Tape 执行；余额、持仓和认证游标一致。证据在新代的 `verification.*` 目录。现场故障验收在真实 Robot 热分区的认证快照前移后自动开始。
- 20:18，原机新代两组客户 `BTC003USDT` 成交均匹配 Order B 的真实发布，Robot `CCZXZE BTCUSDT` 的 37 条公开成交匹配 Order A 的真实发布。证据 `verification.aaOxrP/public-execution-physical-sources.json`。
- 20:28，原盘只读核对 P002/E2 的 B 侧两份认证快照，旧序号 245，现役物理 pin 指向 799。初始轮询到时退出后，直接读回同一原盘的两份验证标记并通过同一增量门禁。`robot-replica-snapshot-advance.json` 保留两份实际目录。随后原机启动 Order A 正常替换 `ha-order-a-term-rx9o0w_g`，固定同一 Robot `CCZXZE`。
- 新代故障前的 5 分钟低负载样本有两个活跃租户、80 个报价请求和 77 个 Tape 请求及 77 笔成交，约 0.257 笔/秒。按同客户订单 ID 关联从 Trade 收到请求到 Order 发布 Filled 的时差，P50 789.554 ms、P95 1116.726 ms、P99 1149.267 ms。证据 `observed-robot-performance-baseline.json`，这是低负载基线。
- 20:34，新代 Order A 正常退出 143，B 在 285.083 秒内接管 256 个分区。原 Robot `CCZXZE` 保持同一进程，接管期间运行 9 轮，最大间隔 31.633 秒。B 单节点产生 2 个唯一 Tape 执行，实际 `Eefa0b65575faf84692f8acf5d4d405` 在公开行情恰好出现一次。纯撮合 `WGYZIP` 的两条执行和唯一公开成交 `E5de563da96c8eadf8117656c26c190` 通过。A 原卷替换保持运行，20:35 已有 43 个分区恢复严格双副本，P002 已到 E4。证据 `ha-order-a-term-rx9o0w_g`。
- 20:47，新代 A 用 763.723 秒完成全部严格 Home，256 对 LOCAL 原 WAL 和 256 对严格快照均一致。`WGYZIP` 的两条原 SQL 执行与原公开行情回读一致，余额和持仓未变；Trade 对账 8 条余额、8 条持仓、5,649 个前驱链接一致。接管期间实测 44 个 Tape 请求、43 笔成交，已成交样本内部延迟 P95 1142.069 ms、P99 1444.331 ms。证据 `ha-order-a-term-rx9o0w_g`。
- 20:49，整轮因同一 `CCZXZE` Robot 严格返场后无新成交停止，保留 `COMMON_PHYSICAL_PAIRS_PASS_BUSINESS_PROOF_PENDING`。A 当前物理角色正常，应用入口 `requireBusinessPartitionRecoveryReady` 拒绝返场时未按原 E2 打开的分区，内部原因为 `Common original E2 replay is fenced for the recovering shard`。`CCZXZE` 与 `WGYZIP` 继续循环但新报单被拒，`AJKDT8` 仍在运行并成交。证据 `robot-after-return-status.json`、`order-a-denial.log`。
- `2ab6826` 在初始业务准入绑定同一个 Common 目标 Epoch 回放门禁。原 E2 保持原检查，返场预约必须在当前认证清单匹配已完成的回放才放行。10 项 Java 8 定向测试通过，2 项按既有条件跳过。独立物理用例增加了返场后调用实际业务准入的断言，原包 SHA256 `77a5eb613a9e90419c8114cff694acccb5936fc93b0264ad72357183a16ba64a` 在 `~/.opentradingcore/t554-common-verifications/20261110-205624` 验证。
- 21:31，`2ab6826` 独立整包物理验收 `PASS`，2014.078 秒。双向接管 202.158 秒（含 4,100 条 LOCAL 写入）和 215.797 秒，归位 470.051 秒和 438.199 秒；256 对 WAL 与快照一致。原应用业务门禁在首轮和第三轮归位后均通过，并写出新双盘确认命令。长前缀、返场中断、冷启动两种账本、历史跨 Epoch 读回全部通过。按封条一键构建耗时 62 秒，原 Mac 新代 `mac-demo-20261110-213105` 开始启动。
- 21:40，新代 `mac-demo-20261110-213105` 的启动、物理核对与业务基线通过，耗时 416 秒，其中业务 98 秒。纯撮合 `XKRPYN` 与资金交易 `YT69XD` 各有两个唯一 SQL 执行，并各有一条对应的公开成交。资金余额 999.98200000 和 999.94600000，双方各 0.001 持仓；Robot 有 40 个报价请求和 7 笔唯一 Tape。Trade 余额和持仓对账通过。证据 `verification.OzepiV`。现役物理热分区为 P073，脚本直接读取目标对侧原盘的认证快照。
- 21:47，真实 Robot `XKRPYN` 热分区 P073/E2 的 B 侧认证快照从 645 前移到 1,349，证据 `robot-replica-snapshot-advance.json`。故障前五分钟样本有 228 个报价请求、223 个 Tape 请求与 219 笔成交，已成交样本内部 P95 1136.160 ms、P99 1198.907 ms。随后 Order A 正常退出，B 在 284.756 秒接管全部 256 个分区。同一 Robot 接管期间运行 9 轮，最大间隔 31.701 秒。B 单节点产生两笔 Tape，并各在公开行情出现一次；纯撮合 `SAWZ5O` 的两个执行及公开行情也通过。证据 `ha-order-a-term-c0asmnsn`，A 原盘替换正在归位。
- 22:05，原机 `2ab6826` 的 Order A 正常滚动验收 `COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS`。严格 Home 归位 762.511 秒，两侧 256 对 LOCAL WAL 和 256 对严格快照一致，纯撮合原 SQL 执行、原公开行情、资金和持仓核对通过。归位期间同一个 Robot 运行 25 轮，最大间隔 35.106 秒；P073 回到 Order A/E5 后有 20 个新报价请求、一笔新 Tape、同一笔成交的两条资金分录及 A 发出的唯一公开成交 `Ed42a1747e45ee242674a86d422b7df`。证据 `ha-order-a-term-c0asmnsn`。随后脚本继续 Order B 正常替换，实际目标 Robot `SAWZ5O` 的热分区 P224 起始由 B 主持，证据 `ha-order-b-term-gnfsaxzu`。
- 22:16，Order B 正常停机后，Order A 接管 255 个分区。P224/E5 已 LOCAL READY，P073/E5 仍是 A 的 STRICT。两份原始 WAL 各 362 帧，SHA256 完全一致。A 保管证书在 362，A 和 B 的独立双签回执在 361，B 保管证书同为 361。Java 8 只读审计使用原 A/B 物理公钥验证两个原盘前缀及回执，精确确认前缀 361 和 SHA256 `5a1c5a06a180bbcee766274153629f79bf3f0fd63acf1e8311f5582c65b441d2`。旧版保留主节点路径从 A 的最新证书开始校验，因此不能通过回执门禁。见 `P073-retained-original-heads.txt`、`P073-retained-watermarks.txt` 和 `P073-signed-prefix-audit.txt`。
- 22:33，当前部分接管的五分钟样本记录两名活跃租户，221 笔报价请求、184 笔 Tape 请求与 184 笔成交，内部 P50 680.901 ms、P95 1135.050 ms、P99 1458.026 ms，Order A 的资源快照为 29.06% CPU 和 748.2 MiB。这个窗口的成交来自继续运行的其他租户。目标 P224 的 Robot `SAWZ5O` 仍在循环，后续五分钟观测 9 轮、最大间隔 33.902 秒，但未观察到该 Robot 新 Tape。其状态记录挂单查询返回通用 `INTERNAL_ERROR`。P073 的 `XKRPYN` 有 Common 分区拒绝。见 `observed-robot-performance-mixed.json`，当前仍是部分接管。
- 22:30，Common `c1659be` 的真实双盘落盘回归已复现主盘证书领先双签的故障窗口。修复用原副本的持久双签回执选择已确认前缀，保留主盘严格退休签名，独立见证再次核对两块原盘。原始未确认尾记录保持可审计。候选 SHA256 `10f9df0dc302cd5f5d67637dca2aff7451a32940afdbf9348af3bb3bc55723e7`，独立演练 `t554-common-verifications/20261110-223044`。
- 22:44，Order `a3bb576` 的挂单查询先筛选租户、用户和品种，再验证匹配分区是否是现任主节点。现场 JFR 在 18 秒内记录了 41,689 次挂单查询触发的已隔离 Epoch 异常，代码仍能捕获其中的 IOException。通用 `INTERNAL_ERROR` 的完整现场因果需在新版反向业务演练核实。定向测试在旧代码复现无关分区异常打断查询，新版连同挂单、撤单及启动门禁共 19 项通过。只提交了该改动及其测试，Order 目录的原有未提交改动仍保留。
- 22:53，部分接管现场按租户复测。相同的五分钟窗口里，`QFAV7O` 和 `YT69XD` 的最长无 Tape 成交间隔分别为 13.469 和 15.345 秒；目标 `SAWZ5O` 和原热分区 `XKRPYN` 整个窗口均无成交。184 笔成交的内部 P95 1729.053 ms、P99 1997.312 ms。证据 `ha-order-b-term-gnfsaxzu/observed-robot-performance-by-tenant.json`。总成交数不能代替故障目标租户的可用性。
- 22:56，现场直接从同一 ZooKeeper 读到 P224 的 Common 签名清单是 A/E5 LOCAL READY，但 Gateway 兼容路由仍是已停的 B/E4。保留着原 A 路由的 P101 与 P039 仍成交。Gateway 现有发布被 P073 的旧 Epoch 隔离拒绝拖住，原 Robot 的挂单查询因此走到旧端点。证据 `P224-gateway-projection-vs-common.txt` 与 `P073-live-census-after-audit.txt`。
- 23:04，Common `d558c84` 定向回归通过。只有已经持有同一 ZooKeeper 会话发布的真实 Gateway 端点，才可逐个更新本机已认证主分区。每次仍需现任物理写入许可、精确版本和业务回放；ZooKeeper 同一事务检查 Common 清单版本及目标路由版本。测试使用真实 ZooKeeper 验证未就绪分区、他节点分区及被隔离的 P073 不更新，P224 可独立推进，变化后的清单拒绝旧版本写入。新包独立物理验收 `t554-common-verifications/20261110-230606` 已启动。
- 23:06，前一个候选 `c1659be` 的独立物理验收 `PASS`，耗时 2077.479 秒。双向接管 204.088 和 231.149 秒，归位 470.094 和 437.892 秒，各 256 对 WAL 与快照一致；4,100 帧 LOCAL 前缀、中断续接、第三次硬停和再次原盘归位均通过。同一时间旧版现场 Order B 正常替换以 `NO_GO` 结束，255 个分区接管，P073 无法通过双签门禁。部署只从已通过物理验收的确切包启动，并保留旧容器和卷。
- 23:18，原 Mac 现役代 `mac-demo-20261110-230620` 安装 Common `c1659be` 和 Order `a3bb576`。构建 124 秒，启动、物理检查和业务基线 617 秒，其中业务 162 秒。纯撮合 `BO2T2H`、资金交易 `HTXWGH` 各两条唯一执行和一笔对应公开行情。资金交易双方各 0.001 持仓，余额 999.98200000 与 999.94600000。Robot 40 个开放报价、6 个唯一 Tape，Trade 游标、4 条余额及 2 条持仓一致。证据 `verification.LldrCB`，三个原 Web 入口均 HTTP 200。
- 23:24，B 原盘同一 P098/E2 的已验证快照在真实 Robot `BO2T2H` 运行中由 390 前移到 948。现场开始 Order A 正常替换，同一 Robot 和真实纯撮合贯穿该轮。证据 `robot-replica-snapshot-advance.json`、`ha-order-a-term-uem_g93b`。
- 23:26，P098 在全量 67／256 时已经切到 B/E3 LOCAL READY；此时 Gateway 仍指向已停的 A/E2，复核了按分区更新路由的必要性。新代故障前低负荷五分钟有 2 个活跃租户、259 个报价请求、108 笔 Tape 成交，内部 P95 1338.762 ms、P99 1745.328 ms。证据 `P098-gateway-route-after-common-local.txt` 与 `observed-robot-performance-baseline.json`。
- 23:30，Order A 退出码 143，B 在 400.934 秒接管全部 256 个分区。同一 Robot `BO2T2H` 在接管期间运行 13 轮、最大间隔 34.507 秒。P098 首次 READY 后、全量接管前，B 已收到 114 个新报价请求并产生 19 笔 Tape 成交，说明该轮旧路由随后推进。全量单节点后，同一 Robot 新增 2 笔 Tape，均按 B 的执行 ID 各出现于一条公开行情。纯撮合 `UQCNQQ` 的单节点成交核验通过，原卷替换进程已启动。证据 `ha-order-a-term-uem_g93b/evidence.json` 及 `robot-public-market-through-fault.json`。
- 23:41，Common `d558c84` 精确包 SHA256 `fc06d06e7307a22563dd3e94884117eff97cf422e87ea132b9b99c756c940909` 的独立物理验收 `PASS`，耗时 2028.230 秒。双向接管 211.135 和 205.786 秒，严格归位 442.816 和 416.438 秒，256 对 WAL 和 256 对快照一致；4,100 帧原始 LOCAL 回放、中断续接及第三次硬停后再归位都通过。现役 A 轮照常完成原卷归位和业务读回，之后从该封条部署后续现场演练包。
- 23:48，Common `c1659be` 的现场 Order A 轮全程通过。A 原盘严格归位 965.366 秒，256 对 WAL 和 256 对快照无差异，纯撮合的原执行、唯一公开成交及资金投影读回一致。返场期间 `BO2T2H` 同一进程运行 32 轮、最大间隔 35.497 秒。归位后新增 20 个报价请求和一笔 Tape，成交对账通过。证据 `mac-demo-20261110-230620/ha-order-a-term-uem_g93b`。A 轮结束后才结束旧调度进程，旧代 B 未注入故障。23:49 在同一台 Mac 开始构建 `d558c84`，保留旧容器和数据卷。
- 23:58，合并版 `d558c84` 成为原 Mac 现役，代号 `mac-demo-20261110-234917`。启动、物理核验与业务基线用时 448 秒，其中业务 101 秒。纯撮合 `M7MF2Q` 和资金交易 `R8VKRM` 各有两个唯一执行并各对应一笔公开成交；资金模式双方各 0.001 持仓、余额 999.98200000 和 999.94600000。两个 Robot 后续均 `RUNNING` 且各 40 个开放报价；基线已有实际 Tape 和投影对账。三个 Web 入口 HTTP 200，Gateway WebSocket HTTP 101。证据 `verification.pDRnAU` 和 `web-readonly-smoke.txt`。正在等待 `M7MF2Q` 所在 P031 的已验证副本快照继续推进，再注入真实停机。
- 11 月 11 日 00:07，P031/E2 的 B 原盘认证快照从 145 前移到 655，合并版现场 Order A 正常替换开始。故障前五分钟有 2 个活跃租户、93 笔 Tape，内部 P95 1105.800 ms、P99 1155.032 ms。证据 `observed-robot-performance-pre-fault.json` 和 `ha-order-a-term-8t17lata`。
- 00:09，A 已停机，B 在 99／256 接管时按认证分区把 P031 的 Gateway 路由提前切为 B/E3。至全量接管前的独立取样中，原 Robot `M7MF2Q` 有 146 个报价请求和 21 笔实际 Tape。每笔按同一成交时间、价格、数量和两个方向核对为恰好一条公开成交，21 笔各有两条 Trade 资金分录。全段记录 24 笔 Tape；全量接管 301.627 秒。证据 `P031-robot-gateway-public-before-full-takeover.json`、`P031-gateway-route-during-partial.txt` 和 `evidence.json`。纯撮合单节点核验通过，A 原卷替换进入归位。
- 00:25，P031/E5 卡在已签名的 Home RECOVERING，其余 255 个分区严格 READY。旧 E4 两份 WAL SHA256 相同且均 2066 帧，旧 B 主盘保管证书到 2066，A 副本已发布证书和两盘双签回执均到 2065。A 的 `head.pending` 是未发布的 2066。两 JVM 的 JFR 都显示 Home 回放因 `pending or unknown custody file: head.pending` 拒绝读取旧盘。见 `P031-home-pending-watermarks.txt`、`home-errors-order-a.txt`、`home-errors-order-b.txt`。
- 00:33，Common `f87ac68` 针对已退休原盘，允许只读核验已有双签的已发布前缀，并保留识别出的待发布证书。完整的待发布证书要通过原 RSA 与原 WAL 前缀校验，仍不会加入回放。定向回归在真实落盘后、发布前触发隔离，19 项通过，另一个依赖外部测试盘的用例跳过。现场原盘的只读副本用 A/B 公钥实际核验第 2065 条和 SHA256 `28a9c5de0e81ab0a843a2b27953bc2d7353ff18ccdea3649eb618b4a0b8b4ecc`，待发布文件的 SHA256 保持一致。证据 `P031-signed-retired-prefix-audit.txt`。
- 00:34，确认原盘、待发布证据及两个物理服务的四个进程都保留后，结束已确认卡住的验收脚本，现场状态仍为 `NO_GO`，Common 进程继续运行。候选 SHA256 `e7d268e42eb19cdfd57b3f50ac601884f01f9f9c8d3c433314eb7770781b1af6` 在 `t554-common-verifications/20261111-003420` 进行独立物理验收，现场部署只在准确封条通过后开始。
- 00:37，返场证据还显示 Gateway 已将 P002 和 P030 指向 A/E5，而 A 的物理端点目录没有活租约条目。旧端点发布仍在等待全部分区 READY，被 P031 阻塞。证据 `P031-stalled-return-gateway-projection.txt`。部分归位的五分钟样本中，`R8VKRM` 仍产生 31 笔 Tape，P95 3382.247 ms、P99 3422.149 ms；`M7MF2Q` 无新 Tape。
- 00:42，Common `3469abb` 合并已退休 WAL 的已发布双签前缀修复及返场端点修复。返场端点需要现役 ZooKeeper 会话拥有该节点物理租约、已建立的原路由，以及至少一个本机主分区已通过精确版本的 Common 权限和业务回放。初次启动继续要求全量物理验收。真实 ZooKeeper 回归覆盖初次启动、会话不符、无有效本机写入者及只就绪一个分区等条件，20 项定向测试通过、1 项缺外部测试盘跳过。Order 和 Trade 的现有轮询在首次登记后再刷新当前清单，以处理尚未完全发布的路由。独立完整演练在 `t554-common-verifications/20261111-004254`，只安排该合并包部署。前一包独立测试继续保存证据。
- 00:51，P2 的稳态和突发入口已准备好。稳态由实际租户申请和 Robot 自发流量测出 10／50／200 租户的吞吐、内部延迟、每租户最大无成交间隔和资金投影。突发在专用 Demo 试用租户内创建认证客户，通过实际盘口发送带唯一编号的 IOC，用实测稳态速率计算额外流量，记录 HTTP 延迟、SQL 执行和资金游标。每轮可在流量持续时执行一个真实 SIGKILL。已验证现场只读盘口字段、SQL 查询结构及价格选择逻辑。实际压测须等合并包的现场正常和硬停试验完成后启动。
- 00:55，`f87ac68` 的单独独立试验在首轮 Home 归位推进到 P111 时达到测试等待时限，保存 `NO_GO` 和完整进程记录，没有独立发布。合并版 `3469abb` 的 SHA256 为 `3eb12536fbcaff9e37b763e3e1f691a5009015d84943620da620228750a88055`。00:58 合并版通过独立首轮归位、中断返场续接、4,100 帧完整回放及两种账本布局。01:02 已通过反向全量接管，继续原盘归位及第三次故障。
- 01:23，合并版 `3469abb` 独立完整验收 `PASS`，耗时 2298.259 秒。两次接管 384.336 和 212.549 秒，归位 432.864 和 457.113 秒，256 对 WAL、256 对快照一致。第三次硬停的全量 LOCAL、原盘再次归位与跨 Epoch 原历史读回通过。证据 `t554-common-verifications/20261111-004254`。同一 Mac 从该确切封条启动合并版部署。
- 01:31，现役代 `mac-demo-20261111-012248` 部署 `3469abb`。构建 82 秒，启动、物理核验及业务基线 420 秒，其中业务 102 秒。纯撮合 `PH5ZWH` 与资金交易 `GM8OJQ` 各两条执行、一条对应公开成交，后者两侧各 0.001 持仓、余额 999.98200000 和 999.94600000；基线通过 Robot Tape 和资金投影对账。四个端点初次登记均走原全量门禁。证据 `verification.fBwSzR`。热分区 P237 在 Order B，先安排 B 正常停机。
- 01:40，P237 的 A 原盘已验证快照从 200 前移到 712，Order B 正常退出。01:41，现场只接管 47／256 时，Gateway 已切换 P237 至 A/E3。同一 `PH5ZWH` Robot 在 121／256 的未完成状态下采到 114 个报价请求、4 笔 Tape，各有唯一公开成交和两条资金分录。证据 `ha-order-b-term-wkj062k_/P237-robot-early-gateway-public.json`。
- 01:45，A 用 288.116 秒接管全部 256 个分区，已通过过去 255／256 的反向卡点。P067 原主 A 有 608 帧，B 原盘和双签前缀为 607 帧，原尾记录仍保存，现场签名清单已恢复 P067/E3 LOCAL READY。全量前 `PH5ZWH` 记录 19 笔 Tape，全量后 4 笔；纯撮合单节点测试通过，B 开始原卷返场。证据 `P067-signed-original-prefix-audit.txt`、`robot-public-market-through-fault.json` 和 `evidence.json`。
- 01:54，返场 B 在原 Home 尚未全部恢复时已发布真实 Gateway 端点。观察时只有 9 个严格分区以 B 为主、247 个仍由 A 主持，B 端点别名已由真实会话持有，日志标明 `returningWithReadyPrimary=true`。证据 `returning-b-gateway-during-partial.json`。这条现场路径通过了此前必须等最后分区的端点门禁。
- 02:01，P237/E5 是最后唯一尚未 READY 的分区。两盘旧 E4 WAL 都是 1553 帧且 SHA256 完全一致，两盘保管证书都已发布 1553，两个双签回执只到 1552。JFR 在 B 的返场线程反复报 `receipt ledger head != physical custody`。利用 A 原物理盘的 1552 提交索引和 B 原盘双签回执，Java 只读复核 1552 前缀及其 SHA256 `93077a447c6ff5d39eee29fedba0cbeb52815d68e08ef5dba8730ebc11a7434c`，两份 1553 原 WAL 均保留。证据 `P237-home-old-physical-watermarks.txt` 和 `P237-signed-retired-prefix-audit.txt`。
- 02:09，Common `3da1ae5` 在同一次双签回执持久化中保留对应原提交证书，不增加新的刷盘步骤。原格式仍可通过原主的只读提交索引复核。普通启动和 ACK 门禁继续要求当前精确水位；跨 Epoch 的原盘审计只采用已发布并经双 RSA 校验的回执水位。36 项定向回归通过，1 项依赖外部测试盘跳过。已结束卡在 P237 的现场验收脚本，四个物理进程仍在运行，旧卷和数据没有修改。新的整包独立验收目录为 `t554-common-verifications/20261111-020920`，候选 SHA256 `979c1bf044b036a762d5800f16d982caa293d54ee10f8de08b23207e4d16c59d`。
- 02:22，`3da1ae5` 独立整包验证首轮通过 4,100 帧 LOCAL 的双盘原字节及回放、中断的已签名返场续接，以及两种冷启动账本目录。反向角色切换继续。现场上一轮 B 正常停机的样本为 P237 在 55.744 秒切到认证 Gateway 路由、63.087 秒有首笔可对账公开成交、288.116 秒完成全 256 分区接管。故障前五分钟两个租户共 84 笔 Tape，内部 P95 为 1094.571 ms、P99 为 1150.097 ms。
- 02:25，只归档 10 个已停止的历史容器的 stdout/stderr 文件。Mac 本地 gzip 回读逐字节核对原 SHA256，复核容器仍停止后才释放 Colima 上的原日志，容器及挂载卷仍保留。约释放 2.94 GiB，归档位于 `~/.opentradingcore/t554-retired-log-archive-20261111`，哈希清单为 `/tmp/mac-t554-v40-archive-retired-logs.log`。
- 02:27，压测采集改为按物理容器 ID 读取采样窗口相交的投票进程，滚动改名后仍能读取退役进程及替换进程的各自日志。用原 Mac 已完成接管的 B 停机窗口读回，同一窗口同时命中原 B 和替换 B，识别 182 笔 Tape、182 个可配对延迟；后续窗口准确排除旧 B。证据 `ha-order-b-term-wkj062k_/performance-with-original-and-replacement.json`。突发验证还要求 Docker 记录的 137 实际停机时刻落在流量窗口内，窗口内、窗口外及错误停机码检查均通过。
- 02:37，`3da1ae5` 独立整包通过双向原进程 SIGKILL、自动接管及原盘严格归位。A/B 接管 217.861、331.476 秒，归位 470.855、475.811 秒，256 对原始 WAL 和 256 对严格快照均相同。第三次真实强杀继续验证重复返场和原历史读回。稳态和突发脚本每 30 秒记录实际投票者、Robot、Gateway、MySQL、ZooKeeper 的 CPU 和内存，已在原 Mac 只读抽样通过。
- 02:48，`3da1ae5` 独立整包验收 `PASS`，2277.188 秒。第三次强杀完成全部 256 个 LOCAL 接管、再次严格归位的 256 对物理匹配及跨 Epoch 已退休历史读回。精确验证目录 `t554-common-verifications/20261111-020920`。同一台 Mac 开始一键部署原件，新代 `mac-demo-20261111-024814`，构建阶段 61 秒，保留先前环境的容器和数据卷。
- 02:56，新版原 Mac Demo 完成物理和业务基线（451 秒，其中业务 102 秒）。全部 512 个 Order/Trade 分区为严格双副本 READY，`L6VR9G` 与 `UDOR88` Robot 均运行。纯撮合和资金交易各有两个唯一执行以及唯一公开成交，资金游标核对了 4 条余额与 2 条持仓。证据 `mac-demo-20261111-024814/verification.KNg5JY`。三个现有 Web 入口返回 HTTP 200，交易 WebSocket 握手为 HTTP 101 且接受签名吻合，证据 `web-readonly-smoke.txt`。首轮将锁定仍在写入的纯撮合 Robot 所在 P045。
- 03:01，持续运行的 `L6VR9G` 将同一 B 原盘 P045/E2 的认证快照从 152 推进到 668。首轮真实正常停机的 Order A 退出码 143，B 在 89／256 时先取得 P045/E3 写入权，现场 ZooKeeper 已将 Gateway 路由改到 B/E3。故障前五分钟两个租户共 72 笔 Tape，内部 P95 1203.661 ms、P99 1254.806 ms。证据 `observed-robot-performance-baseline.json` 和 `ha-order-a-term-vpjatl8h`。
- 03:08，B 全量接管耗时 372.834 秒。同一 Robot 在全量接管前有 658 个报价请求、4 笔 Tape，独立单节点窗口再有 2 笔。停机到全量接管期间同一 Robot 运行 13 轮，最大轮次间隔 33.121 秒。按实际日志窗口回读六笔，公开行情每笔恰有一条、每笔有两条 Trade 资金分录。纯撮合单节点探针通过。A 替换 JVM 已在原卷启动。证据 `P045-robot-pre-full-public-retrospective.json` 和 `P045-robot-single-node-public-retrospective.json`。
- 03:21，返场 A 已发布真实 Gateway 临时端点，端点和投票者物理租约由同一个 ZooKeeper 会话持有。当时只有 61 个严格分区以 A 为主，其余 195 个仍由 B 持有。证据 `returning-a-gateway-during-partial.json`。只读检查 P045/E2 两块原物理卷，均保留 v2 双签回执，第 860 条、嵌入提交证书 SHA256 和原 WAL 前缀完全相同。证据 `P045-retired-receipt-v2-readback.json`。
- 03:24，最新 `3da1ae5` 在原 Mac 的 Order A 真实正常滚动完整通过，原盘归位 920.835 秒，256 对 WAL 和 256 对快照逐一一致。纯撮合单节点及归位后读回、同一 Robot 归位后成交、Trade 余额持仓和事件前驱对账通过。保留 `ha-order-a-term-vpjatl8h/evidence.json`。紧接进入反向 Order B 正常替换 `ha-order-b-term-s_oqsb_s`。
- 03:25，Order B 正常停机后，持续运行的 `BQZMNL` 位于 P130。原容器真正退出后 64.609 秒记录 P130/E5 首次认证写入（36／256），66.569 秒的现场样本在 39／256 时已从 A 路由读到唯一公开成交和两条资金分录。全量 371.475 秒。前段共 89 个报价请求和 47 笔 Tape，全量单节点再有 2 笔，49 笔逐笔回读均恰有一条公开成交和两条资金分录。资金交易单节点探针通过后，替换 B 用原盘启动。见 `ha-order-b-term-s_oqsb_s`。
- 03:34，围绕这次正常停机的八分钟低负荷样本覆盖 4 个有流量的租户和 131 笔 Tape，内部 P95 为 4085.208 ms、P99 为 5014.085 ms。P130 目标租户的最大 Tape 成交间隔为 77.242 秒；其他租户的间隔另列，包含窗口边界。证据 `ha-order-b-term-s_oqsb_s/performance-around-real-term-fault.json`。
- 03:50，最新 `3da1ae5` 在原 Mac 的 Order B 正常滚动也完整通过。全量接管 371.475 秒，B 原盘严格归位 1132.586 秒，256 对 WAL 和 256 对快照一致。资金单节点交易、公开行情、回归后同一 Robot 的实际 Tape 和资金游标均通过。热分区 P130 已从 A/E5 经严格 E6 回到 B/E7，E6 双盘回执 v2 都在第 1865 条并嵌入同一提交证书。证据 `ha-order-b-term-s_oqsb_s/evidence.json`。紧接开始 Trade A 的单节点业务和归位验收 `ha-trade-a-term-4bjygxw2`。
- 04:02，真实 Trade A 正常退出 143 后，Trade B 自动接管 253／256。P010/E3 在 141／256 时已恢复同一 Robot 的 LOCAL 写入。未切换的 P187/P190/P218 均为 B 原主、A 停止。B 的 JFR 在 `common-witnessed-return` 捕获 `Common crashed owner committed window exceeds the frame bound`，从旧主保留分支实际调用原盘窗口检查。
- 04:06，三组原盘各自 v2 双签回执在 5347／5399／4442，证书和已确认前缀匹配。已停 A 的认证快照只到 1／8／2；B 同 Epoch 保留的本地主快照已到 5345／5398／4441。A 原盘文件约 24.11／24.31／20.37 MB，SHA256 等于已确认前缀，B 原盘每组保留一条额外原记录。证据 `ha-trade-a-term-4bjygxw2/trade-a-stopped-retained-snapshot-watermarks.txt`、`trade-a-stopped-wal-and-primary-pins.txt` 和各 Pxxx 回执读回。原盘未变更。
- 04:12，Trade B 在同一 Robot P010/E3 已记录 172 条带 LOCAL RPO 风险的结算收据；在这个未归位的现场，异步 SQL 投影仍在 P010/E2 的 2315，未计为一致性通过。已保存证据并只结束卡住的现场验收进程，Trade A 仍停机，B 与两个 Order 投票进程继续运行。新版 Common `df62b3c` 继续优先采用原 4,096 条窗口与经双签的副本快照，无法使用时才从原有双签 Genesis 离线读取原字节，最多 65,536 帧、64 MiB，以 4,096 条分批核验。严格 ACK、签名 Stage、隔离及独立 Witness 仍要求原证明。精确候选 SHA256 `667121ed729eca5671ac5ee57604974b0e0d3893c92d9ca8aef9a6bb1eac4c2d` 在 `t554-common-verifications/20261111-041149` 独立验证。新回归先用真实双物理投票者写 4,100 条 STRICT，然后停掉副本并验证没有新快照时的同一所有者自动切换与业务回放。
- 04:18，`df62b3c` 独立验证已使用原始签名 Genesis（快照序号 0）恢复保留原主的 P129。两盘旧 STRICT WAL 各 127,100 字节，SHA256 同为 `e89e9bf457774a59513bdf4bb2742edcada473fc5f8a6b1ce3c68bbe2db6d911`；本地恢复账本 `REPLAY_COMPLETE` 到 4,100，独立见证已落 E3 签名。整包仍需双向、原盘归位、跨 Epoch 读回及第三轮强杀结果。证据 `t554-common-verifications/20261111-041149/long-strict-p129-proof.txt`。
- 04:26，独立 `df62b3c` 首次完成 P129 的 4,100 条原始 STRICT 接管，但该分区返场重读已签名 Genesis 时仍走旧的 4,096 条后缀分支，拒绝 `COMMON_STRICT_CROSS_EPOCH_LOCAL_SUFFIX_OUT_OF_RANGE`。原 E3 签名与双方原 WAL 一直保留。Common `3577fa0` 把精确 Genesis 归位重读接到同一离线分页器，非零快照的后缀上限保持不变。等待第一轮独立验收收尾，下一精确整包随后串行执行，避免两个物理测试互相争用。
- 04:30，旧独立整包停在 P129 返场并按原测试时限写下 `NO_GO`，从未部署。精确 `3577fa0` 已在 `t554-common-verifications/20261111-043022` 开始串行复测，JAR SHA256 `665dfe0a3b59b0d9ae23b508e9f9460ef8302ac9b133f3d9b9e980f8a64c8c3f`。只有全部物理、业务快照及重复返场通过才允许原机一键部署。另安排在现役完整的 Trade 双副本阶段只读跟踪原主和认证副本快照水位，必要时采样相同物理 JVM 的拒绝原因。
- 04:41，`3577fa0` 已让 P129 归位为严格 E4。直接只读核对其 E3 交换目录中的两个原 E4 Genesis，均 12,303 字节，逐字节等于原基线加 4,100 条命令，SHA256 `e1881ff4fb52bea4bdf6da62f90084ce7e483014e1dd107dd90e34a5e319992f`。证据 `t554-common-verifications/20261111-043022/p129-actual-strict-rearm-proof.txt`。原验收用例把该文件的交换 Epoch 写成 E4，第一轮原盘已归位后以 `NoSuchFileException` 结束，整包没有发布。仅修正测试定位（E3）并增加严格归位快照通过标记，生产源码相同。新精确 `a888419`、SHA256 `ef897c93f5ea97e650d5d0450668c82f00c0134de30ee7b3af6730d4a6420de4`，串行验证 `t554-common-verifications/20261111-044408` 自 04:44 运行。
- 04:59，`a888419` 正式通过首轮四个检查：P129 的 4,100 条严格记录和 P042 的 4,100 条 LOCAL 记录均按原字节追平，归位快照各自在两盘逐一一致，签名返场被打断后仍成功续接。独立日志新增 `T554_EXTENDED_STRICT_GENESIS_REARMED_SNAPSHOT_PAIR_PASS`，开始反向强杀和归位。
- 05:12，`a888419` 独立双向强杀与严格原盘归位正式通过。两次全量接管分别为 207.413、335.363 秒，两次归位为 479.622、470.743 秒，256 对 WAL 和 256 对快照一致。第三次硬停继续。
- 05:24，`a888419` 独立整包正式 `PASS`，2351.104 秒。第三次强杀、再次严格归位的 256 对物理匹配、跨 Epoch 退休原历史及 LOCAL 读回全部通过。依据 `t554-common-verifications/20261111-044408` 的精确封条，在同一台 Mac 开始一键替换；旧 Trade 单节点的签名证据、原 WAL、容器及数据卷保留。
- 05:34，最新 `a888419` 已成为原 Mac Demo 现役 `mac-demo-20261111-052410`，一键构建 104 秒，启动、物理及业务验收 485 秒，业务 105 秒。Order/Trade 共 512 个分区严格 READY。纯撮合 `LKR4LC`、资金交易 `P02EJA` 各有两个唯一执行与一个公开成交，4 条余额、4 条持仓及 Robot Tape 对账通过。三个原 Web 入口返回 HTTP 200，交易 WebSocket 返回 101。证据 `verification.jQ5Sba`、`web-readonly-smoke.txt`。P115 的认证副本快照正由同一 Robot 推进。Trade 的原主与副本快照开始按租户只读采样。
- 05:38，第二批 15 份只涉及停止容器的旧 stdout/stderr 已 gzip 归档并回读 SHA256，释放 1.031 GiB。业务卷和容器仍保留。Colima 可用空间约 5.2 GiB，归档 `~/.opentradingcore/t554-retired-log-archive-20261111-second`，哈希清单 `/tmp/mac-t554-v43-archive-retired-logs.log`。
- 05:42，新版两租户均运行并各有 40 个开放报价。五分钟共 71 笔 Tape，P95 1199.857 ms、P99 1256.113 ms，最大成交间隔分别为 11.057 和 11.061 秒。见 `observed-robot-performance-before-replica-gate.json`。
- 05:45，持续 Robot `LKR4LC` 的 B 原盘 P115/E2 快照从 120 前移到 586。A 正常退出后 44.685 秒，P115/E3 先在 33／256 时恢复认证写入。现场在 116／256 核对 15 笔唯一公开成交和各两笔资金分录。B 全量接管用时 315.894 秒，全量前 42 笔 Tape，单节点 2 笔，44 笔均逐笔复核。纯撮合单节点通过，A 开始原盘返场。证据 `ha-order-a-term-9ur94nqc`。
- 05:56，在两个 Trade 投票者均健康时，对真实物理 JVM 采集到 `Adjusted frame length exceeds 65536: 65847 - discarded`，同一时间 `common-certified-replica-snapshot` 报 `VerifiedRecoveryStagingClient.stageWithBatch` 的 TCP 读失败。P090 原主快照已超过 512，而副本仍在 7；P170 同类独立采样也复现。原现场不是缺少主快照，原因是请求 65,536 字节的数据后，RSA 签名、控制响应、请求号和 TCP 长度前缀令完整响应达到 65,847 字节，超过应用真实 65,536 字节接收上限。证据 `trade-snapshot-lag/p090-healthy-voter-a.jfr`、`p090-healthy-voter-b.jfr` 及解析文本。
- 06:01，测试先在真实 64 KiB 接收通道和 196,637 字节 RSA 快照中复现 TCP 失败，再让分块按实际配置减去完整签名、控制封包和 TCP 前缀的开销。12 项实际 TCP、传输认证和冷读回测试全部通过，日志 `/tmp/mac-t554-v44-snapshot-red.log`、`/tmp/mac-t554-v44-snapshot-green.log`。Common `ae3d977`，新增大快照回归已接入一键物理验收入口，原物理回归继续使用同一候选 JAR。06:03 开始精确整包 `t554-common-verifications/20261111-060323`，现役现场的本轮归位继续执行。
- 06:42，带自适应签名分块的 `ae3d977` 精确整包正式 `PASS`，独立故障用例 2216.563 秒。双向全量接管 204.483／250.382 秒，严格原盘归位 470.061／446.782 秒，256 对 WAL 和 256 对快照相同。大 RSA 快照 196,637 字节经 64 KiB 接收通道传输和冷读回、4,100 STRICT + 4,100 LOCAL、被打断的签名返场、第三轮强杀和再次归位、退休历史跨 Epoch 读回均通过。证据 `t554-common-verifications/20261111-060323`。原机当前 B 轮继续完成最后归位，旧故障调度器停在下一轮之前，当前物理和业务验收子进程继续。仅在此轮通过且四投票进程都运行时，才写下一版切换边界。下一版先验证两个 Trade 单节点，并分别确认 Order、Trade 的真实认证副本快照至少前移 256 且达到 512。
- 07:04，按用户优先要求，在原 Mac 当前环境通过真实客户认证 API 完成下单、挂单查询和撤单。资金模式 `P02EJA/BTCUSDT` 下单响应 237.160 ms、撤单 182.976 ms，挂单冻结保证金 7.3191 和手续费 0.08343774，撤单后全部释放、余额仍为 1000。纯撮合 `LKR4LC/BTC003USDT` 下单 1045.451 ms、撤单 480.620 ms，挂单前、中、后资金均为零。两单均在实时查询确认挂单后撤销，SQL 最终 `Cancelled`、成交记录为零。第一支纯撮合探针选用了实际为 TRADE 的 BTCUSDT，其无资金请求被 `TRADE_COMMON_SIGNED_FINANCIAL_RESERVE_MISSING` 拒绝，已纠正商品选择并重测。三张测试单均为拒绝或撤销，没有遗留挂单和成交。证据 `mac-demo-20261111-052410/order-cancel-acceptance-20261111-0704.json`。这些单次响应不是 P95/P99 统计。
- 06:49，现役 `a888419` 的 Order B 原盘归位完成，1789.234 秒，256 对 WAL 与 256 对快照一致；后续 Gateway 全清单业务核验失败，现场写为 `COMMON_PHYSICAL_PAIRS_PASS_BUSINESS_PROOF_PENDING`，未计整轮通过。原 A 的 P093/E7 已因一次写入不确定结果保持隔离，A 原 WAL 791 条，B 原 WAL 和两份双签回执均到 790。原 A 的前 790 条逐字节等于 B 完整 WAL，SHA256 `38619cef2f2cc164bd6870a68c4a0eae07626870aed7c1ae3861126ced57a08f`，第 791 条原尾保留。其余三个 Robot 正常，Q90YL4 因 P093 写入隔离报错。没有清空 WAL 或解锁原 Epoch；`P093-confirmed-prefix-and-preserved-tail.json`、`current-source-head-admission.txt`、`P093-current-business-errors.txt` 保留证据。该生产恢复路径仍需解决。
- 用户选择先测本机真实容量和 P99，再确定生产指标，并优先要求下单撤单。07:04 功能检查完成后，依据已有同机重新部署授权，在保留这次失败证据、全部原容器及卷的前提下，切入已完整认证的 `ae3d977` 做健康基线。压测顺序调整为健康基线和真实 Order/Trade 副本快照前移之后，先跑 10／50／200 稳态，再各做 7 分钟 2.5 倍突发和真实 Order／Trade SIGKILL，后续继续完整恢复验收。容量结果与 P093 的故障恢复未通过项分别报告。

## 2026-11-11 07:13 下单与撤单优先测量接续

- v44 同机新代际为 `/Users/kong/.opentradingcore/mac-demo-20261111-070452`。精确 Common SHA 为 `b7609c800637cab23a049084c0a94716e45f7f55fc14b756907cf625ac3ad8f1`。构建 117 秒，物理出生与业务基线正在执行。旧代际全部容器、卷及 P093 791/790 原始证据保留。
- 用户要求先测试下单和撤单，因此只暂停宿主验收调度器 PID 75570，当前部署子任务照常运行。基线通过后先执行 `scripts/verify-mac-demo-order-cancel-capacity.py`，再恢复原 Robot 多租户和 HA 日程。未暂停或重启任何在测业务 JVM。守候入口为 `/tmp/mac-t554-v44-order-cancel-first.sh`，日志为 `/tmp/mac-t554-v44-order-cancel-first.log`。
- 连续测试按 ORDER_ONLY BTC003USDT 与真实 TRADE BTCUSDT 分别使用 1、4、8 个客户端，每档 60 秒。客户端闭环执行下单、确认 New、撤单、确认挂单消失，记录下单 ACK、撤单 ACK 和完整周期 P50/P95/P99、周期吞吐及 CPU/内存。每档独立核对全部 ClOrdID 唯一、最终 Cancelled、零成交及资金回到初值。此为带查询确认的闭环实测吞吐，不能冒充引擎最大 TPS。每次仅一个在途订单，不重放含糊结果的下单。
- 已完成脚本编译、百分位和 ClOrdID 识别检查，连续实测尚未开始。此前 07:04 的两种模式单次实测通过仍独立保存，不用单次数据计算 P99。
- 磁盘清理先核对所有现有容器的 Image ID，再删除三个无标签且无容器引用的旧镜像，ID 为 c8ecc4b89acf、0143d770744e、92ed8a892264。Docker 记录在 `/tmp/mac-t554-v44-unused-image-cleanup.log`。由于共享层仍被引用，本次删除后可用空间未出现明显增加，不能以镜像显示大小宣称释放量。Colima 仍约 3.8 GiB 可用，后续负载前继续检查。

## 2026-11-11 07:29 连续下单撤单发现订单复活竞态，修复后重新实测

- v44 代际 `mac-demo-20261111-070452` 基线实际通过，构建 117 秒，初始化和物理/业务验收 572 秒，业务段 97 秒。纯撮合租户 KPH621，资金撮合租户 FPIP3S，公开成交对应、Robot Tape 与资金持仓游标均有实证。
- 连续实测报告为该代际 `order-cancel-capacity-eb396e82.json`。ORDER_ONLY 单客户端 60.073 秒完成 290 个完整循环，4.827 循环/秒。下单 ACK P95/P99 为 172.587/298.459 ms，撤单 ACK 为 168.323/296.684 ms，全周期 P99 为 601.479 ms。该档 SQL 全部 Cancelled、零成交、资金无变化，PASS。吞吐包含两次私有订单查询。
- 四客户端档 NO_GO。377 次尝试中两次撤单 ACK 后挂单仍持续可见，30 秒后相同订单取消清理成功。日志明确同一订单先发布 Pending_Cancel、Cancelled，随后成为 New，原始过滤日志为 `/tmp/mac-t554-v44-cancel-failed-order-b.log`。测试结束后全部 667 个测试订单 SQL 为 606 Cancelled、61 New，零成交。其余取消后短暂不可见的订单也可能稍后被旧 Maker after-state 重新插入。原失败报告保留。
- 已加强负载脚本，在客户端退出并排空后再核对私有挂单与 SQL，并在失败时使用内存中的原认证会话逐笔清理本轮订单。失败现场的旧账户凭据原先仅存内存，进程退出后已失去会话，未通过改库强行清理。其完整数据随失败代际保留，后续同机新部署使用新业务代际。
- 根因已通过确定性并发回归复现。Order 的 `OrderPartitionBarrier.enterMutation` 使用共享读锁，允许 Maker after-state 准备和取消两阶段并发。Common 串行化物理提交，但过期 Maker 候选仍可在取消 REMOVE 之后提交并重新插入 New。
- 修复复用现有分区屏障，变更为可重入独占锁，使同一分区业务准备与 Common 持久化/apply 连续执行。其他分区独立可用。Common JAR 及 ACK/Fencing 未修改。Order 提交为 `890d260065b8c17f81a29bb3f26bdecf2b118ca7`，只提交屏障与回归测试两个文件，原有脏文件保留。
- 回归先红后绿。红日志 `/tmp/mac-t554-cancel-race-red.log` 明确复现成功取消后 Maker 恢复 New。修复后 28 项通过、零失败零跳过，含真实双 RSA/Common WAL 非空快照与后缀重放、取消分阶段、撮合、部分成交、分区锁可重入及其他分区可用。绿日志 `/tmp/mac-t554-cancel-race-green.log`。测试使用实际 v44 Common 和当前 shared JAR。
- 按用户已授权的同机重新部署，旧失败现场与全部数据保留。流程为 `/tmp/mac-t554-v44-cancel-fixed-capacity-first.sh`，同一已验收 Common v44 配合修复后的 Order，依次完成基线、下单撤单 1/4/8 客户端、副本快照推进、Robot 10/50/200、突发叠加硬故障及正常滚动。原代际 `t554-cancel-race-redeploy-boundary.json` 记录了当时全部 Order/Trade 各 256 STRICT READY 和四 JVM 运行。只结束已暂停的宿主验收调度器，业务容器由原一键部署流程管理。
- 修复后的新代际为 `mac-demo-20261111-072730`，构建 62 秒。shared 源文件逐项 SHA 与前代完全一致，重建 JAR 归档 SHA 为 `f1a95ed0776bf691ed90108cca8066043bfa6255287124870765e5a306f28455`。Common SHA 仍为 `b7609c800637cab23a049084c0a94716e45f7f55fc14b756907cf625ac3ad8f1`。
- 新增一键入口 `./mac-colima-saas.sh verify-order-cancel RUN_DIRECTORY`。实际入口调用、缺参拒绝及既有 Mac 门禁通过，日志 `/tmp/mac-t554-order-cancel-entry-tests.log`。
- 定向清理旧构建缓存保留最近 24 小时与至少 10GB，Docker 实际回收 0B。当前空间压力继续监控。旧 v43 P093 已确认 790 条与未确认第 791 条的自动恢复缺陷仍未完成验收。

## 2026-11-11 07:41 修复版纯撮合下单撤单三档通过

- `mac-demo-20261111-072730` 完整基线通过，初始化与物理/业务检查共 475 秒，其中业务验证 114 秒。运行中两台 Order 的屏障 class SHA 均为 `a834e2f413b625d675094b201f085b1b7187632670250e509a60046bab2af82c`，与 28 项回归使用的字节一致。
- 添加一键撤单入口时修改了正在执行的 `mac-colima-saas.sh`，使原调用者在全部基线检查完成后因读取位置偏移报 unexpected EOF 并退出。当前文件语法与入口门禁通过，业务进程正常。经真实运行状态和完整基线证据核对后，从 `/tmp/mac-t554-v44-cancel-fixed-resume.sh` 接续，日志为 `/tmp/mac-t554-v44-cancel-fixed-resumed-capacity.log`，未重复部署或基线。该调度问题记录于代际 `post-baseline-scheduler-resume.json`。
- 实测报告 `order-cancel-capacity-8d35cf81.json`。ORDER_ONLY 1/4/8 客户端分别完成 286/451/458 个完整循环，吞吐 4.760/7.445/7.524 循环每秒。下单 P99 为 277.096/694.440/1275.599 ms，撤单 P99 为 333.636/434.524/913.143 ms。每档排空后私有挂单为零，全部测试订单 SQL 唯一且 Cancelled、零成交、资金不变，三档 PASS。完整报告仍在继续资金模式，尚未标整体 PASS。
- 这是带下单查询与撤单后查询的闭环、单租户单分区负载。三档均各 60 秒，仍不足以作为生产持续容量承诺。测量环境为原共享 Mac，10 逻辑 CPU、24 GiB 主机内存，Colima 8 CPU、约 15.6 GiB 内存，共 48 个容器运行。07:40 的 Colima 一分钟负载均值为 13.21，其他旧服务照常运行。原始环境证明见 `capacity-environment.json`。
- 77 个已退出容器的轮转日志逐个完成原 SHA、压缩后完整解压 SHA、尺寸、停止状态、归档 fsync 和清理后尺寸核验。释放原文件 3813280816 字节，约 3.55 GiB，压缩归档共 429182694 字节，位于 `/Users/kong/.opentradingcore/t554-retired-log-archive-20261111-rotated`。完整清单与校验为 `/tmp/mac-t554-v44-retired-rotated-log-cleanup.log`。现役日志、业务卷与容器保留，Colima 可用约 6.9 GiB。

## 2026-11-11 07:58 下单撤单专项六档实测通过，保留价格可用性失败记录

- 首轮自然币安 BTCUSDT 资金测试在完成 130 次成功取消后，第 131 笔异步 Rejected，明确业务原因 `MARKPX_NOTEXIST`。该档报告 `order-cancel-capacity-8d35cf81.json` 继续标 NO_GO。账户余额 10000，已用及冻结保证金、冻结手续费均为零，无挂单和成交遗留。Order/Trade 四节点未见 Common poison 或提交阶段错误。同期 APS 未找到相应断流告警，Robot 后续继续成交，当前无法把短时缺价确定为外部币安故障。Trade 的风险标记价格时效为 5000 ms，缺失或陈旧均会拒绝。保留该价格链路可用性问题，未修改时效或缺价校验。
- 为完成可重复的下单撤单专项，通过真实 Manager 自动审批新增同代际测试租户 WOSI39，认证 TenantAdmin 创建 CUSTOM 价格源及 ORDER_ONLY BTC003USDT、TRADE BTC004USDT。认证 broker 每秒公开发布合法源时间、单调序号、60 秒 TTL 的 index 90000 与 mark 90001，共确认 472 次，零发布错误，结束后已删除 broker key。普通 Robot 继续使用各自 BTCUSDT 业务流。该轮是受控测试价格，不是币安实价压力结论。
- 正式专项报告为 `order-cancel-capacity-1ca2616a.json`，整体 PASS。六档每档 60 秒，均有原 HTTP ACK、挂单 New 查询、撤单、排空后私有挂单及 SQL 核对。共 1967 次完整循环，1150 笔纯撮合、817 笔资金撮合，全部唯一 Cancelled，零成交，无遗留挂单。资金测试各账户余额恢复 10000，冻结和已用保证金、冻结手续费回到零。

| 模式 | 客户端数 | 完整循环数 | 完整循环/秒 | 下单 ACK P99 ms | 撤单 ACK P99 ms |
| --- | --- | --- | --- | --- | --- |
| ORDER_ONLY | 1 | 308 | 5.129 | 218.603 | 276.641 |
| ORDER_ONLY | 4 | 422 | 7.006 | 794.287 | 426.401 |
| ORDER_ONLY | 8 | 420 | 6.905 | 1350.331 | 1126.083 |
| TRADE | 1 | 207 | 3.441 | 126.977 | 504.919 |
| TRADE | 4 | 314 | 5.169 | 495.342 | 646.076 |
| TRADE | 8 | 296 | 4.845 | 1015.649 | 1185.198 |

- 吞吐包含每循环两次私有订单状态查询，且同模式集中在单租户单分区。仅代表当前共享 Mac 的实测窗口，不能作为生产最大 TPS 或生产延迟承诺。
- 07:58 再次独立核对 SQL，1150/817 笔仍全部 Cancelled、零成交。全局 Trade 资金游标核对 `order-cancel-financial-cursor.json` 为 PASS，24 个余额、17 个持仓、3 个分区水位及 3801 个前驱链接均一致，零额外余额/持仓或缺失源头。
- 后续流程仍由 `/tmp/mac-t554-v44-cancel-fixed-resume.sh` 运行，最新总日志为 `/tmp/mac-t554-v44-controlled-cancel-capacity.log`。Order 热分区 P142 的原物理副本快照已实测从 712 推进至 1472。Trade 基线热分区 P188 当前副本已验证快照从 1 到 499，门槛要求至少 512 且推进至少 256，正等待自然 Robot 提交触发下一轮快照。另一个真实 Robot 的 Trade P108 已有 7、495、992 的物理副本快照。后续 10/50/200、突发叠加硬故障及四节点正常滚动尚未完成。

## 2026-11-11 08:34 十租户稳态数据与新租户自动引导修复

- Trade P188 原物理副本快照随后从 499 推进到 1038，通过原严格门槛。Order 和 Trade 快照校验均完成后进入十租户实测。
- 新租户首次报价出现 `ORDER_COMMON_SIGNED_NEWING_ALREADY_COMMITTED_TRADE_OUTCOME_PENDING`，没有到达 Trade 资金预占。Order 的原 DB 缺失规则回查只加载规则，未补齐结算模式。Admin 的默认产品由 Manager 直接配置，但没有在启用 Robot 前广播完整 querySymbol，正常定时广播每十分钟一次。08:10 定时广播后，F563OY、XV6I13 从 ERROR 恢复为 RUNNING，后续七个新租户逐步完成启动。此为配置传播问题，不计作集群容量不足。
- 五分钟十租户窗口为 UTC 00:15:52.332153 至 00:20:52.332153。实际 839 个报价请求、751 个 Tape 请求，723 笔唯一 Tape 成交，2.410 笔/秒。719 个配对样本的 Trade Newing 到 Order Filled 发布延迟 P50/P95/P99 为 908.392/1808.928/2340.514 ms。各租户最长成交间隔为 11.780 至 17.449 秒。十个 Robot 均 RUNNING，400 笔挂单，十个租户均有已认证资金 posting，零错误配对。该数据是指定 Robot 配置和共享 Mac 负载，不能当作最大引擎 TPS。
- 初次校验 `robot-steady-10-002052.json` 因一个投影摄取水位领先资金消费水位而标 NO_GO，余额与持仓在资金游标处本身均一致。原文件保留。后续严格复核摄取与消费水位完全相同，生成 `robot-steady-10-002052-reconciled-002456.json`，记录首次失败、原窗口及延后的复核。没有连续采样实际追平耗时，不能把两次检查的间隔认作追平用时。
- 为后续自动化增加最多 120 秒的只读水位重查，保留每次结果，只对单独的 `FINANCIAL_CURSOR_DIFFERS_FROM_SOURCE` 重查。源事件、前驱、余额、持仓等结构或内容差异仍立即失败。没有放宽原核对公式。重查与结构错误立即拒绝的测试通过。压力突发脚本复用此函数。
- Admin 实际运行的 `TrialLiquidityBootstrapWorker.class` SHA 为 `0d4e05222441a1a7b5ae5b0a3efbeeb7a92d7c4dd725ac095b67ad74c1d02412`，与 `.work/adminsvr-tenant-identity-origin-20261019/target/classes` 完全一致，修改使用该原源码，原有 33 行未提交诊断改动保留。
- Admin 修复复用已有 SymbolCache，在启用每个新租户 Robot 前先加载并广播规范规则和结算模式。每轮仍使用原事务租约与资金状态机，但最多推进 64 个可领取步骤，避免每个开户步骤额外等待五秒。没有改变模糊资金结果的处理或重试条件。新增配置广播失败时不能启用 Robot 的回归先红后绿，现有 Admin 回归合计 100 项通过。源码提交 `97eb28c7245d485e47460b9b542000686a7d8c22` 只包含本次三个源码修改块和测试，原有诊断差异保持未提交。
- 本机 Admin 在十租户采样、复核完成且全部开户任务 COMPLETE 的边界更新，四个 Order/Trade voter 与 Robot 容器未重启。候选只覆盖两个 Worker class，原环境、挂载、命令、资源与日志配置逐项核对。保留原 Admin 容器 `mac-demo-20261111-072730-admin-before-catalog-082838` 及全部数据。新镜像为 `sha256:8d7c6c9302f1d9d591d96c7c22f82e6cc97cce9e6cd83d96ea43ef72d3de55c9`，源码完整 SHA 为 `153dcdcb619d8d89591df6f1cf86405b92ea256a29a524c91575bb3607ffc4f4`。08:31:10 正常公共 API 回读通过，证明见 `admin-bootstrap-overlay-deployment.json`。保留原 0.15 CPU、640 MiB 内存限制，维护期间约 145 秒完成新进程启动与路由恢复，不计作 A/B 故障验收。
- 新序列为 `/tmp/mac-t554-v44-50-ha-200-sequence.sh`，日志 `/tmp/mac-t554-v44-50-ha-200-sequence.log`。正常自动审批上限为 200 个活跃租户，因此先完成 50 租户实测、需要新开户的正常滚动与硬故障业务用例，再扩到 200 租户测量，最后做两次七分钟真实 SIGKILL 突发负载。该顺序调整保留原审批政策和数据。
- 08:33:47，50 个租户已通过正常接口获批，14 个 Robot 已 RUNNING、7 个等待行情、其余仍由原持久化任务队列引导。50 租户稳态、200 租户及最新版本的完整 HA 尚未验收。旧 v43 P093 的永久 poison 自动恢复缺陷仍单独保留为未完成。

## 2026-11-11 08:56｜50 租户容量未通过，定位撤单超时与 Tape 精度增长

- 原环境 `mac-demo-20261111-072730` 持续运行。初轮 50 租户五分钟窗口为 UTC 00:46:51.844444 至 00:51:51.844444。1812 个报价请求、1279 个 Tape 请求、452 笔唯一 Tape 成交，1.507 笔/秒。448 个配对样本的 Trade 入口到 Order Filled 发布延迟 P50/P95/P99 为 2775.120/13649.623/35596.098 ms。该值不是客户端下单 ACK 延迟。
- `robot-steady-50-005151.json` 结果保留 NO_GO。窗口覆盖全部 50 个租户，最终 42 个 RUNNING、8 个 DEGRADED。50 个租户均有资金 posting，428 个 posting 事件、零错误配对。严格资金游标检查通过，118 个余额、111 个持仓及 36451 个前驱链接均无差异。容量与延迟未通过不能用资金正确性替代。
- 约 32.58 秒的 cgroup 实测中，APS 271/323 个调度周期、MD 135/327 个周期、Gateway 123/323 个周期受 CPU 限额约束，证明见 `cpu-throttling-50-0846.json`。08:46:50 在线将 APS、MD、Gateway 从 0.35 CPU 各提高到 1.0，Admin 从 0.15 提高到 0.5。容器 ID、启动时间及内存配额逐项保持一致，证明见 `online-cpu-quota-adjustment-0847.json`。该窗口使用调整后的资源条件，不能直接当作与十租户相同条件的容量对比。配额提高后仍有撤单超时，因此没有将问题归结为单一资源原因。
- 08:52 的真实双 Order JVM 线程快照保存在 `/tmp/mac-t554-v44-order-a-50-threads.txt` 和 `/tmp/mac-t554-v44-order-b-50-threads.txt`。撤单线程等待现有 Common 物理 WAL/签名 custody 和 Trade 释放回调，另有同分区变更等待正确性修复后的排他锁。Gateway 观察到一笔撤单批次后端回复耗时 37341 ms，调用方已失去该次响应。Robot 原批次上限为 50，现缩为 10，原分块循环继续处理全部输入。原模糊写入禁止自动重放的规则保持有效，实际效果须由新测量确认。
- Robot Tape 的 `capBacklog` 原来反复乘 18 位比例，每次继续累积 18 位小数，真实日志已产生数万位数。新增 2000 次交替方向积压上限回归先红后绿，积压预算保留 18 位小数向下舍入，舍弃部分仍计入 droppedNotional。逐次验证积压不超过原上限、输入量等于保留量加舍弃量。该值用于 Robot Tape 流量预算，资金余额与 Common 提交机制均由原路径处理。
- Robot 现有回归与新增回归共 128 项通过，日志 `/tmp/mac-t554-robot-precision-all-tests.log`。修改前运行中的 `TradeReplayEngine.class` 与原目标 class SHA 完全相同。修改前 `TradingGatewayClient` 从现有源码重新编译的全部反汇编字节码与实际运行 class 完全一致，避免部署错误源码覆盖历史修复。
- 候选镜像 `local/otc-t554-robot-bounded:13caf50d3a01`，镜像 ID `sha256:3e265cdace4f0cb52ac27c6165fd8fda74719e1054b587e901358dfaf20298a1`，仅覆盖实际测试的两个 class。同环境计划更新 Robot，保留原容器、原挂载与原数据，并单独记录维护时间。该维护不计作 Robot 持续流量下的 A/B 故障验收。正常滚动、SIGKILL 与 200 租户序列在首轮 NO_GO 后已停止，修复后的稳态结果仍待验证。

## 2026-11-11 09:10｜用户补充的高性能整链路压测要求

- 严格同步 ACK 和异步复制必须分别测量。核实每种模式实际成功返回对应的本地持久化、远端持久化及复制水位，记录配置、镜像、Common SHA 和资源条件。当前几百毫秒的观测值是需要继续优化的基线，整体性能验收尚未完成。
- 下单、撤单和真实成交分别统计吞吐量、P50/P95/P99/P99.9、最大延迟、错误率及超时率。分别记录初始意图 ACK、真实挂单可见、成交确认、行情成交发布和资金投影完成的时间点。Robot 固定策略的稳态流量与引擎饱和容量分别报告。
- 在现有同一 Mac 环境按模式顺序逐级增压，测可持续吞吐、排队增长和饱和点。拆分 Gateway 队列、业务校验/撮合、Order 与 Trade 提交、复制及 ACK、RSA 签验、磁盘持久化、行情与投影延迟。负载器自身调度延迟与丢弃也须计数。
- 两种模式都覆盖持续下单/撤单/成交中的正常 A/B 替换、真实进程故障、自动接管、恢复追平和 Home 归还。异步模式另需记录复制积压、已返回成功请求的恢复结果及实际数据损失边界。所有模式均核对订单、成交、资金和持仓一致性，保留原物理 ACK 与 fencing。
- Robot 本轮源码已提交 `acb947644f6aa54e6d24848b0eb09f3368bd55cc`，仅本次四个文件的相关修改块，原三个未提交文件差异保留。原 Robot 退出等待 45 秒后由 Docker 强制结束，退出码 137。新 Robot 于 08:56:38 启动，09:03:46 两个实际 class SHA 及 50 个新心跳核对通过。原挂单清理由正常接口逐租户完成，四个核心 voter 均持续运行。该证明仅是 Robot 更新完成，50 租户性能复测仍在等待完整双边报价状态。

## 2026-11-11 09:20｜Common 控制请求分流候选与异步成功边界

- 用户已确认异步成功返回要求为本机日志已落盘，备节点随后异步复制。压测需要量化复制积压、故障后的实际 RPO、已确认请求丢失或重复情况，以及资金、持仓和订单一致性。
- 代码核查显示，正式写入注册表已经调用故障降级后的 `CommonCertifiedDegradedPrimary.commitThenApplyLocal`，并通过现有后台追平恢复双副本。该类的 `mirrorLocalFsyncedRecordToReplica` 逐笔异步镜像接口在当前 `src` 中只有定义，没有调用。双节点长期保持异步复制的能力尚未完成正式接线与验收，不能将其与已有单节点 LOCAL 降级恢复混为一项已完成能力。
- Common 传输层所有 control 操作原共用 `recovery-control` 一条对端连接。Netty 的按连接有序持久化执行器会把 WAL custody 安装、双物理 receipt 安装及恢复读取串行排队。新增真实 TCP 回归在阻塞 P037 custody 时，要求 P038 custody 和恢复读取能够前进，同时 P037 后续 receipt 必须继续等待前序。
- 原代码该回归因 P038 请求超时而失败，证据 `/tmp/mac-t554-common-control-red.log`。修改仅将三个已有持久化 control 操作按现有四条分区 lane 分流，恢复读取保留原独立连接。复用原请求格式、物理签名、持久化处理器、队列上限及线程池，同分区控制顺序保持一致。12 项实际 TCP、旧 Epoch 前置校验、RSA 快照传输、篡改拒绝和落盘重新打开回归通过，证据 `/tmp/mac-t554-common-control-green-rerun.log`。
- 候选源码提交 `ab9459306aa4b33f50bb6d1ee9e535536d1ae025`。09:20:13 启动独立 Common 完整故障门禁，目录 `t554-common-verifications/20261111-092013`。当前 Mac Demo 四个 voter 仍运行 v44，候选尚未集成。P093 永久 poison 分区的自动恢复缺口仍保持未完成。

## 2026-11-11 10:35 Common 完整门禁失败与运行中 poison 证据

- 09:20 候选 ab9459306aa4b33f50bb6d1ee9e535536d1ae025 的完整 Common 门禁耗时 1064.803 秒，结果 NO_GO。大 RSA 快照及 4100 条严格历史校验通过，中断 A 返回后卡在 P000/E4。A 缺少安全的 E4 物理目录，B 持续报告无权威 rearm。ZooKeeper 会话隔离与恢复授权接线仍在核查，原因尚未最终确定。候选未集成，原四 voter 继续使用 v44。失败目录为 t554-common-verifications/20261111-092013。
- Robot 两 class 更新后的 50 租户重试未能全部进入 RUNNING。robot-steady-50-011907.json 保持 NO_GO，所列五分钟为等待引导期间的回顾窗口，资源采样数为零，不能作为有效稳态性能对比。后续曾有 48 个 RUNNING、2 个 ERROR，两个错误来自 Trade P144、P180 的已 poison 主节点。当前运行环境集群验收未完成。
- 已保留原 Trade P144/P180 E2 的 A/B 四份独立磁盘副本，原文件复制前后 SHA 全部一致。证据位于 performance-50/poison-P144-P180。仅使用原 ACK 公钥验证。P144 两侧原 WAL 头均为 704，完整双物理确认水位均为 703，确认前缀 SHA 均为 2dedcdfec5c9aa1bf31d02b621acbb9d138be79ed3129cee7c89f56ad20518a4。P180 两侧原头均为 2189，确认水位均为 2188，确认前缀 SHA 均为 341ab3b1ee297f152a47516a65ddef79597e584c263629aac467baae417f43c4。末条未确认记录继续保留，未按已提交重放。原节点未重置 grant、清 poison 或重启。
- Common 正在复用已有签名 poison notice、严格角色交换 Stage、旧 WAL 物理退休、原 RSA 与安装 receipt 修复同会话活主 poison。独立真实 A/B JVM、真实 ZooKeeper、256 分区测试已通过一次和连续两次 poison 后的 E2→E3→E4、E4→E5→E6 自动接管及 Home 归还。测试验证业务快照原序列化 Epoch、已确认字节、未确认尾保留、其他分区继续写。日志为 /tmp/mac-t554-common-live-poison-reader-release.log 与 /tmp/mac-t554-common-live-poison-repeat-watch-fix.log。过程中修复原只读证据锁未释放及角色变换后旧 Replica watch 未关闭问题。新增候选接管中途重启测试仍在验证，尚未提交或部署这批修复，前两项通过不能替代完整 P0。
- JFR 使用真实 Order A、Trade A 进程。零阈值 FileForce 记录中，Order 4038 个 force 事件的 P50/P95/P99 为 23.161/97.142/102.538 ms，Trade 858 个为 132.293/158.517/158.517 ms。这是共享 Mac、同期 Common 门禁下的内部 IO 样本，不能等同客户端延迟。采样也发现 Order 幂等清理、全订单扫描和 Trade execution 去重全租户扫描的 CPU 成本。原始证据位于 performance-50。
- Trade ExecutionDeduplicator 改为从原 canonical map 派生的按 location 索引，快照只遍历目标租户。维护 applied、terminal、过期、恢复、clear 和并发所有权，不增加持久状态或第二账本。扫描结构与并发 clear 回归先红后绿，全部 54 个测试类、221 项通过，使用当前运行 v44 Common 和 Shared JAR。提交 1f9fa1d25b54d332f04f5d45b16a20b8f4433890，尚未部署，未声称已改善生产测量。
- 另有 143 份已停止容器日志归档并完整解压 SHA 校验后清空原日志，共回收 2391115826 字节。归档位于 /Users/kong/.opentradingcore/t554-retired-log-archive-20261111-medium。现有容器、业务 WAL、快照、卷及活动日志均保留。未执行 Colima 重启或磁盘扩容。
- 一次配置检索误将已有 Demo 恢复接口私钥输出到工具记录，已通知用户并限制后续输出为字段名、路径和指纹。public-key-scope.json 通过公钥派生比较确认该密钥与原物理 ACK RSA 密钥不同。未输出原 ACK 私钥，未轮换现有密钥。本次泄露尚需在后续同 Mac 新代际部署时更换恢复接口密钥，不能将现有运行密钥视为未泄露。
- 异步合同按用户明确选择执行，本机落盘后返回，备节点异步复制。长期双节点异步模式正式接线、复制积压、故障 RPO 和两模式整套饱和压测仍待完成。当前状态继续 NO_GO。

## 2026-11-11 11:05 统一候选验证与低磁盘维护

- Common 修复提交 462b6c5e00ea27a002feb24b74745353f6952956，候选目录 t554-common-candidates/20261111-105444，JAR SHA256 为 9fece20e63351ed926fe2b76507eb545854b45b78c79cf8e790f4a981a13fb29。工作目录改动已按明确的 15 个文件提交，没有覆盖用户其他仓库未提交修改。
- 五项独立真实进程回归通过，包括一次 poison、Home 后重复 poison、接管方在 E3 中途重启、接管方在 E5 中途重启、旧主在恢复中途重启。每项保留 A/B 日志、公钥、签名 Stage、WAL、快照和最终 manifest，位于 t554-common-verifications/20261111-105444/process-evidence-live-poison，合计约 19 MiB，不含测试私钥或 HMAC key。统一 JAR 的 101 项安全及 TCP 回归也通过，原 RSA 测试身份路径明确提供。早先一轮六项原 Home 测试因漏传身份路径失败，补齐后全部六项通过，没有修改校验逻辑。完整 P0 双向 SIGKILL、单节点继续写、恢复追平、Home、再次故障及中断返回演练仍运行，整体状态 NO_GO。
- 一键 Common 校验已串联新增五场景，并要求封存相应物理证据。原完整门禁仍保留，不能由新增测试替代。完整候选尚未安装至 Order/Trade。
- Docker 镜像列举等待 180 秒后超时，未执行镜像删除。全盘 Docker 占用递归扫描迟迟未完成，已结束该只读扫描，避免继续增加 IO。当前数据盘为 /dev/vdb1，147 GiB，与 VM 的 19 GiB 系统盘分开。不能用系统盘剩余空间代替 Docker 数据盘容量。
- 11:00 数据盘仅约 326 MiB，因此按已获批准的短时维护暂停原 dc-saas-robotsvr。容器 ID d98219f8dfa108cc52cc1dc15cb22483d62621d3f9a5a19413acd00602e42d2f 和启动时间不变，内存与数据保留。storage-maintenance-robot-paused.json 记录状态。此暂停不计连续 Robot 故障演练，必须在维护后恢复并重新验收。
- 214 份已停止容器日志完成 gzip 全量读回和原 SHA 校验，实际回收 272253865 字节。每次从原日志 inode 文件描述符复核停止状态、长度、mtime、SHA 后才清空该旧日志，不涉及活动容器日志或业务文件。归档目录 t554-retired-log-archive-20261111-small，明细 /tmp/mac-t554-small-log-archive.log。11:04 数据盘约 546 MiB，可用空间仍不足以恢复压测，维护尚未结束。当前四 voter 未重启，容器、数据卷及原业务 WAL/快照保持保留。

## 2026-11-11 11:16 数据盘预留调整完成与业务拒绝复核

- 专用数据盘 /dev/vdb1 的 ext4 UUID 为 9a9fa453-e7d9-4069-9a54-a061f8a956de，块数 39321088，块大小 4096。原管理预留块数 1966054，约 5%。核对精确 UUID、挂载目标、块数及原比例后，将预留调整到 1%，393210 块。额外可分配容量 6442369024 字节，df 可用 6918230016 字节，约 6.44 GiB。没有扩大虚拟盘或重启 VM，也没有删除现有容器、业务文件、卷或镜像。该调整可按原预留块数恢复，证据 storage-data-reserve-adjustment.json。
- tune2fs 记录文件系统状态 clean with errors，错误计数 4，首次为 2026-10-09，最后一次 2026-10-17，函数 ext4_journal_check_start。当前内核未检出新的相应错误。未将历史错误认定为本轮延迟或 poison 的原因，也未将预留调整视为文件系统修复。后续已授权维护仍需离线检查，当前没有运行 fsck 或修复磁盘。
- Robot 在 11:00:23 至 11:09:48 暂停约 9 分 26 秒，随后解除暂停。原容器 ID、启动时间、环境、内存状态及数据保留，无进程重启。恢复后有新心跳，但并非全部 RUNNING。11:13 复核为 24 RUNNING、3 DEGRADED、23 ERROR，其中 22 个错误包含 ORDER_COMMON_CERTIFIED_PARTITION_BUSINESS_DENIED，一个包含撤单释放 Trade 主节点认证拒绝。不能把该状态写成服务恢复 PASS，拒绝根因继续核查。
- 11:14 四个原 voter 的 ZooKeeper 租约都有最近更新时间与递增版本。此证据仅说明会话及租约 CAS 活动，不证明业务写入认证成功。当前仍使用 v44，候选 v46 仅在完整 Common 门禁中运行，尚未集成。

## 2026-11-11 11:27 多分区 poison 与整节点租约失效是两个验收场景

- 统一候选完整演练已完成双向 SIGKILL、旧主追平及 Home 归还，256 组 WAL 与 256 组业务快照匹配。演练输出 aFailoverMs=224988、aHomeMs=472618、bFailoverMs=243134、bHomeMs=483518。这些是整个 256 分区阶段完成的时间，不能当作单笔交易延迟或最早恢复写入时间。耗时仍需后续优化。第三次真实故障与再次回归正在继续，整套门禁尚未封存为 PASS。
- 新增两个分区同时 poison 的真实进程测试，仍使用相同候选 JAR 9fece20e63351ed926fe2b76507eb545854b45b78c79cf8e790f4a981a13fb29。测试停止真实 B 进程，A 对 P000/P001 各发生一次真实提交超时，然后恢复 B。使用 10 秒节点授予、20 秒 ZooKeeper 会话时，两次连续 2.5 秒提交超时仍处于节点授予期内。两个分区均自动升 Epoch、恢复确认前缀、归还 Home，并保留两条未确认尾，其他分区可继续 ACK。26.430 秒通过，日志 /tmp/mac-t554-common-simultaneous-live-lease.log，完整物理证据 /tmp/mac-t554-common-simultaneous-live-lease/physical-live-poison/multiple。此参数仅用于隔离分区 poison 场景，没有修改 Demo 的生产参数。
- 同一测试另以 3 秒节点授予、20 秒 ZooKeeper 会话运行，保留了独立 NO_GO。两次超时使 B 整个节点授予过期，ZooKeeper 会话仍可存活。B 日志明确 node quorum lease expired，成功续约计数停在 63，失败续约随后增长至 44。A 在健康 P002 的提交被 B 返回 noWalWrite 拒绝，P000 恢复等待旧主退休，构成额外整节点失效场景。证据 /tmp/mac-t554-common-node-lease-expiry/tests.log 与 physical-live-poison/multiple。不能用 10 秒配置的分区恢复通过覆盖这个失败，也没有放宽旧 Epoch fencing。
- 已向用户提出架构边界确认，是否接受整节点不可逆隔离后由 Common 关闭节点、复用现有 Docker 进程重启和回归流程。另一选择是保留进程并在现有机制内完成全分区升 Epoch。该问题涉及此前不随意重启及 AGENTS.md 不新增恢复框架的约束。用户选择尚待回复，尚未加入自动退出代码。其余授权验证仍继续。
- 运行中 v44 的错误分类进一步确认，Order A/B 与 Trade B 的近期日志均含 Common poisoned primary Epoch cannot renew，Trade A 未匹配到同类错误。四节点租约活跃不能替代物理写入认证。当前业务仍 NO_GO，候选尚未集成。

## 2026-11-11 12:46 整节点退出授权、并发回归修复与实际 OOM

- 用户已明确接受整节点永久隔离后的自动退出、容器重启及完整认证回归。候选为独立 voter 进程增加退出码 78 生命周期，普通短时续约失败与单分区 poison 不触发退出。旧 Epoch 授权继续永久失效。Order/Trade 正式接入及 Docker 重启策略尚未部署。
- 原候选 462b6c5e00ea27a002feb24b74745353f6952956、JAR 9fece20e63351ed926fe2b76507eb545854b45b78c79cf8e790f4a981a13fb29 的完整 P0 已通过，完整主测试耗时 2307.858 秒。五项 poison 真实进程测试及 101 项安全/传输测试通过，证据封存于 t554-common-verifications/20261111-105444。此 PASS 未包含新增整节点自动退出场景，新候选尚待重新通过完整门禁。
- 新增整节点测试证明原 B 自行退出 78，监督进程延迟 45 秒后才重启，A 在此期间对实际 LOCAL 分区 P133 完成本机持久化写入。B 回归后该分区 Home 保留业务字节并接受后续严格写入。但一个 P225 卡住，整套测试 NO_GO，证据 /tmp/mac-t554-common-node-single-actual-partition。
- P225 原因为两个节点并发归还不同 Home 分区时共享 manifest CAS 竞争。一方提前持久化的未激活签名 Stage 在 CAS 失败后与新全局版本冲突。修复保留原签名字节，仅在自身前后物理角色及 Epoch 未变化、自有会话租约 quorum CAS 和精确前驱核对成立时，在原目录归档未激活提案并重新准备。已激活、READY、外部会话、quorum 失败、签名损坏均拒绝。31 项相关回归通过。修复后的整节点真实流程耗时 123.489 秒通过，已验证 256 分区严格 Home、单节点已确认数据保留、旧 Epoch 隔离和未确认尾保留。全部七场景复测进行中，未安装至业务环境。
- 12:32:51 本机原 Order A 因容器 OOM 退出，exit 137、OOMKilled=true，原重启策略为 no。证据 order-a-oom-20261111-123251.json。未手工重启或清理业务状态，其余三个原 voter 与 Robot 继续运行。12:38 数据盘可用约 2.3 GiB，业务仍 NO_GO，继续容量维护及内存根因检查。
- 下一代一键准备脚本已增加旧恢复接口 RSA 密钥轮换，真实 RSA 单元测试通过，原物理 ACK 密钥保持原身份。尚未在运行环境生效，先前输出到工具记录的旧恢复接口私钥仍视为暴露。

## 2026-11-11 13:06 新候选完整门禁与旧环境资源清理

- 整节点恢复及并发 Stage CAS 修复已提交 dbff8ac，候选 JAR SHA256 为 bd346b0f808e6671048b32ab8616ad497518f5bd6155c1b51308febbe0834a1f。完整门禁目录 t554-common-verifications/20261111-125445。同一 JAR 的七类真实进程故障测试耗时 280.445 秒通过，另有 92 项安全及传输回归通过。原完整双向 SIGKILL、单节点继续写、Home、重复故障和中断返回演练仍在运行，整体未放行。
- 内核证据将 Order A 退出原因进一步定位为虚拟机 global_oom，并非已证明超过单容器 2 GiB 限额。该 Java 被杀时匿名常驻约 840356 KiB，JVM 配置为 Xms128m/Xmx1g。此前 MySQL、旧 ClickHouse 也多次遭 global OOM。虚拟机一度仅约 432 MiB 可用，3 GiB swap 用满。前文关于容器 OOM 的表述以此次内核证据为准。
- 已停止 21 个旧验收后端，包含 t522/t523/t529 至 t539 的旧业务服务、旧 MySQL/ClickHouse、t319 MySQL 及 t84 ZooKeeper。当前 mac-demo-20261111-072730 与全部 Web 容器排除在本次停用范围外。21 个容器、镜像、挂载和全部业务数据均保留，身份及停用前后状态记录 retired-backend-resource-maintenance-20261111.json。可用内存回升至约 7088 MiB，swap 已用降至约 177 MiB。没有将本次维护停用作为 HA 验收。
- 562 个创建于 2026-11-10 之前、无任何容器引用且无运行中 bind mount 指向的匿名卷完成清理。内容限定为空目录或旧 ZooKeeper 的 myid/version-2 测试文件，实际已分配文件仅 69009408 字节。它们大量使用稀疏预分配，不能按逻辑文件大小声称释放数十 GiB。清理记录 storage-orphan-volume-cleanup-20261111.json。
- 九个不被任何容器引用的 Maven、npm、Node modules 及 E2E 工具缓存卷已移除，均可由依赖重新生成。旧后端 32 份日志完成完整 gzip 读回及原 SHA 复核后清空原日志，共回收 1509491314 字节，归档 t554-retired-log-archive-20261111-backends。没有清空运行中日志或当前失败业务 WAL/快照。
- 数据卷扫描约 65 GiB。大项包括旧 t530 ready 约 11 GiB、当前 ready 约 11 GiB、旧 t529 MySQL 约 7.3 GiB、旧 t398 MySQL 约 6 GiB、20261109-174426 ready 约 6 GiB。当前业务与原失败证据卷均保留，继续核查细分增长来源。对无任何容器引用且创建超过七天的旧镜像执行 Docker 原生清理中，13:05 数据盘可用约 9 GiB，最终回收量尚未结算。
- 下一代 hostready voter 使用 on-failure 容器策略，其他安装阶段保持原生命周期。独立无网络 Docker 生命周期探针已证明退出 78 自动重启，以及显式 SIGKILL 故障注入仍保持停止，证据 docker-fatal-restart-policy-proof.json。该探针没有 Common 角色、READY 或业务状态，不代替真实集群验收。当前原四 voter 策略尚未改变。
- 一键准备脚本同时保留已调整的 Gateway/MD/APS/Admin CPU 配额及当前 Robot/Liq 镜像，避免重新部署回退到静态旧默认值。恢复接口密钥轮换单测仍通过。源扫描门禁已识别现行 Common FirstReady binding，仍拒绝尚未改为专用进程生命周期的 Order/Trade 接线。相关源扫描 14 项回归通过，必须待完整 P0 GO 后集成。

## 2026-11-11 13:19 完整门禁 NO_GO、证据补全与同 JAR 复验

- dbff8ac 候选的完整主测试于 1022.585 秒失败。严格长历史恢复已通过，但中断返回后等待 A Home 超时，停在 P024/E5。日志包含缺失 Genesis、目标镜像签名及 recovery receipt 等拒绝。B 原进程最终记录真实 ZooKeeper NoNode /first-ready-test/leases/DemoSvrB 并按新生命周期退出 78。缺失证据与 B 退出的完整先后因果尚未证明，不将其表述为已验证签名损坏或已解决的问题。新候选未集成。
- 原完整测试导出过程只保存日志及阶段标记，失败后的物理目录被 JUnit 临时目录清理。七类新增进程测试已有完整物理导出，原完整测试的这项取证不足此次补齐。仅修改 fixture，新增清理前各 voter 存活/退出码、最终 manifest、公钥、签名 Stage、WAL、快照及批准记录导出，排除测试私钥与 HMAC key。生产源码及候选 JAR 保持不变。一次 fixture 编译类型错误已修正并通过单文件编译，未运行或发布该失败构建。
- 13:18 同一个 bd346b0f808e6671048b32ab8616ad497518f5bd6155c1b51308febbe0834a1f JAR 重新运行完整门禁，目录 t554-common-verifications/20261111-131835，fixture 提交 85f3ced6fbe83e6bdf951cc4cbfa36ffb651bf65。未调整原会话、租约、超时、物理 ACK、Epoch 或数据校验标准。此次在旧后端停用和磁盘清理结束后复验，不能把先前 NO_GO 删除或改记为 PASS。
- Docker 原生清理完成，移除没有任何容器引用且创建超过七天的旧镜像，报告回收 4.063 GB。九个缓存卷清理及第二轮旧日志归档也完成，13:10 数据盘可用约 13 GiB，虚拟机可用内存约 7076 MiB。容器数据卷扫描与清理同时进行，du 对已删除的旧缓存目录报不存在，因此该扫描只用于占用量估计，不是文件系统错误证据。尚未执行离线 fsck。
- 当前 ready 卷约 11 GiB，其中 Order 约 4.1 GiB、Trade 约 6.9 GiB，Trade B 快照约 2 GiB。原业务 WAL、快照和失败证据继续保留。仍需验证后续长期保留与归档策略，不能把磁盘可用恢复等同于交易恢复。

## 2026-11-11 13:57 会话与真实写入租约分别定位，候选仍 NO_GO

- 同 JAR 的 131835 复验七类进程测试通过，但完整主测试在 89.666 秒失败，尚未注入 A 故障。B 退出 78，最终 manifest 全部为 E2 STRICT READY。完整物理目录已导出，约 16 MiB。P129 双边 WAL 均为 76601 字节，不把未完成压力历史记为已确认 4100 条。
- 加入纯诊断会话日志后，以同一 v47 JAR 跑原第一轮返回流程。B 记录 Disconnected 与 SyncConnected 相距约 1829 毫秒，随后因硬隔离退出 78。该单轮诊断整体失败，完整现场保存在 /tmp/mac-t554-full-control-trace/physical，约 36 MiB。原完整 fixture 只有最初 A/B 被单独设为 2000 毫秒会话，返回节点使用 Common 客户端默认配置。客户端默认请求 120000 毫秒，嵌入测试服务器将其限制为 10000 毫秒。
- 为对齐原始与返回节点的实际启动配置，取消上述两个测试专用 2 秒覆盖，所有 voter 统一 Common 默认客户端配置。3 秒 Common 写入授予、硬会话隔离、Epoch、物理 ACK 与数据校验保持原合同。此项是测试配置调整，旧 2 秒失败仍保留。不能声称此前完全未改动测试会话参数。
- Common 提交 4c6027b918258eb208629487516872b7da129713，生产改动仅增加自动退出前的固定安全诊断字段，报告 hardRevoked、manifestRevoked、租约年龄/TTL、续约计数及异常类型，不输出私钥或原始配置。43 项控制/授予回归通过。候选 JAR 为 48463564a5f38b7cdf6c038458a3711eda65f70804eaee910c387a5ee26f042d，目录 t554-common-candidates/20261111-134030。
- 新候选七类真实进程测试 280.519 秒通过，完整主测试仍在 380.230 秒失败。B 明确 hardRevoked=false、manifestRevoked=false、leaseAgeMillis=3101、leaseTtlMillis=3000、successfulRenewals=3950、failedRenewals=11，并退出 78。这次是实际节点写入授予过期，不能归因于测试 2 秒会话。返回 A 也因授予过期在启动 census 校验时退出 1。未集成或部署这个候选。
- 当前对同一 v48 JAR 增加测试侧只读观察器，读取续约计数和线程栈，等待超过一秒没有成功续约时保存控制线程位置。诊断 fixture 位于 /tmp/mac-t554-control-stall-trace/source，不修改生产授予、不注入 READY/ACK、不重置 Epoch。目标是定位续约停顿的具体阻塞点。
- 完整门禁封存脚本新增主流程物理证据 SHA 与清理前进程退出状态校验，保留旧 fixture 支持。三项物理导出哈希、私钥拒绝及目录符号链接拒绝回归通过。Trade B 快照只读统计为 3680 份、逻辑数据 2201588218 字节，另有同数 metadata 文件；当前业务快照保留策略尚未修改。


## 2026-11-11 15:23 完整门禁进展、配置对齐与旧卷归档

- 原 Mac Demo 与一键模板的实际 Common 节点写入租约均为 15000 毫秒，每 1000 毫秒续约。完整 256 分区测试对齐这两个生产参数，测试 ZooKeeper 服务端最大会话设为 40000 毫秒，所有 voter 使用同一默认客户端会话请求。session-policy.txt 固化参数。独立七类进程测试仍保留 3 秒整节点租约过期场景和 10 秒单分区隔离场景，物理 ACK、旧 Epoch 永久隔离与签名校验保持强制。
- 只读停顿诊断发现控制线程处于定时器等待位置，尚未证明宿主系统根因。90 秒定时探针中，本机 Java 8 P99 为 108.166 毫秒、最大 145.887 毫秒，实际 Linux Java 8 P99 为 119.728 毫秒、最大 278.105 毫秒，两者没有超过 300、1000 或 3000 毫秒的样本。此探针不能排除此前短暂环境停顿。
- 141300 的整节点测试失败来自测试 replay assignment supplier 把短时授予刷新 IOException 包装成 IllegalStateException，致使仍健康的对端进程退出。测试改用已有 assignments(manager) 空 census 重试路径，仍由 Common 拒绝不可证明的写入。目标场景 118.695 秒通过。13379ea 仅修改两个测试文件。
- 142635 七场景 276.626 秒通过，完整测试在首次 LOCAL 写入和签名 E4 中断恢复成功后，于等待旧进程 ZooKeeper 租约消失的 40000 毫秒边界失败。等待期限与服务器最大会话完全相同，未覆盖会话清理 tick。测试提交 beed60fe7b4fcededa515ecc522f7ded29f44485 将等待上限对齐实际服务端最大会话加 5000 毫秒，仍等待真实租约消失，没有删除租约或伪造授予。此前失败现场保留。
- 当前 144410 统一候选运行使用生产提交 4c6027b918258eb208629487516872b7da129713 的原 JAR 48463564a5f38b7cdf6c038458a3711eda65f70804eaee910c387a5ee26f042d。七类真实进程测试 255.171 秒通过，92 项安全、控制和传输测试通过。完整流程已完成双向 SIGKILL、追平、Home 归还，256 组 WAL 和快照一致。整阶段 aFailoverMs=232174、aHomeMs=467335、bFailoverMs=241332、bHomeMs=420645。第三次真实 SIGKILL 后已再次 LOCAL 继续写入，最终回归与封存仍运行，尚未宣告完整 GO。
- 受当前失败代际快照持续增长和可用空间下降影响，按已授权维护停止 Robot 与剩余三个核心 voter，均正常退出 143。先前 Order A 的 137 为已记录的虚拟机全局 OOM。现有代际冻结记录 failed-generation-update-maintenance-20261111.json，容器、业务卷与故障证据均保留。此次维护不能计为 Robot 连续故障测试通过。
- 旧 otc-t530-ready-data 卷有 20 个已停止容器引用，没有活动容器挂载。完整归档逐一校验 1093947 个文件及 1098603 个条目，并完整解压 gzip、比较原文件 SHA 和元数据。原独立占用 11094257664 字节，归档大小 1754585642 字节，SHA256 为 834b15f8effd785459c96791b01176a2ac368c1837707857b4fb209f76fe83d8。归档目录 /Users/kong/.opentradingcore/t554-retired-volume-archive-20261111-1438，verification.json 为 VERIFIED_FULL_ARCHIVE。原件清理前重新检查停止状态、树结构、文件 inode、长度与修改时间，正在执行清理，当前业务卷不在清理范围。
- 归档子进程已完成，但其 sudo 父进程仍处于此前维护暂停状态，导致外层锁尚未释放。核对精确进程参数后恢复该父进程，外层正常退出，随后取得同一部署锁继续清理。未强制绕过部署锁。
- 最新业务仍 NO_GO。Common 尚未安装至 Order/Trade，正常双节点异步复制尚未接线，泄露的旧恢复接口密钥将在新代际替换，物理 ACK 身份未泄露且不随意替换。


## 2026-11-11 15:26 P0 GO 与同版业务构建启动

- 144410 完整统一候选门禁封存 PASS。主流程 2110.822 秒，七类真实进程故障测试 255.171 秒，92 项安全/控制/传输回归通过，大 RSA 快照冷打开通过。双向 SIGKILL、LOCAL 继续写、原节点追平、Home 自动回归、中断签名恢复、第三次故障及再次回归全部通过。封存 verification.seal.json 同时包含七场景和完整流程物理文件哈希，未包含私钥。生产 JAR 保持 48463564a5f38b7cdf6c038458a3711eda65f70804eaee910c387a5ee26f042d，生产提交 4c6027b918258eb208629487516872b7da129713，测试 fixture 提交 beed60fe7b4fcededa515ecc522f7ded29f44485。P0 GO 仅适用于该版本和已声明配置，业务 P1/P2 仍待实测。
- Order dfab91f 与 Trade 01ea3c3 各仅提交一行现有绑定工厂调用，采用 CommonCertifiedFirstReadyE2NodeBinding.forDedicatedVoterProcess()。通过索引精确写入该单行提交，工作区原有 17/15 个文件改动保留，没有捎带提交。源码边界门禁通过，仍明确要求业务真实物理恢复。最新 Common、Shared、Order 与 Trade 的同版镜像构建开始，构建目录 /Users/kong/.opentradingcore/mac-demo-build-20261111-1526。Shared/业务原有未提交源码一并按工作区快照构建并记录哈希，不将镜像描述为纯提交构建。
- 旧 otc-t530-ready-data 原文件在完整备份且再次校验 1098603 个条目后清空，原卷和 20 个已停止容器保留。清理报告 CLEARED_WITH_VERIFIED_FULL_ARCHIVE，可用字节从 7171190784 增至 18348756992。完整私有归档继续保留，旧容器原 always 重启策略被设置为 no 并另存原值，避免之后误启动已归档空卷。当前失败代际的数据没有清理。
- 仅对既有 Docker 数据文件系统执行在线 fstrim，报告 trim 19900198912 字节。此操作回收已经释放的虚拟磁盘块，不是扩容、离线检查或 ext4 历史错误修复。未重启 Colima。新代际仍需核验实际磁盘和内存余量。
- 部署相关 18 项 Python 回归全部通过，包括证据封存、恢复密钥轮换、Common 边界与当前 Epoch 源码门禁。真实 Docker 即时自动重启、业务负载下回归及长期异步复制仍需后续验证。


## 2026-11-11 15:32 业务测试边界与同 Mac 新代际替换

- 第一轮业务构建 1526 的 Trade 221 项通过，Order 两项失败。一项因调用测试时漏传既有独立 RSA 测试身份路径，另一项旧结构测试仅允许 businessRegistry，未随既有 mutation barrier/readiness 两个 Common BusinessPorts 回调同步更新。没有修改生产接口来迎合旧断言。Order 测试提交 e6c2a44 精确列出三个既有业务回调，逐个核对 Common BusinessPorts 的参数与返回类型，仍拒绝任何业务自建物理恢复方法。
- 新构建 1529 保留第一次失败日志。显式传入既有测试身份后，Order 173 项中 171 项通过、2 项跳过、零失败和错误，Trade 221 项全部通过。两个跳过项为旧 T343/T344 专用历史 P193 E1 镜像和 E2 WAL 只读回放，因本轮未提供这两个旧现场而按既有 @Ignore 跳过，不把它们算通过。本轮真实恢复由已封存完整 Common 门禁和后续业务物理演练验收。
- 正常入口 mac-colima-saas.sh fresh 使用上述已构建、已验 Common 版本，开始替换原 Mac 单套环境，代际 mac-demo-20261111-153021。旧服务先停止并保留，再启动同端口新代际，没有并行业务 Demo。旧失败数据仍保留，重建不计为旧失败分区恢复成功。
- 新代际配置已经替换两组泄露的旧恢复接口 RSA 身份，所有新公钥指纹与旧值不同，两组新身份各异。实际运行验证仍在进行，既有独立物理 ACK RSA 身份继续按原只读挂载使用。轮换报告只记录公钥指纹，私钥不输出。
- 在线 trim 后宿主可用约 26 GiB，Docker 数据盘约 18 GiB。原 ext4 5%→1% 预留调整仍保留，没有进行虚拟盘扩容、Colima 重启或离线 fsck。新代际尚未完成业务启动，整体交付状态继续 NO_GO。


## 2026-11-11 15:38 同 Mac 新代际业务基线 PASS，真实替换继续

- mac-demo-20261111-153021 正常启动与物理检查、业务基线耗时 367 秒，其中真实业务验证 71 秒。ORDER_ONLY 租户 IS5NPN 与资金租户 FBOGNX 均完成独立 Maker/Taker 成交，客户两条执行与唯一公开成交匹配。Robot 两租户均持续报价，查询窗口记录 9 个唯一 Tape 成交执行、12 条 posting、6 个 posting 配对事件、无异常配对，余额/持仓/投影 cursor 检查 PASS。证据 verification.4JjX9i。此结果为 PASS_LIVE_BUSINESS_NOT_HA，不能提前计为故障切换通过。
- 四个运行 voter 逐一读取实际容器内 Common JAR 哈希，全部为 48463564a5f38b7cdf6c038458a3711eda65f70804eaee910c387a5ee26f042d，均为 on-failure 策略、零次重启，独立容器内存限额 2 GiB。记录 baseline-runtime-proof.json。Shared 51 项测试全部通过，运行版本为 1529 构建，恢复接口新密钥已随容器只读配置挂载。
- 一键构建脚本现已直接运行 Shared、Order、Trade 的 Maven 测试与 package，取消此前跳过业务单元测试的行为。使用可显式设置的 MAC_DEMO_TEST_RSA_KEYS 指向已有独立测试身份，Mac 默认复用原已存在测试路径，不生成或替换生产物理 ACK 身份。新实际构建 mac-demo-build-20261111-1536-unit-gated 已完整通过，输出 business_unit_tests=PASS。Shared 51、Order 173（2 项既有历史现场跳过）、Trade 221，零失败。此构建用于核验一键门禁，当前运行容器仍是前一份已单独全量测试通过的 1529 构建，未做额外业务重部署。
- 开始 Order B 正常停止与替换验证，机器人选择实际 Order P156/B 主租户 IS5NPN，要求 Robot 进程身份与启动时间始终不变，故障前、单节点阶段与回归后都提供新报价及成交证据，同时验证 ORDER_ONLY 受控撮合、Common 256 分区真实 LOCAL→STRICT Home 过程、双物理 WAL/快照 SHA 和最终财务投影。结果尚待完成，整体 HA 与两模式性能目标继续推进。


## 2026-11-11 15:51 业务正常停机竞态复现，P1 恢复保持 NO_GO

- Order B 正常停止演练未通过。B 在 Spring 销毁期间仍由独立 Common witnessed-return 线程发布 P093 E3 STRICT RECOVERING，原 signed Stage mtime 为 15:38:30.887398578，B 最终退出 143 于 15:38:33.431684496。当前 A 热分区 P093 已因物理复制失败永久隔离，RECOVERING 的候选 B 随后消失。Common 的全 manifest 单 Stage 串行限制阻止其他分区开始 LOCAL 接管，实际 survivor_local 0/256。未改 READY、Epoch、水位或签名条件。
- Spring 15:38:27.954 开始 taskScheduler 关闭，随后业务连接和 Netty 退出。源码显示 CommonCertifiedNodeRuntime.close() 会关闭物理服务与 WAL，但 binding 独立 return runner 由另一 Bean 后续关闭。StrictHomeHandoff 的 poison 分支仅检查 manager 的 Replica 授予，没有同时检查运行时已关闭。此生命周期间隙与现场相符，正在以相同生产 JAR 新增进程回归来确认。
- 原演练 evidence.json 保留 NO_GO，主动中止仍在等候的观察器以免空等 30 分钟。P093 A/B 原始 WAL、custody 与 B signed Stage 先复制到 blocked-P093-before-return，未复制私钥。Robot 未暂停或重启。随后通过原 Docker start 返回同一个已停止 B 容器、相同镜像与 Common 入口，没有创建替换环境或手工切换。B 正常启动后 P093 自动进入 E4 STRICT READY 并归还 A，P030 同样 E4，另 254 分区 E2 STRICT READY。该回归不能改记为之前单节点演练成功。
- 同一 Robot 原进程恢复持续报价，15:49 三个租户均 RUNNING、各 40 开放报价。新第三租户 K1332Y 为本次中止的 ORDER_ONLY 受控业务探针创建，数据保留，不能混作原两租户基线。
- 新增 Common 进程测试，故意将运行时关闭与 binding/控制管理器关闭分开 20 秒，复现 Spring Bean 销毁的生命周期顺序。首次测试只关闭出站 Netty client，入站复制仍可 ACK，不能复现真实失效，14.932 秒失败为测试模型错误，保留 /tmp/mac-t554-graceful-shutdown-red。已改为关闭真实 Common runtime 的入站服务与 WAL，等待确实关闭的标记后再发写入，第二次正在验证。生产 Common 尚未再改，当前正在运行的 4c 版本仍保持其原 P0 封存；P1/P2 停机恢复和最终交付继续 NO_GO。
- 另外确认一个更广泛的机制边界，候选进程在已发布 RECOVERING 后消失会占住全局 Stage。修复本次关机后继续发 Stage 的生命周期问题，不能自动等同于已经解决任意候选在 Stage 中永久丢失的情况。该差异必须继续验证和记录。


## 2026-11-11 16:00 正常停机生命周期最小修复与新统一候选

- 修正后的 Common 原版进程回归 78.347 秒稳定失败，测试在 B 真正关闭 runtime（入站物理 TCP 服务与 WAL）后保持 binding 和控制续约存活 20 秒。旧版 return runner 在已关闭的 B 上仍发布 P000 E3 RECOVERING，A 无法在 B 返回前继续 LOCAL 写入，与 Mac Spring 销毁现场一致。证据 /tmp/mac-t554-graceful-runtime-close-red/physical-live-poison/graceful-shutdown，保留两盘 WAL、signed Stage、进程日志及最终 manifest。
- 最小修复仅在 CommonCertifiedStrictHomeHandoff 发布新 Stage 前增加现有 runtime.requireAuthenticatedPartitionRole(partition) 检查，并与 runtime.close() 使用同一生命周期 monitor，保持既有 manager.requireReplica 授予检查。物理运行时关闭后，即使 ZooKeeper 会话与节点授予仍存活，也不能再成为新的恢复候选。没有新增关机框架、重启服务或认证类型，没有放宽物理 ACK/旧 Epoch 隔离。
- 相同测试在单类覆盖的定向诊断中 149.326 秒通过。A 在 B 返回前真实 ACK 为 P145/E3/1 LOCAL_DURABLE_ASYNC，随后 B 经原启动入口回归，两盘确认前缀、正常 Home 分工与业务回放通过。该诊断用于确认因果，正式安装仍等待新完整 JAR 的全门禁。
- 生产及测试提交 6ad4461，候选目录 t554-common-candidates/20261111-155552，JAR SHA256 为 7914c4ba0690e7ab354fb955184a670e0a4f445a6206d19d0d5f4da18a94d4a8。新全门禁将原七类故障与新增正常停机共八类真实进程演练一起运行，然后继续完整 256 分区双向 SIGKILL、中断返回和重复 Home 演练。封存器要求新增 graceful-shutdown 物理证据、原进程退出 143 和返回前真实 LOCAL ACK。92 项安全、控制与 TCP 测试 31.395 秒通过。新 JAR 尚未安装到业务容器。
- 当前业务维持已恢复的 4c 版本、三 Robot 租户 RUNNING。启动 45 秒只读 JFR 诊断采集 Order A 与 Trade A 的真实 force/CPU，诊断目录 performance-v48-steady-diagnostic。同期独立原生 Common 门禁运行，明确标为诊断样本，不能作为独占机器容量或最终客户端 P99。


## 2026-11-11 16:08 JFR 落盘耗时校准失败，撤回旧内部 IO 分位数

- 新的 45 秒诊断出现同一线程数百次 FileForce 的纳秒级耗时完全相同。对实际容器 Java 1.8.0_392 做独立校准，连续 16 次 FileChannel.force(true) 使用 System.nanoTime 实测 16 个不同耗时，约 1.189～15.939 毫秒，而对应 16 个 JFR FileForce 耗时全部为 1.285208 毫秒。宿主 Java 8u504 重新读取原记录也得到相同重复值，问题存在于已记录的事件，无法通过换解析器还原真实时长。证据 performance-v48-steady-diagnostic/java8-force-calibration.json 及同目录校准源文件，校准仅在自建临时文件操作并删除，没有修改业务数据。
- 公开 OpenJDK 8u392 实现使用每线程复用事件，force 的插桩调用 begin/commit/reset，reset 只清业务字段，commit 对已有非零 duration 直接复用。此实现路径与重复耗时相符，不将这些重复值当作多次独立物理计时。[force 插桩实现](https://github.com/openjdk/jdk8u/blob/jdk8u392-b08/jdk/src/share/classes/jdk/jfr/internal/instrument/FileChannelImplInstrumentor.java)、[事件 reset](https://github.com/openjdk/jdk8u/blob/jdk8u392-b08/jdk/src/share/classes/jdk/jfr/events/FileForceEvent.java)、[事件 duration 写入逻辑](https://github.com/openjdk/jdk8u/blob/jdk8u392-b08/jdk/src/share/classes/jdk/jfr/internal/EventInstrumentation.java)
- 正式撤回此前 performance-50 中 Order 内部 force P50/P95/P99 为 23.161/97.142/102.538 毫秒、Trade 为 132.293/158.517/158.517 毫秒的解释，以及据此推断实际每次落盘耗时的结论。原始 JFR 与 JSON 保留，并新增 JFR_DURATION_WITHDRAWAL_20261111.json。当前新诊断 summary.json 明确 FILE_FORCE_DURATIONS_WITHDRAWN，保留原事件计数与 CPU 栈，旧数值另存 unvalidated-jfr-duration-summary.json 作为错误分析记录，不能再用于验收。
- 独立 Python 单调时钟探针在实际 Colima Docker 数据文件系统，以自建临时目录完成 256 次 4 KiB 顺序写入与 fsync，P50/P95/P99/最大为 1.155/3.805/18.403/102.074 毫秒，写入总计 1 MiB，临时文件已删除。同期原生 Common 门禁仍运行，只用于底层 IO 诊断，不能等同交易延迟、独占吞吐容量或生产指标。后续客户端下单/撤单和完整链路 P99 仍需独立实测。
- 新候选 155552 的八类真实进程场景合计 413.937 秒全部通过，完整 256 分区主流程继续。另以同一正式候选 JAR 做额外独立进程诊断，将测试 supervisor 的首轮 45 秒等待改为 100 毫秒立即重启，检验实际 Docker 较快重启边界。只改变独立测试调度，原正式门禁档案和业务容器均未改，该诊断结果仍待完成。


## 2026-11-11 16:20 客户端下单撤单重测与快速重启补充证据

- 当前 4c 代际完成六个 30 秒窗口，合计 995 组真实下单、New 查询、撤单、消失查询闭环。受控认证 CUSTOM 源共发布 296 次，零源错误，结束后测试 Broker Key 已撤销。六阶段 SQL 订单集合、撤单终态、零成交、资金一致及零测试残留挂单均通过。Robot 在背景继续运行，Common 新候选门禁同时运行，所以这是共享负载下的诊断，尚未作为最终整机容量验收。下单 ACK 为实际 API 的受理语义，后续 New 与撤单终态通过独立查询、SQL 和余额核验。

| 模式 | 并发客户端 | 完整闭环每秒 | 下单 ACK P99 毫秒 | 撤单 ACK P99 毫秒 |
|---|---:|---:|---:|---:|
| ORDER_ONLY | 1 | 4.725 | 211.286 | 270.96 |
| ORDER_ONLY | 4 | 7.755 | 814.478 | 452.847 |
| ORDER_ONLY | 8 | 7.102 | 1541.488 | 1079.36 |
| TRADE | 1 | 3.717 | 166.226 | 299.383 |
| TRADE | 4 | 4.852 | 405.998 | 751.564 |
| TRADE | 8 | 4.337 | 1090.184 | 1698.484 |

- 完整结果 order-cancel-capacity-0bf190f2.json，环境范围 order-cancel-diagnostic-context.json。当前单租户分区闭环吞吐随 4→8 并发未继续提升，延迟升高，后续需结合多租户与分阶段计时定位串行提交、复制和排队成本，不能把本轮闭环每秒当撮合最大 TPS。长期正常双节点异步复制正式入口仍未接线，尚无该模式整套性能结果。
- 同一新候选 JAR 7914c4ba0690e7ab354fb955184a670e0a4f445a6206d19d0d5f4da18a94d4a8 的快速重启独立进程测试 48.312 秒通过。测试 supervisor 首次与后续重启等待均为 100 毫秒。原节点因写入授予过期退出 78，原 ZooKeeper 租约自然释放前有六次新进程以 ZkNodeExistsException/退出 1 安全拒绝创建同名租约，随后成功认证回归。第一笔真实单节点 ACK 为 P141/E3/1 LOCAL_DURABLE_ASYNC，终态分区 Home 与业务数据验证通过。该证据的 3610 个公开物理文件、原日志与独立测试源码已复制并逐文件封存至 t554-common-verifications/20261111-155552/additional-immediate-restart。100 毫秒是尝试重启的等待时间，完整恢复耗时按整场 48.312 秒记录。真实 Docker 运行进程的租约过期→退出→自动重启仍待部署后的实测。
- 新候选完整主测试已推进至双物理初始历史、保留旧主归档并发读取、严格冷安装、跨 Epoch 快照和 LOCAL 历史、签名恢复中断后续接等阶段。主流程尚未结束，新 JAR 仍未集成。当前原 Mac 业务使用前一版已恢复基线，完整 HA 与严格/正常异步两模式性能目标仍在推进。


## 2026-11-11 16:39 停机竞态候选 P0 GO 与同 Mac 新代际部署

- Common 6ad4461、正式 JAR 7914c4ba0690e7ab354fb955184a670e0a4f445a6206d19d0d5f4da18a94d4a8 的完整门禁封存 PASS。八类进程故障 413.937 秒，主流程 2123.897 秒，92 项安全与 TCP 回归通过。完整双向 SIGKILL、LOCAL 继续写、Home 归还、签名中断后续接、第三次故障及重复回归全部完成，256 组 WAL 与快照一致。证据 t554-common-verifications/20261111-155552。各阶段 aFailoverMs=240427、aHomeMs=454100、bFailoverMs=239600、bHomeMs=417716，为整个 256 分区阶段完成耗时，仍有恢复速度优化空间。
- 通过正常 mac-colima-saas.sh fresh-verified 入口启动新同 Mac 代际部署。本次选择用户已授权的失败后新代际流程，复用完整 P0 通过的同一 JAR，保留上一代际容器与数据，停止旧服务后再启动新服务。新构建会直接运行 Shared/Order/Trade 单元测试。前一代际的停机失败继续保留 NO_GO，新的空业务数据不会被当作旧失败分区的恢复证明。正式业务停机演练和持续 Robot 故障测试将重新进行。
- 新增可复用 Docker 整节点租约故障验证工具 scripts/verify-mac-demo-node-fence.py，目前仅完成语法及 CLI 检查，真实执行待新代际验收。工具暂停一个真实 voter 超过实际写入租约，在 ZooKeeper 原会话仍存活时解除暂停，观察 Common 退出 78、既有 Docker 自动重启、同容器新会话认证回归，并核对 Robot 连续身份、报价与 Tape、财务 cursor 和观察到的不可变 LOCAL 物理文件。重启完成需新启动标记与稳定 Home 位置，后续对账结束再复核同一 census。该工具只负责注入暂停与观测，恢复动作仍由 Common 和现有 Docker 执行。


## 2026-11-11 16:49 新停机修复版本业务基线通过，复验原失败场景

- mac-demo-20261111-163937 已通过同一原 Mac 的正常一键新代际部署。源码编译与 Shared/Order/Trade 测试合计 66 秒，物理启动及真实业务验证 352 秒，其中业务验证 72 秒。Shared 51、Order 173（2 项既有旧 P193 现场测试跳过）、Trade 221，零失败。实际四个运行 voter 的 Common JAR SHA 均为 7914c4ba0690e7ab354fb955184a670e0a4f445a6206d19d0d5f4da18a94d4a8。Shared 本次构建 JAR SHA 为 f9d3094fd49c5a863cbc9bd57dba936b1865fca743f8fcf042111511bdbe5fc6，业务源码仍包括之前保留的工作区修改，构建记录其原状态和 SHA。
- ORDER_ONLY 租户 F6LPER、资金租户 LUCQCB 均完成客户成交与公开成交匹配。两租户 Robot 自动报价、Tape 真实成交、posting 配对和财务 cursor 基线通过。原四 voter 与支持服务的上代际数据保留，当前业务完全位于新代际，旧失败仍按原 NO_GO 归档。新代际恢复接口 RSA 再次轮换两组公钥指纹，既有独立物理 ACK 身份保持原绑定，配置实际挂载生效。
- 开始复验曾失败的 Order B 正常停止场景，同一 LUCQCB Robot 的 Order 分区 P175 正在 B 主节点。要求 Robot 原进程持续运行，ORDER_ONLY 受控撮合在全分区 LOCAL 接管后继续，B 正常替换后回归 Home，并验证不可变物理文件与财务投影。结果尚待完成。


## 2026-11-11 17:07 Order B 正常停止、替换及持续 Robot 验证通过

- 163937 代际的 Order B 正常停止演练完整通过，状态 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS，证据 ha-order-b-term-jd60laa8。原 B 正常退出 143，A 自动接管并发布 256 个 LOCAL READY，受控 ORDER_ONLY Maker/Taker 成交在 B 离线阶段完成，资金及持仓维持原值。B 从相同 Common 镜像、原物理卷启动新进程、新会话，自动追平并恢复 A/B 各 128 Home，两个物理节点共比较 256 组 LOCAL WAL 和 256 组恢复 Snapshot，零差异。
- 整个 256 分区 LOCAL 完成耗时 266.136 秒，替换启动到整个 Home 完成耗时 603.763 秒。单个热点 P175 在接管 62/256 时已经进入 E3 LOCAL，从故障注入到该位置约 69.4 秒。其后在全量接管完成前，同一 LUCQCB Robot 已记录 34 个新报价请求、35 个 Tape 请求及 33 个唯一成交执行。部分分区恢复的实际业务持续性已验证，整体阶段耗时不替代单个分区恢复时间。
- Robot 容器 ID、启动时间和重启次数保持连续。接管期间 9 个业务循环、最大间隔 31.836 秒，回归期间 20 个循环、最大间隔 30.645 秒。单节点阶段新报价与 3 个实际 Tape 成交执行通过，回归后有新的报价与成交，三阶段成交 ID 无重复，posting 成对且财务 cursor 对账通过。新代码使原正常停机失败场景完成了真实业务回归，前一代际的失败证据继续保留。
- 此后准备 Trade A 停止、Trade B 单节点资金交易及替换回归演练。性能定位准备使用从 Ubuntu 原包校验 SHA 后仅解压至 VM 临时目录的 syscall 观察器，对已有 Order A、Trade A 分别观察 20 秒真实 fsync，不修改服务 JAR。观察器开销明确归入诊断范围，后续客户端容量验收使用独立窗口。


## 2026-11-11 17:09 实际 JVM fsync 系统计时复核与 Trade 单节点演练

- Order B 完整回归结束后，在当前 Common 6ad 实际 Order A、Trade A 上分别观察 20 秒 fsync/fdatasync syscall。临时 strace 仅附着和分离既有进程，前后容器 ID、进程启动时间和重启次数均核对。该诊断有观察器开销，不作为客户端容量窗口。证据 performance-kernel-force/context.json、两个 syscall 原记录及 summary.json。
- Order 771 个成功系统调用记录有 606 个不同耗时，P50/P95/P99/最大为 0.982/3.413/7.692/96.695 毫秒；Trade 128 个记录有 125 个不同耗时，对应 0.872/2.073/4.204/7.333 毫秒，两者未见失败的 fsync 系统调用。此独立计时再次确认 JFR 每线程重复时长不能解释整条交易链路延迟，客户端延迟需继续按完整 API/终态分别测量。Trade 样本较少，所有统计均保留样本数和范围。
- 继续 Trade A 正常停止演练，Trade B 将以明确的 LOCAL_DURABLE_ASYNC 合同单节点承接资金、持仓与结算。同一 F6LPER Robot 的 Trade 分区 P089 原主为 A，要求离线期间真实资金交易与 Tape 成交持续，替换 A 后追平、Home 归还、双物理文件与财务 cursor 一致。受控签名 Maker/Taker 探针使用正常 API 和 SDK，结果待完成。


## 2026-11-11 17:22 Trade 单节点阶段与严格写入实际成本

- 用户已明确接受整节点不可逆隔离后的自动退出、现有 Docker 自动重启和认证回归。现役节点均使用 on-failure，独立 Common 的立即重启门禁已通过。实际 Docker 演练待本轮业务回归完成后执行，不能提前列为通过。
- 当前代 mac-demo-20261111-163937，Trade A 正常停止 143，Trade B 自动完成全部 256 分区 LOCAL 接管，314.309 秒。受控资金租户 DTENK8 在 P071/E3/403 完成 Maker/Taker 资金及持仓变更，检查两个账户。原 F6LPER Robot 的 P089 在 70/256 READY 时取得 B/E3 LOCAL 角色。Robot LOCAL 采样已取得新报价、Tape 请求和实际 Trade 本地结算收据，采样内尚未看到 Order 日志中的 Tape execution，最终以回归后的原坐标成对 POSTING 及财务 cursor 核验。
- 17:22 的实际清单 NPC1/842，164 个分区已恢复 E4 严格双副本，92 个仍为 E3 LOCAL，尚未自动归还 Home。当前演练仍 NO_GO，未报整轮 PASS。证据 ha-trade-a-term-gyhkrpsk/evidence.json。
- syscall 原记录与现有 Common 热路径核对，每个严格 Common command 的 Primary 发生 7 次 fsync，Replica 发生 5 次。Primary 为 WAL 一次、CommitIndex 文件及目录两次、Custody 文件及目录两次、Receipt Ledger 文件及目录两次。Replica 无本机 CommitIndex 的两次，共五次。一个客户端交易可涉及多个 Common command。
- Order 20 秒实际 147 次 WAL force，其中 18 条本机 Primary、129 条 Replica，总计 7×18+5×129=771，与观察完全相等。Trade 为 14 条 Primary、6 条 Replica，总计 128，相等。这是已测协议成本，尚未通过独立端到端窗口证明其占全部延迟的比例。未删除任何现有持久化证明。数据 performance-kernel-force/summary.json。


## 2026-11-11 17:32 Trade A 正常替换完整通过，接续 Order A 强杀

- ha-trade-a-term-gyhkrpsk/evidence.json 最终 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS，原 A 实际退出 143。全部 LOCAL 接管 314.309 秒，替换启动至全部严格 Home 归位 837.021 秒。A/B 各 128 主，256 对历史 LOCAL WAL 与 256 对恢复 Snapshot 的精确物理哈希一致。财务 cursor PASS，余额及持仓差异为零，来源 HEAD 和 predecessor link 完整。
- 同一 F6LPER Robot 容器、启动时间、重启计数全程不变。接管期间 10 轮、最大间隔 47.086 秒，回归期间 27 轮、最大间隔 41.327 秒。原日志阶段计数分别为故障前 23 次 Tape execution、LOCAL 窗口 41 个新报价及 5 个 Tape 请求和 5 条本地结算、回归后 1 次新 execution。LOCAL 窗口 Order 日志尚无 Tape execution，5 条 Trade 原坐标均在回归后精确核对到 5 个成对 POSTING 事件。阶段间 execution 不重复。
- 17:30 已接续在同一代 Order A SIGKILL，沿用正常签名业务探针和同一 F6LPER Robot，目录 ha-order-a-kill-p7cw3m4j。后续 Trade B SIGKILL、两种服务整节点租约隔离的 Docker 自动重启与财务检查、独立严格模式下单撤单窗口依赖前一项通过后自动接续。

## 2026-11-11 17:54 Order A SIGKILL 完整通过与 Trade B 热分区故障

- ha-order-a-kill-p7cw3m4j/evidence.json 最终 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS。原 A 实际 SIGKILL 137，B 全部 256 LOCAL 接管 368.753 秒，替换 A 至全部严格 Home 回归 893.180 秒。256 对旧 LOCAL WAL 与 256 对恢复 Snapshot 精确一致，受控带资金成交、公开 MD 和最终财务 cursor 一致。
- 同一 F6LPER 的 Order P065 原 A/E4，接管到 B/E5，在 112/256 READY 时已可写。全部接管之前已观察到 112 个新报价、34 个 Tape 请求和 33 个 execution。纯 LOCAL 阶段另有 2 个新报价、3 个真实 execution 和 3 个成对 POSTING 事件，回归后另有 1 个新报价、1 个 execution 及对应 POSTING。故障全程 Robot 容器、启动时间及重启计数不变。
- 17:52 自动开始 ha-trade-b-kill-k74tehu6，正常探针已就绪，选中 AU0MF2 Robot，Trade P224 原主 B/E4，确保故障击中正在交易的 Primary。继续要求 A 单节点资金结算和回归后的全部严格 Home、物理及财务一致。
- 压测统计三处统一增加 p99_9 并保留样本数，沿用原 nearest-rank 定义，空样本仍为 null。1000 条确定性样本的 P50/P95/P99/P99.9 分别为 500/950/990/999，语法与边界检查通过。未改变业务或服务持久化配置。

## 2026-11-11 18:44 Trade B 物理回归完成，但业务超时，定位历史读取放大

- ha-trade-b-kill-k74tehu6 的原 B 实际强杀，A 全部接管 462.955 秒，替换 B 到全部严格 Home 1268.879 秒。双盘历史 LOCAL WAL 和恢复 Snapshot 精确一致。单节点受控租户 M44Y1U 已完成两个账户资金、持仓核验，AU0MF2 Robot 也取得 9 条实际 LOCAL 结算收据。最终签名探针在读回阶段超时，整轮保留 NO_GO，后续故障注入和独立压测未启动。
- 18:25 独立财务检查为 PASS_FINANCIAL_CURSOR。余额和持仓差异为零，missing_source_heads、extra_cursors 均为零，20279 条 predecessor link 核验通过。物理与财务通过不能代替客户 API 读回及 Robot 连续业务通过。
- 超时附近存在已失效身份查询的 9002，最初列入认证传播候选。正常注册两个零资金诊断用户，在 A 主的 M44Y1U 和 B 主的 AU0MF2 分别进行 Web、签名 API、再次签名登录后的只读查询，12 个请求全部 code=0，16 至 516 ms。仅查询和注册，未为诊断账户入金或报单，创建的诊断 API Key 已通过正常接口撤销。证据 auth-read-diagnostic-88z0rf6u/evidence.json。当前证据不足以认定认证本身是根因。
- Robot 原进程线程采样显示多个 worker 等待 cancelBatch 请求，Tape 线程等待同一个 TradingSession。只向已核对的实际 Java 子进程发送 QUIT 输出线程栈，容器 ID、Java 启动身份及重启次数均未改变。未重启 Robot。
- 四业务节点进一步采样显示大量 gateway-api-worker 执行 fetchCommittedOrderProjectionEvents、fetchCommittedTradeProjectionEvents，以及退休 LOCAL 命令的结算重读。它们反复从 CommonCertifiedStrictHomeHistory.verify 重开整个跨 Epoch 历史链，包括已经消费完毕或一直为空的分区。Trade B 多个结算线程等待同一历史读取锁，持锁线程正在重开原 WAL 和验证祖先安装。跨 Epoch 历史增多后，此工作反复占据有限服务工作线程，客户请求排队。继续按此已观察到的读取放大修复，认证失败记录仍保留。
- 修复候选只在既有 Common registry 中保存与实际 installed writer 实例绑定、容量上限 4096 的已认证退休 prefix 元数据。保存 epoch/head/path/digest，释放完整 History、恢复图片和命令内容。首次加载仍核验完整签名链，writer 退休或替换立即清除其条目。每次读仍核对当前 Permit、CommitIndex/Custody、原 WAL 帧和哈希，并在返回前复核当前 writer，已有物理 ACK 和 Fencing 条件保留。候选尚未通过独立门禁，未集成业务。
- 已增加独立物理进程回归检查，反复读取时仅认证一次元数据，缓存后破坏测试原盘 WAL 仍须拒绝，恢复测试原字节后可读，退休并重新绑定同一真实 writer 必须重新验证。测试只操作隔离 Common fixture 的临时文件，现役业务盘未改动。正在用旧 6ad JAR 做失败对照，再验证候选。


## 2026-11-11 19:11 Common 历史前缀元数据缓存门禁进展

- 生产修订 27b752ee0c8789361cff53ac669912896566c149，候选 t554-common-candidates/20261111-184641，精确 JAR SHA256 为 ea31fd936b2b193b3ec49580fb7dbe87092a32dd8fb12f1c23c317c65fcdc380。工作树干净。修改范围为既有 registry 的元数据读取与独立物理回归夹具。
- 旧 6ad JAR 配合新增回归夹具，25.737 秒按预期失败，同一历史页四次读取重复验证四次完整历史。候选诊断 18.533 秒通过。此对照验证调用次数与正确性，客户端性能另行测量。日志为 /tmp/mac-t554-archive-cache-regression/red.log 和 green.log。
- 精确候选通过 126 项安全、控制、传输和 WAL 测试，79.622 秒。八轮独立进程 live poison、重复 poison、重启、整节点租约过期和正常关闭也全部通过，421.605 秒。适用的缓存回归保留原 WAL 损坏拒绝和 writer 退休后重新验证。
- 全量 256 分区独立进程门禁在 t554-common-verifications/20261111-184641 继续。第一方向真实强杀、LOCAL 持续写入、全部 Home 回归、两种布局的冷严格安装、长 STRICT/LOCAL WAL 前缀、并发历史读取、中断后的签名 rearm 续接已经通过。反向和第三次故障仍待完成。候选业务部署等待完整门禁。
- 本地依赖控制器等待完整封条 PASS 和 126 项测试 PASS，随后在原 Mac 调用既有 fresh-verified。此前失败代和数据保留。新业务基线通过后，依次进行用户已同意的 Order A、Trade A 实际 Docker 整节点租约过期、自动退出重启及 Robot 连续业务检查。这两轮实际 Docker 验收仍待执行。

## 2026-11-11 20:29 完整 Common P0、实际 Docker 隔离与 LOCAL 最终确认

- 27b752e 精确 Common 已完成全部独立物理门禁。256 分区主程序 2620.372 秒，含双向 SIGKILL、第三次重复故障、中断后的 LOCAL→STRICT 签名 Stage 续接和跨 Epoch 原始前缀读取。每轮 256 对 WAL 与 256 对 Snapshot 精确匹配。独立结果 20261111-184641 已封存 PASS，55539 个公开证据文件哈希。126 项安全测试和八轮独立故障也全部通过。
- 原 Mac 193908 代使用同一 ea31fd936b2b193b3ec49580fb7dbe87092a32dd8fb12f1c23c317c65fcdc380 JAR。构建 102 秒，实际物理启动及业务 420 秒，其中业务基线 81 秒。ORDER_ONLY、带资金成交、MD、Robot、财务 cursor 已通过。旧失败代停机保留。
- 真实 Order A 整节点写入租约过期，在原 ZooKeeper 会话仍存活时由 Common 自动退出 78，同容器由 Docker on-failure 自动重启。最终 52.423 秒恢复全部严格 Home。证据 node-fence-order-a-f3w8ic97。真实 Trade A 同样通过，67.565 秒恢复，证据 node-fence-trade-a-fpj_ik_v。两轮均核验同一 Robot、故障期间报价、恢复后成交、财务及实际观察到的历史物理内容。
- Order 早先两轮审计保留 NO_GO。第一轮实际恢复 54.248 秒，短窗口只有一个 Robot 周期，不满足两轮观察。第二轮观察器的稳定计时条件在同一 manifest generation 下由未完成变为完成时未启动计时，已停止该观察器并修复条件。业务节点持续运行。最终审计把真实恢复 RTO 与至少 120 秒 Robot 观察窗口分别记录，故障到回主期间的真实成交数量照实保留。
- 用户已确认严格模式单节点期间采用本机落盘后最终确认成交，回执明确标记单副本风险。Shared 的已验证 LOCAL 签名回执现按原持久化级别完成结算。Order 仍须验证真实 Trade 节点 RSA、原订单分区/Epoch/序号/租户/MatchKey，并把完整签名回执再次提交到原 Common WAL 后才退结算待办并发布成交。原物理 ACK 和 Fencing 保留。
- 新成交回执附加 TradeSettlementDurability、TradeSettlementQuorumDurable、TradeSettlementRpoRisk，LOCAL 另带 TradeSettlementCommit。旧 LOCAL 原始回执即使后来追平，仍保持 LOCAL/false/true。标记描述 Trade 结算。实时回执及短时运行态查询携带这些字段，历史投影保留原签名 ACK，缺失字段不代表双副本保证。
- 业务构建 mac-demo-build-20261111-202055-local-final 已通过 Shared 51 项、Order 176 项中通过 174 项并跳过原有 2 项、Trade 221 项。覆盖 LOCAL 一次完成、重复回执、篡改签名、错误原始 Order 坐标及恢复待办不重结算。正在原 Mac 正常 fresh 部署 202414 代，193908 的证据和业务盘保留。业务最终确认仍待实机门禁。
- Trade 单节点门禁已收紧。允许备节点返回之前，必须取得 Maker/Taker 两个带 LOCAL 风险标记的最终成交回执和匹配的公开 MD，坐标必须与真实 Trade 本地结算日志一致。Robot 单节点窗口也必须出现实际 Tape execution。正常双节点异步复制尚未接线，其压力测试仍待开发与独立安全验证。

## 2026-11-11 20:51 LOCAL 最终成交实机通过与 Trade B 强杀完整回归

- 新 202414 代基线已通过，业务 61 秒。四业务进程由 fresh 入口核对实际 Common 和 Shared JAR。Common 保持 ea31fd936b2b193b3ec49580fb7dbe87092a32dd8fb12f1c23c317c65fcdc380，Shared 为 efaf9a37281a67216fe86d868ab1a10329c3344bf72844b035b53e12d7aecbbc。Shared/Order/Trade 源码状态及完整源码哈希保存在 202055-local-final 构建目录。
- ha-trade-b-kill-lsunj93r 最终 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS。真实 B SIGKILL 137，A 全部分区 LOCAL 接管 320.856 秒，替换 B 启动至全部严格 Home 回归 656.071 秒。旧 LOCAL WAL 与恢复 Snapshot 各 256 对精确匹配。严格回主后客户 API、公开 MD、财务 cursor、来源 predecessor 均通过。
- 受控租户 Q978Q9 的 Trade P043/E3/339 在 B 仍停机时已更新两个账户资金及持仓，Maker/Taker 最终回执分别为 E590fc406c0d9140edbde1985da6ab1 和 E36846245f288a8ce1873894c6d9f5c。两条回执均返回 LOCAL_DURABLE_ASYNC、TradeSettlementQuorumDurable=false、TradeSettlementRpoRisk=true、TradeSettlementCommit=P043/3/339，公开 MD 已出现 Maker 的对应成交。上述字段由两个客户各自认证的运行态成交查询取得，早于允许 B 返回的 business-local 检查点。
- 原 C5LQZZ Robot 热分区 Trade P161 原主 B/E2，在 70/256 READY 时已由 A/E3 接管。其原进程身份与启动时间不变，接管期 10 轮、最大间隔 42.052 秒，回归期 22 轮、最大间隔 30.718 秒。独立 LOCAL 窗口实际 Tape execution Ece1a91c05140dc6d6d19d1416100f3 对应 P161/E3/377 的原始资金成对 POSTING，回归后另有新 execution 且阶段间无重复。此前仅有资金更新而最终成交等待回归的问题，在本轮收紧门禁下已通过。
- 在尚未全部接管时，还独立记录了 B 仍停止状态下 Order WAL 中真实签名 LOCAL 最终结算 ACK。证据 early-local-final-before-full-takeover.json。运行态回执字段说明已同步到当前 SDK 源 README 的中英文部分，公开文档网站和 UI 未发布变更。
- 为使下一轮故障命中 Order B 的实际 Robot Primary，通过既有正常基线新增两名自动审批试用租户 HEYFVS、W9X37B，基线及财务核验通过，仍使用同一代和同一 Robot 进程。Order B TERM/ORDER_ONLY 演练已启动，目录 ha-order-b-term-734rqr5r，后续 Order A KILL、Trade A TERM 和严格压力窗口按结果依次执行。
- 恢复 RTO 仍为分钟级。额外线程采样保存在 takeover-thread-samples，单次采样看到既有 Common 回归工作线程等待控制读、其他控制线程和 Witness 处于等待，尚不足以量化归因。源码确认现有逐分区回归固定间隔，另确认实际 Order 配置的签名结算扫描间隔为 1000 ms。后续用独立客户端窗口分开测量恢复时延和正常成交延迟，再据实优化。

## 2026-11-11 21:16 Order B ORDER_ONLY 通过与即时结算派送候选

- ha-order-b-term-734rqr5r 最终 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS。原 B 正常退出 143，A 全部 LOCAL 接管 305.710 秒，替换 B 启动到全部严格 Home 回归 819.647 秒。旧 LOCAL WAL 与恢复 Snapshot 各 256 对完全一致。受控 ORDER_ONLY 成交、公开 MD、资金不变及财务 cursor 验证通过。
- 同一 HEYFVS Robot 的热分区 Order P245 原主 B/E2，在 89/256 READY 时已由 A/E3 接管。接管期间 10 轮、最大间隔 31.670 秒，回归期间 27 轮、最大间隔 30.814 秒。独立 LOCAL 窗口得到 7 个新报价、11 次实际 Tape execution，全部匹配唯一的成对资金 POSTING，回归后再核对新成交和跨阶段不重复。
- Order A 强杀及带资金业务已接续，ha-order-a-kill-fc208ncn。后续仍需 Trade A 正常替换和反方向单节点最终成交，以及完整独立压力窗口。
- 已在既有 Order 待结算 WAL 索引增加提交后的内存通知。仅在原 Common 已提交且两侧订单状态已应用后发出，新成交交给既有结算 Worker 的两个有界派送线程，签名、原始来源验证、Trade 资金提交和 Order 最终 ACK 的物理 WAL 流程保持原路径。每秒扫描继续负责冷恢复及失败重试。通知队列满或停止后，原 WAL 待办保留。
- 此即时派送候选已通过 Order 180 项测试中 178 项，跳过原有 2 项。新增测试覆盖无扫描直接派送、重复通知、通知失败后原待办不变和原定时重试恢复。候选构建 order-immediate-build-20261111-205855，镜像 local/otc-mac-demo-order-immediate:1c854e4c20313c15，实际镜像 ID 为 sha256:b235cf9f33b3165bf9e95f1d1d2c8a269f191152ba281604ecfb9eacc48d204b。保留原 ea31 Common 和 efaf Shared JAR 的实际字节并已核对。候选尚未部署，当前实机故障矩阵仍验证 202055-local-final 的原始已测构建，正常成交时延改善尚待实测。

## 2026-11-11 22:18 第二轮 Trade 故障暴露业务重放入口上限

- Order A 强杀 ha-order-a-kill-fc208ncn 完整通过。原进程退出 137，全 LOCAL 接管 363.772 秒，全部严格 Home 回归 816.657 秒，256 对 WAL 和 256 对 Snapshot 完全一致。原 C5LQZZ Robot 热分区 Order P099 从 A/E4 到 B/E5，在 79/256 READY 时接管。接管期 10 轮、最大间隔 63.271 秒，回归期 27 轮、最大间隔 33.665 秒。独立 LOCAL 窗口 33 个报价、3 次 Tape 成交及唯一资金 POSTING 全部核验。
- 接续 Trade A TERM 的 ha-trade-a-term-3jmbns5s 在 P008/E5 RECOVERING 停滞，30 分钟等待超时，原结果保留 NO_GO，后续压力流程已停止。A 原退出 143，B 原容器、启动时间和重启次数保持。反方向业务验收仍未完成。
- 只读观察器取得既有 Watch 的拒绝摘要 TRADE_COMMON_RECOVERY_BUSINESS_BARRIER_FAILED。该摘要丢失内部 cause，随后临时给 Trade 业务恢复适配器的异常重抛加入诊断输出，取得完整异常后已移除诊断转换并恢复原字节码。记录 recovery-exception-cause.txt 明确指向 TradeRecoveryStateMachine.apply 的 Trade replay exceeds bounded committed prefix。诊断过程记录 ORIGINAL_BYTECODE_RESTORED。
- Common 已验证 P008/E4 的真实签名提交 HEAD=4983，但 TradeRecoveryStateMachine 在第 4097 条记录时拒绝。此前 TradeColdSignedLargePrefixTest 只验证后续 TradeRecoveryApplier.requireColdSignedEnvelope，覆盖不到此实际 snapshot/byte[] 入口。新增 TradeRecoveryStateMachineLargePrefixTest 在旧镜像对应的原 classes 上按预期失败，2 项中 1 项失败，异常与现场一致。新增负例仍拒绝超出认证 HEAD 的帧。
- Trade 入口现在与 Order 既有实现一致，允许 Common 已认证完整历史的最多 65536 帧，保留 Common 原有逐帧、提交 HEAD、完整字节预算、签名及隔离证明。业务回放仍在 finishReplay 前暂存，未向 Common 添加业务或 HA 分支。完整 Trade Maven 223 项全部通过，13.393 秒。测试明确验证 4983 条经真实适配器 restore/apply 暂存，仅在最终回调进入业务 apply。
- 修复构建 trade-recovery-bound-build-20261111-215941，镜像 local/otc-mac-demo-trade-immediate:759a26a28765dc5f，实际 ID 为 sha256:5ed96f4dca1e835a6de560a4387d7991cf2b838ced56fd60b03f04b26cba9062。Common 与 Shared 字节仍为 ea31 和 efaf。Trade 类原 SHA 为 b08ddac9c1bcee7bc3d9142cb46a9f7fd124d1689c23c30dcb1e29b73db426fc，新类 SHA 为 2b2e8887c4fc4d0a62d5d313a4a5bf003347dcb00ad47b0622087a26f77c9304。
- 为保留现有真实故障现场，完整单测和镜像构建通过后，将这一处已核对原/新类 SHA 的业务类方法体热更新到原 B 进程。Common 既有恢复重试随后越过 P008 并完成全 256 分区 LOCAL 接管。该更新是实际运行代码变化，尚需通过正常滚动镜像替换消除 B 的临时内存差异。全部身份、原/新类、镜像和日志标记记录在 trade-domain-replay-bound-live-patch.json。此热更新恢复不替代一次完整正常镜像故障验收。
- 原失败文件保持原样。新增恢复观察 ha-trade-a-term-y0254hzp 从实际全部 READY/LOCAL 清单、原 A 停机身份及相同 B ZooKeeper 会话接续，仅观察物理回归，业务验收仍待重跑。A 已使用正式修复镜像正常启动，正在追平和自动 Home 回归。恢复脚本仅允许精确的原超时、完整当前 LOCAL 清单、正确逐分区下一 Epoch 及原物理身份，不接受缺分区、RECOVERING、错误 Epoch 或更换的存活节点会话。
- 正常应用覆盖镜像验证已同时支持 Order 和 Trade，并保持精确基镜像及实际 Common/Shared JAR 校验。新增 7 项脚本门禁测试，涵盖两种合法服务应用镜像、错误服务标签、错误基镜像、修改 Common/Shared 字节，以及部分清单、错误 Epoch 和会话变化拒绝。接续控制流程等待物理回归和独立财务门禁，再进行新 Trade 镜像 B TERM、A KILL 的双向业务演练，随后正常滚动部署即时 Order 派送候选并执行业务及压力门禁。

## 2026-11-11 23:05 持仓实时风险缓存导致恢复图片不一致，已修复并准备正常重建

- 接续物理观察 ha-trade-a-term-y0254hzp 同样保留 NO_GO。Trade P161 在 E7 严格恢复后发生单分区隔离，后续 E8 恢复阻塞，其他 255 分区严格 READY。通过只读字段观察取得候选 Watch 的已关闭历史 registry 摘要以及既有回归 Runner 的真实拒绝，A 为 invalid signed original Genesis voter，B 为 Common immutable local recovery image differs。实际拒绝图片不一致的条件继续保持。
- 原 A/B 的 P161/E8 Genesis 原始 JSON 已分别只读复制到 p161-e8-genesis-diagnostic，文件各 1830577 字节。A SHA 为 367730c57778b0b434279958fc2555e2d9bb695f2a552cd805433eefa2b0f097，B SHA 为 f4827dc9e55860bf3ba3361b4b6958e990122de4f85ae095199136d38e79235f。逐字段比较只有 8 个差异，全部在 positions 中的 pnl、longBankruptcyPrice、shortBankruptcyPrice、shortLiqPrice 和 riskUpdatedAt。资金、持仓数量及去重记录一致。差异路径及值哈希单独记录在 differences.json，原始 JSON 私有保存。
- 进一步源代码核对确认，RiskPositionPublisher、浮动盈亏及强平价计算在实时行情缓存中更新 Position，PositionFacade.snapshotLocation 返回实时 Position 对象。Trade 严格恢复快照直接序列化了这些实时缓存，两端不同的计算时点造成字节不一致。此定位为 Trade 业务快照问题，Common 继续使用已通过完整 P0 的 27b752e 精确 JAR，工作树保持干净。
- TradeBusinessSnapshotCapture 在严格恢复检查点对 Position 创建完整副本，然后把实时风险价格和浮动盈亏清零，将风险有效性标记为 PENDING_RECALC、false、时间零。资金、数量、均价、保证金及已实现盈亏等经济状态保留原值，实时 Position 对象保持其实际缓存。后续行情风险计算沿用原流程。现有业务快照格式保持兼容。
- 新增 TradeStrictSnapshotRiskCacheTest，旧 classes 上两项均按预期失败，分别暴露风险 Tick 导致图片不同，以及捕获结果直接引用实时对象。修复后完整 Trade 225 项全部通过，16.199 秒，Order 180 项中通过 178 项且跳过原有 2 项，Shared 51 项全部通过。原实际字节冲突证据和两个 NO_GO 文件保留。
- 为防止再次只由短期业务窗口覆盖少量数据，带资金 Trade HA 探针新增可选的 MAC_DEMO_HA_TRADE_PREFIX_COMMANDS，限定 4097 至 8192 个真实签名设置命令，在预备账户无仓位时交替设置杠杆并恢复原值，随后核对真实 Trade 投影 HEAD 超过单页界限。该步骤只用于实机回归探针，实际 HA 机制仍全部由 Common 完成。
- 已按既有失败优先保存证据再 fresh 的规则准备新代。第一次正常一键构建在部署前退出，Trade Docker 构建报 mount options is too long。现役 Trade 构建基底已累计 356 层，原较早 Trade 基底也有 315 层，Order 现役基底 272 层。已定位为反复从上一代应用镜像继续叠层导致的构建问题。
- 构建入口新增本地深镜像基底物化缓存。保留完整源运行配置，把原镜像文件系统物化为一个文件层，加载后再次导出并比较全部文件内容、类型、权限、所有者、链接和扩展属性。Trade 356 层基底已通过完整运行配置相等及 10051 个文件系统条目相等验证，缓存镜像 bffc0bfec453f0f95c18a258538253293a86614fed063381f7455ca5e630224c。完整 Common/Shared JAR 的后续实际镜像校验继续执行，缓存验证记录在 mac-demo-flat-base-cache 对应源镜像 SHA 目录。
- 已接续 fresh-verified 重试，日志 /tmp/mac-t554-canonical-risk-fresh-retry.log。旧 202414 代及所有业务盘、签名 Stage、冲突图片和原失败结果保留，新代须重新通过实际基线、带长提交前缀的 Trade 双向单节点、Order 双向替换、Robot 和财务一致性后再进入压力窗口。两个旧依赖控制器已因 NO_GO 停止，压力测试仍未启动。
- 另已归档两份停止增长且超过七天的轮转日志，原 12674871863 字节压缩为 263091666 字节。完整解压字节数、SHA、原文件稳定性及归档 SHA 均核对完成后释放原文件，净回收 12411780197 字节，约 11.56 GiB。清单 t554-retired-log-archive-20261111-222546/manifest.json，Mac 可用约 21 GiB。该归档只涉及旧轮转日志。

## 2026-11-11 23:25 正常构建接续与大前缀单节点成交

- 当前唯一活动业务代为 mac-demo-20261111-230352。正常一键构建 176 秒，物理启动及完整基线 390 秒，其中业务基线 71 秒。Shared 51 项、Trade 225 项全部通过，Order 180 项中通过 178 项，保留原有 2 项跳过。基线包含正常资金成交、ORDER_ONLY、公开行情、同一 Robot 及财务 cursor 核验。
- Common 仍为 27b752ee0c8789361cff53ac669912896566c149，实际 JAR SHA ea31fd936b2b193b3ec49580fb7dbe87092a32dd8fb12f1c23c317c65fcdc380，与完整独立 P0 封存结果一致。Shared 实际 SHA f1f8b791f571a058e7b6eaf1d89e6fec58716031bd8d0a4af34c3bf7d590402a。正常 Order 镜像 local/otc-mac-demo-order:ea31fd936b2b-f1f8b791f571-b37739001d74，Trade 镜像 local/otc-mac-demo-trade:ea31fd936b2b-f1f8b791f571-f453c646b26d，均包含正式源码修复，当前代未做运行时热更新。旧失败代和诊断证据保留。
- Order 272 层、Trade 356 层构建基底分别物化为一层，并验证完整运行配置及 10022/10051 个文件系统条目。实际完整构建已验证缓存接线。基底校验清单保存在 mac-demo-flat-base-cache。
- 新 Trade B KILL 演练 ha-trade-b-kill-mcw4ejhq 在故障前通过签名 API 提交 4105 次杠杆设置，投影记录 P249/E2 HEAD=4191。故障后全部 256 分区完成 LOCAL 接管。B 仍停止时，Maker/Taker 取得对应 P249/E3/305 的最终成交回执，均有 LOCAL_DURABLE_ASYNC、QuorumDurable=false、RpoRisk=true，公开行情出现对应 Maker 成交。当前正在正常替换 B、追平和自动 Home 回归，最终物理文件及全财务验收仍待完成。
- 连续控制器按实际门禁依次执行 Trade A TERM 同等大前缀、Order B TERM/ORDER_ONLY、Order A KILL/带资金，之后严格下单撤单和 Robot 10/50/200 压力。前一阶段失败会停止后续故障及压力，需定位修复后接续。正常双节点异步仍未接线，当前单节点 LOCAL 测试不列为其验收。

## 2026-11-11 23:36 新镜像 Trade B 完整通过

- ha-trade-b-kill-mcw4ejhq 最终 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS。原进程实际退出 137，全部 LOCAL 接管 317.047 秒，替换进程启动到全部严格 Home 回归 663.064 秒。256 对 LOCAL WAL 与 256 对恢复 Snapshot 一致，客户 API、MD、财务 cursor 及 predecessor 检查通过。
- 同一 QVQU6T Robot 进程贯穿故障，接管期间 9 轮、最大循环间隔 44.174 秒，回归期间 22 轮、最大循环间隔 30.398 秒。这些数值衡量 Robot 循环，持续成交间隔需单独测量。LOCAL 窗口另有真实 Tape 成交、精确单副本 Trade 提交以及成对资金 POSTING 的对应证据。其后新成交与先前阶段核对无重复。
- 反方向 Trade A TERM 已自动接续，ha-trade-a-term-zt_u632e。故障前真实提交 4105 次杠杆设置，P100/E4 投影 HEAD=4281，目标在 B 单节点期间再次核对客户最终回执及风险标记，随后严格追平、回归和全部业务一致性。
- 第二批旧轮转日志已完整压缩并回读校验，归档目录 t554-retired-log-archive-20261111-233400。RobotSvr.log.2026-11-03 和 AdminSvr.log.2026-10-26 原合计 3519896326 字节，压缩后 1223274946 字节，净回收 2296621380 字节。文件稳定性、内容 SHA 和归档 SHA 已记录，原文件经验证后释放。清理超过一天的未引用构建缓存回收 0 字节，超过一天的无标签旧镜像回收 88.31 MB。当前业务数据及带标签回退镜像保留。

## 2026-11-11 23:55 Trade 反方向大前缀完整通过

- ha-trade-a-term-zt_u632e 最终 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS。原 A 正常退出 143，B 全部 LOCAL 接管 268.061 秒，替换 A 启动到全部严格 Home 回归 590.489 秒。256 对 WAL 和 256 对 Snapshot 完全一致，客户 API、公开行情、全部财务 cursor 和 predecessor 验证通过。
- 受控租户故障前 P100/E4 HEAD=4281。A 仍停止时，在 B 的 P100/E5/235 真实提交后，两侧客户得到最终成交 E71849446f4cf15337ea67998bb886d / Eca5fdc0bea3ea300a672f5c07ac04c，两个回执均标记 LOCAL_DURABLE_ASYNC、QuorumDurable=false、RpoRisk=true，公开行情出现对应 Maker 成交。单节点窗口还验证了正常下单冻结和撤单释放。
- 同一 KZKHKH Robot 的 Trade 热分区 P078 原主 A，在 20/256 READY 时由 B/E5 接管。接管期间 9 轮、最大循环间隔 30.412 秒，回归期间 19 轮、最大循环间隔 30.699 秒。独立 LOCAL 窗口 5 个报价、5 次 Tape execution、5 个 Trade LOCAL 提交均对应原始成对资金 POSTING，回归后再次取得新成交并核对无重复。
- 当前正常镜像已完成两个方向 Trade 单节点最终成交风险标记和大于 4096 条历史提交的实际回放。Order B TERM/ORDER_ONLY 的 ha-order-b-term-34ppcs5h 已自动接续，接下来为 Order A KILL/带资金和严格压力门禁。正常双节点异步容量及高性能目标仍待完成。

## 2026-11-12 00:10 新镜像 Order B ORDER_ONLY 完整通过

- ha-order-b-term-34ppcs5h 最终 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS。原 B 正常退出 143，A 全部 LOCAL 接管 266.967 秒，替换 B 启动到全部严格 Home 回归 640.293 秒。256 对 WAL 和 256 对 Snapshot 一致，ORDER_ONLY 客户成交、公开行情、资金保持及财务 cursor 验证通过。
- 同一 Robot 热分区 Order P137 原主 B，在 18/256 READY 时已由 A/E3 接管。接管期 9 轮、最大循环间隔 30.907 秒，回归期 21 轮、最大循环间隔 32.521 秒。独立 LOCAL 窗口取得新报价及 1 次真实 Tape execution，对应唯一成对资金 POSTING，回归后再取得新成交并核对阶段间无重复。循环间隔只衡量 Robot 活动。
- Order A KILL/带资金已接续，ha-order-a-kill-7uyuwn2w，完成后按连续控制器进入六个严格下单撤单压力窗口，以及 10/50/200 租户 Robot 稳态窗口。

## 2026-11-12 00:28 最新正常镜像四项业务故障矩阵全部通过

- ha-order-a-kill-7uyuwn2w 最终 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS。A 实际强杀退出 137，B 全 LOCAL 接管 321.824 秒，替换 A 到全部严格 Home 回归 735.238 秒。256 对 WAL 和 256 对 Snapshot 一致，带资金客户成交、公开行情、完整财务 cursor 及 predecessor 验证通过。
- 原 KZKHKH Robot 的 Order 热分区 P057 在 79/256 READY 时由 B/E5 接管。接管期 9 轮、最大循环间隔 63.306 秒，回归期 24 轮、最大循环间隔 31.749 秒。独立 LOCAL 窗口 21 个报价及 1 次真实 Tape execution 对应唯一资金成对 POSTING，回归后另有新成交，阶段间无重复。
- 当前正常构建的 Trade B KILL、Trade A TERM、大于 4096 条真实提交回放、两个方向单节点最终成交风险标记，以及 Order B TERM/ORDER_ONLY、Order A KILL/带资金四项矩阵全部完成。各服务自动回到 A/B Home 128/128。仍使用同一 ea31 Common JAR，实际 ACK、Fencing、签名及文件一致性门禁均经过原生产入口。
- 已在 00:27:53 启动严格下单撤单压力。ORDER_ONLY 和带资金产品分别执行 1/4/8 个闭环客户端，每档 60 秒，统计 HTTP 下单 ACK、撤单 ACK 和完整可见闭环的样本数及 P50/P95/P99/P99.9，逐笔核对终态取消、零成交、资金回原值和无残余委托。压测环境为原 Mac Colima，8 vCPU、约 16 GiB 内存，现有 Robot 同时运行。该阶段未叠加独立 Common 故障程序。
- 恢复时间仍为分钟级，严格与正常双节点异步的高性能验收尚未完成。当前单节点 LOCAL 成功只覆盖其真实保证和风险标记。

## 2026-11-12 00:36 严格下单撤单六档完成，热点吞吐瓶颈仍存在

- order-cancel-capacity-674b4edb.json 完整通过，共 2089 个实际下单可见、撤单消失闭环。各档逐笔 SQL 订单取消、零成交、无残余委托、余额及冻结回到原值全部核对。活动 Robot 同时运行。
- 此压力使用同一受控租户 X4YGFC，每个产品各自落在单一 Order 热分区。表中吞吐为完整闭环每秒数，单闭环包含一次下单、一次撤单和可见性查询，不能把它视为全 256 分区的总容量上限。

| 产品模式 | 并发 | 闭环样本 | 闭环/秒 | 下单 P99 ms | 撤单 P99 ms | 下单 P99.9 ms | 撤单 P99.9 ms |
|---|---|---|---|---|---|---|---|
| ORDER_ONLY | 1 | 283 | 4.709 | 269.567 | 365.928 | 353.486 | 510.694 |
| ORDER_ONLY | 4 | 452 | 7.495 | 687.783 | 506.539 | 842.875 | 580.374 |
| ORDER_ONLY | 8 | 456 | 7.498 | 1291.206 | 1031.548 | 1652.991 | 1449.396 |
| 带资金 | 1 | 232 | 3.858 | 96.201 | 272.231 | 120.856 | 668.615 |
| 带资金 | 4 | 325 | 5.372 | 577.137 | 796.677 | 737.630 | 1061.812 |
| 带资金 | 8 | 341 | 5.580 | 917.719 | 960.816 | 993.011 | 1022.172 |

- 每档样本少于 1000，最近秩 P99.9 在这些窗口等于最大值，需保留样本数解释。4 到 8 并发吞吐几乎不再增长，尾延迟上升，热点分区压力已显现。功能正确性通过，当前时延仍不足以验收高性能目标。
- 另读取原始 Common 控制清单，与最近一轮已通过 HA 的最终清单逐分区比较。六档结束后 Order/Trade 均仍为 signed generation 2562，512 分区的 Epoch、policy、角色和 READY 状态与压力前相等。中途和结束观察的 census SHA 一致，排除本轮默默切到 LOCAL 后再恢复的模式混淆。证据 strict-pressure-census-after-first-three-phases.json、strict-pressure-census-after-all-six-phases.json。
- 10 租户 Robot 五分钟稳态已启动，后续为 50/200 租户。下单撤单脚本在本轮退出后新增可选 --mode / --concurrency 选择，默认六档行为保持，便于后续重复单档诊断。参数帮助及语法检查通过，选择性实机诊断待执行。

## 2026-11-12 01:20 10 租户通过，50 租户压力 NO_GO，并发隔离通知刷新存在饥饿

- robot-steady-10-164116.json 通过，五分钟内 10 个活动租户、691 个报价请求、624 个 Tape 请求、623 次最终 Tape execution，2.077 次成交/秒。Trade 入口至 Order 最终成交发布的 621 个配对时延样本，P50/P95/P99/P99.9 为 174.594/367.445/462.958/699.754 ms。最大逐租户成交空窗 11.532 秒，成对资金 POSTING 和财务 cursor 核验通过。此指标为服务间实际日志时间差。
- robot-steady-50-165703.json 保留 NO_GO。15 分钟预热结束时 H5W957、HJ96AE、N4ZVYJ、SXB8KU 仍为 WAITING_MARKET_DATA，没有取得合格五分钟稳态窗口。末尾五分钟实际观察有 4048 个报价请求、1601 个 Tape 请求、1230 次最终成交，4.1 次/秒，1223 个配对时延样本的 P99/P99.9 为 6548.785/8046.632 ms。只有 37 个租户在该资金窗口有 POSTING，最大成交空窗 300 秒。所有已观测 POSTING 均成对，完整财务 cursor 仍 PASS。该观察不能列为 50 租户稳定容量通过。
- 50 租户继续运行期间发生物理提交超时。实际 00:58:04 已出现 CUSTODY_INSTALL_AND_REPLICA_LEDGER 阶段失败，00:58:14 出现 INDEPENDENT_WAL_FSYNC_RECEIPTS 阶段失败，随后出现分区隔离、控制清单变化和业务拒绝。旧日志归档从 00:59:00 才开始，归档阶段不作为干净压力窗口，不能用其后的诊断结果归因之前的容量窗口。
- 已通过正常 ManagerSvr robotControl STOP 接口停止本轮额外新增的 40 个压测 Robot，仅保留最后通过的 10 租户集合。用户和资金持仓数据保留，证据 pressure-50-reduce-to-passing-cohort.json。部分停止动作因当时分区隔离而记录 ERROR，实际委托取消和本机完整恢复尚需修复后重新核验，不能把 enabled=0 当作委托已清空。200 租户未启动。原依赖控制器已如实记录 50 档退出 2 后结束。
- 对当前 Order A/B 仅读取既有恢复 Runner 拒绝摘要及控制线程队列，没有更改 Common 运行字节码。实际 pendingPoison，A 为 P042/E7、P118/E7，B 为 P137/E7、P248/E7、P149/E7、P135/E7、P172/E7、P229/E7。前两项队列观察分别由 succeeded=4144/6683、failed=7/8 的正常续约线程取得。恢复拒绝为 Common poisoned marker exact old manifest/RSA claim mismatch。
- ZooKeeper 原始签名通知印证刷新饥饿。P042 和 P137 的 256 字节 RSA 通知已刷新到清单版本 2571，同期 P118 仍绑定 2564、P135 仍绑定 2561。现有 NodeClusterControlManager 每个控制周期只发布 ConcurrentHashMap 中首个有效条目，并将该条目保留到角色改变，导致其他并发隔离分区的通知无法随共享清单更新。恢复方保留了原有严格拒绝。
- 新增 pendingPoisonRefreshRotatesEvenWhenTheFirstShardKeepsFailing 回归测试，旧生产代码实际失败，6 次控制续约一直服务同一条目。修复在原控制线程内按分区 ID 轮转，每轮仍最多一次真实 RSA/ZK 发布，失败也让出下一轮，角色改变后仍清除旧项。原通知字节、RSA、原节点会话、全清单版本、Epoch、物理 ACK/Fencing 和恢复流程保持既有校验。NodeClusterControlManagerTest 11 项和 CommonCertifiedPoisonedPrimaryNoticeTest 10 项全部通过。
- Common 修复提交 cbe1d2850cac2fdaac7a0001c7d5e35f1728a0bd，工作树已干净。新候选 t554-common-candidates/20261112-011857，JAR SHA 4793eecc9b219bc10d6236522557e3018732bd6a22f7730a97048df02a35c87f。完整独立 P0、签名快照、8 项真实进程故障和 256 分区双强杀、重复回主及中断 Stage 门禁已启动，结果待完成。新候选未进入业务容器。现役业务仍为原 ea31 Common。
- 一次候选构建因 Git 提交身份未配置而错误读取旧 HEAD。已停止该构建的全部自有进程，目录 20261112-011748 标记 ABORTED_WRONG_REVISION，完整记录保留，新修复验收排除该目录。随后使用仓库既有 Assistant 提交身份完成提交，并按精确 cbe1d285 SHA 重新构建。
- 已完整归档 68 份原已停止旧 Demo 容器日志，共释放虚拟机 2528512917 字节，清单 t554-retired-demo-log-archive-20261112-005900/manifest.json。每份均核对停止身份、源大小和 SHA、完整解压内容及归档 SHA，持久化清单后再截短源日志。当前代和本轮故障保留容器的日志不在该清单，业务 WAL、快照和数据库保留。虚拟机目前约 4.6 GiB 可用，尚未执行扩容或 fsck。
- 当前总体仍为 NO_GO，四项已通过的业务故障矩阵保留其原结果，性能压力暴露的问题另行验收。正常双节点异步仍未实现，Order 网络回执处理线程上的同步物理提交也待独立诊断，不能把已有八条 WAL/持久化控制 TCP 通道误认为只有一条连接，更不能直接再加一套复制通道。

## 2026-11-12 01:44 新通知调度实进程红绿通过，完整门禁继续

- 新候选 4793eecc 的 29 类安全测试共 170 项全部通过，124.068 秒，实际使用候选 JAR 作为唯一优先生产类来源。包含物理 WAL、CommitIndex、Custody/Receipt、严格及 LOCAL ACK、授予隔离、控制线程、签名通知、原始 Home、归档读、真实 Netty 和角色切换门禁。结果在 20261112-011857/safety.log、safety.status、safety-tests.list。
- 新增真实 ZooKeeper、独立 A/B JVM 和真实 TCP 的阻塞通知用例。观察者以自己的会话预占两个通知路径，不具备原节点会话/RSA 证明，随后仅释放非首项，要求其在另一项仍被拒绝时独立追平、自动回到 Home 并完成真正严格业务 ACK，再释放剩余通知。源端不确定 WAL 尾部保留，READY 和授予仍由 Common 自动流程完成。
- 同一新用例使用原 ea31 JAR 实际失败，60.525 秒，非首分区无法取得 Home 业务证明；改用候选 4793eecc 实际通过，19.907 秒，输出 blocked=P001 recovered=P000。证据 t554-poison-notice-regression-20261112-012719 下 red/green 日志及两组完整公共物理文件。此时间差用于证明有无进展，不能当作正常恢复性能对比。
- 第一次完整门禁 20261112-011857 的 8 个独立进程用例中 1 项失败。整节点租约测试中回归 B 再次超过 3000 ms 租约，3862 ms 时真实退出 78，原结果保持 NO_GO。该轮与上述安全测试同时运行，尚不能据此单独认定超时原因。
- 第二次完整门禁 20261112-013031 的 9 项中 1 项失败。原租约用例通过，但正常关闭用例的 A 测试进程在 Home 提交后遇到临时证明拒绝，测试循环再次提交同一业务阶段，后续断言期望 6 字节却见到 9 字节而退出。源代码确认测试阶段把提交及之后的归档证明放在同一重试分支，提交后的 IOException 会重发新 WAL 命令。该失败保留，未放宽生产 ACK 或状态断言。
- 测试器现在根据已由 Common 应用的精确目标状态幂等地重试证明，归档、签名、当前授予和快照校验继续全部执行。新增阻塞通知用例中还确定性注入真实 Home 提交返回后的证明重试，要求完成证明且业务阶段只应用一次。仅修改测试夹具，生产 JAR 仍为原 cbe1d285 / 4793eecc。
- 当前夹具提交 42ce8ad675ede35d191b4d2084c899ad31b9498d，与生产候选的 pom.xml、src/main 全部一致。第三次完整门禁 20261112-014140 已启动，源 SHA、实际 JAR、9 个独立进程用例及后续 256 分区双强杀/重复回主/中断 Stage 全部重新执行，结果待完成。业务容器尚未部署新候选。
- 封存器已把 blocked-poison-notice 的实际进程目录、真实公共物理文件及独立 Home ACK 结果纳入新夹具的必需证据，原 3 项封存器单测通过。Common 候选构建入口另新增 HEAD 未提交源/测试检查，暂存、未暂存、新文件 3 个子场景均验证会在创建候选前退出，防止此前构建旧 HEAD 的错误再次被当作最新代码验证。

## 2026-11-12 02:16 九项进程门禁通过，业务回执接收线程阻塞已有修复候选

- 20261112-014140 的 9 项真实进程门禁全部通过，439.306 秒，包含新阻塞通知场景、整节点过期真实退出 78 和认证回归、正常退出 143、重复隔离及各类进程返回。当前正在执行完整 256 分区双向强杀、重复 Home 和中断 Stage 的后续门禁，已输出扩展签名 Genesis、并发归档读、两种持久化目录布局、LOCAL 前缀和中断 Stage 恢复的通过标记，完整 P0 尚未封存。
- 新用例的父 JUnit 进度点会与业务结果打印在同一行。封存器已同时接受有进度点和无进度点的精确结果行，仍限定一次结果以及 P000/P001 不同分区。4 项封存测试通过，并使用本轮真实 9 项日志验证结果提取，避免完整长演练结束后因日志格式误报失败。
- 50 租户失败后的真实 Order A 线程采样保存在 pressure-50-diagnostic/order-a-jstack.txt。其中 ReadProtoProcess 网络接收线程直接执行 DurableWalCustodyReceiptLedger.persist 的物理 force，另有多个业务线程等待独立 Custody/Receipt RPC。已有 8 条 WAL 与持久化控制 TCP 分道，已核对源码，未增加第二套通道或放宽物理确认。
- OrderSignedMatchDeliveryWorker 的 Trade 回执回调现只校验基本返回字段并保存不可变签名字符串，然后交给原有两个线程、1024 队列上限的派送线程池。签名与精确原 Order 来源验证、第二次真实 Common WAL、持久 ACK/Outbox 退役和最终客户/MD 发布仍按原顺序执行。队列关闭或满时保留原 WAL 待办，原重试扫描继续工作。
- 新增网络线程阻塞回归。修复前实际失败，断言 network receive thread waited for the physical receipt WAL。修复后 13 项 Worker 测试通过，覆盖慢物理提交时接收线程返回且最终成交尚未发布、队列满后原待办保留及原扫描恢复、关闭队列不伪造成功、错误来源/签名拒绝、LOCAL 原始风险字段和原通知丢失后的扫描恢复。
- 独立构建 order-receipt-dispatch-build-20261112-015752 完成 Order 183 项测试，通过 181 项、保留原有 2 项跳过。该业务单测候选复用已验证 ea31 Common 与 f1f8 Shared 字节，源码完整清单 SHA 68824bf4ca2194fe93ab11609e13c2f3f1001c0a2b134fdcd817bf4f5c153649，记录 verification.json。候选尚未部署，实机时延改善待后续同代窗口测量。
- 压力门禁已增加源清单 generation 的窗口前后记录。严格下单撤单、Robot 稳态和无故障突发窗口只有控制 generation 保持不变才可通过，故障突发仍要求原物理故障证据。避免将中途切换后返回的混合窗口误作正常稳态。此前六档历史结果已有额外实际 generation 不变证据，不追改旧结果。
- 活动负载清单现在只统计 enabled=1 的 Robot，故障状态 ERROR 仍计入。实际只读回查确认额外 40 个压测 Robot 通过正常接口禁用后，保留的 10 个身份完整相等，未隐藏故障状态或删除租户数据。当前旧代仍有错误 Robot，整体恢复保持未完成。
- 连续依赖控制器 /tmp/mac-t554-fairness-after-p0.py 已启动，只在精确 4793eecc JAR 的完整 P0 封存 PASS 后才继续。计划随后完成旧主机轮转日志归档、正常一键构建及 fresh 基线，再对新 JAR/新业务类完整执行四项故障矩阵、严格下单撤单、10/50/200 稳态和两倍突发。后续压力结束或失败后，通过正常管理接口停止额外压测 Robot，保留最后通过的 10 个身份及全部数据。正常双节点异步仍待实现和独立门禁。

## 2026-11-12 02:50 新 Common 完整封存及原 Mac 新代业务复验

- 精确生产候选 cbe1d285 / Common SHA 4793eecc9b219bc10d6236522557e3018732bd6a22f7730a97048df02a35c87f 的完整 P0 已通过并于 02:27 封存，目录 t554-common-verifications/20261112-014140。9 项真实独立 JVM 故障用例共 439.306 秒，完整 256 分区用例 2234.162 秒。196637 字节签名快照经真实有界 TCP 和冷重开验证。双向强杀、第三次全分区 LOCAL、重复严格 Home、中断 LOCAL→STRICT Stage、跨 Epoch 前缀以及 256 WAL 与 256 快照物理配对全部通过。此前 170 项安全测试的通过结果单独保留。
- 完整用例中 A 接管 242121 ms、回 Home 498315 ms，B 接管 261007 ms、回 Home 429155 ms。这是该次实际恢复记录，生产 RTO 和资源条件受控的性能对比仍待验收。
- 原 Mac 正常一键 fresh-verified 已部署唯一业务代 mac-demo-20261112-022723，旧代正常停止且数据保留。构建 127 秒，启动和物理/业务基线 401 秒，其中真实业务基线 86 秒。精确 Shared SHA 666c047cfdb022938d6e30263c0f0b8e0428114b7b4f6d0b8ebe8dd7faec8dc6，源码 revision 04bd45b592511c9177c9b954234f8dc557e49406。Order 镜像 local/otc-mac-demo-order:4793eecc9b21-666c047cfdb0-f2b5a7f19dbd，Trade 镜像 local/otc-mac-demo-trade:4793eecc9b21-666c047cfdb0-f453c646b26d，均为正常源码构建，新代未进行运行时热替换。
- ORDER_ONLY 租户 QFN4K3 的真实成交、MD 对应及资金保持通过，资金交易租户 I7IDRI 的双方成交及结算通过。Robot 2 个持续运行，80 笔报价、9 条实际 Tape 成交报告，POSTING 配对无异常，认证 Trade 游标与资金持仓核对通过。新代四项故障矩阵仍在继续。
- 首项 Trade B SIGKILL 带 4105 条真实 Trade 命令前缀正在执行。单节点期间已观察到实际成交回执和持续 Robot 成交，物理备节点正在自动追平、回 Home，完整结果待通过后再记录。
- 02:27 归档并完整读回 Login 2026-10-27 与 Trade B 2026-10-24 两份旧日志，共净释放主机 2058821290 字节，清单 t554-retired-log-archive-20261112-022715/manifest.json。当前虚拟机仅约 3.2 GiB 可用，已停止旧卷 otc-t529-fresh-mysql-data 占约 7.2 GiB。后续测试调度暂挂，当前故障子进程与业务继续运行。待当前用例结束后完整归档并核验旧卷，再释放其已归档数据。当前代业务数据保留，扩容及 fsck 尚未执行。
- 新代严格性能待四项故障完成后重测。正常双节点异步仍待实现和独立门禁。

## 2026-11-12 03:09 新代 Trade B 全项通过，旧卷完整归档释放

- ha-trade-b-kill-kq_5xiis 全项完成，状态 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS。真实退出 137，全部 256 分区单节点接管 331.558 秒，替换后严格 Home 645.495 秒，最终 256 WAL 与 256 快照内容相同。单节点实际结算坐标 P118/E3/46，Maker/Taker 最终回执明确 LOCAL_DURABLE_ASYNC、QuorumDurable=false、RpoRisk=true，备节点返回前已有匹配公开 MD。同一 I7IDRI Robot 在全接管期间 11 轮最大循环间隔 30.343 秒，返回期间 22 轮最大 30.886 秒。完整单节点窗口另有 3 次真正 Trade 提交、3 笔 Tape execution 与 POSTING 配对，恢复全财务核对通过。
- 已完整归档旧停止 MySQL 卷 otc-t529-fresh-mysql-data 的 226 文件、235 条目，源实际分配 7731580928 字节，归档 844136616 字节。归档 SHA 624a018456b51db17e08acd9f208ef2a49d4c2c4240519c7c7bc808570af17b8，目录 t554-retired-mysql-archive-20261112-024650。全部文件内容、权限、uid/gid、路径树、硬链接及完整 gzip 读回核对后，释放前再次逐文件核对 SHA/源身份并确认唯一旧容器已停且 restart=no、没有运行进程挂载。cleanup.json 先持久化意图再清理，完成状态 CLEARED_WITH_VERIFIED_FULL_ARCHIVE。旧容器保留，旧数据可由归档还原，当前代数据保留。
- 虚拟机可用空间从约 2.8 GiB 恢复约 10 GiB。fstrim 返回 12186447872 字节，主机可用约 15 GiB。释放后实际回查 Order/Trade 全 256 READY STRICT，清单 generation 分别 2/1282，全财务游标通过。三名启用 Robot 在上游连接重连后均恢复 RUNNING，后续测试调度已恢复，检查点 storage-maintenance-checkpoint.json。未执行虚拟机扩容或 fsck。

## 2026-11-12 03:27 新代 Trade 双向单节点及回归均通过

- ha-trade-a-term-8otqtzev 完成 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS。A 正常结束退出 143，B 接管全 256 分区 264.592 秒，替换 A 后严格 Home 582.572 秒。最终 512 项 WAL/快照物理配对无差异，全财务认证游标通过。
- A 仍停止时，真实结算 P173/E6/61 已向 Maker/Taker 发布最终回执，均带 LOCAL_DURABLE_ASYNC、QuorumDurable=false、RpoRisk=true 和该原始坐标。整个备节点离线窗口的客户资金、持仓及公开成交均通过。原 Robot 的 P118 在仅 120/256 分区完成接管时已取得 LOCAL 授予，全接管期间 8 轮最大循环间隔 46.933 秒，回归期间 19 轮最大 30.313 秒。全 LOCAL 窗口另有 6 笔报价请求和 8 次实际 Tape 成交，完整配对保留。
- 新代两个方向 Trade 物理回归与单节点最终成交已通过，Order B TERM / ORDER_ONLY 已自动接续。硬件实测为 Apple M4、主机 arm64、Colima aarch64、8 vCPU、16732614656 字节内存，当前 Order/Trade 镜像均 Linux arm64。每个物理投票容器限制 1.7 CPU、2 GiB，Robot 限制 0.75 CPU、1 GiB，MySQL 限制 0.5 CPU、1.5 GiB，后续压力按该实际资源条件记录。

## 2026-11-12 03:43 新代 ORDER_ONLY 故障回归通过

- ha-order-b-term-oi77yvh9 完成 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS。真实退出 143，全部分区 LOCAL 接管 259.595 秒，替换后严格 Home 575.880 秒。ORDER_ONLY 单节点实际成交、撤单、资金保持及公开行情核对通过，最终 256 WAL 与 256 快照无差异，全财务认证游标通过。
- 同一 Robot 在接管期间 9 轮最大循环间隔 31.858 秒，返回期间 19 轮最大 31.005 秒。全 LOCAL 窗口取得实际 Tape execution 及配对。最后一项 ha-order-a-kill-t8xidopk 已自动开始，携带真实资金交易及持续 Robot。完成后依次运行严格下单撤单和容量门禁，当前总体性能验收仍待完成。

## 2026-11-12 03:58 新代四项故障矩阵通过，严格压力开始

- ha-order-a-kill-t8xidopk 完成 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS。A 真实强杀退出 137，B 全 256 分区接管 304.192 秒，替换后严格 Home 582.664 秒。带资金的单节点成交、撤单、持仓、公开行情与最终财务认证游标通过，256 WAL 与 256 快照配对无差异。同一 Robot 接管期间 10 轮最大循环间隔 31.603 秒，返回期间 19 轮最大 30.829 秒，全 LOCAL 窗口有实际报价及 Tape execution。
- 至此精确 Common 4793eecc、Shared 666c047c 及正常源码构建业务镜像的四项故障矩阵均通过，原始完整证据保存在本代四个 ha-* 目录。后续性能尚待完成，正常双节点异步仍待开发和完整门禁。
- 严格下单撤单于 03:56 开始。首档 ORDER_ONLY / 并发 1 的 60.078 秒窗口完成 453 个闭环，7.540 个闭环/秒，下单 P50/P99/P99.9 为 48.944/103.467/150.057 ms，撤单为 62.914/179.033/477.326 ms，全部撤净、无执行，余额保持。窗口前后 Order/Trade generation 均为 2562/2562。该档样本少于 1000，最近秩 P99.9 等于最大样本，完整六档仍在运行。测量范围是 HTTP 下单成功返回及撤单确认、New/消失查询闭环，另有真实 Robot 背景流量。

## 2026-11-12 04:05 严格六档通过，补齐状态可观察时延

- order-cancel-capacity-2e800480.json 六档全部通过，共 2920 个真实下单/撤单闭环，全部无剩余挂单、无成交、资金恢复原值。ORDER_ONLY 并发 1/4/8 吞吐为 7.540/9.558/11.267 个闭环/秒，资金交易为 5.437/6.781/7.828，所有窗口前后 Order/Trade generation 均为 2562/2562。原样本和完整资源记录保留。
- 上一节及上述文件中的 place_ack_ms、cancel_ack_ms 对应 HTTP 成功返回时间。脚本确实等待 New 和撤单消失后才计入通过闭环，但原统计缺少这两个状态的独立延迟。完整下单状态延迟和撮合提交延迟尚不能从 HTTP 返回值直接确定，原字段继续保留其原语义。
- 已补入 place_new_ms 与 cancel_absent_ms，从原请求起点计时直到经过客户认证的查询首次观察到目标状态，新增字段说明和原 50 ms 查询重试周期。此结果包含查询请求及观察等待。新增确定性回归以 20 ms HTTP 返回、50 ms New、30 ms 撤单 HTTP 返回、70 ms 消失分别验证。旧脚本实际失败为缺少 place_new_ms，补齐后通过，脚本编译通过。
- 当前脚本已结束后才修改，原结果完整保留。后续压力调度短暂挂起，业务进程继续运行，同一代际正在重新执行六档并同时记录两类确认点，日志 /tmp/mac-t554-fairness-strict-full-state-order-cancel.log。该轮结束后接续 10/50/200 Robot 容量。

## 2026-11-12 04:14 完整状态确认六档通过，Robot 容量接续

- order-cancel-capacity-2f71738d.json 六档全部通过，共 2865 个真实闭环，全部撤净，无成交、资金恢复原值，所有窗口前后 Order/Trade generation 均为 2562/2562。此表为从请求到经客户认证查询首次观察到状态的实际时间，包含 HTTP 查询及 50 ms 重试等待。各档样本少于 1000，最近秩 P99.9 等于各档最大样本。

| 业务模式 | 并发 | 样本 | 完整闭环/秒 | 下单至 New P99 ms | 撤单至消失 P99 ms |
| --- | --- | --- | --- | --- | --- |
| ORDER_ONLY | 1 | 482 | 8.024 | 150.014 | 137.950 |
| ORDER_ONLY | 4 | 636 | 10.559 | 544.549 | 361.660 |
| ORDER_ONLY | 8 | 611 | 10.113 | 799.905 | 525.075 |
| TRADE | 1 | 320 | 5.333 | 184.753 | 153.865 |
| TRADE | 4 | 402 | 6.659 | 770.860 | 482.204 |
| TRADE | 8 | 414 | 6.801 | 1200.958 | 682.425 |

- 单租户每产品一个热 Order 分区，闭环吞吐在并发 4→8 基本持平，状态观察尾延迟继续上升。整套多租户持续成交和正常异步性能仍待测量。上一轮 2e800480 的实际 cgroup 两点窗口差分中，四个投票容器的 6 档 nr_throttled 增量均为 0，每档采样跨度约 33 秒，不能从累计限流数推断该窗口 CPU 配额为瓶颈。
- 04:13 恢复原依赖调度，strict-robot-10 已开始，随后按门禁推进 50/200 和突发。补测结果及脚本 SHA 保存在 full-state-order-cancel-checkpoint.json。所有临时挂起的调度均已恢复，业务进程持续运行。
- 已将本轮已实测、与正常构建副本逐字相同的 Shared 两个源/测试文件归档为 saas-crypto 本地提交 5d12c4f9b7ef59333ffbc4ea82b2ccec30ff11ff。正常构建副本的 Shared 51 项测试全通过。当前运行镜像仍为已封存构建的原字节和原构建时 revision 记录，后续提交仅归档已部署源，无重新部署。其他仓库未提交改动保留。

## 2026-11-12 04:17 容量租户登记观察修正，原代际接续

- 第一次 strict-robot-10 在申请新增租户后 4 秒内退出，原因是脚本立即要求启用 Robot 清单恰好多出该审批身份。原异常及调度失败保存在 /tmp/mac-t554-fairness-strict-robot-10.log 和原 after-p0 日志。该次未进入五分钟计量窗口，未生成容量 PASS。之后实际只读回查唯一 T554_CAPACITY_20630dd439c31b27 为 APPROVED / MPBGXI，9 个已启用 Robot 全 RUNNING，保留原已批准身份。
- enroll 现在仍要求申请返回明确 APPROVED 及唯一合法新身份，但给该身份的启用 Robot 记录最多 60 秒观察窗口。等待期间只允许原清单保持相同，新增其他身份或原身份消失立即失败，超时退出且不重发申请。包含旧 ERROR Robot 在成员清单中的行为保持。新增 3 项回归，覆盖批准返回后登记稍晚、无关新增身份拒绝和超时不重复申请。旧代码实际出现 1 失败、1 错误，新代码 3 项通过，下单撤单计时回归也再次通过。
- 原调度已退出，已通过新的依赖控制器 /tmp/mac-t554-fairness-pressure-resume.py 在同一业务代接续 10/50/200 及突发，旧已批准租户计入当前清单，不重建环境，不重复故障矩阵。新日志 /tmp/mac-t554-fairness-pressure-resume.log。通过的最后 10 身份仍用于压力后正常管理接口停止额外负载。

## 2026-11-12 04:22 新代 10 Robot 五分钟严格稳态通过

- robot-steady-10-202147.json 为 PASS，窗口 04:16:47–04:21:47，共 10 个启用 Robot。632 笔报价请求、637 笔 Tape 请求、635 次实际成交，2.117 次/秒。635 个配对样本的 Trade ingress→Order 最终成交发布 P50/P95/P99/P99.9 为 141.629/261.226/351.293/451.105 ms，各租户最大成交间隔 11.130 秒。
- Order/Trade generation 窗口前后均 2562/2562，全部启用 Robot 为 RUNNING，真实 POSTING 配对与认证资金、持仓游标核对通过。完整资源样本和每个租户的成交间隔均保留。该窗口为服务间实际成交发布时延，客户请求到回执和完整撮合容量需分别按其实际观测点解释。
- 50 Robot 阶段 04:22 已自动开始，扩充租户使用正常申请/自动审批及 Robot 启用，当前更高负载结果待完成。

## 2026-11-12 05:03 50 档 NO_GO，MD 风险价格推送缺陷已复现并修复源代码

- robot-steady-50-204210.json 保留 NO_GO。正常申请扩充到 50 后，15 分钟预热结束仍有 HPWY6L、IIA7JZ、NSVW6X、YPQ6UX 未进入 RUNNING，未取得合格五分钟稳态窗口。最后五分钟的观察值为 1173 次实际成交、3.910 次/秒，1142 个配对样本的 P99/P99.9 为 14356.685/176120.939 ms。该观察值属于未通过预热后的负载现场，50 档容量未通过，200 档未启动。
- 本次 Order/Trade 清单始终 2562/2562，实际四节点全 256 READY STRICT，未发生新增 Common 隔离或恢复转换。高负载结束时 10 个资金投影水位与来源不一致，保留原 NO_GO。正常管理接口 STOP 额外 40 个压测 Robot 后，保留原通过的 10 个身份且全部 RUNNING。04:49 同一全量核对变为 PASS_FINANCIAL_CURSOR，45 个水位差异全部为 0，业务数据保留。
- 预热期间实际保存四个投票节点线程采样及原 Robot JVM 线程报告，目录 pressure-50-warmup-diagnostic-042705。Order 两节点各 14 个 ReadProtoProcess 均无物理 force 栈，真实回执提交已位于原 order-committed-match-delivery 工作线程，符合前述网络回调修复。采样发生在合格窗口之前。Robot 由 docker-init 启动，线程诊断选取了实际 Java 子 PID 并核对原进程 starttime。未替换运行类。
- 实际拒单原因定位为 Trade UpdateOrderHandler 返回 MARKPX_NOTEXIST / 5003，同一一分钟取样 150 次。部分 Robot 虽然仍显示 WAITING_MARKET_DATA，已经持续取得新鲜 BBO 并发出报价，源码该状态仅在完整报价收敛后才改为 RUNNING，不能根据该状态直接判断外部行情全断。VU4L79 实际认证查询出现 92 笔活跃报价，20 个卖价、16 个买价，最后 4 个买价两分钟内各重试 6 次而未形成活跃单。数量精度和报价分档已只读核对。
- 对原进程现有缓存只读采样确认了价格失活。Trade 中 HPWY6L 的缓存价虽有值，但距最后更新 285924 ms，远超原 5000 ms 风控上限。MD 的共享 BTC 标记价仍实时更新，绑定目录含全部 50 租户、价格选择器启用、MD 为原单节点模式。原始共享 BTC 事件的 MarketIndicator 实际为 null。运行中 IndexFacade 的反编译确认其将这个 null 传入 publishTenantEffectiveMarkPrice，而该入口先检查 market==null 后直接返回，未进入已有的 MD 默认市场及物理归属校验，导致连续推送遗漏。
- 普通 queryPublicMarket 查询取得真实币安标记价并触发一次缓存刷新，HPWY6L 在后续 60 秒仍未收敛，原观察 one-normal-md-read-observation.json 保留。它验证了一次查询刷新不足以替代连续价格流，未注入价格或成交。全部诊断代理仅反射读取已存在对象与普通 getter，未注册类转换器，原物理 ACK、授予、会话和数据保持原机制。
- MD 正式源码使用既有 .work/t446-md-price-independent。新增缺失市场字段回归，旧代码实际失败 expected 1 but was 0。修复去掉该冗余空市场提前返回，继续由原 MdPartitionRuntime 按已有默认市场处理并执行原归属隔离，原产品绑定、来源选择、数据时效及发布路径保持既有规则。完整 MD 204 项测试全部通过，提交 25153545d3e05998053914d3abd05674cc2c06a2。
- 另有 40 条真实 keyed MDSvr trade image failed / partition is not routable 警告，源为 Shared 的 MDSvrClient 在 MD 分区集群关闭时仍强制查询分区表。现按既有 PartitionConfig 开关使用原单节点逻辑服务，同时保留认证的租户 routing key。旧测试实际失败 SERVER.MDSvr 与 SERVER.MDSvrA 不符，修复后 Shared 52 项全部通过，无跳过，提交 010038a35967acbd8c9af45c0e5930564e1ebfc6。
- 一键 fresh-verified 现增加本次 MD 正式源码的正常构建，复用原 build_service、源文件清单、测试和镜像校验。MD 镜像也须在切旧代前核对与本次 Common/Shared 完全相同的 JAR 标签及实际字节。旧构建目录没有 md_IMAGE 时保留原调用方式。新修复尚未安装至业务进程，Common 候选仍为已完整封存的 4793eecc，正常双节点异步仍待开发。

## 2026-11-12 05:29 压测残单撤净，新 MD 价格镜像进入正常部署

- 原 STOP 返回后实际仍有残单，36 个禁用 Robot 保留 CANCEL_FAILED 历史状态。通过原认证 API 对本次自有压测身份逐户查询和撤单，第一轮处理在批次拒绝时跳出了整个账户，两个原清理报告均保留 NO_GO，涉及 7 个未确认账户。清理器改为继续处理独立批次并基于实际剩余订单重查，完整重查 40 个账户全部观察到 0 挂单。最终报告 pressure-disabled-quote-cleanup-retry-20261112-051925.json 为 PASS，未修改原错误状态、资金或持仓记录。
- 05:28 再次检查原代全 256 分区 READY STRICT，清单 2562/2562，保留原通过的 10 个 Robot 且全部 RUNNING，完整资金与持仓认证游标核对通过。检查点 pre-md-price-deployment-checkpoint.json。后续调度在该检查点通过后才进入部署。
- 新正常构建目录 mac-demo-build-20261112-051209-md-price 已完成，共 664 项业务测试，662 项通过、保留 Order 原有 2 项跳过。Shared 52、Trade 225、MD 204 全部通过且无跳过，Order 183 项中 181 通过。精确 Common 继续 4793eecc9b219bc10d6236522557e3018732bd6a22f7730a97048df02a35c87f，Shared 为 3bfdcdabd2b14a6abe30e47df2b6f8209c8cb6b50b6c62e34cde29fd03aa8796。MD 镜像 local/otc-mac-demo-md:4793eecc9b21-3bfdcdabd2b1-8473f93141ea，正常源码构建并完成 JAR 实际字节校验。Order/Trade 源清单指纹仍为 f2b5a7f19dbd / f453c646b26d，Shared 更新为上述已测试客户端修复。
- 使用正式 build-mac-demo-core.sh 构建后，已通过正式 mac-colima-saas.sh fresh BUILD_DIRECTORY 接续部署，日志 /tmp/mac-t554-md-price-fresh.log。新控制器 /tmp/mac-t554-md-price-after-build.py 在新代真实物理和业务基线完成后验证 MD、Order、Trade 的 Common/Shared 实际字节，再依次执行完整状态确认的六档下单撤单、10/50/200 Robot 和突发。压力结束后正常 STOP 额外自有身份，并增加实际挂单消失检查。
- 已另外完整归档 48 份已停止旧代容器日志，共释放虚拟机 1991475711 字节，清单 t554-retired-demo-log-archive-20261112-050345/manifest.json。当前代日志排除在外，逐份核验停止身份、原内容及完整解压 SHA，清单持久化后再截短旧日志。fstrim 返回 7479025664 字节，部署前虚拟机约 6.7 GiB、主机约 11 GiB 可用。扩容及 fsck 仍未执行。

### 2026-11-12 05:53 新行情镜像业务基线失败及回滚冷启动阻塞

- `mac-demo-build-20261112-051209-md-price` 构建成功，664 项测试中 662 通过、2 项原有 Order 跳过，含 MD 204 和 Shared 52 项全部通过。该结果不能代替真实部署验收。
- `mac-demo-20261112-052943` 业务基线两项均未通过。ORDER_ONLY 未看到自定义 mark，funded 测试报 `Current source quote was not received by MD`。部署工具已自动保留失败代并回滚 `022723`。新行情镜像仍为 NO-GO，尚未开始新代 10/50/200 稳态压测。
- 回滚后实际资金持仓投影核验通过，45 个 watermarks 全部一致。但 10 个 Robot 为 ERROR，Order A/B 冷启动反复退出。ZooKeeper 上保留的 256/256 READY STRICT 静态记录不能证明 JVM 已恢复业务。
- 原盘只读结构检查显示，Order P114/E7 的 A/B WAL 各 9342 条，两个 custody HEAD 均 9341。B 上历史 P133/E5 另有 514/513，尚未认定为当前启动阻塞。所有完整物理尾部保留。
- 同一生产 Common 入口的新真实双 JVM 回归先经过正常签名恢复和 Home，再停止 A/B、在两份 E4 WAL 各保留一条已落盘但未签名确认的尾部，随后冷启动。旧代码实际重现两边 `Common restarted Home WAL has no exact signed commit HEAD`，32.77 秒失败。旧代码确实拒绝重放未确认尾部，但整节点冷启动被阻塞。
- 正在修复通用 Common 冷启动对该分区的保留式隔离，复用既有签名 poison、Stage、物理 retirement 和严格恢复链路。尚未部署修复，须重新通过 P0 完整门禁。没有删除旧 WAL、补签旧 ACK 或强制修改 READY/Epoch。

### 2026-11-12 06:00 冷启动尾部修复进入完整 P0

- Common 源码提交 `3ec4b50`，候选 `t554-common-candidates/20261112-0557`，JAR SHA256 `2b19533e276da3382428b0aff26233d8078579b0f2bc46e8c1f07f33d03dd8e2`。
- 新真实双 JVM 冷启动用例通过，31.27 秒，备节点真实物理提交证据验证 E6/seq1，主节点获得严格双副本业务 ACK。主备旧 E4 的未确认尾部逐字节保留。使用原有 cold reservation、poison、signed Stage、retirement 和物理恢复入口，没有让未提交尾部进入业务重放。
- 第一轮修复版用例已到主节点真实 Home 业务写入 ACK，但夹具错误地期望备节点内存自动应用新业务回调，因此失败。修正夹具后独立验证备节点 Common 物理证书与冷重放状态，不把复制落盘误作业务回调。
- 29 类 170 项安全测试首次独立调用遗漏既有 `otc.demo.existing.keys` 参数，6 项因夹具缺失失败，原日志保存为 `safety-missing-existing-rsa-fixture.log`。已补齐参数，完整重跑后才进入 10 项真实 poison/节点生命周期和 256 分区多次双向故障门禁。
- 冷启动新用例加入门禁要求，必须带公开物理文件证据和实际 Home 业务 ACK marker。门禁封存脚本 5 项回归通过。完整 P0 正在运行，修复版尚未部署。
- 旧停止日志 2 份已完整 gzip 读回校验后归档，释放原始 919751859 字节，归档 80833798 字节，净回收 838918061 字节。清单 `t554-retired-log-archive-20261112-055747/manifest.json`。主机约 7.2 GiB 可用，VM 约 6.4 GiB。扩容和 fsck 仍未执行。

### 2026-11-12 06:16 独占重跑及原盘证据

- 原 `022723` 的 P114/E7 原盘只读校验通过，实际使用候选前已验证的 Common 4793eecc、原 A/B 公钥、两份原始 WAL、备节点 custody 与双方 receipt ledger。真正已确认水位为 9341，前缀 SHA256 `8c7a74d7cbc5582c269fc64de9372ddac90ff9bc4fbbdffef52b499ae6fb7ca4`，两份原盘物理 head 均 9342。证据 `022723/rollback-p114-readonly-audit/result.json`。审计进程无网络，业务卷与公钥均只读挂载，没有写入、签名或修改 ZooKeeper。
- 新 Common `2b19533e...` 的 170 项安全测试通过，10 项真实物理恢复测试全部通过，467.493 秒，含冷尾部、阻塞 poison 通知、多个分区、退出重启、中断恢复等全部场景。
- 完整 256 用例在故障注入前的 P129/E2 预填 seq3606，`CUSTODY_INSTALL_AND_REPLICA_LEDGER` 确认等待超时，fixture 原始 B 退出。本轮 `20261112-0557` 保留 NO_GO。当时有后台旧构建依赖清理，可能造成存储干扰，尚未证明因果。不修改 2500ms 确认等待参数，结束清理、暂停原已失败 Order A/B 重启循环后，以新目录 `20261112-0616` 独占完整重跑。
- 为防旧失败循环持续消耗资源，原 Order A/B 正常停止，原容器、restart 配置、卷、Epoch 和所有日志保留。准确身份和原因记录在 `022723/order-cold-recovery-maintenance.json`。这不是恢复完成，Robot 和真实交易仍未恢复。
- 单个 MD 在原代内做了两次有界替换诊断，随后均恢复原容器。第一次 35 秒只看到旧注册会话残留等待，未采到 Spring 启动，不能据此诊断源码。第二次覆盖 85 秒注册窗口，新 MD 正常启动，Admin 目录线程已运行，原租户 public market code=0。未解决新建租户品种的真实基线失败，不能把该诊断记为业务 PASS。
- 新部署验证脚本在基线失败、自动回滚前，会有界采集同一代 MD 的只读线程转储，便于定位目录是否初始化。只保存在本地私有目录，语法校验通过，完整现场分支还待下一次真实失败触发。
- 已清理 2921 份 11 月 9–10 日完成构建的第三方依赖副本，每一份先匹配现存 Maven 缓存的文件大小与 SHA256，并持久化恢复来源清单后才删除。保留源码、测试报告、构建日志、Common/Shared 自产 JAR、镜像和全部业务数据。逻辑重复量 4295228306 字节，主机实际可用空间升到 11880316928 字节。清单 `t554-old-build-dependency-cleanup-20261112-061301/manifest.json`。Maven 原件保留。

### 2026-11-12 06:40 用户确认正常双节点异步的故障接管合同

- 用户明确选择主节点本机落盘后返回，备节点正常异步复制。主节点故障且备节点未追平时，按备节点实际已持久化水位立即接管，接受未复制的已确认交易可能丢失。
- 验收必须记录故障前本机确认水位、备节点落盘水位、新 Epoch 的实际起点及允许丢失的序号区间。新 Epoch 须经过真实旧主隔离和物理恢复证明。旧主多出的本地尾部保留为证据，并防止回归时混入新的有效历史。
- 成功回执须继续保留 LOCAL 持久化和单副本风险，后续追平不改写原始承诺。正常双节点异步、单节点降级、严格双副本分别记录验收结果。
- 当前正常双节点异步功能仍未实现，既有 LOCAL 降级追平和业务回调移出网络线程均不能代替该功能。先完成严格模式恢复部署，再推进同一 Common 入口的正常异步与故障、资金持仓、行情、投影一致性验证及容量/P99 对比。
- 独占 P0 `0616` 已越过前轮 seq3606 超时点并完成 4100 条预填，第一方向接管、Home、长日志/快照重放及中断恢复均已通过。控制脚本 `mac-t554-cold-tail-after-isolated-p0.py` 只在精确 JAR 完整门禁 PASS 后启动正常 `fresh-verified`，随后执行严格下单撤单、四个真实业务故障、10/50/200 Robot 和 burst。仍须以各阶段实际结果为准。

### 2026-11-12 07:14 MD 订阅静默丢弃根因及依赖修复

- Common `2b19533e...` 的完整独占 P0 已通过。170 项安全测试、10 项物理恢复（445.77 秒）、完整 256 分区多次双向故障与返回（2064.074 秒）及大快照冷重开均通过。`0616/status=PASS`，封存包含新增 `cold-strict-tails` 的原盘证据。
- 实测 A 接管 228870ms、回 Home 454570ms，B 接管 237730ms、回 Home 401800ms。最后第三次强杀、256 LOCAL、再次 Home 128/128、256 WAL 和 256 Snapshot 配对均通过。控制阶段文件现场计时显示多数阶段的相邻发布间隔约 0.75–1.1 秒，后续可继续分析控制推进耗时。计时为现场元数据采样，末段只采到部分文件，下单延迟另行测量。
- 正常一键部署 `mac-demo-20261112-065755` 再次在自定义行情业务基线失败并自动回滚 `022723`，其 Order 仍按维护记录保持停止。新的只读代理在首次失败前后采到 MD 的现有单例状态，未替换或变换业务类，未写业务字段。目录已包含 HPWVPM 的 CUSTOM 绑定、6 步注册完成、Broker subscribed=true，但 accepted=0/rejected=0，共享 BTC 指标也未收到。
- 已验证明确根因。新 MD Maven 构建继承了 `commons-lang3-3.5.jar`，原实际运行镜像为 3.10。Common `BaseApi.subscribeWithImage` 在调用客户回调前使用无参 `StringUtils.isNoneBlank()`。真实库探针显示 3.5 返回 false，3.10 返回 true，因而 3.5 下全部通知被跳过。Admin 目录仍能由独立的 requestSync 全量轮询加载，故出现目录有数据而价格接收计数为零的现场。
- 加入实际 Common 通知解码测试，Map、数组及现有空字符串回调在原 MD 依赖下均失败，3 失败、0 错误、0 跳过。MD 显式固定原运行依赖 Commons Lang 3.10 后，207 项 MD 测试全部通过，源码提交 `578ed2f22882b1a20b9d9c63c9333a3417956201`。
- 正在正常 `fresh-verified` 重建部署，继续使用已完整通过 P0 的精确 Common `2b19533e...`。这一轮 MD 依赖修复没有更改 Common 字节或 HA 承诺。Common 通用入口去除无参版本依赖的源修复另行回归，后续 Common 新 JAR 仍须独立重新通过门禁。

### 2026-11-12 07:33 内部复制端口冲突及正常镜像复用重试

- MD 依赖修复的一键构建 `mac-demo-build-20261112-071311` 已完成，Common 继续精确 `2b19533e...`，MD 提交 `578ed2f`，正常构建内 MD 207 项全部通过。
- `mac-demo-20261112-071311` 在真实业务基线开始前失败。Trade A 的 Common Netty 监听报 `java.net.BindException: Address already in use`，自动重启 22 次仍未取得业务启动门禁。Trade B 已正常启动并认证其 Gateway 发现。失败代保留，工具自动回滚 `022723`，未把容器 Up 记作通过。
- Trade A 原内部复制端口 48422，VM 实际临时出站端口范围为 32768–60999，`ip_local_reserved_ports` 为空。失败现场未采到具体占用进程，不能把临时出站冲突认定为唯一已证原因。
- 新部署配置选择 bootstrap 28120–28123、常驻运行 28220–28223，均在当前 VM 的临时端口范围之外。所有 phase 的 bindPort 与 nettyPeers 一起生成，4 项源回归和 VM 中两组真实 socket bind 检查均通过。启动 bootstrap、启动常驻 JVM 前分别检查对应端口，异常进入原有自动回滚路径。没有修改全局端口分配设置。
- 正在复用已通过源码构建的 `071311` 镜像重试正常 fresh，避免同样源码重复构建。Common ACK、Fencing、签名和原始数据未作人工变更。控制脚本 `/tmp/mac-t554-md-ports-after-p0.py` 继续接续后续业务门禁与压测。
- Common 通用通知入口另已提交 `b9a6b0b`，只将无参库判断改为内容非 null 判断，保留既有空字符串通知语义。原 3 项实际分发测试在 3.5 下全部失败，修复后 3.5、3.10 下均 3 项通过。当前部署仍为通过完整 P0 的 `2b19533e...`，通用通知源修复尚未进入运行 JAR，需随后续 Common 版本完成独立完整门禁。

### 2026-11-12 07:49 本机交易恢复与严格下单撤单结果

- 唯一在线业务代 mac-demo-20261112-073320，复用正常源码构建 mac-demo-build-20261112-071311。Common 2b19533e276da3382428b0aff26233d8078579b0f2bc46e8c1f07f33d03dd8e2 已完整通过 P0，MD 为 578ed2f22882b1a20b9d9c63c9333a3417956201。ORDER_ONLY XC7SO2 与带资金 JCQ88V 的真实客户成交、MD execution ID、SDK 历史与账户核验通过。两个 Robot RUNNING、80 挂价、12 次真实 Tape 成交，资金持仓投影逐项一致，2 个 watermarks 无差异。业务基线 76 秒，完整启动及业务验证 356 秒。
- order-cancel-capacity-8b236d24.json 六档均 PASS，共 2962 个完整下单撤单循环，测试挂单全部撤净，清单始终 2/2。ORDER_ONLY 并发 1/4/8 吞吐 7.060/10.438/10.991 循环每秒，下单 New 可见 P99 为 182.206/489.203/685.932ms，撤单实际消失 P99 为 174.530/304.344/511.097ms。带资金并发 1/4/8 为 5.349/7.597/7.659 循环每秒，下单 P99 为 196.102/585.690/1037.583ms，撤单 P99 为 199.682/345.922/652.855ms。单租户热点分区且有背景 Robot，不代表整集群最大 TPS。每档不足 1000 个样本，P99.9 为最大值，含查询轮询开销。性能目标仍未达成。
- 07:46 自动开始 Trade B SIGKILL，随后依次 Trade A TERM、Order B TERM、Order A SIGKILL，再进行 10/50/200 Robot 稳态与突发。同一个 Robot 持续运行，使用真实 Tape。
- 正常双节点异步尚未部署。首版源码复用同一物理 WAL 及原双签名复制和恢复，客户在本机 fsync 与 apply 后收到 LOCAL 风险回执，后台继续真实双副本复制。每分区最多一条待复制命令，下一条追加前背压。该实现边界由开发者选择以保留现有严格物理 HEAD 证明，不能预先声称吞吐提升。新增真实 TCP 延迟对端测试和完整 P0 通过后，才可接入业务和异步压测。

### 2026-11-12 08:17 当前严格故障演练及异步研发边界

- 073320 新代 Trade B SIGKILL 完整通过，报告 ha-trade-b-kill-ttnmjfgk/evidence.json 状态 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS。全 256 单节点接管 322.223 秒，回归自动 Home 720.652 秒，真实 LOCAL 成交 P176/E3/131，原风险标记保留。同一个 JCQ88V Robot 接管期间 10 个报价轮次、最大轮次间隔 43.717 秒，回归期间 24 个轮次、最大轮次间隔 31.808 秒。512 份物理 WAL/快照成对核对及资金游标核对通过。以上轮次间隔不是成交延迟，RTO 仍为分钟级。08:05 已自动进入 Trade A TERM，仍在进行。
- Common 工作目录开始正常双节点异步研发，全部为未提交 WIP，未建立新候选和完整 P0，也未安装进业务。第一版沿用同一 WAL、后台双签名物理复制、每分区一条待复制和独立命名空间只创建一次的 client-ack-policy。默认 STRICT，选择 LOCAL 仅允许在实际全空 E2 物理盘首次创建模式 pin，已有历史和 A/B 配置冲突拒绝启动。
- 最初 31 项边界测试通过。包含 BaseApi 通知修复和首版异步的 174 项安全测试通过，但发生在后续 peer retry 修改之前，不能作为当前 WIP 的完整验证。
- 最初异步夹具把备节点超时后的本机已确认尾部按严格未确认尾部排除，这不能证明健康主节点的本机持久化保证。该接受标准已撤回。改为备节点短时暂停超过单次复制超时，保留本机已确认数据，重试原帧，不重复 apply、不切 Epoch。新正常 TCP 用例及原物理运行时 9 项共 10 项通过，日志 /tmp/mac-t554-normal-async-retain-local.log。
- 原严格传输仍按失败隔离，异步只对明确传输超时/连接失败重试同一物理序号。原 CommitIndex 若已持久化该序号而远端 custody 回复丢失，必须验证同一证书和 SHA 后续完原流程，不可重复创建或回退水位。长期备节点失联、控制租约过期后原主仍存活的本机已确认尾部保留与继续写入，正在新增真实双进程门禁，尚未验证，异步仍为 NO-GO。
- 主节点本机确认后立刻 SIGKILL 的新夹具有三份失败证据。第一份 60 秒等待不足，第二份在 replay 回调后过早认定 READY，第三份在其他分区仍 RECOVERING 时首次回归启动失败。分别保留 native-0805/0806/0809 系列证据。现夹具等待真实业务写授权，并在真实全 256 分区单节点可写后启动回归节点，同现有 Mac 故障驱动的步骤。该修正还未重新通过，不能宣告异步主故障恢复完成。
- 只清理 11 月 11 日已完成构建内可从现有 Maven 原件逐字节恢复的第三方依赖副本，13 份 897630331 字节和 208 份 410979751 字节，清单 t554-old-build-dependency-cleanup-20261112-081402、081422。Common/Shared 自产 JAR、源码、测试报告、日志、镜像和业务数据保留，Maven 原件保留。清理时没有独立 Common 演练或容量压测在运行。当前主机约 6.6GiB、VM 约 4.7GiB 可用，扩容与 fsck 尚未执行。

### 2026-11-12 08:59 存活主节点异步尾部缺口与修复状态

- Trade A TERM 完整通过，073320/ha-trade-a-term-4kdsskaq/evidence.json，08:25:32 自动进入 Order B TERM。Order B 的 ORDER_ONLY 场景也已通过，目录 ha-order-b-term-wrvf2lzc。08:48:02 已进入最后 Order A SIGKILL，目录 ha-order-a-kill-tj9w8_gc，仍在等待自动回归 Home。实际在线代及 Common JAR 继续为 073320 / 2b19533e...，没有部署当前异步 WIP。
- 08:49:59 仅暂停了自有容量测试父调度进程 PID 14312，当前 Order A 故障子进程继续完整运行，所有业务服务和 Robot 持续运行。容量测试必须在独立 Common 开发/完整 P0 等后台工作结束后再测，避免共享主机竞争导致错误容量结论。恢复该父进程仍是待完成任务，应核对 PID 身份后发送 SIGCONT，并更新 capacity-controller-serialization.json 的 resume_required。
- native-0818 新门禁真实复现缺口。备节点因租约过期通过 exit78 退出，存活 A 恢复后实际状态仅 BASE+COMMAND，丢失已本机确认 UNCERTAIN 尾部，预期 9 字节、实际 6 字节。证据 native-0818-live-poison/normal-dual-async-backup-expiry，日志 /tmp/mac-t554-normal-async-backup-expiry-red.log。该版本异步为 NO-GO。
- 当前修复复用原退役证明，增加兼容的签名 V2 字段 originalClientAckPolicy。普通严格回执仍保持原 V1 字节；只有实际 Common registry 的 LOCAL 客户确认模式才可签 V2。退役后以原节点真实 RSA、原物理 WAL 全前缀和既有 signed Stage 证明本机已提交水位。旧 V1、错误原角色、错误 Epoch、SHA 或签名均不能将普通未确认尾部提升为 LOCAL 已提交。没有创建新的恢复账本、服务或第二套 WAL，没有伪造第二物理签名。
- 恢复流程继续复用原生产 Common 入口、退役、原 signed Stage、原业务 Snapshot/WAL 恢复事务、原独立 C 风险批准和原 LOCAL READY CAS。存活原主的 V2 前缀作为明确 LOCAL 证据，不能用作双副本 custody。原主真的故障时仍只按备节点提交水位接管，不合并旧主未复制后缀。实现涉及既有 source reader、恢复 authority、publisher 和 manifest transition 等现有类，全部未提交 WIP，未完成当前完整 P0。
- 第一轮正向修复 native-0840 在 Local 恢复复用函数中遗漏了旧严格 reader 的空引用分支，10 分钟门禁保留 NO-GO。已修正该分支。只读诊断在该隔离 fixture 的 A 进程读取到实际 lastRejection 为 NullPointerException，同时另一个只读原盘审计验证签名 LOCAL 模式、真实 head2、2 条原始物理帧通过。只读观察 agent 未修改类、字段或业务状态，仅向 /tmp 写诊断，未加载到 Mac Demo 业务进程。
- 第二轮 native-0854 的固定 45 秒备节点重启早于 P000 转入 LOCAL，该分区保持合法 E2 并已在两份原盘复制 seq2。夹具只等待更高 Epoch，无法证明所需的长失联单节点继续写入。已保存观测 /tmp/mac-t554-backup-expiry-second-fix-observation.json，主动终止该隔离 fixture A，触发原 finally 保存 NO-GO 证据。现在将该测试的备节点持续关闭至原主取得真实新 LOCAL 写入回执，再通过原入口重启并验证回归后状态与新双节点异步写入。第三轮日志 /tmp/mac-t554-normal-async-backup-expiry-third-fix.log，正在运行。
- 本机新增回收 503 份旧已完成构建的重复第三方依赖，包括原清理未覆盖的 target/dependency、shared/target/javalib、projection/base/lib。每份先匹配现存 Maven 原件完整 SHA 和大小，再持久化清单后删除。释放 3229147181 字节，主机可用从 5626126336 升到 8853794816 字节，清单 t554-old-build-dependency-cleanup-20261112-085100。原件、源码、所有业务数据、私钥、公钥、证据和自产 JAR 均保留。该轮开始前独立 Common 夹具已经结束，没有与容量压测并发。
- 新异步 P0 seal 将要求短时备节点超时、本机 ACK 后原主 SIGKILL、备节点整节点过期而存活原主保留尾部并继续写入/回归三类真实证据。脚本回归 7 项通过。当前任何新增异步证明都尚未完整通过，不能选择 LOCAL 生产部署。Mac 一键脚本也尚未接线该模式参数，须待 Common 新精确 JAR 全门禁后进行。

### 2026-11-12 09:31 新候选与严格业务四故障结果

- 用户已明确异步接管边界。原主故障时，备节点按自己真实持久化且认证的提交水位立即进入原有接管流程，允许丢失原主已确认但尚未复制的交易。仍需通过真实 Fencing、独立见证、业务重放和 READY，不能将“立即”解释为跳过这些步骤。原主返回时不能把旧未复制后缀重新并入已接管业务状态。
- 073320 的四项业务故障均已通过 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS。Trade B KILL 接管 322.223 秒、Home 720.652 秒，Trade A TERM 为 412.192/763.434 秒，Order B TERM 为 451.782/805.854 秒，Order A KILL 为 372.651/860.167 秒。实际 Robot 持续运行并核对真实成交、物理 WAL/快照及财务游标。部分故障与独立 Common 开发测试共享主机，以上用于功能验证，不作为独占生产性能对比。容量父调度器 PID14312 仍因资源串行测试暂停，后续必须恢复。
- 异步备节点整节点过期的第三轮修复通过，249.2 秒。证据 t554-normal-async-native-20261112-0859-live-poison/normal-dual-async-backup-expiry。B 实际 exit78，保持关闭直到 A 保留原本机确认尾部且取得真实新 LOCAL 写入回执，再通过原入口返回，核对 Home 后完整状态和新的双节点异步写入。原 0818 缺口、0840 空引用和 0854 夹具时序失败仍保留为 NO-GO 历史证据。
- Common 源码已提交 d47ab93277b2bf69c7db6ec2da2e8a0b793b89be，包含原 BaseApi 通知兼容修复。当前源码的 174 项安全测试通过，构建新候选 20261112-0918，精确 JAR SHA256 为 94a89274ee87fcc448d5ce27b0dbec3a6aea927a1c284a507a5156d1cc5eda5e。09:31 该候选 JAR 优先类路径的 174 项测试通过，121.372 秒，safety.status=PASS。尚未完成新候选完整 P0。异步原主 KILL 用例已改为等待所有 256 分区实际回归 Home，尚未取得修改后的完整通过证据。
- 一键 fresh 新增 MAC_DEMO_CLIENT_ACK_POLICY，默认 STRICT_QUORUM。LOCAL_DURABLE_ASYNC 必须有同一精确 JAR 的完整物理 seal，且包含三项正常异步故障证明与一条待复制上限，才可进入部署。bootstrap 使用原严格路径，hostready 才采用选定客户确认语义，模式写入部署记录和实际容器标签，故障替换沿用原启动参数。清除继承的同名 JVM 参数并保留其他参数，覆盖整参数引号、值引号、无值及重复部署。根脚本相关回归 28 项通过。该接线尚未实际部署，在线业务仍为 2b19533e... 严格版本。
- 全卷只读扫描耗时较长，09:28 限时结束，仅保留已扫描部分，不能称为完整磁盘排行。发现旧 mac-demo-20261111-072730-ready 卷约 14.8GiB，20 个关联容器均停止、restart=no，无在线挂载。准备先完整归档与逐文件 SHA/元数据校验，再清理原卷内容。当前在线代数据保留，扩容和 fsck 尚未执行。
- 09:38 持续 Robot 下在线复核 PASS_FINANCIAL_CURSOR，结果保存为 073320/financial-convergence-after-four-faults-20261112-0938.json。此前一次即时抽样捕获投影两个独立事务之间的暂态游标差异，随后按现有严格相等重试函数复核通过，没有修改游标或业务数据。
- 自有串行调度脚本 /tmp/mac-t554-async-exact-p0-after-archive.py 等待完整归档，通过后重新核对原卷所有文件并清理，fstrim 回收空间，再执行新候选完整 P0。新完整门禁通过后核对原容量调度器 PID14312 的精确进程身份并发送 SIGCONT，更新原暂停记录，接续严格容量测试。完整门禁未通过时保留 NO-GO 并继续修复，不能用单项通过替代完整门禁。

### 2026-11-12 10:20 旧卷安全清理完成

- 旧 mac-demo-20261111-072730-ready 已完整归档，727280 份文件、734960 个条目，逐文件核对 SHA256、inode、大小、mtime、权限和所有者，另做完整 gzip/tar 读回。归档 t554-retired-072730-archive-20261112-093143/mac-demo-20261111-072730-ready.tar.gz，2639794950 字节，SHA256 a54d305ffd49a6dbf3c102f9a6d8bc9683d471cc5067baea48f1cfa58cdb055b。
- 再次核对归档 SHA、全部原文件及 20 个停止容器、无在线挂载后清理原卷内容。cleanup.json 状态 CLEARED_WITH_VERIFIED_FULL_ARCHIVE，原文件实际分配 15852531712 字节，VM 可用从 2059255808 升至 17948479488 字节。容器和原空卷保留，数据可由归档恢复。主机可用约 14GiB，VM 约 17GiB，后续 fstrim 正在完成。在线 073320、其他卷、所有源码和业务证据保留。
- 该旧卷主要逻辑占用为 Trade A 主快照 4.014GB、Trade B 主快照 2.900GB，其余主要为 Order/Trade 原分区 WAL/证明及快照。完整分组统计为同目录 size-breakdown.json。统计仅代表这一旧卷，不能当作全系统排行。此前全卷扫描限时结束的边界保持不变。
- 异步业务的后续验收必须强制覆盖真实未复制确认窗口，核对接管后订单、成交、资金持仓、MD 与投影的一致性和幂等。正常双节点都已追平后再故障，不能代替用户接受 RPO 损失边界的验证。

### 2026-11-12 10:45 真实在途尾部与验收夹具修正

- fstrim 已完成，实际回收 19413225472 字节，主机约 17GiB、VM 约 17GiB 可用。新精确 JAR 的首轮完整门禁为 t554-common-verifications/20261112-102013。196637 字节真实 RSA 大快照传输与冷重开通过，13 项原生恢复中 12 项通过，1 项在新主故障用例最后的备盘字节比较失败，整轮保留 NO_GO，未执行后续完整 256 多次故障门禁，未部署新 JAR。
- 失败位置 CommonCertifiedLivePoisonRecoveryTest.java:289，预期旧 B WAL 31 字节，实际 62 字节。只读原盘 CRC、Epoch、序号和 SHA 审计显示 A/B 旧 E2 WAL 均为两条合法物理帧，seq1/seq2，SHA 都为 027ceeb5033b7b87327dde4444dd7e20eef26dfd19b46d4ba30f33097cd72b33。首帧为真正提交前缀，第二帧由 A 强杀前已经进入网络，B 继续运行后收到。原子接管仍正确使用已认证 head1，排除未完整认证的 seq2，真实新业务写入和全 256 Home 128/128 已通过，最终 manifest NPC1/1282。该尾部不能冒充已认证提交。审计副本已存首轮门禁目录 async-primary-loss-readonly-wal-audit.json。
- 原断言将“故障后禁止修改原提交前缀”错误写成“备盘绝不能收到在途帧”。夹具改为保留并逐字节比较故障前 A 本机确认原件、B 原提交前缀，B 最终盘只允许原前缀或与 A 原件完全相同的在途后缀，真实恢复业务证明继续排除未认证尾部。额外保留两份故障前原件和 Home 业务证明，seal 独立复核这些原件。错误前缀、未知后缀、原主盘改变、缺少真实 Home 业务证明均拒绝封存。
- 夹具提交 264d8c7f08a361719e02ce5024a39683e5138eef，生产 pom.xml/src/main 与候选 d47ab93 完全相同，复用精确 JAR 94a89274...。根脚本回归现在 29 项通过。新的完整门禁由 /tmp/mac-t554-async-exact-p0-retry.py 接续，仍要求所有 13 项、完整 256 双向强杀/重复 Home/中断恢复通过后，才自动恢复原容量调度器。当前完整门禁仍未通过，异步业务部署仍为 NO-GO。

### 2026-11-12 11:00 异步原主强杀用例通过

- 同一候选 94a89274... 的完整重跑目录为 t554-common-verifications/20261112-104421。新增原主本机确认后 SIGKILL 场景已通过，日志 T554_NORMAL_DUAL_ASYNC_PRIMARY_SIGKILL_AFTER_LOCAL_ACK_REAL_WITNESS_HOME_PASS，真实备节点已认证水位 1、原主本机确认尾部 2 被排除、新真实业务确认、256 Home 128/128、原主原盘不变、备节点原提交前缀保留均通过。新增原件可由 seal 独立对照，整轮其他原生用例和完整多次双向故障仍在继续，不能标记完整 P0 PASS。
- 为严格和异步容量测试补充运行时模式核对。开始测量和结束核对时，必须检查四个真实 Order/Trade 容器的 Common JAR 标签 SHA、进程运行状态、部署模式标签和实际 JVM 模式参数。异步必须显式选择 LOCAL_DURABLE_ASYNC，错误/重复模式参数、错误 JAR、错误节点或停止节点拒绝测量。旧严格默认配置继续支持。容量、下单撤单、突发报告都记录 common_release，包含精确 JAR、源码版本和客户确认模式，防止将单节点降级误记为正常双节点异步。
- 根脚本回归 32 项通过。当前 073320 的新运行时模式检查实际通过 STRICT_QUORUM，四节点均为 2b19533e...，完整只读 preflight 的 Order/Trade manifest generation 均为 2562。容量测试父进程 PID14312 仍在等待完整独占 Common 门禁完成后的自动恢复。

### 2026-11-12 11:15 原生 13 项通过与同 JAR 对比队列

- 104421 门禁的原生 13 项全部通过，1228.783 秒，包括三个正常双节点异步场景、原严格毒化、节点租约过期、冷尾部和独立分区恢复。196637 字节 RSA 大快照冷重开也通过。现在开始原完整 256 分区、4100 条严格历史与真实业务重放、多次双向强杀和重复 Home/中断恢复，日志已有 T554_EXTENDED_STRICT_GENESIS_BOTH_PHYSICAL_WALS_AND_REPLAY_PASS。完整门禁 status 仍为 NO_GO，直至最终全部通过封存。
- 为使用同一精确 JAR 比较两种模式，已主动结束旧版 2b 的自有调度器 PID14312。当时四项故障均通过、容量阶段尚未开始、无运行中的故障子进程。仅向自己的父调度器发送 SIGINT/SIGCONT，使其退出，未操作业务服务。原控制源保留在 073320/completed-four-fault-controller-20261112-1111.py，原证据完整保留。旧 PID 已退出，不应再次恢复。
- 新控制器 PID30553，实际命令仍为 Python -u /tmp/mac-t554-md-ports-after-p0.py，当前状态 T，等待完整精确 Common 门禁。原 capacity-controller-serialization.json 已更新新 PID/精确命令，并保留 previous_controller 交代旧队列结束。当前 resume_required=true 指新 PID30553。现有 P0 retry 调度器在成功封存后从该记录读取新 PID，核对命令与暂停状态，再自动 SIGCONT，避免遗留暂停队列。
- 新队列先以候选 94a89274... 通过正常 fresh-verified 安装严格模式，完成真实业务基线、下单撤单、四项 A/B 故障、10/50/200 Robot 和突发，再恢复已通过的 10 Robot。随后复用完全相同的构建镜像选择 LOCAL_DURABLE_ASYNC 全新部署，执行同样的验收与容量序列。始终使用同一 Mac，旧代退役后才启用下一业务代。各阶段错误立即保留 NO-GO，由主任务继续诊断修复，不能把失败跳过为 PASS。专门强制业务 RPO 损失窗口仍是后续必须执行的独立验收。
- 新控制日志 /tmp/mac-t554-latest-same-jar-controller.log，阶段日志 /tmp/mac-t554-latest-common-*.log。HA 报告也新增客户确认模式，并兼容没有该字段的历史严格 resume 证据。在线业务目前仍为 073320 / 2b 严格模式，尚未部署候选 94。

### 2026-11-12 11:43 精确候选完整 P0 PASS，自动接续业务构建

- 104421/status=PASS，verification.seal.json 已验证精确 JAR 94a89274ee87fcc448d5ce27b0dbec3a6aea927a1c284a507a5156d1cc5eda5e、源码 d47ab93277b2bf69c7db6ec2da2e8a0b793b89be、夹具 264d8c7f08a361719e02ce5024a39683e5138eef。174 项 JAR 优先安全测试、13 项原生恢复（1228.783 秒）、196637 字节 RSA 大快照与冷重开通过。完整 256 多次故障用例 2157.225 秒，通过双向真实 SIGKILL、256 LOCAL、第三次强杀及再次 Home、256 WAL 和 256 Snapshot 成对一致，以及中断 signed Stage 恢复和跨 Epoch 历史读取。
- 完整用例实测 A 全分区接管 245492ms、回 Home 469430ms，B 为 241244/409593ms，仍为分钟级 RTO。该轮是通用恢复功能门禁，不能将其当作客户成交延迟或整集群最大吞吐。源检查显示现有常驻恢复按单个全局 manifest 的一项活动分区 stage 串行推进，并使用固定延迟 tick，后续控制耗时分析应以这一实际机制为基础。
- seal 的 normal_dual_async=true、max_pending_per_partition=1、recovery_head=backup_certified_committed，三项正常异步物理场景均已封存。异步客户承诺仅为本机 fsync 后返回，后台完成原双副本物理证明，原主故障按备节点已认证提交水位接管，未完整复制认证的本机确认尾部可能丢失。不能把本机确认回执解释为双副本零 RPO。
- 11:41:39 串行门禁自动恢复新 PID30553，resume_required=false，实际启动 strict-fresh。正在正常 fresh-verified 构建候选的业务镜像，准备严格模式 P1/P2 和容量。新候选的业务完整验收及正常异步业务 RPO 窗口仍未完成，不能把 Common P0 PASS 记作整套业务或生产性能交付。

### 2026-11-12 13:38 最新 Common 严格业务验收与容量状态

- 唯一在线代为 mac-demo-20261112-114139，构建 mac-demo-build-20261112-114139，实际 Common SHA 为 94a89274ee87fcc448d5ce27b0dbec3a6aea927a1c284a507a5156d1cc5eda5e，客户确认模式 STRICT_QUORUM。旧代已退役，数据与证据保留。正常 fresh 基线通过，ORDER_ONLY JRNZRF、带资金 L5MYBC，实际客户成交、MD execution ID、SDK 历史与金融游标均通过。业务组件测试 667 项，其中 665 PASS、Order 历史跳过 2 项，prepared 镜像启动及实际业务门禁约 384 秒。
- order-cancel-capacity-00213864.json 共 2924 个完整下单撤单循环，六档均 PASS，测试挂单全部撤净。ORDER_ONLY 并发 1/4/8 吞吐为 6.727/10.343/10.639 循环每秒，下单 New 可见 P99 为 164.288/373.769/908.113ms，撤单实际消失 P99 为 181.242/292.462/557.071ms。带资金为 5.755/7.272/7.689 循环每秒，下单 P99 为 180.720/544.746/1017.953ms，撤单 P99 为 161.469/388.023/681.305ms。这是单租户热点分区、含背景 Robot 与查询轮询的实际往返测试，每档少于 1000 样本，P99.9 仍为最大值。
- 同一实际 JAR 的 Trade B SIGKILL、Trade A TERM、Order B TERM（ORDER_ONLY）、Order A SIGKILL（带资金）全部完成 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS，目录依次为 ha-trade-b-kill-aegjqywe、ha-trade-a-term-lt_5snw_、ha-order-b-term-gk0scmtk、ha-order-a-kill-6nzb30kr。四项全程使用同一 Robot 进程，验证真实 LOCAL 成交、自动全分区接管、追平和 Home 128/128、物理 WAL/快照与金融一致性。最后一项 13:11 完成。
- robot-steady-10-051707.json 为 PASS。五分钟内 quote 545、Tape 请求 548、真实成交 547，约 1.823 笔每秒。Trade ingress 至 Order final publish 有 546 对样本，P50/P95/P99/P99.9 为 158.337/276.015/520.445/862.854ms。10 Robot 全部 RUNNING，金融游标 PASS。该档各主要容器 CPU 配额未耗尽，不能据此认定延迟瓶颈。尚未满足高性能交易系统验收。
- 50 Robot 招募完成后曾有 1 个 WAITING_MARKET_DATA，随后自主转为 RUNNING，当前正在进行正式五分钟测量，尚无该档 PASS。没有强改运行状态。13:36 仅暂停自有队列父进程 PID30553，当前容量子进程 PID40413 继续原窗口。原因是在继续 200 租户前检查真实容量结果与主机剩余空间，并将强制异步业务 RPO 损失窗口串行插入后续部署。capacity-controller-serialization.json 已记录 resume_required=true，主任务负责继续，无业务进程因此暂停。
- 主机约 6.8GiB、Colima Docker 盘约 12GiB 可用，未进行扩容或 fsck。已归档后清空的旧 072730 代保持完整校验归档，不能删除其唯一归档副本。
- 正常异步业务仍未部署。新增 verify-mac-demo-async-rpo.py 仅为待执行验收驱动。其有界故障工具已在 Mac Java8、实际 Linux 镜像以及独立暂停看门狗自测通过，尚未附加任何真实业务 JVM。当前代无热替换或诊断 agent。该驱动计划真实暂停备节点、在本地确认后强杀原主，核对备节点接管水位、原风险回执、原 Robot 连续性及成交与资金持仓一致性。先保存故障意图并在清理中检查实际 Docker 状态，恢复原 on-failure 策略，禁止将命令部分失败后遗留的停机漏报为未发生故障。

### 2026-11-12 13:50 严格 50 Robot NO-GO 与降载核验

- robot-steady-50-053611.json 未通过。正式窗口为 13:31:11–13:36:11，50 个 Robot 全 RUNNING、控制面 generation 前后相同。quote 2898、Tape 请求 1955、实际成交 1592，5.307 笔每秒。1575 对成交样本的 P50/P95/P99/P99.9 为 1446.912/9107.525/15697.292/20155.528ms。5 个租户整窗没有实际 Tape 成交，只有 45 个租户有窗口资金 posting，不能继续宣告 200 档通过。
- 测量后等待核验仍有 13 个投影消费水位落后。账户余额和持仓与各自金融游标的数值差异为 0，源事件连续与 predecessor 检查也为 0 差异。这次首先证明高负载下端到端成交和投影追平未通过，不能单凭游标滞后称资金损坏。CPU 增量采样显示 Order A/B 各约 90% 单核、Trade A/B 约 50.9/40.3%、Robot 20.1%、Gateway 37.8%，均未耗尽各自配额。MySQL 有 453/2759 个周期被限流，累计限流 24.460 秒，是后续需区分的候选因素，尚未建立成交延迟因果。
- 13:39 已恢复原自有父调度器，使其按失败路径停在 50 档并降载。40 个本轮新增 Robot 全部经正常 Manager STOP 停用。首轮挂单清理有认证和已撤订单竞争等错误，保留原 NO-GO。第二轮完整逐户正常认证复核全部 40 个通过，最终挂单 0，证据 pressure-disabled-quote-cleanup-confirmed-20261112-134512.json。启用队列已恢复原通过的 10 个。随后真实全量金融检查为 PASS_FINANCIAL_CURSOR，48 个水位全等、116 个账户余额与 116 个持仓逐项无差异，68015 条 predecessor 无差异。
- 只读 Order 日志还发现 ORDER_MATCH_NO_FILL_IOC_FOK_BUSINESS_CANCEL_NOT_YET_CONNECTED 和 ORDER_MATCH_MULTI_MAKER_REQUIRED。这是目前 certified 业务撮合路径已有的能力缺口，需要按正常业务状态机及同一 Common 写入路径修复后验证，不能删安全异常或把未成交订单伪装为成功。当前未修改业务源码，也尚未证明这些异常是全部延迟的主因。
- PID30553 已退出，serialization 记录为 EXITED_STRICT50_NO_GO_CLEANUP_RECHECK_PASS、resume_required=false，不能再恢复此 PID。准备新串行驱动 /tmp/mac-t554-normal-async-business-20261112.py，先复用同一构建顺序 fresh 异步、执行专门 RPO 窗口。若真实 RPO 通过，再退役该故障工具附加代，全新同镜像部署作为异步比较代，保证正式压测 JVM 不含该故障工具。任何失败保持 NO-GO，由主任务继续处理。
- 已按用户既有旧镜像清理授权，清理无标签、无容器引用、创建超过 12 小时的 Docker 镜像及可删除父层，Docker 报实际释放 522.6MB。日志 /tmp/mac-t554-old-untagged-image-prune-20261112.log，清理前清单 /tmp/mac-t554-untagged-image-inventory-20261112.json。现用与带标签回退镜像、业务卷、原始 WAL/快照和源码保留，未新增环境或重启服务。

### 2026-11-12 14:30 正常异步业务 RPO 实测 NO-GO 与在研修复

- 唯一在线代为 mac-demo-20261112-135231，仍复用构建 mac-demo-build-20261112-114139、精确 Common 94a89274...，四个实际 JVM 模式为 LOCAL_DURABLE_ASYNC。正常 fresh 的 SDK/真实客户成交、ORDER_ONLY、Robot Tape、MD、金融游标基线均通过，业务约 70 秒，正常启动与真实门禁约 415 秒。所有业务生产 Java 仍为原 114139 构建，后述源码改动尚未部署。
- 新队列 PID43203 在首次 RPO 探针失败后正常退出，状态 t554-normal-async-business-controller-20261112.json 为 NO_GO，未进入异步普通四故障或压测，也未创建比较代。旧 PID30553 同样已经退出。当前没有等待恢复的暂停队列。
- 首次探针 async-rpo-2b40c6a3 在真实暂停备节点/强杀之前因 10 秒 Order SQL 等待不足失败。独立只读 audit 证明相关事件从原始业务时间到 SQL 入库约 14.662–15.044 秒，projection-delay-readonly-audit.json 已存。实际暂停 2 个 Order 结算交付线程及其 1 个空闲 Spring retry 调度线程，最长 20 秒，已确认 RESUMED。此工具只暂停线程，未改类字节、业务字段、ACK 或 Common 控制。首次另一次 TenantAdmin 登录使 helper 原会话失效，broker 删除为 false，证据保留。helper 现可向调用者以内存字典传递原管理会话，全部令牌仍不写报告。
- 第二次 async-rpo-68745ee6 也在真实节点故障前结束。Trade 查询已看到 warmup 持仓，但独立 SQL Trade 投影尚未出现，驱动过早认为无唯一分区。驱动改为先等待实际认证 SQL 投影。两次均保持原 NO_GO，E2 未改变，可在同代继续新受控租户。现有原租户经济数据保留。
- 第三次 async-rpo-356001e5 真实捕获 P025/E2，备盘认证前缀与原始 WAL head11，原主本机 fsync 后 head12，两名客户最终 Filled 发布均明确 LOCAL_DURABLE_ASYNC、QuorumDurable=false、RpoRisk=true、TradeSettlementCommit=P025/2/12。备节点暂停期间确实尚无 seq12，原主 Trade A 在 14:06:31 实际 SIGKILL 退出 137，暂停总时长约 0.778 秒。原主、备原件与原始客户 ExecID 均保存在该目录。全 256 单节点接管完成后，按既有入口启动原 A，最终全 256 自动 Home 128/128、512 份 WAL/快照成对一致、原 on-failure 策略恢复、原 Robot 进程未变、线程工具全部释放。
- 业务一致性实测失败。Order 的 P025/E2/13 原撮合与 /14 结算确认均已认证保留，但 Home 后两名客户持仓各为 0.001，预期各 0.002，两个已发布 ExecID 没有对应金融 posting。独立只读 business-readonly-during-home-return.json 也记录这一差异。最终金融游标自身仍 PASS，5 个水位全等、18 个余额与 12 个持仓同各自 Trade 来源一致，1645 predecessor 无差异。这说明仅比 Trade 来源和投影会漏掉 Order 最终成交与 Trade 金融状态之间的缺口。Common 保持备水位接管，原未认证尾部未被人工补成提交。
- 驱动第三次的首个失败原因仍为测试顺序问题。在整个 Trade LOCAL 阶段要求 SQL posting 追平，而该现有投影端点读取严格认证窗口，需等原节点回归后才输出新增 LOCAL 前缀。后续驱动应先核对实际 Trade API 的持仓，再在 Home 后核对所有原始 posting，保留强制 RPO 窗口与严格物理证明。当前真实业务缺口已由 Home 后客户查询和独立只读数据证实，不能把它归为只有探针问题。
- 同一次演练 Robot 连续性也 NO_GO，30 轮中最大间隔 120.9 秒，超过既有 100 秒门槛。该阈值未放宽。待定位停顿与串行恢复/调用积压的实际关系，不能把容器一直 Up 记作业务连续通过。
- 另已修复源码中无成交 IOC/FOK 的业务撤单缺口。新代码复用 OrderCertifiedCancelSaga 原 Pending → Trade 精确释放 → Order terminal REMOVE 流程。回归先出现 2 项实际红测，修复后完整 Order 187 项无失败、2 项历史跳过，目录 t554-order-unfilled-cancel-validation-20261112-1356，before/after 日志与原始 reports 保留。改动为 OrderFacade、CrossStrategy 及两个既有测试文件，尚未部署。
- 正在修异步已最终确认后过早丢弃重试源的业务缺口，全部为未验证 WIP。Common 生产源码/JAR保持不变。方案复用原 Order outbox、同一 Common WAL、原 settleSignedOrderMatch 幂等 RPC 和 Shared 已有 LOCAL 回执附加 rearm evidence 格式。新增 Order ACK payload v2 记录待复制状态，先保留原撮合和第一份本机确认，待原通用物理认证读取获得真实复制证明，再以同一业务 ACK 事件持久化退休。原 v1 重放语义保留，客户第一次风险标记保留，后续复制确认仅用于内部退休并防止再次发布客户/MD 成交。
- 当前 WIP 涉及 OrderCertifiedMatchAck、OrderCertifiedMatchOutbox、OrderStateJournal、OrderSignedMatchDeliveryWorker 及两个既有测试文件。Trade 的 SettleSignedOrderMatchHandler、TradeSignedOrderMatchAdmission 复用同一 RPC 的 confirmReplication 字段，首个 LOCAL 响应继续独立于复制完成，后续查询调用 Common 现有 readCertifiedCommittedWindow 或 readRearmedLocalCommand 验证原字节，再使用现有签名附加证据。初始 outbox 新回归在原码下实际失败，预期保留1、实际0，rpo-before.log 已存。新 WIP 尚未编译/全测，尚未完成实际故障复验，仍为 NO-GO。
- 当前源码仍缺多 maker/部分 taker 的完整 certified 业务规划。正常两种模式的性能目标、200 Robot 和突发均未完成。先保留真实故障和金融差异，完成上述修复及再部署验证，再继续比较。不得从 Common P0 或正常异步基线 PASS 推导整套目标完成。

### 2026-11-12 15:29 业务修复通过源码测试，部署兼容补齐与 Common 初始化竞态

- Order 最新源码完整 188 项，186 PASS、2 项历史跳过；Trade 226 项全 PASS。outbox 新红测在旧码下预期保留1、实际0，rpo-before.log 保留。当前新 ACK payload v2 保留已本机确认的原撮合和第一份确认，在既有幂等 settleSignedOrderMatch 请求上查询后续复制证明，复用 Shared 原 LOCAL wire + rearm evidence。确认真实复制后，在原 Common WAL 追加同一 ACK 事件退休。后续复制确认的 journal 返回值抑制第二次客户/MD 发布，首次风险字段保留。新 checkpoint 保存原撮合及本机确认两份原始帧，冷重放、复制、快照往返及旧 v1 重放已进测试。版本1演练缺口作为原始失败证据保留，新流程待新部署实测。
- 新业务构建 mac-demo-build-20261112-144703 已实际重跑 Shared/Order/Trade/MD 全部 673 项，其中 671 PASS、2 项历史跳过，仍使用 Common 94a89274...。未把源码测试记作真实故障通过。
- 部署检查发现 Projection 两个读取入口仅接受 ACK version1，且旧投影镜像构建清单只覆盖5个类族。第一次新构建在业务验收前经有意 SIGINT 进入既有 KeyboardInterrupt rollback，旧代 135231 的原容器和原运行状态已恢复，意图记录 144703/intentional-deployment-abort.json。原构建核心镜像保留，投影读取端兼容 version1/2、加入 OrderProjectionService 与 SettledExecutionProjection 两个类族。两项实际红测后，Projection 源码全部43项通过，t554-projection-ack-v2-validation-20261112-1455。镜像编译 SHA cd996b1fb6267547f94b7b1251a5925bc0686f0a39f3350c399f9cee43ea7d9b，7个类族实际镜像校验通过。
- 144703/images.env 在上一部署进程退出后仅更新投影镜像及其编译 SHA，原件 images.before-projection-ack-v2.env、完整 provenance projection-ack-v2-upgrade.json 保留。复用已测核心镜像再次正常 fresh，创建 150027，尚未进行客户业务即失败并自动回滚 135231。该次失败已定位为 Common 原始 Home 文件并发发布竞态，不能归为投影或端口问题。
- 150027 的 Order A home 实际抛 COMMON_ORIGINAL_HOME_DURABLE_FILE_INVALID:original-home.v1，Order B 与 Trade A/B 均已产生真实 Home fsync marker。源码确认两个 genuine E1 节点先通过同命名空间双活租约 rendezvous，再同时 CREATE_NEW 同一 canonical Home 文件。胜者在文件创建后写入、fsync，另一节点可能在写完前看到0或部分长度而安全拒绝。运行现场、旧数据与新命名空间保留。
- Common 修复仅更改原始 Home 文件发布。先在同目录独占创建临时文件并 fsync，以不覆盖的硬链接原子发布最终名字，再 fsync 目录。原目标若已存在，继续逐字节检查长度、常规文件与 SHA 比对，既有不完整文件仍拒绝且原件保留。旧码回归实际观察到可见文件长0，预期16777216，8项 ledger 测试中1项失败；修复后8项全部通过，包括预存不完整文件仍拒绝测试。日志 t554-common-home-atomic-publication-20261112-1512/before.log、after.log。真实双物理签名、E1双活租约、Fencing与落盘门禁继续执行。
- Common 已本地提交 137cab8ada0facfa33dd7285fac755e8bb4abbec，沿用仓库 Codex/codex@local 提交身份，无全局 Git 配置修改，工作树干净。新候选 t554-common-candidates/20261112-1521，JAR SHA f0d74f25234386ede54a4fc021e11e584f0e451736b6e9aa1499353f9a37d218。旧94完整门禁是历史证据，现已知首次部署存在上述竞态；当前仅新候选待通过完整门禁后用于业务复验。
- 新串行驱动 /tmp/mac-t554-home-atomic-p0-and-business-20261112.py，PID51448，tool session68282，日志 /tmp/mac-t554-home-atomic-p0-business-controller.log，状态 t554-home-atomic-p0-business-controller-20261112.json。先执行精确候选 JAR 优先176项安全测试，随后13项原生恢复、RSA大快照冷重开、完整256/4100严格和LOCAL、多次强杀及中断恢复，再 full fresh-verified 构建最新业务/投影与真实异步 RPO。176项仍在执行，P0尚未通过。验证目录 t554-common-verifications/20261112-152632。无其他待恢复的暂停控制器，先前47608、49572及旧30553均已退出，不应再恢复。
- 投影一键构建现加入实际镜像 overlay 对应的22项回归门禁，失败阻止产出可部署镜像。完整源码43项另经 Maven 全测。首次尝试将全部9个源码测试类放进旧基础镜像 classpath，暴露基础镜像未包含与本次overlay无关的旧事件/权限类，保留该编译 NO_GO。门禁范围改为覆盖实际overlay的5个测试类，真实镜像 classpath 22项全通过，t554-projection-ack-v2-image-testgate-20261112-1524/tests.status=PASS。新构建清单7类族，源码/编译/镜像逐项 SHA 验证继续执行。
- 回滚后实际只读 census 为 Order/Trade 各256 READY、物理 STRICT、A/B各128主，客户模式仍正常双节点 LOCAL_DURABLE_ASYNC，唯一在线代仍135231、原114139业务构建。现有测试租户的已确认成交/金融缺口尚存，尚未报告恢复完成。当前代曾附加仅暂停线程的测试工具，已全部 RESUMED，无类字节热替换。正式容量比较仍需要新的干净 JVM。
- Robot 停顿的只读 phase audit 已保存到 135231/async-rpo-356001e5/robot-availability-phase-audit.json。最大 BEGIN 间隔为120.867秒，14:08:37的 QUOTE 后直到14:10:38才进入下轮；另有73.651、60.574秒间隔。Common 源码 awaitAsyncReplication 对每分区唯一待复制帧等待完成或隔离，现有恢复轮询按分区串行推进。两者是否造成此停顿需用下次演练实际线程栈确认，尚未修改调度或放宽100秒门槛。正常双节点 Order 对外发送撮合前的跨服务因果持久化边界也待补充验证。
- 只清理已完成的022723/051209/065755/071311/114139构建中 image/lib 与 base/lib 内8份大于5MiB、同现有 Maven 原件 SHA 完全一致的第三方副本，共552387896字节。源码、自产 Common/Shared JAR、所有 target 依赖目录、镜像和业务数据保留，逐项校验/元数据见 t554-old-image-context-library-cleanup-20261112-151511/manifest.json。主机可用从5840781312增到6393159680字节，后续构建后约5.5GiB。P0与后续构建继续检查磁盘，扩容/fsck尚未执行。

### 2026-11-12 16:02 新候选安全与13项原生恢复通过，继续完整256门禁

- f0d74f25234386ede54a4fc021e11e584f0e451736b6e9aa1499353f9a37d218 精确 JAR 优先安全176项已于15:28:45通过，原始 safety.log/status/list 已写候选目录。随后196637字节RSA快照与冷重开通过，13项原生恢复全部通过，耗时1298.385秒。三个正常双节点异步场景均通过，包含主节点本机确认后强杀按备认证水位恢复、在途尾部排除与原盘保留、短时断联同Epoch补齐、备节点租约过期后保留健康主的本机确认数据并继续写入。当前开始完整256分区与4100条严格/LOCAL、多次双向强杀、重复Home及中断恢复，完整P0状态仍待通过。
- PID51448的同一串行驱动继续运行，无暂停控制器。旧135231仍是唯一在线业务代，原服务已恢复Home128/128。新修复的业务RPO实测会在此精确JAR完整门禁通过及源码重新构建后接续，现有金融缺口继续保持NO-GO。
- 主机空间降至约4GiB时，整理了已完成旧构建中1111份同现有Maven原件SHA一致的依赖JAR，使用APFS写时复制克隆并原子替换原副本。每份验证内容，沿用原路径、mode及mtime，源码/当前构建/业务卷未纳入整理。共替换6766426162逻辑字节，观测可用空间从4295532544增至11023888384字节，约4.0→10.3GiB。全部记录 t554-old-build-dependency-reflink-20261112-154451/manifest.json，底层存储去重实际完成，完整原路径仍可供旧构建使用。该步骤未执行Colima重启、扩容或fsck。
- RPO驱动增加CLI SIGTERM处理，进入既有异常清理流程，执行工作线程释放、备节点解暂停、原主按既有入口回归与重启策略恢复。导入模块的测试进程不安装该信号处理。根脚本38项回归通过。


### 2026-11-12 16:29 新 Common 精确 JAR 完整 P0 通过，最新业务串行部署

- 精确 JAR f0d74f25234386ede54a4fc021e11e584f0e451736b6e9aa1499353f9a37d218 的完整 P0 于16:25:43通过。176项安全、196637字节RSA快照冷重开、13项原生恢复与完整256/4100严格/LOCAL全部通过，包含双向独立 SIGKILL、返回 Home voter 第三次强杀、再次全部256 Home与物理 WAL/快照相等、跨Epoch退休前缀和LOCAL重放。验证目录 t554-common-verifications/20261112-152632，status=PASS。完整256门禁耗时2070.738秒。
- 同一PID51448随后自动开始 fresh-verified，以当前最新业务源码重新构建，正常双节点 LOCAL_DURABLE_ASYNC。新构建 mac-demo-build-20261112-162543，新业务代 mac-demo-20261112-162543 正在初始化，尚未取得客户业务验收。旧135231数据与证据保留，部署仍采用既有失败回滚入口，无平行业务运行代。
- 普通客户验收增加 funded 与 ORDER_ONLY 各两项实际不成交 IOC/FOK 验证，走认证订单入口及现有取消 Saga，检查真实SQL终态、CumQty=0、无Trade执行、订单已从Open API消失，funded还比较账户Balance/UsedMargin/FreezedMargin/FreezedCommission。仅非故障基线调用，已通过Python语法检查，真实运行尚待本次部署。此项验证完全无成交场景，部分成交与多maker支持尚未完成。
- 用户询问异步数据丢失后的自动恢复。已明确只有尚存可靠日志或完整业务指令的交易才可自动重放/补结算，所有可靠副本均丢失时无法保证重建。现有DMPZEB已确认成交的资金缺口仍保留NO-GO，不能因新Common P0通过而宣称其已自动修复。新业务v2 ACK保留与复制证明清理路径将在此次真实RPO演练中验证。


### 2026-11-12 16:48 最新业务基线通过，真实异步丢尾部已自动补回持仓

- 新代162543已通过最新源码全构建、物理启动与真实客户验收，fresh完成16:35:05，构建131秒、启动与验收431秒，其中客户业务134秒。Order与Trade各256 READY、物理STRICT、各Home128。客户确认模式为正常双节点LOCAL_DURABLE_ASYNC。ORDER_ONLY和funded各有真实成交，两种模式的无成交IOC/FOK四例均自动Cancelled、CumQty=0且无Trade执行，funded冻结资金完全释放。两名SDK Trader的持仓/账户/历史查询、成交唯一MD ID、两Robot报价与Tape以及金融游标核对通过。
- 同一控制器继续真实RPO，证据162543/async-rpo-fa0f5f21。受控租户FQQT5F、Trade P017/E2，主A真实已本机确认12、备B只认证到11，原报告两条ExecID E4ff7db18db15bbbdf88b4b3ca0848a 与 E3128e8e0e507f2d18c984c3ec2f272，原风险字段LOCAL/quorum=false/rpo=true，原坐标P017/2/12。实际A于16:35:47以137退出，备暂停0.562834秒，原WAL与认证头证据保留。自动接管后256 LOCAL，原Order指令自动重试，双方实际API持仓均由0.001恢复为0.002，local_business_consistent=true。新v2 ACK保留与重试路径的实际金融补回已得到验证。尚在原主同入口返回与全Home/512物理对比阶段，完整RPO仍待最终验收。
- 同一Robot BKFQCU在LOCAL后产生真实报价和Tape，P071/E3/118原坐标。故障开始至16:43左右的中途只读审计18轮，最大BEGIN间隔40.633秒，未放宽100秒标准。另在故障观察后60/120/180秒对存活Trade与两Order共采9次jstack，均成功，manifest在readonly-thread-diagnostics。此为诊断故障演练，不能作为干净性能容量数据。第一组Order线程确实处于TradeSvrClient放置路由重试，未捕获awaitAsyncReplication阻塞，不能凭旧推断宣称该点是已证实根因。
- 后续串行驱动 /tmp/mac-t554-latest-business-ha-capacity-20261112-1647.py，状态 t554-latest-business-ha-capacity-controller-20261112-1647.json，tool session63102。当前只等待原RPO控制器完整PASS，未启动新故障。PASS后先Trade B KILL并指定原Robot BKFQCU观察留守主业务，再Order A TERM含ORDER_ONLY、Order B KILL含funded、Trade A TERM含funded，四例均要求实际Robot连续与物理Home。然后正常异步下单撤单与10Robot容量。任一失败停止后续队列并保留现场，root继续诊断。严格50 Robot旧结果仍NO-GO，多maker/部分taker尚未完成，尚无整套生产GO。


### 2026-11-12 16:53 真实正常双节点异步丢尾部完整业务RPO PASS，继续反向故障

- async-rpo-fa0f5f21于16:51:00完成NORMAL_ASYNC_UNREPLICATED_FILL_RPO_BUSINESS_AND_HOME_PASS。自动补结算后LOCAL与Home双方持仓均0.002，原两ExecID均有唯一成对金融流水，512组物理WAL/快照一致，Trade全256恢复STRICT Home128/128。金融游标ACCOUNT_BALANCE10/0/10、POSITION8/0/8、watermarks3/0/3、1184条predecessor links/0错，缺失/额外游标均0。原Robot与Order进程均相同、暂停线程全部RESUMED、故障主重启策略恢复原on-failure，临时密钥正常清理。原LOCAL客户风险字段未升级或重复对客发布。
- Robot BKFQCU全故障期间31轮，最大间隔40.633秒，小于未变更的100秒门槛。此结果覆盖主A丢尾部、备B真实认证水位接管、原Order指令补结算和A自动返回的这一具体场景，不能推导所有异步已确认交易零丢失或全业务性能通过。所有可靠副本/指令都丢失时仍无法保证重建。
- 原PID51448控制器已成功退出，新PID58144于16:51:03接续Trade B SIGKILL。真实故障已发生，正在A单节点接管。指定原Robot BKFQCU，Trade P071原Primary A、Epoch5，刻意覆盖此次存活的原主分区也须继续交易。新演练目录ha-trade-b-kill-8_zx9h11，附加只读线程诊断计划90/150/210秒，仍不属于干净容量测量。之后队列顺序Order A TERM/ORDER_ONLY、Order B KILL/funded、Trade A TERM/funded、异步下单撤单、干净JVM10Robot容量，任一失败即停止队列并保留现场。


### 2026-11-12 17:11 反向备故障证实存活主等待复制过久，已修调度并开始新精确P0

- ha-trade-b-kill-8_zx9h11完成物理恢复与认证业务验收，但Robot连续性失败，状态COMMON_PHYSICAL_AND_SIGNED_BUSINESS_PASS_ROBOT_PROOF_PENDING。BKFQCU在故障到LOCAL期间4轮，最大间隔110.5秒，超过100秒门槛。其存活主分区P071实际于16:54:57进入E6 LOCAL，整个256 LOCAL到16:56:32。funded受控客户GTJNGU两边成交、原ExecID、单副本风险字段、P086/E6/152资金流水与MD ID核对通过，物理Home与WAL/快照相等完成。整体继续NO-GO。原PID58144控制器失败退出，后续Order故障/容量队列未启动，不应恢复旧控制器。
- 90/150/210秒只读线程采样共9份成功，150秒和210秒的存活Trade A多个业务线程实际阻塞于CertifiedBusinessCommandBoundary.awaitAsyncReplication，包含新单冻结与成交结算，Common层单待复制帧在断联期间继续等待。现有节点恢复按分区号轮询，活跃存活主需等空分区推进才转LOCAL。实际证据在上述演练readonly-thread-diagnostics，与上一轮新主接管最大40.633秒的情况不同。
- Common最小修复优先选择已有pendingAsyncReplication的存活主分区，随后沿用原完整认证恢复。只新增包内只读调度hint，pending字段改volatile，既有stage/CAS/物理签名/WAL认证/隔离和提交门禁保持。两组内仍按原cursor轮询，活跃分区退休后自然清除hint，空分区继续推进。未引入新RPC/账本/协议/配置。
- 五项调度回归在原顺序下实际两项失败，before.log/xml已保留；修复后五项通过。首次未提供原测试密钥的21项运行有13项Assume跳过，未据此验收。随后带原密钥执行全部16项NodeRuntime、5项调度、1项真实备断联原生演练，22项全通过、0跳过，用时104秒。原生演练还验证LOCAL ACK后包内pending提示确实可见。证据t554-common-pending-recovery-priority-20261112-1701。
- Common只提交本次6个文件，提交677dc0c0851c664f14fca9a6f87e1f4f33221a5c，工作树干净。新候选t554-common-candidates/20261112-1707，JAR19a6252d0bc6b9961294d52c6a448ea1b61b9d8e25b7dca0899ed60cb93c68d0。新的精确JAR优先181项安全测试于17:08:39开始，完整P0尚未通过，验证目录t554-common-verifications/20261112-170831。
- 新串行控制器/tmp/mac-t554-pending-recovery-p0-and-business-20261112.py，PID59800，tool session14930，状态t554-pending-recovery-p0-business-controller-20261112.json，日志/tmp/mac-t554-pending-recovery-p0-business-controller.log。先181安全与完整P0，再新源码fresh/真实RPO，随后自动选择原Robot存活主的对侧Trade节点强杀以复现本次留守阻塞，继续Order A TERM/ORDER_ONLY、Order B KILL/funded、另一Trade TERM/funded，之后正常异步下单撤单与干净JVM10Robot容量。只有精确P0通过才部署。当前唯一在线代仍162543、旧f0精确Common，禁止将源码调度修复描述为已上线/已通过真实留守故障。


### 2026-11-12 17:13 新调度候选181项安全通过，完整P0继续

- 新19a6252d0bc6b9961294d52c6a448ea1b61b9d8e25b7dca0899ed60cb93c68d0精确JAR优先181项安全测试于17:10:41全部通过，含原176与新5项调度回归，完整P0开始。当前不得部署此候选，仍等待13项原生与完整256、多次真实强杀、4100严格/LOCAL、Home/物理一致门禁。
- 主机可用空间约6.8GiB时，对完成的144703和162543构建中167份同Maven原件SHA一致的第三方release JAR执行APFS写时复制克隆替换，保留路径/mode/mtime，排除自产com.app、SNAPSHOT及所有业务卷，活动容器镜像内容不变。主机可用恢复约7.8GiB，清单t554-old-build-dependency-reflink-20261112-171022/manifest.json。未清理WAL/快照或执行Colima维护。


### 2026-11-12 17:30 用户要求性能提前，先做同构建严格/正常异步对比

- 用户最新指示要求尽早发现性能问题，明确授权调整Docker CPU/内存，并继续当前修复。原181项安全已通过的新Common19候选完整P0在原生阶段尚未完成，17:22:35主动中断独立测试以释放同Mac资源，full-p0 exit143，验证保持NO-GO，需之后从头重跑。所有中断对象只限PID59800的隔离验证子树，原业务服务未被该中断脚本选中。证据t554-pending-recovery-p0-interrupted-for-capacity-20261112.json，必要性为避免并行故障验证污染性能结果。PID59800及所属测试进程均已退出，无暂停待恢复控制器。19候选尚未部署。
- 提前性能控制器/tmp/mac-t554-strict-async-capacity-first-20261112-1726.py，PID60896，tool session67004，状态t554-strict-async-capacity-first-controller-20261112-1726.json。复用同一已验证构建mac-demo-build-20261112-162543、精确Common f0完整P0证据、相同最新业务与投影镜像，先fresh干净STRICT_QUORUM，再六组下单撤单与10/50Robot；随后串行fresh干净正常双节点LOCAL_DURABLE_ASYNC，重复相同负载。某容量测量NO-GO仍保留完整报告并测另一模式，启动/控制面异常则停止。严格新代mac-demo-20261112-172512正在初始化，当前阶段尚无新压力数据。
- 性能采样脚本补齐MD、Projection、APS、Login、Admin、Manager、Liq、ClickHouse，与原Order/Trade/Robot/Gateway/MySQL/ZK一同每30秒采CPU、内存与cgroup限流。此前严格50的采样范围遗漏这些服务，旧报告未改写，不能将旧报告当完整资源覆盖。
- 当前Colima默认VM实配8CPU/16GiB，主机10CPU/24GiB，另有原ha-test-sshfs VM运行4CPU/8GiB。只读memory_pressure显示主机空闲比例48%，当前未据此修改内存。现有Order/Trade每容器1.7CPU/2GiB，MySQL仅0.5CPU/1.5GiB，Projection仅0.2CPU/512MiB。旧严格50确实有MySQL cgroup限流，决定两模式均采用MySQL2CPU、Projection1CPU，先保持其余资源与内存一致。该变更属于新对比资源基线，旧严格94数据只保留历史参照，不能把差异全归因于ACK模式。
- 资源驱动/tmp/mac-t554-capacity-resource-plan-20261112-1729.py，tool session35416，状态t554-strict-async-capacity-resource-plan-20261112-1729.json。仅各fresh在4真实业务进程启动后、压力开始前更新两容器CPU上限，验证容器ID/StartedAt/内存未变化，两模式统一2/1CPU。benchmark控制器另外记录全部服务镜像和前后实际资源，后续据实际瓶颈调参复测，当前未声称已取得严格/异步同版性能比较结论。
- 原162543反向Trade故障后的全局只读金融核对另通过，余额14/0/14、持仓12/0/12、4个水位一致、4262前序关联0错，证据ha-trade-b-kill-8_zx9h11/post-fault-readonly-financial-cursor.json。其110.5秒Robot连续性失败继续保留，Common调度修复后仍须新P0与真实重验。


### 2026-11-12 17:44 提前严格压测启动发现投影订阅竞态，已修复并重启同版比较

- 首次性能新代172512在客户基线失败，尚未进入任何压力窗口。实际funded订单已于17:31:10.405产生两条真实QUORUM_DURABLE Filled报告，问题为Projection启动失败导致SQL无订单。Order-only maker也未进入SQL预期状态。17:29:42 Projection的OrderProjectionBinaryConsumer.run初次refreshSubscription调用GwClientWrapper.subscribe时，源连接尚未加入，result.gwClient为空触发NPE，Spring CommandLineRunner失败。已有“Started ProjectionSvr”和“CERTIFIED_TRADE_FINANCIAL_READMODEL_STARTED”日志早于该失败，原部署等待项不能代表整个投影应用已存活。该代自动停止并回滚162543，旧数据保留。
- MySQL2CPU/Projection1CPU调参17:29:36完成，容器ID、StartedAt、内存均不变。该调参让启动时序发生变化，暴露早于源就绪的订阅异常，尚无证据将失败归因于严格提交机制。此轮不是性能结果。原性能PID60896与原资源驱动均已退出，不应再恢复。
- 投影最小修复为Order与Trade消费者run中首次订阅复用既有safeRefreshSubscription，源暂不可用时保留原周期重试与持久源安全轮询，随后自动订阅。未新增恢复线程/框架。两个正常run入口回归在原码均真实NPE，修复后完整源码45项全部通过、0跳过。最初测试IMessage导入包写错导致编译失败，已修正，原日志保留。证据t554-projection-source-startup-race-20261112-1736/before.log、before-retry.log、after.log。根脚本另外38项通过。
- 一键部署现等待Order/Trade投影消费者各自启动完成的两个额外marker。实际新镜像classpath24项全部通过，构建t554-projection-source-startup-image-20261112-1741，镜像local/otc-mac-demo-projection-history:180c3b85802a-79af053fc856，SHA79af053fc856da77f06cb568e909e252186528fbe770be68f8fb9eaa073e034e。
- 原162543构建清单与此前RPO证据保持。通过APFS完整写时复制构建目录派生mac-demo-build-20261112-174400，仅替换投影镜像/哈希，保留images.base-162543.env与projection-source-startup-upgrade.json。Common f0、Order、Trade、MD镜像完全相同，后续严格和异步都使用这份派生构建进行公平比较。
- 新性能驱动/tmp/mac-t554-strict-async-capacity-first-20261112-1744.py，tool session72874，状态t554-strict-async-capacity-first-controller-20261112-1744.json，于17:42:27开始严格新代174227。新资源驱动/tmp/mac-t554-capacity-resource-plan-20261112-1745.py，tool session31687，状态t554-strict-async-capacity-resource-plan-20261112-1745.json，仍为两模式统一MySQL2CPU/Projection1CPU，内存未更改。尚未进入新压力窗口。
- 诊断时一条失败Demo租户的会话标识出现在工具记录，该失败代172512现已停止，测试交易与Broker API密钥已按失败清理撤销，文档不保存标识正文。此前历史Demo恢复接口私钥进入工具记录的事件仍以原说明为准，后续全新部署继续轮换恢复接口密钥。


### 2026-11-12 18:25 严格10/50新性能结果，正常异步正在同版测试；定位撤单查询空窗

- 新代174227严格模式、派生构建174400、Common f0、投影79af、MySQL2CPU/Projection1CPU，于17:49:42完整真实业务基线通过。17:49:45开始下单撤单。ORDER_ONLY并发1/4/8分别完成454/656/688循环，7.558/10.905/11.367循环每秒，下单New P99为143.273/375.530/677.914毫秒，撤单消失P99为191.393/274.683/439.755毫秒，三组均通过且无残单。8并发吞吐接近4并发，但尾延迟继续升高。该范围是单租户热点分区，含50ms轮询观察时间，不能当全256分区最大吞吐。
- funded并发1在8.722秒、48成功循环后一次撤单API异常，清理重试成功，测试保持NO-GO，funded4/8未执行。失败订单T554CC-7b27a438-TRADE-1-0-48，17:53:39.287真实ORDER_COMMON_CANCEL_OUTSIDE_AUTHENTICATED_SCOPE，原日志已脱敏保留order-cancel-7b27a438-failure-redacted-log-audit.json。后续只读SQL复核该单和早前Pending单均Cancelled，账户10000、used/freezed/fee均0，证据failure-readonly-followup.json。不能将其8秒短样本视为通过的完整60秒性能组。
- 严格10Robot五分钟已通过，419笔成交、420次Tape请求，1.397成交每秒。419配对成功样本P50/P95/P99/P99.9为126.328/214.529/260.469/509.701毫秒，419在窗内完成、1未在窗内观察到成交。资金30/0/30、持仓23/0/23、10水位一致、2396条前序关联0错。Order/Trade/MySQL CPU限流增量0。证据174227/robot-steady-10-095942.json，报告含实际测量脚本SHA4f12b3750a7cb6c42fbf996c32b74e349d60feb80c8ea970067149c38d5634a0。
- 严格50Robot实际18:07左右至18:12:38五分钟、50全部RUNNING且控制代稳定。3888报价、2061Tape请求、1765成交，5.883成交每秒，1760配对样本P50/P95/P99/P99.9为1104.988/3040.047/5744.653/7603.020毫秒。资金110/0/110、持仓103/0/103、47水位一致、23083前序关联0错。脚本passed=true，但延迟数秒，生产性能不达用户预期。CPU峰值Order A/B154.1%/127.53%，Trade B/A64.04%/62.86%，MySQL59.46%且无限流，Projection27.55%且限流0.01秒。Order A/B限流增量2.946/1.351秒，Login/Manager分别9.138/10.501秒。不能仅凭这些计数认定唯一瓶颈。
- 单独对严格50原请求逐单复核已保存strict-50-terminal-readonly-audit-20261112.json，观察至停代前最多窗口后60秒，2061原请求中1764见Filled、205见Cancelled、92未见已发布终态，源订单日志有101次ORDER_MATCH_MULTI_MAKER_REQUIRED文本，后者是日志出现次数并非去重请求数。92条仍需用原WAL或原SQL状态证明实际状态，当前不能把缺少发布日志直接等同资金丢失或订单一定仍开着。多maker/部分taker仍是已知业务规划缺口，完整业务GO继续未完成。
- 同一性能驱动62990于18:13:22自动串行fresh正常双节点异步代181322，于18:21:18完成真实基线、同镜像与同CPU/内存配置核对。18:21:21开始异步下单撤单，初始OO1并发7.844循环每秒、New P99 185.989ms，OO4并发9.937循环每秒、New P99 493.664ms，完整异步6组与10/50仍在执行。不能据当前少量组宣称异步已提升性能。
- 撤单源码定位为OrderStateRecovery结构变化（含New转Maker）先OrderManager.removeOrder、再addOrder，remove先从全局ID索引删除，未加读锁的认证scope检查可能短暂查不到已提交订单。新确定性book回归在原码真实观察到全局lookup为空而失败。首次测试用了不存在的无参OrderBook构造器导致编译失败，已改正确三参构造，再次运行2测试1失败，before-retry.log保留。修复为Common已提交after-state先对原全局ID条目CAS原子替换，再更新Book索引，沿用原分区屏障及完整scope约束。只更改OrderManager、OrderStateRecovery与原测试类，不更改Common/认证合同。目标2测试通过。
- 该修复位于源工作树和t554-order-atomic-lookup-validation-20261112-1812，当前压力镜像尚未包含，故两模式比较仍一致。完整189项第一次有1项因未传原RSA测试密钥参数而失败、2项原有跳过，其余通过，尚不能据此报告全套回归完成。需带otc.demo.existing.keys在所有压力窗口结束后重跑。为避免测试混入测量，18:20只暂停性能父控制器等待下一阶段，fresh子进程照常完成，全测结束已在finally恢复，full-test-controller-guard.json resume_required=false，无暂停待恢复控制器。
- 测量脚本在任何新压力窗口开始前补充窗内完成/未观测完成/窗口前发起成交的分开计数及报告自身SHA，两个模式实际用同一SHA。控制器预启动记录的脚本SHA早于最后这几个报告字段，实际结果中的measurement_source_sha256为最终版本，独立finalized和counter selftest证据已保存。后续没有修改正在运行的测量脚本。P99仅来自成功配对的成交，未成交终态与错误需要独立核对。

### 2026-11-12 19:40 Capacity ended, storage emergency maintenance in progress

- Same-build async order/cancel all six groups passed. Async 10-Robot five minutes: 758 fills, 2.527 fills/s, 757 paired P50/P95/P99/P99.9 = 91.919/229.417/394.228/836.818 ms, financial differences zero. Closed-loop offered loads differ between strict and async, so this does not isolate ACK-mode latency at a fixed arrival rate.
- Async 50 did not reach all-ready and has no qualified steady window. Startup last-five-minute 4.607 fills/s and P99 13992.134 ms are diagnostic only. Original benchmark controller has ended. Existing normal 10 cohort should be preserved, added 40 stopped through normal Manager API after recovery.
- Host free space fell to about 120 MiB at 19:02. Robot paused. Deleted only >24h regenerable Homebrew download cache, 273465636 bytes, with manifest. Host then had about 1.3 GiB free. Host 24 GiB RAM, VM allocations total 24 GiB, swap used about 8.5 GiB. Guest data filesystem still had 5.4 GiB free, but kernel shows root vda and data vdb WRITE EIO, vdb aborted journal and read-only remount. Multiple services unhealthy because exec has I/O error. Financial queries are unavailable, data integrity is not yet certified.
- First maintenance controller failed at Docker restart-policy update due metadata EIO. It made no VM stop, disk clone or memory change. Original container identities, images, mounts, restart policies and kernel log preserved in t554-default-vm-maintenance-20261112-192935. New storage recovery script /tmp/mac-t554-storage-recovery-stop-preserve-20261112.py attempts orderly load/voter/app/database shutdown, then default VM stop, then APFS original disk preservation. Live status storage-recovery.json in that evidence directory.
- User already authorized resource tuning and brief same-Colima maintenance. Planned default VM remains 8 CPU, reduces RAM 16 to 12 GiB, aligns disk config to already-existing actual 150 GiB. Other ha-test-sshfs VM contents unknown because SSH failed, not stopped or deleted. Maintenance interruption excluded from Robot continuity acceptance. Overall NO-GO. No original disks cloned yet at this entry time.

### 2026-11-12 20:12 Storage maintenance and serialized fresh replacement required

- Default VM stopped normally at 19:39. OS 20 GiB and data 150 GiB original raw disks retained unchanged as disk.original-at-stop and datadisk.original-at-stop under t554-default-vm-maintenance-20261112-192935. Expected disk paths are distinct-inode APFS COW working clones, size and sampled first/middle/last 6 MiB equality checked, not full-file hash verification.
- Retired dc-saas-runtime-clean-20261016/log had no original active container mounts. Fully compressed and SHA-verified decompression for 184 regular files older than Nov 8, then removed only matching original files. 10280714403 original bytes -> 763062720 compressed bytes. Manifest legacy-log-compression.json. Retired T367 inactive MySQL binlog.NUMBER files also compressed/fully SHA-verified, excluded keys/index/data tables; t367-inactive-binlog-compression.json. Original current-generation data retained.
- Default VM now 8 CPU/12 GiB, disk config aligned to existing 150 GiB. First startup took about five minutes in ext4 journal recovery. Original-only restart quarantine missed historical containers, leading to historical autostarts and guest OOM. All Docker/containerd services subsequently stopped. Offline inventory found 1605 containers. Every original hostconfig backed up, only RestartPolicy changed to no with equality of all other fields checked. Historical containers remain stopped with restart=no. Restore only original 27 prior-running container identities. Maintenance/autostarts/OOM excluded from all continuity and performance acceptance.
- Offline unmounted /dev/vdb1 e2fsck -fn returned4, orphan-list and extent errors. Conservative -p refused and required manual repair. Four damaged extent inodes mapped to retired otc-t399-services-data MDSvrA/B/C OHLC market/trade LevelDB logs. No claim all current files are sound merely from this mapping. Original disks retained. Repair used -fy -E fixes_only and an e2undo file, exit1. Second offline -fn completed exit0. Filesystem check proof is not a financial data reconciliation.
- Remounted original data and started Docker with all historical restart policies disabled. Only original current services restored. MySQL/ZK/ClickHouse healthy. Normal Manager STOP successfully disabled 39 still-enabled added pressure Robots, preserving original passing10; one other added worker was already excluded from enabled listing. Robot and Liq remain stopped, with no forced quote/order deletion.
- Four current Common voters could not start on original persisted data. Redacted actual errors include Order A pending or unknown custody file head.pending and Order B Common physically fsynced WAL head mismatch. Automatic restarts disabled and voters stopped. No pending file removed, no head/CAS/physical proof overridden. Original181322 generation remains NO-GO and preserved. Following user authorization and AGENTS fresh-first policy, next step is serialize a fresh generation on this same VM using fully verified f0 Common plus latest validated business fixes, retire current namespace, then resume real business/performance.
- Root deployment script adds minimum8GiB host backing-store space alongside existing2GiB guest check, disables restart policies for retired/failed containers before stop, records old policies and restores exact on-failure retry limits on rollback. New targeted storage/policy tests plus existing test_mac_* total43 tests PASS. Main normal deployment entry point still needs actual fresh verification. Latest Order atomic lookup fix full suite with real fixture keys remains to rerun before image build. Common19 candidate still not deployed and needs full P0 from scratch.

### 2026-11-12 20:38 Latest business build and automated performance continuation

- Latest build mac-demo-build-20261112-201300 completed using exact fully verified f0 Common. Shared52/Order189/Trade226/MD207 total674 tests, no failures, Order2 pre-existing skips. Real fixture RSA keys supplied. Projection exact image24 tests passed, same79af image with previously full45 source tests. Shared JAR a76a1404d6f53a822e5208ef55de2ebc77935b4c7a36c48170cdc48dcdaa28ae, new Order image includes atomic lookup fix. Initial direct shell script invocation failed permission126; explicit bash fixed it. Build then stopped because reviewed MD base env was omitted after successful Shared/Order/Trade steps. Remaining canonical MD/Projection functions resumed with exact reviewed old MD image, source script/resume SHA in resume-build-plan.json. Builder now validates required MD base before starting work. Completed results were retained, not claimed as a single uninterrupted build.
- Idle Common candidate third-party release dependency COW dedup585 files and idle workspace/latest-completed-build dedup330 files preserve bytes/fullSHA/mode/mtime and original Maven files. Application/Common JARs, physical ACK fixtures and sealed proof files untouched. Manifests t554-common-candidate-dependency-reflink-20261112-201836 and t554-workspace-dependency-reflink-20261112-202211. Host free recovered about11GiB before next fresh.
- New controller /tmp/mac-t554-post-storage-capacity-controller-20261112-2026.py PID recorded in t554-strict-async-capacity-first-controller-20261112-2026.json, tool session34331. Resource helper /tmp/mac-t554-post-storage-resource-plan-20261112-2026.py, tool session76739, same MySQL2CPU/Projection1CPU in both modes. VM8CPU/12GiB is a new round distinct from prior16GiB. Per-phase host storage sampling every5sec, abort/pause own Robot/Liq load below4GiB, deployment/fault entry guard8GiB host and2GiB guest. Current pressure scripts must not be edited while running. No background Maven/Common P0 during qualified pressure.
- New strict generation mac-demo-20261112-202659 passed real physical initialization and signed SDK/ORDER_ONLY/funded/IOC-FOK financial baseline at20:33:19, fresh376sec. Balance6/0/6, positions6/0/6, source cursors exact. Original181322 remains retained failed data and is no longer active. New real trading is restored on a fresh dataset under the user's fresh-first authorization, not a restoration/certification of original corrupted data.
- Strict order/cancel began20:33:22, OO1/4/8 all passed (9.250/12.653/13.101 cycles/s, NewP99 77.418/312.996/521.486ms). Funded groups still in progress. Automatic next stages 10Robot,50Robot, excluded-window thread diagnostics, then serialized fresh async and same tests. Added memory/IO PSI, disk counters and host storage/vm_stat to new measurement snapshots. Diagnostic jstack snapshots are outside qualified windows, no fsync percentile inferred from them. Prior temporary strace binary is no longer present, so no strace result claimed.
- Order batch cancellation source has a separate prepared race fix. Old batch scope check occurs before waiting for per-order/partition locks. New source rechecks live state/scope inside existing stripe->partition order, rejects vanished/terminal/out-of-scope IDs while retaining fail-closed financial uncertainty. Four deterministic tests prepared, before/after Java snapshots in t554-order-batch-scope-validation-20261112-2036. NOT TESTED, NOT DEPLOYED, does not alter this same-build strict/async comparison. Run old-red/new-targeted/full tests only after qualified load window and before a subsequent image upgrade. No Robot feed fix has been made; earlier WAITING_MARKET_DATA may reflect an unfinished first cycle or scheduler blocking, needs actual stacks rather than inferred feed failure.


### 2026-11-12 22:40 同机维护后性能仍 NO-GO，恢复优先级修复进入完整 P0

- VM 已调整为 8CPU/12GiB，数据盘实际 150GiB。202659 严格新代完成六组下单撤单，ORDER_ONLY 并发1/4/8为9.250/12.653/13.101循环每秒，funded为6.520/9.072/9.326。严格10 Robot合格五分钟536笔、1.787TPS，成功配对P50/P95/P99/P99.9为105.408/141.934/288.606/517.266ms，资金持仓和6042条前序关联零差异。该延迟范围为Trade Newing入口至Order Filled发布，完整客户端成交回执延迟尚未测量。
- 第一轮严格50完成窗口后被部署级8GiB空间检查中断，未保存完整报告。脚本已将压测准入空间设为4GiB，窗口后继续完整物理身份与ACK检查、跳过重复空间准入，部署/故障仍要求8GiB。第二次严格50实际五分钟1874笔、6.247TPS，1865配对样本P50/P95/P99/P99.9为1062.058/14550.185/28929.771/31785.976ms，765个请求未在窗内观察成交，9个成交缺窗内入口。资金/持仓各110项及92317前序关联零差异，但49 RUNNING、1 STALE_RUNTIME、最大成交间隙133.47秒，NO-GO。其JVM经历清理/故障恢复，不能作为干净同条件ACK模式比较。
- Robot就绪检查已识别RUNNING但runtime_owner缺失或租约过期的STALE_RUNTIME。最新压力与存储生命周期48项脚本回归通过。资源采样增加主机空间、内存、客机CPU/内存/IO压力和块设备计数。块设备计数均值不能代表fsync百分位。原async10为2.527TPS、P99 394.228ms，async50尚无合格窗口，两模式闭环到达率不同。
- 已完整保留原容器元数据，并对1128个非保护代的已停止容器先压缩、逐文件SHA及解压SHA验证日志，再使用Docker rm且不带-v，所有卷保留。证据t554-guest-docker-cleanup-20261112-2107。202659/181322/174227受保护。重启策略隔离已写入正常fresh退休和回滚路径。
- 202659已停止四个Order/Trade及两见证、restart=no，Robot/Liq暂停。Ready卷先完整归档623030902字节，SHA ef01812051fea35ba3a617ed29e7c3e86ca692c742916cac00a6f59c6ad73df9，344129文件逐一完整SHA/权限/属主核对，完整gzip读回，再清空原卷内容。证据t554-retired-202659-archive-20261112-220847/verification.json与cleanup.json。当前Order/Trade处于维护停服，不能恢复暂停负载到已清空旧卷。原181322故障数据和停止时两份原始raw盘仍保留。旧代072730与Nov9已停止MySQL binlog也经过完整压缩解压SHA验证后归档，当前主机可用约13GiB。
- 新Order批量撤单竞态修复已完成真实旧码3项失败、新码定向及完整193项通过、2项原有跳过。现有201300镜像尚不含此修复。路径t554-order-batch-scope-validation-20261112-2036。修复在原stripe到partition锁序内重查scope，已消失/终态/移出租户范围返回拒绝，Trade不确定性仍保留Pending并失败，不放松认证。
- Common提交8288c4fbe68253d3ae9c38f9a498dacc06fc5c27，在既有轮询选择器中优先处理真实签名认证的poison恢复，避免空闲正常Home回归阻塞健康业务分区。继续保留失败候选轮转、防外来poison通知饥饿、物理ACK及CAS合同。原677异步pending优先逻辑也包含。定向23项全通过，包括双poison真实恢复和外来通知不阻塞另一分区。没有新增恢复框架/证明/开关。
- 新候选t554-common-candidates/20261112-2232，JAR ebd808a3b45838329612db7e8c7409ab9c6d016da0d3e5e130d6e85ab92a15ec。181安全测试通过，22:36:54进入完整P0，验证目录t554-common-verifications/20261112-223437。状态t554-poison-priority-p0-business-controller-20261112-2232.json。P0尚未通过，不能业务部署该候选。
- 控制器在完整P0通过后自动fresh-verified构建最新Order193等业务、正常双节点异步真实RPO、四个Order/Trade A/B故障与连续Robot验证，再测恢复后下单撤单和10Robot。这些恢复后窗口独立标记，之后仍需干净JVM严格/异步同版比较。总体NO-GO。
- 两轮20秒strace只采fsync/fdatasync，未采载荷/私钥，位于202659/fsync-diagnostic-20261112-213903与214907。包装器将Colima外层exit1/内层预期timeout124误标NO-GO，原记录保留待离线解析；四个被观测PID/StartedAt未变化。这些数据在资格窗口外，有附加观测开销，不能当无观测生产SLO。jstack仅四核心有效，其他四目标因JRE无jstack或Java不在PID1未成功，未声称八容器栈完整。


### 2026-11-12 22:57 异步物理故障门禁13项通过，开始全256分区演练

- 精确候选ebd808的完整RSA快照验证和13项真实进程poison/租约/异步RPO测试通过，耗时1129.664秒。真实异步主强杀证明backupCommittedHead=1、abandonedLocalHead=2，旧主WAL及备节点原提交前缀不变，inflightTailExcluded=true，最终home128Each=true。该结果仍只是完整P0的一部分。随后全256分区、4100记录、双向强杀、第三次强杀、重复回主与中断回归正在运行，完整seal尚未PASS。
- 两轮fsync原始记录已离线按线程ID连接unfinished/resumed，逐调用strace elapsed取nearest-rank百分位，保留信号/结束时未完成调用计数。解析v1把信号误当未解析行，保留原件；v2为DIAGNOSTIC_TRACES_PARSED。213903四核心P99为7.017/7.288/7.713/7.930ms，214907为16.585/16.507/13.790/18.611ms。所有成功样本以及按路径聚合见原目录parsed-fsync-diagnostic-v2.json。只含成功完成的调用，采样结束未完成另记，无未匹配resumed/覆盖的unfinished。带strace开销且四进程同时采样，不能用作无观测生产分位值或单独证明几十秒排队的原因。
- 容量脚本先将实测窗口/资源样本以passed=false、MEASUREMENT_COMPLETE_VALIDATION_PENDING写入JSON，再执行窗口后控制、日志和财务核验，最终原子替换。新增真实入口mock回归证明后置控制失败时仍保留原始资源证据，49项脚本回归通过。
- 新脚本scripts/verify-mac-demo-execution-capacity.py准备固定速率0到10单/秒、60到300秒、最多900单的签名HTTP发单到私有WebSocket最终成交推送测量。独立自审批租户、受认证CUSTOM价格、funded产品、一笔预挂足量maker、16并发上限、不重试模糊写入。报告HTTP ACK、客户端收到成交、含调度等待、错过/重复/窗口后成交和SQL逐单/资金校验，清理本轮订单与API key。单租户热点范围不代表全分区容量。尚未真实运行，不能宣称SDK测量已验证。两项解析/缺失样本回归加现有共51项通过。运行前需完整Common P0和新业务部署就绪，并与故障/构建窗口隔离。


### 2026-11-12 23:09 提前干净异步性能窗口排程

- 新辅助驱动/tmp/mac-t554-early-clean-async-capacity-guard-20261112-2306.py已启动，状态t554-early-clean-async-capacity-guard-20261112-2306.json，tool session40307。此前nohup后台方式未产生进程或状态文件，已改前台受工具会话管理，当前实际运行。
- 只在主控制器完成精确P0并启动fresh-verified子进程后，暂挂本次测试父控制器，fresh构建/部署/完整客户基线子进程继续，业务JVM不暂停。确认fresh子进程退出且完整业务成功marker后，提前执行干净异步六组下单撤单、固定速率客户端1/5/10单每秒各60秒、10/50Robot。期间不进行故障/构建/额外采样器。固定速率工具只停止自己新建租户的试用Robot，其余背景cohort保留。
- 主控制器暂挂责任由JSON的parent_resume_required显式记录，辅助驱动finally恢复。50测完通过正常Manager robotControl STOP只停掉本轮新增且核实属于T554 Demo Capacity的额外40租户，保留合格10，再恢复主控制器原RPO和四业务故障序列。若10未通过不准入50。host4GiB/guest1.5GiB动态负载保护，部署/故障8GiB门禁继续。严格同版干净窗口仍需随后执行，尚未完成。


### 2026-11-12 23:32 精确Common完整P0封存通过，最新业务构建完成

- 23:30:19精确828/ebd808完整P0成功退出0，t554-common-verifications/20261112-223437/status为PASS，verification.seal.json核对same candidate/fixture revision、normal_dual_async=true、interrupted_local_rearm=true、双向及重复Home=true、256对WAL与snapshot。13真实故障1129.664秒，全256扩展2035.055秒，实际第三次强杀和重复回主、跨Epoch退休前缀通过。未跳过或放宽物理ACK。
- 23:30:20进入正常fresh-verified，候选最新业务构建mac-demo-build-20261112-233020用时110秒，business_unit_tests=PASS。实际Shared SHA5b84faf5cb5020aedc6b053742169b79cd0a2ea99a0568ebf5942f5670d32461，Order2e7b98095e99、Trade492866ade255、MD075263aeeb55前缀，Common均ebd808。精确Projection79af复用。新代233020仍部署中，业务基线尚未通过。
- 早期异步性能辅助驱动94034已在fresh子进程94827运行期间暂挂父控制器92324，实际ps状态T。parent_resume_required=true。仅暂挂本轮控制器，构建/部署子进程继续执行，当前阶段没有正式性能窗口。辅助驱动finally负责SIGCONT恢复父控制器，主状态文件尚停在fresh阶段属于预期。勿重复启动控制器或手动恢复使故障并入性能窗。


### 2026-11-12 23:40 原Mac最新233020恢复交易，干净异步压测正式开始

- 同机串行fresh233020完整基线通过，构建110秒，物理启动及业务380秒，客户业务106秒。实际SDK签名funded双方成交、ORDER_ONLY、未成交IOC/FOK正常取消、MD公有trade与唯一真实ExecID关联通过。两个Robot真实Tape24个成交回执，资金6项、持仓6项、源头/投影水位零差异，尚无业务HA验收。
- 新构建精确Common828/ebd808，Shared52、Order193（2原有跳过）、Trade226、MD207合计678项0失败，Projection79af复用精确既有验证镜像。Order镜像包含批量scope屏障竞态修复。
- 辅助驱动23:38:33开始干净异步六组下单撤单，随后固定速率端到端和10/50Robot。主控制器92324仍T等待，resume_required责任在辅助驱动94034，期间无业务故障、Maven或strace。host约12GiB、guest约13.7GiB，存储保护持续。当前真实交易已在新数据集恢复，原181322仍保持故障证据与NO-GO。


### 2026-11-13 00:10 最新异步业务性能结果与测量接入修正

- 233020干净异步六组下单撤单全部通过，无残单。OO并发1/4/8为9.667/12.437/12.770循环每秒，New P99为82.021/295.360/545.683ms，撤单消失P99为113.747/217.946/351.527ms。funded为8.906/10.949/11.360循环每秒，New P99为99.243/398.607/713.250ms，撤单消失P99为66.648/289.629/357.899ms。同一租户热点，不是全分区最大容量。
- 异步10Robot五分钟报告robot-steady-10-155227.json PASS，669 Tape请求、668成交、2.227TPS，服务内Trade Newing到Order Filled P50/P95/P99/P99.9为78.634/167.201/311.260/520.460ms，1请求未在窗内观察到成交。42资金/31持仓及8457条前序关联零差异，13源Epoch范围均E2，10全部RUNNING。
- 最初三次客户端工具准备失败，SDK缺可选websocket-client依赖，均未进入发单窗口。按已部署SDK0.1.9元数据的realtime约束>=1.7,<2下载并安装1.9.0到原SDK目录，wheel完整SHA与安装目标保存233020/sdk-realtime-install-20261112.json。系统旧pip不支持--report，首次安装未改任何依赖；改下载wheel再安装并自建SHA清单。新增依赖预检在创建租户之前执行。
- 23:46手工暂挂辅助控制器94034，原92324也仍T。execution-measurement-debug-controller-guard-20261112.json resume_required=true，防止50窗口与测量修正混用。其已运行10Robot子进程照常完成。一次手工客户端尝试撞该10Robot锁而BlockingIOError退出，未产生新租户/负载。工具脚本仅在无该工具运行时修改。
- 首次真正客户端60单均成功推送、SQL逐单一致，P50 69.287/P99 435.169ms，但清理调用原cancelAllOrder触发ORDER_COMMON_DURABLE_BATCH_NOT_CONNECTED，整体NO-GO。证据execution-capacity-993ba17a.json。该质量缺口真实存在，未移除安全拒绝。残留本轮maker少量未成交余额，需要正常单撤清理，原密钥已撤销，勿假称整轮通过。一次只在内存从本轮日志提取候选会话尝试正常认证readback未通过，未执行撤单、未输出或保存会话，execution-993ba17a-owned-maker-cleanup-20261113.json保持NO-GO。
- 工具清理现逐单查询本轮前缀并走已接通的SDK单撤，避免在未发单准备失败时发清理写入。批量全撤业务缺口仍须单独修复验证，不能用此工具调整宣告mass-cancel通过。新固定1单/秒60单报告execution-capacity-c289a6bc.json PASS，客户端P50/P95/P99为77.167/112.893/160.854ms，无重复、缺成交、残单/清理错误，SQL和资金一致。
- 固定5单/秒300单execution-capacity-6e924898.json PASS，客户端P50/P95/P99/P99.9为80.942/222.702/584.594/779.636ms，300均窗内成交、无调度丢弃、清理和资金校验通过。当前10单/秒测试进行中。客户端修正重跑在合格10Robot背景负载下，后续严格同版比较需匹配同样背景。host约9.2GiB，50前需要重新确认余量。


### 2026-11-13 00:18 固定10单每秒证实健康E2队列拥塞，正常清理完成，50Robot继续

- execution-capacity-ecd54564.json为干净双节点异步、背景合格10Robot、固定10单每秒60秒。600 HTTP接收确认，无调度丢弃，窗内415个最终成交，加最多30秒尾部等待共收到512个，配对客户端P50/P95/P99/P99.9为10401.931/18616.723/22447.383/35248.465ms，控制前后Order2/Trade2不变。工具仍NO-GO，不能把窗口后或未收到客户端回执计成合格延迟。清理一次单撤响应9000，原记录保留。
- 两个30秒间隔资源样本内，OrderA/B峰值73.32/46.26%，TradeA/B23.45/37.55%，四核throttled_usec增量均0。MySQL8.22%、Projection3.12%、Gateway32.39%，客机MemAvailable约4.7GiB、memory PSI avg10=0，IO full avg10约3.39到6.92%。样本有限，不能排除未采到的瞬时CPU峰值，但当前无核心CPU配额耗尽证据。
- 失败工具两轮993ba17a、ecd54564均已正常清理核对，证据failed-client-runs-normal-cancel-reconciliation-20261113.json为OWNED_FAILED_RUNS_CLEANED_AND_FINANCIALLY_CONSISTENT。只读取这两个本轮自建账户的原持久WEB/API会话到内存，通过原认证queryOpenOrder/cancelOrder，未打印/保存会话、未造身份、未改密码或绕开ACK。四账户都无开单、无冻结保证金及手续费，真实已成交持仓继续保留，金融源/投影一致。前一次993ba单撤HTTP成功后SQL/余额尚未追上，后续已等到完全一致，不用早期Partially_Filled回读冒充终态。
- 单独窗口外逐单复核execution-ecd54564-late-readonly-reconciliation-20261113.json确认原600全部最终Filled且各1个执行。原测量仍NO-GO，晚到数据不能回填客户端原P99，也不能把其解释成丢单。
- 00:15:18至00:16生成目录t554-codex-generated-dependency-reflink-20261113-001518，68个闲置Codex工作目录/完成233020构建内的第三方release依赖，以原Maven文件APFS clone逐文件全SHA验证替换，内容/路径/权限/mtime保留，应用Common JAR与封存证明均排除。主机空闲约8.8GiB恢复13GiB。两份原raw停止时备份继续保留，未删除。该去重在合格客户端窗口结束后、50窗口之前执行。
- 00:16:59恢复辅助控制器94034，手工execution-measurement-debug-controller-guard-20261112.json resume_required=false。它已收取合格10Robot结果并保留原10名单，继续robot50。原92324仍预期暂挂，由辅助驱动finally恢复RPO/四故障。当前无手工待恢复性能控制器；自动父恢复责任仍在t554-early-clean-async-capacity-guard-20261112-2306.json的parent_resume_required。
- mass-cancel实际ORDER_COMMON_DURABLE_BATCH_NOT_CONNECTED业务缺口仍未修复。端到端工具现只对自身前缀查询后正常逐单SDK取消，正常1/5单每秒两轮清理无错误。两项工具单测再过，完整脚本此前51项通过。目标仍NO-GO，严格最新同版窗口和新Common下真实四业务故障尚未完成。


### 2026-11-13 00:31 异步50全部正常，进入正式窗口，定位配额与阻塞线程耦合

- 50Robot于约00:29全部RUNNING，开始无构建/无profile五分钟窗口。之前49 RUNNING、1 XXWVCF WAITING_MARKET_DATA持续预热，没有人为STOP/START该工作者。预热期间一次Robot线程转储按实际Java PID7发送SIGQUIT，仅生成线程栈，容器ID/StartedAt不变，不是重启。首个诊断因主类猜错RobotSvr而assert退出，finally恢复容量子控制器，未发信号；第二次使用真实com.app.dc.robot.RobotSvr成功。robot-warmup-threads-20261113-002601/guard.json resume_required=false，容量子进程973已恢复。
- 实际8个robot-worker都在同步等待Gateway请求，含place/cancelBatch/openRobotOrders。随后同机OrderA/TradeA jstack成功，身份不变，仅在预热、正式窗口之前采集。对应核心栈与thread-role-counts.json同目录。OrderA的8异步复制线程里6个awaitPeer、1个本机receipt ledger force、1个custody文件open，8个业务线程awaitAsyncReplication。先前口头称8个都等备节点不够准确，已向用户更正为6远端+2本机I/O。
- DirectNettyReplicationServer按max(2,min(8,availableProcessors))创建阻塞持久化工作线程。当前Order/Trade均1.7CPU配额，对应实际各2个durable handler。它们负责阻塞落盘及凭据RPC，异步复制池固定8，并且每分区只允许一个未完成副本复制。源码证实下一次commitThenApplyAsync会等待前次pending复制，保持现有精确头认证合同。该结构限制高负载吞吐，异步不代表下一次写入完全独立于备节点。
- 已决定当前原配额基线结束后把四核心容器CPU配额提高4核，保留VM总8CPU/12GiB、既有内存、安全和代码SHA。已有JVM线程池已初始化，单纯docker update不会重建线程池，需利用原计划四节点故障/滚动回归产生的新JVM验证实际线程数，再做同配额两模式干净比较。尚未执行CPU更新，不得把当前50结果当4线程配置。


### 2026-11-13 00:41 原配额异步50 NO-GO，4CPU参数已审核，已恢复RPO主流程

- robot-steady-50-163351.json五分钟1733成交、5.777TPS，1710配对服务内P50/P95/P99/P99.9为563.140/3767.563/6014.271/91228.435ms。1903 Tape请求、193未窗内成交、23成交缺窗内入口。Control始终Order2/Trade2，未主动故障。47RUNNING/3STALE_RUNTIME、49posting_locations，XXWVCF最大成交间隙299.965秒，整体NO-GO。138资金、119持仓、59365前序关联全部零差异，52源Epoch范围均未变代。
- 正式五分钟没有Maven、strace、源码部署或CPU参数变更。此前预热Robot/两核心栈在正式窗口开始之前完成。容量父控制器94034被手工暂挂等待原配额子进程正常结束，子进程973未被停止，CPU参数在其退出Z后更改。cpu-tuning-controller-guard-20261113.json现resume_required=false。
- reviewed-core-cpu4-20261113/evidence.json证明四核心实时CPU1.7->4，容器ID、StartedAt、内存不变，没有重启；每个config-hostready的voter-launch.json仅CPU flag值1.7->4，原全文备份及前后SHA保存，其他JSON字段相等，避免后续滚动替换又恢复旧1.7配额。当前已有JVM的durable handler仍2，计划内重启后需核验4。下一次fresh也按正常入口继承当前4CPU。
- 50轮额外40Robot通过正常Manager STOP，等待全部原运行owner释放，保留原合格10。added-forty-normal-stop-owner-drain-20261113.json为ADDED_FORTY_STOPPED_AND_ALL_OWNERS_RELEASED_KEEP_TEN，00:40核对10全部RUNNING。未重启Robot/Liq，未手动修改runtime_owner或业务数据。
- 第二轮第三方依赖APFS clone在资格窗口结束后完成，t554-codex-generated-dependency-reflink-20261113-003801，排除首轮68路径，新增81个文件，完整SHA/模式/mtime验证，主机可用恢复15038615552字节约14GiB。两原raw备份仍保留，原Common候选/封存证据未改。期间没有正式性能窗。
- 00:40:11恢复辅助94034，它正常结束且parent_resume_required=false。原主控制器92324已恢复并于00:40:13启动business-rpo，随后按原顺序四个Order/Trade故障、恢复后业务测试。所有手工暂挂责任均已清除。主状态fresh阶段的23:30到00:40包含人为插入的早期性能窗口，不能当成部署耗时，实际正常构建110秒、物理+业务380秒以fresh子日志为准。
- 后续4CPU两模式干净比较还没执行。现有原配额异步1/5/10固定到达率结论保留，不能跨资源配置声称调参收益。mass-cancel、multi-maker/partial-taker/FOK不足量等业务缺口仍需完成，整体NO-GO。


### 2026-11-13 00:53 RPO准备竞态修复及观测时钟修正后继续

- 原2232主控制器00:41因async-rpo-944ac8a2准备失败退出NO-GO，没有注入任何节点故障。Manager审计证明RLP1YL于00:40:23.593 STOP时before/after enabled都false，初始化工作器随后00:40:23.600正常ENABLE为1。原测试仅等Robot行存在，误把CREATE_ROBOTS到ENABLE之间的禁用行当作完整就绪。修复是共用stop_trial_robot_after_bootstrap，等待dc_tenant_liquidity_bootstrap COMPLETE后正常STOP并等待enabled0+owner释放；同样复用于客户端测量工具，保留RPO原cohort/无开单检查。未修改Bootstrap、Owner、ACK或运行数据。
- 新两个回归证明PENDING/ENABLE阶段绝不STOP、COMPLETE后才STOP且等原owner释放，首次测试漏导入Mock导致2项NameError，修正导入后53项全过。失败准备租户RLP1YL用正常Manager会话停止，10原Robot全RUNNING保留，setup-normal-stop-cleanup-20261113.json已保存。没有修改密码或直接改SQL业务状态。
- 0050续跑控制器4624在同233020、同ebd808、原HomeE2、4CPU元数据上重试RPO，async-rpo-3ffa1d43准备成功后，于暂停备节点期间未在原0.75秒总预算观察到最终回执而NO-GO。没有强杀Primary，独立看门狗自动解除备节点pause，交付线程/scheduler已RESUMED，Home和Robot原进程保持。原pause总计3.456869秒，旧预算从Docker pause调用之前开始，包含主机Docker操作及日志轮询开销，不能作为客户端成交延迟样本。
- 测试观测时钟现从Docker暂停及交付释放调用结束后单独开始，观测2秒，独立备节点暂停看门狗4秒。严格核验现有生产Node lease 15000ms至少为看门狗3倍，未改任何租约/业务超时。仍必须在备节点实际Paused时看到带LOCAL风险的原最终回执、强杀原Primary退出137、备节点原物理提交头保持不变，后续512对真实WAL/快照和资金/Robot连续性检查均保留。若看门狗先释放或真实尾部已复制，则失败，不会放宽物理证明。此处增加RPO故障注入观测余量，不更改性能压测P99/SLO，也不把前两轮NO-GO覆盖掉。
- 新时钟回归通过，共54项test_mac_*通过。0053续跑控制器/tmp/mac-t554-poison-priority-business-resume-20261113-0053.py、状态t554-poison-priority-business-resume-20261113-0053.json、tool session2098，于00:50后从RPO继续，之后四故障及恢复后业务。0050/2232两原控制器均已退出，保留NO-GO历史。无手工暂停控制器或待恢复docker pause。


### 2026-11-13 01:10 先拿齐4CPU严格基线，RPO物理头前置检查准备完成

- 0053续跑因把Java点分属性交给仅解析env变量的env_pairs而KeyError，未注入故障。已改独立严格读取trade.common.control.leaseTtlMs，要求唯一数字且满足暂停预算，新增回归，55项test_mac_*通过。0055续跑async-rpo-04a4eb99仍在2秒观测窗口没有收到最终本地回执，NO-GO，未强杀Primary。实际Docker暂停调用0.086658秒、暂停及交付释放共0.143560秒、观测2.320675秒、总pause2.585958秒，说明该轮等待确实在业务/复制路径，不能再归结为主机操作开销。看门狗及交付线程释放、HomeE2已检查，原10Robot保留。
- 又发现原fully_copied_reservations只比较主备WAL原字节头和SQL源投影水位。这不能证明上一笔异步复制的Custody/双物理receipt已全部完成。Common明确只允许每分区一个未完成复制，下一笔等待前次复制。新增测试前置只读观察器调用既有CommonCertifiedPartitionRuntime.requireAuthenticatedPhysicalCommitHead并两次检查pendingAsyncReplication=false，两端都需与原WAL epoch/seq/SHA完全一致。没有新增生产API、证书、WAL、写许可或恢复协议，也不修改业务字段。此前真实10Robot场景仍保留NO-GO，尚未证明此前失败唯一来自该前置缺口。
- 新fixtures/async-rpo/T554PhysicalCommitHeadObserverAgent.java及独立Test为只读Attach观察器，Mac与Linux原Order镜像下自测通过，覆盖pending、精确头、旧头、错前缀、缺分区。head-observer.jar、独立两平台状态文件追加在既有t554-rpo-delivery-fault-agent-20261112-v2，原fault-agent.jar与原自测不变。RPO在原交付暂停之前先把观察器准备到两Trade JVM，暂停前真实验证认证头。仅自测通过，尚未在真实JVM集成验证，不能当物理恢复PASS。
- 为避免RPO测试准备阻塞用户要求的严格性能数据，先正常同机构建复用fresh STRICT_QUORUM，新代mac-demo-20261113-010057，原233020已按正常入口退休，数据/镜像均保留。未创建并行活动业务代。tool session98110，日志/tmp/mac-t554-clean-cpu4-strict-fresh-20261113-0102.log。同一build233020/ebd808，构建复用0秒，物理及业务393秒，真实客户110秒，全ORDER_ONLY/funded/IOC-FOK/MD关联/资金6持仓6与源水位通过，两个新Robot成交17。四个核心正常入口继承4CPU，内存不变。新JVM按现有公式初始化4个durable handler，实际线程计数仍需在资格窗口外核验。
- 当前严格4CPU性能控制器/tmp/mac-t554-clean-cpu4-strict-capacity-controller-20261113-0105.py，PID7357，tool session63438，状态t554-clean-cpu4-strict-capacity-controller-20261113-0105.json。01:08:42进入六组下单撤单，之后10Robot、固定1/5/10单每秒各60秒（原10背景），逐案例正常清理及财务核对、50Robot、正常停额外40并等owner释放。动态host4GiB/guest1.5GiB保护，部署/故障8GiB门禁保留。严格4CPU和随后干净异步4CPU结果仍未完成，原1.7配额结果独立保留。
- 新controller会从既有正常清理脚本派生本轮前缀清理，仅使用自己新建账户原持久会话进行普通认证撤单，凭据只在内存。其结果保留每案例JSON，原失败压测报告不覆盖。没有后台Maven/Common P0或额外profile并入正式窗口。所有旧RPO控制器已退出NO-GO，无手工暂停待恢复。
- 原233020 Ready卷尚未归档/清空，需在两模式之间安排已授权的短时维护归档并校验，必要时只在四个业务voter/见证均停止时fstrim，再串行fresh异步4CPU。避免在运行/压力窗口内fstrim诱发IO停顿。两份原raw备份继续保留。总体NO-GO，Common P0已过，但最新真实RPO/四业务故障、严格/异步4CPU完整对比、mass-cancel和multi-maker等仍待完成。


### 2026-11-13 01:30 严格4CPU六组与10Robot通过，真实物理头观察器验证通过

- 严格4CPU六组order-cancel-capacity-6a5803b1.json全通过、无残单。OO并发1/4/8为8.272/11.608/11.630循环每秒，New P99为109.064/387.272/747.980ms，撤单消失P99为174.067/312.175/517.178ms。funded为5.972/7.953/8.540循环每秒，New P99为164.739/691.659/1074.489ms，撤单消失P99为133.137/353.718/537.633ms。单热点仍逐笔等待，扩大CPU并未消除该串行开销。不能把这些4CPU数据与旧异步1.7CPU直接当纯ACK模式对比。
- 在6组子进程7421正常结束为Z后、下一资格窗口之前，暂挂测试父控制器7357进行只读物理头工具验证、CPU线程核对和第三方依赖去重。strict-between-windows-preparation-guard-20261113.json已于01:21:38 finally责任清除resume_required=false，父控制器正常继续。各组真实窗口都由其独立started_at/elapsed60秒记录；父phase的01:08到01:21含额外准备间隔，不是下单撤单采样持续时间。
- physical-head-observer-live-e0c65369/evidence.json实际Trade主备、P086一次观测成功，调用Common生产原方法，两端真实认证epoch/seq/SHA与原物理WAL一致，错误SHA返回WAIT exactHead=false，前后同JVM。不是只用Fake自测结论。观察器无class transform、无字段写入、无额外签名/ACK/READY，文件只保存诊断输出。下一异步RPO会使用它在暂停之前排除上一笔复制尚未完成的情况。
- cpu4-durable-handler-verification-20261113/evidence.json真实4个核心JVM的durable handler线程均4个，jstack成功，容器ID/StartedAt不变，采集在正式窗口之间。当前配置已实际生效，不再仅依据Docker标签推测。
- 第三次COW去重t554-codex-generated-dependency-reflink-20261113-011847，共2085个闲置第三方release库完整SHA/模式/mtime一致替换，排除前149路径，主机可用16544399360字节，约15.4GiB。实际扫描根为Documents/Codex和完成build233020；原继承脚本的core_builds_excluded_*字段不适用于这次选根，已以scope.json明确注明，逐文件files[]与实际SHA记录为准。应用/Common JAR、封存P0与原Maven文件均保留。
- 严格4CPU10Robot五分钟robot-steady-10-172729.json PASS，513成交/513请求、1.710TPS，服务内P50/P95/P99/P99.9为116.815/183.641/321.974/613.985ms，30资金、30持仓、6172前序关联零差异，10水位一致。固定1单每秒execution-capacity-422e2b23.json PASS，60个HTTP确认及最终私有推送全部完成，客户端P50/P95/P99为138.074/212.126/319.261ms，清理无错误。后续5/10单每秒与50Robot继续。
- 原233020 Ready仍未归档/清空。已派生/tmp/mac-t554-archive-retired-233020.py及-guest.py，供两模式之间必要维护使用，尚未执行，不能把空间收益归给这份归档。若需fstrim，只在计划替换间隙停止4业务voter+见证且暂停Robot/Liq后执行，再串行fresh，不在资格窗口运行。
- 待改一键部署小项为mac-demo-fresh.py当前只继承GW/MD/APS/Admin实时CPU配额，MySQL/Projection仍需每轮手动update2/1。compose已有MYSQL_CPU_LIMIT及PROJECTIONSVR_CPU_LIMIT，下一模式之间可把这两个加入既有继承表，并通过真实fresh验证，避免额外参数漂移。当前严格正式窗口中实际Docker配额已2/1，未修改其运行脚本。


### 2026-11-13 01:45 严格4CPU完整性能窗结束，容量NO-GO

- 同generation010057、build233020、Common ebd808下，固定5/s的execution-capacity-221a9fb4.json为300确认/300最终回执且窗内完成，客户端P50/P95/P99/P99.9为137.979/224.801/652.213/762.327ms。10/s的execution-capacity-afca2b64.json为600确认/600最终回执，其中579在60秒发单窗口内完成，P50/P95/P99/P99.9为502.526/1683.657/2129.318/2154.504ms。两项功能检查通过，不代表高性能指标通过。各案例正常独立撤单清理及财务核对通过，实际最终回执均QUORUM_DURABLE、RPO risk false。
- 严格50的robot-steady-50-174251.json整体NO-GO。实际五分钟17:37:51到17:42:51 UTC，1822成交、6.073TPS，1814配对服务内P50/P95/P99/P99.9为732.699/1762.640/10914.296/41728.983ms。1948 Tape请求、134未窗内成交、8成交缺窗内入口。49 RUNNING、TXVATM STALE_RUNTIME，最长GZ9Q02间隙244.329秒，50个posting locations。122资金、122持仓、29335前序关联零差异，51源水位一致，Order2/Trade2控制代始终未变。四核心cgroup无CPU throttling，单个资源快照约Order107%/107%、Trade60%/55%，不能把单点CPU当全窗口峰值。
- 子进程正常结束后通过Manager STOP新增40 Robot并等待owner正常释放，保留原10。随后准备串行干净异步4CPU对照与新观察器RPO/四故障，未把性能NO-GO改成PASS。
- 在mac-demo-fresh.py既有配额继承表加入现有MYSQL_CPU_LIMIT与PROJECTIONSVR_CPU_LIMIT，避免fresh把已审核MySQL2/Projection1复原默认。55项test_mac_*.py通过，实际fresh验证待执行。未增加新参数，也未在性能窗口修改运行进程配额或Common代码。


### 2026-11-13 01:55 两模式间计划维护已完成，异步4CPU新代启动中

- 严格控制器已正常结束STRICT_CPU4_RESULTS_RECORDED_CLEAN_ASYNC_AND_BUSINESS_FAULTS_PENDING，额外40通过Manager STOP且owner全释放、保留原10。该状态仅说明结果已记录，严格50仍NO-GO。
- 维护证据t554-between-mode-storage-maintenance-20261113-0147/state.json。暂停Robot/Liq后，将010057四voter与两个witness的restart设no并全部正常停止，实际Stopped核对后才压缩旧233020 Ready及fstrim。没有在活跃核心进程或正式性能窗口fstrim。原严格010057 Ready继续保留，原181322问题数据及两原raw也继续保留。
- 旧233020完整归档t554-retired-233020-archive-20261113-014636，共310684文件/316603条目，原逻辑2882489974B、分配3807641600B；压缩661663604B，SHA d43286b19b287cac6a338ee5bb2f388a440da5ead9509f61198b6e102c2b92ff。每文件SHA/模式/uid/gid/源文件前后状态校验与完整gzip回读通过，落盘归档与目录fsync后才清理这一已停止旧卷内容。未删除其归档。offline-core-fstrim.log为11990171648B trim，主机可用由13923622912增至18164625408B，约16.9GiB。Robot/Liq已解除pause，无手工暂停责任。
- 原Mac同namespace串行替换的新异步代为mac-demo-20261113-015117，使用相同build233020及ebd808，MAC_DEMO_CLIENT_ACK_POLICY=LOCAL_DURABLE_ASYNC。维护与fresh中断不计Robot故障连续性成绩。新的全链路baseline仍进行中，后续同4CPU六组/10Robot/固定1-5-10每秒/50Robot后正常回收额外cohort，再新观察器真实RPO及四业务故障。
- t554-async4-and-business-queue-20261113-0150及两个子控制器已实际排队，单一步骤失败会保存NO_GO后交由当前会话诊断，不会伪造后续PASS。四核心内存2GiB、VM8CPU/12GiB不变，MySQL2/Projection1通过fresh既有表继承后还需Docker实值核验。整体NO-GO。


### 2026-11-13 02:12 同配置异步六组/10Robot通过，恢复调度小改动待验证

- 新代015117正常fresh物理及业务检查380秒、业务131秒。真实自动审批、ORDER_ONLY及funded SDK成交、投影/MD/资金持仓通过，原2Robot23Tape最终回执，6资金6持仓水位零差异。队列核验Docker MySQL2000000000/Projection1000000000 NanoCpus，既有配额继承表修改实际生效，四核心均4000000000，Common仍ebd808。
- 六组order-cancel-capacity-045ec8b3.json PASS、无残单。OO并发1/4/8循环TPS为9.475/12.618/12.798，New P99为78.923/280.231/523.286ms、撤单消失P99为117.751/176.957/489.632ms。funded循环TPS8.802/10.875/11.347，New P99为95.368/335.790/618.435ms、撤单消失62.665/220.236/349.287ms。与严格4CPU相比热点吞吐提高有限，CPU线程数增长没有解除每分区等待上一复制完成的限制。
- robot-steady-10-181132.json PASS，454配对成交、约1.513TPS，服务内P50/P95/P99/P99.9为67.069/100.903/119.752/253.819ms，财务水位检查通过。Robot市场输入/发单量不恒定，不将其TPS直接当固定到达率模式收益，接下来1/5/10每秒真实客户端最终回执比较仍进行中。
- Common源码当前有两处有意未提交修改，尚未进入镜像。CommonCertifiedFailoverWatch在拿到或恢复现有真实RSA Stage后，于同一个cold probe立即调用原completeStagedRecovery，省去再排队等下一轮；不更改Stage、ACK、physical fence、恢复或READY检查。两个确定性回归通过原probe生产方法验证新Stage与冷恢复Stage，并检查未发布实际READY时仍fail closed及继续重试。当前只有源码与待执行runner，尚不能称PASS。
- /tmp/mac-t554-cold-probe-immediate-completion-regression-20261113.py已准备独立编译，对照原ebd808应两项失败、修订两项通过，强制无skip。执行推迟到当前容量及故障资格窗结束，避免Maven/javac/测试CPU污染。之后必须提交精确Common候选并完成全部P0，才能部署任何新Common JAR。所有正在运行的性能结果仍对应原828/ebd808。整体NO-GO。

### 2026-11-13 02:27 异步4CPU固定到达率结果与晚到核对

- 1/s execution-capacity-fc509707.json功能PASS，60确认/60最终且都在发单窗，客户端P50/P95/P99为73.199/103.202/178.819ms。5/s execution-capacity-5b60f7ea.json PASS，300确认/300最终且都窗内，P50/P95/P99/P99.9为76.592/174.978/214.043/537.771ms。实收分别60/300全部LOCAL_DURABLE_ASYNC、risk true，实际双节点正常。
- 10/s execution-capacity-6fa7bef5.json整体NO-GO，600确认、450窗内完成、限定排空后519最终，81未在原窗口收到最终回执。客户端P50/P95/P99/P99.9为9788.577/15041.621/29355.782/36232.765ms，已收519全部LOCAL_DURABLE_ASYNC/risk true。API ACK P99亦846.987ms，初始清理错误9000保留。
- 后续普通认证单撤清理execution-6fa7bef5-post-window-normal-cleanup.json通过，两个原账户都无开单、无冻结保证金/手续费，财务核对通过。execution-6fa7bef5-late-readonly-reconciliation-20261113.json确认原600客户端ID全部最终Filled、每笔一条execution、数量.001。该证据在原延迟窗口之外，原NO-GO保持。
- 两个资源采样相隔33.517秒，核心未发生CPU quota throttling。guest内存可用约4.75GiB、memory PSI为0，IO full avg10从2.40升至8.00，存在I/O等待。Mac原窗只有12页swapin、0页swapout，swap累计用量不能单独证明当前大量换页。
- 同CPU/同构建对照的各案例仍使用不同新试用租户、不同分区和采样时段。依据Common原CRC32和分隔规则，只读核对严格10/s为OrderP007/TradeP198、异步10/s为OrderP197/TradeP194，两者均无背景Robot分区碰撞。异步5/s的TradeP113与背景Z70SOW共享。路由位置纳入解释，全部差值的模式因果仍需重复采样。
- 当前50Robot已全部运行，五分钟测量进行中，没有编译、新JAR部署、线程转储或CPU调整混入资格窗。Common同probe继续Stage的改动仍仅在源码，待当前窗口和故障流程结束后执行定向对照及完整P0。整体NO-GO。

### 2026-11-13 02:30 异步4CPU容量窗完成，真实RPO和四故障已继续

- robot-steady-50-182806.json运行及财务门禁PASS，实际18:23:06至18:28:06 UTC五分钟，2281成交、7.603TPS、2276配对，服务内P50/P95/P99/P99.9为182.432/1011.134/3023.456/5747.322ms。2314 Tape请求、38未窗内成交、5成交缺窗内入口。50全部RUNNING，最大成交间隙44.537秒，50 posting locations，122资金122持仓及24866前序关联零差异，47源水位一致，Order2/Trade2控制代未变。
- 该PASS为现有Robot连续性及业务一致性门禁，3秒级P99和7.6TPS仍未达到高性能交易系统目标，整体性能NO-GO。严格4CPU50为6.073TPS/P99约10.9秒且连续性NO-GO，两种模式单热点10/s也都存在明显长尾，异步尤为严重。
- 额外40通过正常Manager STOP、owner全部释放，保留原合格10。t554-clean-cpu4-async-capacity-controller-20261113-0150已正常结束ASYNC_CPU4_RESULTS_RECORDED_BUSINESS_FAULTS_PENDING。当前队列已自动继续真实business-rpo，之后按原审定四业务故障顺序进行，不等待用户逐项提醒。
- RPO使用已在真实Trade主备验证过的新只读物理头观察器，在暂停前检查既有RSA/水位/双安装回执及pending async false。观测器与4秒独立看门狗、原SIGKILL137、备节点无新副本、512对物理证据及财务/Robot门禁全部保留。本轮尚未完成，不宣称RPO通过。Common调度小改动仍未编译/部署，全部当前业务验收对应828/ebd808。

### 2026-11-13 02:55 最新Common真实业务异步RPO完整通过，四故障继续

- async-rpo-9127994f/evidence.json状态NORMAL_ASYNC_UNREPLICATED_FILL_RPO_BUSINESS_AND_HOME_PASS。暂停之前，真实Trade A/B的P117同为E2/95、SHA 374910f242f93f250312b7f6d778625a468166c675d0fbe2d97760516618b0fb，既有物理头认证READY、pending false。暂停后0.950453秒观察到双方最终Filled、LOCAL_DURABLE_ASYNC、QuorumDurable false、RpoRisk true、Commit P117/2/96。备节点头仍95，原主本地已确认头96，主节点真实SIGKILL退出137、非OOM，备节点实际pause1.541588秒，低于独立4秒看门狗。
- 自动接管后，原Order已保存的match意图正常重放，原双方ExecID各一次，持仓均.002等于预期。Trade单节点期间实际Robot持续报价、6条成交与LOCAL提交证据存在。回归后256分区严格Home全部恢复、512对WAL/快照证据相符，最终持仓仍.002。126资金126持仓、38240前序关联及48水位零差异。
- 原Robot、Order进程保持同一进程，受测保留Robot全故障过程33轮，最大成交间隙70.873秒，原重启策略已恢复。该轮只证明原订单意图仍在时的自动重放恢复，其他副本和意图一并丢失的情况仍按用户接受的异步RPO边界处理。
- 主阶段02:29:36至02:47:40，含fixture准备、真实故障、全量回归和完整证明核对。真实kill为02:30:32、返回A重启为02:36:02，全量接管约五分钟，之后回归继续约十一分钟。客户首笔恢复与全量终态耗时需区分，现有分钟级全量恢复仍需优化。
- 02:47:45起已继续trade-a-kill-retained，受测Robot Home B，故障Trade A，验证保留写主和Trade实际单节点。后续Order A TERM加ORDER_ONLY、Order B KILL加funded、Trade B TERM加funded及恢复后业务检查仍在队列。当前Trade A新故障已完成全量LOCAL及单节点business/Robot实成交，替换进程已启动，正自动回归Home。总体NO-GO，不能将这一项RPO通过代替四故障/性能交付。

### 2026-11-13 03:29 Trade A强杀通过，调度优化本地199项回归通过

- ha-trade-a-kill-07jqy77k/evidence.json为COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS，旧节点Exit137，当前客户端确认策略LOCAL_DURABLE_ASYNC。全量LOCAL331.121秒、严格Home895.629秒，均为脚本实际测量。受测保留Robot在takeover阶段7轮最大间隙86.186秒、return阶段29轮最大35.305秒。512项返回/存活WAL与快照哈希一致、unequal为空，财务、单节点signed-business及回归回读通过。分钟级全量恢复仍为待优化项。
- 仅暂挂父控制器22811，实际roll子进程24154独立正常结束后，才在故障窗口之间编译和测试新调度源码。t554-between-fault-development-guard-20261113-0310.json已03:15:38恢复父控制器，parent_resume_required=false，没有遗留手工暂挂。父phase耗时包含该插入间隙，不能替代上述331.121/895.629实际计时。
- t554-immediate-cold-completion-regression-20261113-031129保存原ebd808两项确定性失败、新源码两项通过、无skip。原181项安全类全部PASS。首次包装器误将独立两项也计入同一日志、断言应183，JUnit原日志实际OK(181 tests)，该包装器AssertionError保留并以safety-count-correction.json说明。再完整跑协调器类18项PASS，其中包括新增2项，合计199项。全部没有混入正式容量或故障采样窗口。
- Common本地提交5f93ac5acd641a6889c88677f6e90a5ba76b460a，仅6行生产调度变动与48行针对性回归，源码工作区干净。原Git全局身份为空导致首次commit失败，随后沿用该Common仓已有Codex/codex@local身份进行单命令提交，没有修改用户全局配置。完整签名快照/13原生故障/256双向SIGKILL与反复Home P0尚未重跑，新JAR尚未构建或部署。运行镜像仍旧828/ebd808。
- 原父已自动继续Order A TERM加ORDER_ONLY，实际已完成survivor LOCAL、单节点OrderOnly成交与Robot观测，替换节点正在自动Home回归。主机可用约7.4GiB，下一故障仍保留8GiB入场门禁。两份原故障raw维护备份继续保留，尚未清理或改写。后续需释放空间再继续新Common完整P0及剩余故障，整体NO-GO。

### 2026-11-13 03:45 Order A通过，存储门禁与旧归档清理，新Common P0进行中

- ha-order-a-term-r7mpeiyg/evidence.json为COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS。ORDER_ONLY、旧节点Exit143，实际全量LOCAL290.495秒、Home746.102秒，512对物理哈希一致、unequal 0、财务回读通过。Robot takeover10轮最大32.440秒，return24轮最大33.438秒。原OrderOnly恢复目标在该轮得到真实单节点成交验证，分钟级全量恢复尚需优化。
- 下一order-b-kill在任何故障注入之前，被8GiB主机空间入场门禁拒绝，实际6850MiB。原主队列及0150业务控制器均结束NO_GO，四核心已全量回归，当前仍是015117/828/ebd808正常10Robot。没有遗留手工pause或未清除的故障注入。本轮新版Order B/Trade B尚待完成，旧版两轮结果保留作基线，优先完成优化版Common全P0后接续完整业务矩阵。
- 对旧150GiB故障数据盘备份尝试有界zstd归档，只有完整源SHA与解压全量SHA一致后才允许退休raw。第一次taskpolicy路径写成/usr/bin导致无写入失败，修正到实际/usr/sbin。第二次在约6.44GB源输入、2.35GB压缩输出时触及4GiB剩余保护，自动结束并移除自己新建的失败partial。两原raw仍在原位置、内容未改，没有声称完成整盘归档。失败状态保存在t554-original-data-backup-compression-20261113-033609及033849。
- 按用户已授权清理旧Demo生成数据，退休三份更早、已停止且原卷早已清空的数据归档。t554-obsolete-demo-archive-retirement-20261113-034234/state.json完整记录每份删除前重新SHA验证、原卷无活跃挂载、全部引用容器停止且restart=no。退休mac-demo-20261111-072730-ready.tar.gz 2639794950B、otc-t530-ready-data.tar.gz 1754585642B、otc-t529-fresh-mysql-data.tar.gz 844136616B，共5238517208B，约4.88GiB。各原目录新增retirement-20261113.json，保留原verification.json、每文件files.jsonl和故障日志。三份旧数据整卷归档本身已删除，历史整卷回退需其他副本。当前015117、严格010057、较近233020/202659归档及两原故障raw继续保留。
- 该步骤无服务重启或新故障，主机可用由6741987328增至11915321344B，约11.1GiB。未在活跃核心运行时执行fstrim。
- 新精确Common候选t554-common-candidates/20261113-0340由本地提交5f93ac5构建，JAR SHA b62c45b942a2fe9b9c93fd5a155acdc2deea8098e183c68df28eb405d91eb0db。t554-cold-probe-p0-controller-20261113-0340实际运行，验证目录t554-common-verifications/20261113-034337。先199安全测试，再真实RSA快照、13类实际原生故障、完整256分区双向独立SIGKILL、打断重臂、第三次故障及反复Home，并要求normal_dual_async与interrupted_local_rearm。尚未通过全部门禁，未部署新JAR，整体NO-GO。

### 2026-11-13 04:26 调度候选完整P0拒绝，发现LOCAL刷新等待的稳定回归

- b62c45候选199安全测试及真实196637B RSA快照传输/冷打开通过。13个真实原生用例于04:14:40结束，12通过、1失败，失败为expiredWholeNodeExitsAndTheProcessSupervisorRejoinsCertifiedState。完整256双向故障阶段未执行，status继续NO_GO，没有有效新seal，也没有部署该候选。其余正常双节点异步主SIGKILL、备失联等用例通过的原日志保留。
- 失败现场process-evidence-live-poison/node-lease-expiry公开证据保留，B原进程实际Exit78并由既有进程监督入口重启。A最终P145停留E3 LOCAL READY，local-async-business.wal有一条31B记录，但成功的r-first-ack为另一个P139。P145没有E4 Stage，也没有catchup exchange。A反复无法导出可信LOCAL头，导致回归停滞。P250原始目录缺失报错随后已实际补齐E4，为早期瞬态，不能据旧lastRejection将其认定最终根因。
- 仅测试夹具提交7387074eda628d36d13b41ac1f044961d040e2e3，给原生过期场景的首次LOCAL确认前异常增加原始栈输出，生产源码与5f93相同。t554-paired-expiry-diagnostic-20261113-0415同夹具顺序复跑原828和优化5f93，两次均通过，原失败因此仍属间歇边界，不能凭独立复跑通过消除NO_GO。
- 随后通过现有CommonCertifiedDegradedPrimary正常commitAndApply入口，稳定模拟WAL force以后、授权短暂刷新超过2秒，而控制器仍持续认证新的manifest generation。原b62c45在此测试失败并永久poison该LOCAL writer，另外原有7个LOCAL安全用例通过。证据t554-local-progress-regression-20261113-042203/baseline.log及baseline.status。这与原失败的已写入未确认LOCAL分区无法继续追平的症状一致，原生偶发失败的直接异常仍需新版夹具继续核对。
- 当前未提交修订复用原DurableWalCommitAckGate等待与NodePartitionGrantTable.generation，只在LOCAL after-force等待期间，遇到新的已认证manifest generation时更新原2秒重试预算。每次成功仍必须获得原精确分区/Epoch/策略/租约证明。相同generation的心跳不延长预算，真正旧Epoch拒绝仍立即失败，没有新账本、恢复凭据、配置或HA服务。等待总时长可在连续真实控制面推进时超过2秒，这是明确的行为调整。
- 13项定向用例通过，包含新增LOCAL恢复等待、同generation超时仍有界、真实撤权不能返回ACK、原业务apply失败仍永久隔离等。210项完整安全类正在补跑，尚未宣称新的生产JAR通过原生门禁。当前Mac Demo继续运行828/ebd808，当前所有容量与业务故障结果仍是旧版本证据。整体NO_GO。

### 2026-11-13 04:53 完整210项通过，存储恢复，新精确候选开始P0

- t554-local-progress-regression-20261113-042203/all-safety.log为OK(210 tests)。原永久刷新拒绝、业务apply失败隔离及旧Epoch拒绝均通过。修订已提交5b2ad4c6e305d81bf43abe1ea4ea5b82cad102ce，Common工作区干净。新增生产逻辑使用已有的认证manifest generation作为等待进展提示，只有LOCAL after-force门禁采用该提示，所有成功仍执行原精确物理与授权检查。同一generation心跳不会更新预算。总等待可随持续真实generation推进超过原2秒，这项行为调整明确记录。
- 旧版原生证据归档仅处理11月10/11日不活跃process-evidence目录。t554-old-native-evidence-archive-20261113-043133完整保存44个目录、424391文件，压缩104997003B。逐文件SHA、POSIX mode/uid/gid、原文件前后状态及完整gzip回读均通过，才清空源目录内容。各旧验证目录有archive-locator，复验旧版本物理证据需先按定位解包。近期223437、034337及新的验证目录继续保留原物理目录。首次Mac Python3.9不支持stream tar的compresslevel参数，在任何原目录清理之前失败，改用显式GzipFile后完成；原失败目录042941保留。
- 维护时发现旧业务故障夹具又创建了CFAU7S、MKGA0K两套试用Robot，当前实际为12个。第一次按额外8个的保护断言失败，未停止任何Robot。随后限定原已记录的10个容量成员及两个故障租户，核对测试组织归属，通过正常Manager停止10个附加Robot并等owner释放。maintenance-extra-capacity-and-fault-robots-stop-20261113.json为PASS式完成状态，当前仅原A6DS80、DR0PVE两个Demo Robot继续运行。故障场景历史实测计时与间隙保持原结果。
- 150GiB逻辑大小的临时原始数据盘维护备份已按用户允许清理旧生成数据的范围退休。t554-original-data-backup-retirement-20261113-044330/state.json记录完整161061273600B SHA c7e28ebfede3d6611e3bbe054a8df062cf58858bc59057a00fbaf8042d6e3862，且首/中/末原6MiB采样与19:39保存值完全一致。确认该备份无进程打开、与实际工作盘不同inode，工作盘被真实VM打开，原181322 Order/Trade卷仍存在、postrepair fsck exit0、e2undo非空，且新代RPO和Trade/Order故障验证已通过，才删除这一个旧备份文件。该150GiB原始镜像内容未另行完整归档，完整pre-repair数据盘镜像回退已退休。20GiB boot原备份、工作盘、原故障业务卷、修复撤销文件与日志继续保留。原181322业务状态仍未认证，不能将其宣称为财务恢复通过。
- 该备份的原分配量约153442488320B包含APFS共享块，实际可用空间从7762358272增至24853790720B，释放约15.9GiB。删除与目录落盘耗时包含APFS清理，四当前核心仍Running且RestartCount0，没有在活跃JVM下fstrim。
- 0430发布队列曾在旧原生归档完成后、备份退休前自动入场，因7652MiB不足8GiB而在candidate创建前结束NO_GO。原失败JSON和日志已由storage-admission-retry目录保存，备份退休完成后自动重试。新精确候选为t554-common-candidates/20261113-0430，JAR SHA 2571ee62270ca5e280100423954eb5d1183380a78268fff3422b21af5faceb4e，来源提交5b2ad4c。验证目录t554-common-verifications/20261113-044954，04:49:55开始，当前先重跑精确JAR的210安全，再全物理P0，尚未部署新JAR。
- t554-local-progress-release-queue-20261113-0430已自动接续，严格要求210与完整P0、normal_dual_async/interrupted_local_rearm及源码一致后，才走原Mac fresh-verified单环境入口部署异步模式。随后先真实10Robot五分钟基线、RPO和四业务故障。每个独立业务故障及postfault下撤单完成后，通过正常Manager收回该夹具新增且归属已核验的试用Robot，保持原10个基线成员，避免病例后活跃数增长造成负载漂移和postfault10Robot入场错误。新helper没有任何直接SQL业务写或owner修改。
- 另发现ha-test-sshfs旧Colima VM仍Running、4CPU/8GiB。lsof将PID17411准确映射其磁盘，实测约3.5 CPU核持续占用；默认VM PID74900也占约2至3核，二者共用24GiB Mac。其管理连接返回empty runtime，尚不清楚其他用途。已向用户询问该旧环境是否可正常关停并保留磁盘，回答前继续当前修复和验证，尚未停止或修改该VM。原容量结果是在这个共存背景下取得，后续性能对照需记录资源背景。整体NO_GO。

### 2026-11-13 05:54 最新 2571ee 完整 P0 通过，部署被客机空间拦截

- 精确 Common 5b2ad4c6e305d81bf43abe1ea4ea5b82cad102ce、JAR 2571ee62270ca5e280100423954eb5d1183380a78268fff3422b21af5faceb4e 在 20261113-044954 完整通过。210 项安全通过，原生故障 13 项全部通过，真实双向全 256 分区、4100 帧长前缀、恢复中断续接、第三次 SIGKILL、再次自动 Home 回归及跨 Epoch 退休前缀物理验证全部通过。05:44:22 完成签封，normal_dual_async 与 interrupted_local_rearm 均为 true。
- 本轮全量接管 A 为 204710ms、B 为 208846ms，回归分别 444824ms、393542ms。旧 828 同类测试为 228057/236673ms、440584/393528ms。接管有约 10% 级变化，完整回归未显著改善，不把不同时窗的差异全部归因于代码，也未达到秒级恢复目标。
- fresh-verified 已完成新业务镜像和单测，准备构建为 mac-demo-build-20261113-054422。05:45:52 在创建新业务代之前，客机 1744MiB 不足既有 2GiB 门禁而退出。新 generation 目录未创建，当前旧 015117 四核心仍运行，未发生替换。原发布队列 NO_GO 保留，不能把 P0 PASS 当业务部署 PASS。
- 检查客机数据盘 147GiB 已用 144GiB，主机仍约 21GiB 可用。停止了两条重复、耗时的只读 du 扫描及 docker system df 客户端，未重启 Docker。发现两个不带卷、restart=no 的历史 Docker 构建临时容器，命令分别为构建清理 classes 和检查 Common JAR 数量。保存 inspect 与读日志错误后，正常 docker rm 且不带 -v，再无 force 删除两个无标签镜像。t554-unused-build-image-cleanup-20261113-055235 记录完整镜像 ID。实际只释放约 200MiB，共享镜像层的逻辑大小不能当实际收益。首次日志读取因历史日志文件缺失在任何删除之前失败，原目录 055208 保留。
- 当前对已停用的 otc-t398-ready-data 做完整归档，确认所有 42 个引用容器均 stopped/created 且 restart=no，运行容器无挂载。沿用已有每文件 SHA、模式 uid/gid、源文件前后稳定、完整 gzip 回读、归档 SHA 与落盘后清理的流程。原 181322 卷和当前 015117 卷不在清理范围。随后计划同法处理已停用的严格性能 010057 Ready，保留完整归档后再继续使用已构建的精确镜像部署，避免重复构建。

### 2026-11-13 06:18 已归档清理旧卷，新 2571ee 业务代真实启动通过

- otc-t398-ready-data 完整归档位于 t554-retired-t398-archive-20261113-055413。667418 文件、672041 条目，原分配 5390647296B，归档 754196281B，SHA 6bdf61fbd09b82f6fe394cb0a5b734e154a4ff0a43f7f95d61afa9a2771d1ce7。完整每文件/元数据与源稳定校验、gzip 回读、落盘和归档再 SHA 后清空旧卷内容，旧 42 个容器继续 stopped/created、restart=no。旧数据仍完整保留于归档，恢复需离线解包与重新验真。
- 严格性能旧代 010057 Ready 同法完整归档并清空，t554-retired-010057-archive-20261113-060726，128709 文件、134366 条目，原分配 1286361088B，归档 190465674B，SHA bcd38ff865c55237e6ac02f5bed738a53957aea1003b2bbab2874ec0e0fbc327。原严格性能 JSON 及所有结果继续保留，清理不会把性能 NO_GO 变为 PASS。两份归档均保留，没有在活跃核心上 fstrim。
- 新控制器 t554-verified-release-guest-storage-resume-20261113.json 保留旧队列空间失败记录，核对完整 P0 签封及已构建镜像后，复用 mac-demo-build-20261113-054422，通过原一键入口 fresh 指定构建串行替换。新代 mac-demo-20261113-060903，06:09:03 开始、06:15:30 结束，物理及业务启动 387 秒，实际新租户 DLOLND 的 ORDER_ONLY、N2BD7C 的 funded 两方签名 SDK 成交、IOC/FOK 空簿取消、MD 精确成交链接均通过，初始 6 资金 6 持仓与 2 水位零差异。此阶段只算启动业务通过，尚非 HA 总验收通过。
- 实际四核心 Common 2571ee、来源 5b2ad4c、客户端 LOCAL_DURABLE_ASYNC，4CPU/2GiB，MySQL2CPU/1.5GiB、Projection1CPU/512MiB，四核心 Running/RestartCount0。客机剩余约 7.9GiB，主机约 20GiB。旧 015117 已正常串行退休，原 181322 问题卷未清理。
- 当前 baseline-robot-10 已自动注册到 10 个 RUNNING，进入完整五分钟窗口。之后自动继续真实未复制 LOCAL ACK 后 SIGKILL 的 RPO，再做 Trade KILL、Order A TERM、Order B KILL、另一侧 Trade TERM，故障中保留同一 10Robot 基线。尚未宣告最新业务故障或性能通过，整体 NO_GO。

### 2026-11-13 06:30 用户授权的旧 VM 已正常关停，数据盘保留

- 用户明确回复 ha-test-sshfs 已无用途，可正常关停并保留磁盘。06:27:06 开始，执行不带 force 的 colima stop ha-test-sshfs。宿主代理收到正常停止请求，解除挂载后关闭 VZ，06:27:43 报实例已关停。SSH 转发取消出现原管理连接异常相关警告，随后正常退出 0。未强杀虚拟机进程，也未删除 profile 或磁盘。
- t554-authorized-old-vm-stop-20261113-062706/state.json 确认 ha-test-sshfs Stopped，原 PID17411 和17401退出，boot disk 与 datadisk 均原 inode 和大小保留。当前默认 VM PID74900仍运行，8CPU/12GiB/150GiB。释放此前约3.5个CPU核的持续竞争及旧VM内存资源。
- 资源背景变化发生在新代 RPO 的实际主节点故障之后、Home 追平期间。此前最新10Robot五分钟结果 robot-steady-10-222128.json 通过，427成交、426配对、1.423TPS，服务内P50/P95/P99/P99.9为69.947/107.691/130.620/279.211ms，0请求窗内未成交、1成交缺窗内入口，控制代前后2/2。该窗口仍为旧VM并存背景。后续性能结果应明确旧VM已关闭，不能把全量差值归因于新Common。
- RPO b5a15dc9 已真实观察主本地99、备认证98，LOCAL最终回执观察0.453186秒、备暂停0.929783秒，实际杀掉Trade B主节点。当前已全256 LOCAL可写，正自动Home追平，最终财务/物理核对尚未结束，整体NO_GO。

### 2026-11-13 07:32 最新 Common 的真实 RPO 与四方向业务故障通过，性能复测排队

- mac-demo-20261113-060903 的 async-rpo-b5a15dc9 为 NORMAL_ASYNC_UNREPLICATED_FILL_RPO_BUSINESS_AND_HOME_PASS。Trade B 主本地99、备认证98，最终 LOCAL 回执在备暂停后0.453186秒观察，备实际暂停0.929783秒，真实主进程 SIGKILL 后按备认证水位接管，原 Order 意图重放，最终512物理对一致、26资金26持仓及9032前序关联零差异、11水位一致。同一Robot和Order进程保留，选定Robot故障全程27轮、最大间隙55.285秒。此用例的Home恢复中旧无用VM获用户授权关停，时间改善不能全归代码。恢复依赖原Order意图仍存，不等于任意已丢的异步尾都可保证重建。
- 四方向均实际执行并得到 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS。Trade A KILL 位于 ha-trade-a-kill-gx6y_rc6，LOCAL251.212秒、Home512.916秒。Order A TERM/ORDER_ONLY 位于 ha-order-a-term-0onvz_d5，200.929/506.867秒。Order B KILL/funded 位于 ha-order-b-kill-8q6ikd8p，240.404/501.983秒。Trade B TERM/funded 位于 ha-trade-b-term-2ve0qmv_，203.033/522.361秒。持续Robot报价、故障中真实单节点业务、恢复后订单/资金持仓/MD/SQL及物理链路按现有门禁核对通过。每例的精确物理证据保留于对应目录。
- 每例完成后正常Manager收回该夹具新增试用Robot并等待owner释放，四份 owned-extra-trial-cleanup 报告完成，保留原同一10Robot基线。07:29:02已继续六组恢复后下撤单，之后完整10Robot五分钟。当前这些postfault检查仍进行中，尚未把整轮业务控制器置为完成。
- 用户本次明确要求提交GitHub。本轮本地已提交 Order a478e35baff86c46603c4f7b50e90a03d5827bb5、Trade aefad60d5107f9b595b20c7b20bb5008584eb3f3、Projection6f38cf6aa4ac56464d63a48f61530f7e381061a8。Order/Trade/MD/Shared源码与部署构建原始 source.sha256 逐文件完全一致，Projection源码清单亦一致。源码提交没有改变当前运行字节。
- 7仓库统一推送研发分支 t554-mac-recovery-20261113 并逐个 ls-remote 核对完整SHA，记录 t554-github-code-checkpoint-20261113-070126/state.json。Common5b2ad4c6e305d81bf43abe1ea4ea5b82cad102ce，MD578ed2f22882b1a20b9d9c63c9333a3417956201，Shared010038a35967acbd8c9af45c0e5930564e1ebfc6，部署92f24c74dc2c15c1c4186f3fbd2d153da490a5bc，以及上述三业务仓库。部署提交限定48个本任务路径，compose仅暂存trial bootstrap和Robot认证两处，其他原有工作区修改继续保留。55项Mac Python测试重新通过。远端saas-crypto-latest存在独立演进，本轮用研发分支保存精确验收源码，后续整合仍需相应验证。
- 第一次直连推送RPC连接超时且未成功，使用本机已在监听的既有SOCKS代理按单命令参数重试后全部成功，没有更改全局Git代理或身份。Common/MD/Shared工作流分支过滤不覆盖本研发分支，新增业务和部署提交均带skip ci，未请求或启动GitHub Actions。
- t554-clean-capacity-after-business-20261113 已实际排队。只有完整业务控制器通过才开始，先完整归档已停用015117 Ready，再用同一精确构建串行fresh严格模式，归档已停用060903 Ready后测六组下撤单、10Robot、固定1/5/10每秒最终回执和50Robot，正常回收额外cohort。随后同构建fresh异步模式并归档退休严格Ready，重复同一矩阵。资格窗口不并行编译、归档、剖析或调整资源，旧ha-test-sshfs必须为Stopped。两模式均是独立时间段的同Mac串行干净业务代，不存在并行活跃业务环境。当前分钟级恢复和已知高负载长尾仍未达目标，整体性能NO_GO。

### 2026-11-13 07:50 最新完整业务门禁已完成，修复退休故障容器策略后继续性能复测

- 六组恢复后下撤单 order-cancel-capacity-c4ce1746.json 全部通过，07:36:30结束，原测试账户无残单。funded并发4/8循环TPS分别18.974/18.809，New P99为259.974/513.964ms，cancel-absent168.128/282.218ms。此为故障后原JVM及诊断背景，独立干净两模式性能复测仍需继续。
- postfault robot-steady-10-234145.json 通过，07:41:55完成。858成交且858配对，服务内P50/P95/P99/P99.9为41.892/82.707/120.293/196.168ms。最新Common210安全、完整原生P0、真实未复制LOCAL最终成交后主SIGKILL的RPO、四业务方向和postfault检查均通过，t554-local-progress-business-controller-20261113-0430最终状态EXACT_COMMON_P0_RPO_FOUR_FAULTS_AND_POSTFAULT_BUSINESS_PASS_CAPACITY_RECORDED_PERFORMANCE_NO_GO_REMAINS。功能门禁完成，高性能和恢复耗时仍未达目标。
- 性能队列首次归档旧015117 Ready前被restart策略检查拒绝，没有创建归档或清理任何原数据。发现旧两次滚动故障保留的原容器仍为on-failure，正常fresh只处理当时四个当前核心，未覆盖更早故障保留的副本。失败目录t554-clean-capacity-queue-20261113-073101和原队列NO_GO完整保留。
- 根因在roll-mac-demo-voter.py保留旧容器之后直接启动replacement，未明确关闭旧容器的Docker重启策略。已在正常替换入口保存旧策略并对退休原容器设置restart=no，新replacement继续使用已记录的正式on-failure策略。若replacement尚未创建而流程失败，原容器恢复原名时同步恢复原策略及重试次数。Common、业务镜像、Epoch、ACK或物理证明均无变更。
- 新增3个实际生产分支AST回归，原版本3项稳定失败，修改后完整58项Mac Python测试通过。首次测试选中了另一个同名条件分支而报2个测试错误，收紧到真实replacement分支后完成旧红新绿对照，全部原日志保留于/tmp/mac-t554-retained-restart-policy-*20261113*。
- 已对历史015117两个和当前060903四个、合计6个已停止且精确匹配hostready-retained名称/代/卷的故障保留原容器正常设restart=no。t554-stopped-retained-voter-policy-fix-20261113-074930保存每个原inspect和策略，不涉及任何正在运行的核心。当前4个正式核心仍Running/on-failure/RestartCount0。其数据保留，随后归档仍要求完整每文件与gzip校验。
- 新性能队列t554-clean-capacity-after-business-retry-20261113已实际启动，先继续完整归档015117，再串行同构建严格/异步干净复测。原失败队列和不可用日志没有被覆盖。

### 2026-11-13 08:34 旧 VM 关闭后的严格模式完整容量结果

- 新严格代mac-demo-20261113-075548使用同一build054422、Common2571ee、四核心4CPU/2GiB、MySQL2/Projection1。旧015117 Ready和完成四故障的060903 Ready均已完整归档、逐文件与gzip校验后清空原卷内容，归档继续保留。全部归档在严格资格窗开始前完成，窗口没有Common编译、归档、剖析或资源变更。当前宿主尚有约13GiB，客机约14GiB可用。
- order-cancel-capacity-37e8127d.json六组全部通过。ORDER_ONLY并发1/4/8循环TPS为17.782/23.523/22.027，New P99为42.995/221.990/478.314ms，撤单消失55.061/164.354/307.343ms。funded为9.273/18.376/19.561，New86.500/209.645/358.382ms，撤单消失64.434/131.080/221.680ms。所有账户清理与财务核对通过。
- robot-steady-10-001734.json通过，422配对、1.407TPS，服务内P50/P95/P99/P99.9为53.865/67.959/75.046/94.931ms。
- 固定客户端每秒1笔execution-capacity-044a39e7.json通过，60全部在60秒发单窗内完成，成交P50/P99为73.496/100.468ms，HTTP确认P9930.484ms。5笔3ed2a215通过，300全部窗内，68.222/101.358ms，确认23.698ms。10笔db771254通过，600全部窗内，68.793/98.396ms，确认21.240ms。三例均零调度丢弃、无缺失最终回执、无流错误、控制稳定及财务投影核对通过。口径为客户端实际发单到私有最终Filled推送，有原10Robot背景。不能把10TPS称为饱和容量。
- robot-steady-50-003120.json通过，2664成交、2664配对、8.880TPS，服务内P50/P95/P99/P99.9为102.161/282.981/452.097/768.464ms。2670请求中6个未在原窗口成交，0成交缺窗内入口。该未完成数保留，未伪造为零。原40新增Robot已正常STOP、owner释放并保留10，严格容量控制器完成。随后父队列已按计划进入同构建干净异步代部署。
- 当前10笔/秒没有触及上限，已将客户端测试既有速率上限扩到15笔/秒，原至少60秒、最多900笔总量、最多16个HTTP在途和原资金准备均不变。59项Mac Python测试通过。该改动只扩大测试覆盖，不改变交易或持久化语义。异步控制器尚未启动时已加入15笔/秒，严格15会在异步完成后同资源的新严格代补测。
- 曾尝试在严格50之后、下一模式之前插入15测试，边界保护在父队列已进入fresh异步时拒绝，未暂停任何进程、没有执行额外负载，t554-extended-strict-rate15-20261113.json为NO_GO且parent_resume_required=false。保持该失败记录，选择完成当前异步后串行新严格代补测，不中断正在进行的部署。

### 2026-11-13 09:12 高负载异步结算拒绝已复现，保留现场并提供集群原理审阅

- 当前干净异步代mac-demo-20261113-083209。六组order-cancel-capacity-f2b4c018.json全部通过，ORDER_ONLY并发1/4/8循环TPS18.400/24.570/24.848，New P9939.585/148.398/322.630ms，撤单54.954/109.368/183.429ms。funded11.691/20.116/21.728，New85.557/224.273/384.336ms，撤单30.793/118.137/207.903ms。10Robot robot-steady-10-005138.json通过，488配对、1.627TPS，服务内P50/P95/P99/P99.9为39.711/71.383/91.748/177.315ms。
- 固定1笔每秒execution-capacity-7dcf544b.json通过，60全部窗内，客户端最终P50/P99为43.575/101.697ms，确认P998.430ms。5笔49261124在资格窗口开始前的准备阶段失败，RuntimeError code5004，无计划量、无实际订单窗口，不能当5TPS性能样本。10笔89dbb5d8通过，600全部窗内，成交P50/P95/P99/P99.9为39.128/146.134/208.235/253.777ms，确认P9945.145ms。
- 15笔2902d25c整体NO_GO。计划900、900接口ACK，60秒内165最终成交、限定排空后169最终，731缺最终回执。已收到169条客户端P50/P95/P99/P99.9为44.730/29046.743/70400.845/70451.798ms，接口ACK P99133.497ms。控制代前后Order2/Trade2稳定，资金游标检查PASS，成交明细投影未完成，初次清理code9000保留。
- 后续只读检查显示900个taker订单已Filled、maker为Pending_Cancel，但原taker成交明细仅191条。Trade A日志明确重复TRADE_COMMON_FILL_OVERFILL_OR_INCONSISTENT_REMAINDER。900个订单Filled不能视为900笔经济结算已完成，目前正在核查连续部分成交投递顺序与Trade累计/剩余量条件，未将问题直接归因于Common复制或普通排队，也未以SQL修改状态。
- 正常认证单撤清理在180秒超时后保留NO_GO，异步控制器据此停止后续50Robot，父性能队列及额外严格15队列均NO_GO，未执行后续fresh。当前083209全部原进程及数据继续保留。t554-async-rate15-diagnosis-20261113-090038保存只读线程转储及原进程身份，Java标准QUIT仅打印线程栈，两个受测A进程ID/启动时间/RestartCount保持。暂停下一窗口的父控制器保护已正常解除，resume_required=false，不存在待恢复的人工暂停。
- 用户请求集群原理以审阅合理性。新增docs/T554_CLUSTER_MECHANISM_REVIEW_20261113.zh-CN.md，核对当前5b2ad4c代码、实际部署、单节点ZooKeeper standalone、Witness两端数据只读挂载、实际协商40秒ZK会话及15秒写租约。文档区分双节点客户端异步策略与分区降级状态，说明签名/落盘/托管链、单Stage串行恢复、跨Order/Trade三阶段结算和异步尾部恢复条件，并列出生产故障域、旧主磁盘不可达、证明保留和业务因果顺序的审阅重点。当前生产交付仍NO_GO。

### 2026-11-13 09:38 Order 结算顺序修复已通过完整单测，原现场滚动恢复进行中

- 原因已在投递层稳定复现。已提交匹配的即时hint来自两个线程，可将后一个部分成交先发送到Trade，Trade按自身已结算前缀核对CumQty/LeavesQty时正确拒绝。15/s首次拒绝发生08:55:54，距离08:55:44开始负载约10秒，早于任何窗口后清理。原现场问题不能归给清理操作。后续周期重试和高负载下的失序共同放大尾延迟。
- Order55234c23a3ab28f65d30efb7253935c9f7f72847已提交并推送T554研发分支。沿用既有pendingPartition索引和inFlight，初次结算选择分区内最早未本地确认的匹配，待其Order回执持久化后主动调度下一笔。已本地结算、仅等待复制确认的意图独立重试，ORDER_ONLY成功hint保持原语义，未添加新持久化账本或业务外的Common分支。
- t554-order-settlement-ordering-regression-20261113-092022证明原生产版本5个新测试中4个稳定失败，修改后新5项及原投递13项共18项通过。完整57个Order suite为198项，失败0，原有assumption跳过2。首次汇总把预期数量误写196，实际JUnit成功198导致工具计数断言失败，原full-order-tests.json保留NO_GO。独立RunListener再次运行，精确run198/ignored0/assumptions2/failures0，full-order-summary.json为PASS，未拿错误计数的摘要放行镜像。
- 已构建并逐字节核验应用覆盖镜像sha256:7ed920af7712700ce3bec55020f83e92405c932c1ed8fc2f62ac3b277af62270。基于当前原Order镜像cedad9d，只安装实际受测的OrderSignedMatchDeliveryWorker.class，SHA e57452f2333ada3249492fca71ab37e82bdb8ad4562c24def718665646142f0e。Common仍2571ee、Shared仍5d38aaaeb1c820354bef893b49d130821c6c42c96e745ded860cd7666250489d，经候选镜像中实际文件sha256校验。完整证明在t554-ordered-settlement-overlay-20261113-092831。
- 09:29已通过原roll-voter正常入口对083209 Order A做TERM滚动更新，开启signed-business和持续Robot检查。证据ha-order-a-term-ou3gr8mc，当前已完成存活B全256 LOCAL、真实单节点业务与Robot成交，新A已安装精确e574类，正在原数据上追平及回主。09:35旧900单成交明细已推进592条，09:36只读P095仍由B以E3 LOCAL持有，故这段恢复不能全部归功于新A。原900单窗口NO_GO保持，最终恢复需另立原身份精确核对。
- 同时发现失败5/s准备留下U4QGZF Robot，原1/s样本背景10，原10/s和15/s样本实际背景11。原10基线来源robot-steady-10-005138.json/runtime_status，已限定测试组织归属、通过Manager正常STOP附加U4QGZF并等待owner释放，owned-extra-trial-cleanup-failed-client-setup-before-recovery.json确认原10保留。原样本负载条件已补正，后续固定10复测。
- code5004在现有CodeMsgEnum中为SYMBOL_NOTEXIST。测试准备创建产品后MD注册短暂滞后，原查询立即异常退出。现在沿用原60秒屏障，仅对只读queryPublicMarket的5004继续轮询，其他错误仍直接失败。将既有stop_trial_robot_after_bootstrap移到受控产品准备早期，防止后续准备失败遗留自动Robot，并在下撤单结果记录实际背景cohort。61项Mac Python测试通过。原始失败样本与所有场景数据继续保留，当前没有手工暂停责任。


### 2026-11-13 10:35 原 900 笔恢复、Order 双向滚动与混合确认恢复阻塞

- Order A TERM 滚动替换完成，ha-order-a-term-ou3gr8mc 为 COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS，全量 LOCAL 199.749 秒，Home 532.409 秒。Order B KILL 加 ORDER_ONLY 和持续 Robot 的滚动替换完成，ha-order-b-kill-ka1blzkl 同为 PASS，全量 LOCAL 243.910 秒，Home 526.242 秒。两端实际 Worker.class 已核验 e57452f2333ada3249492fca71ab37e82bdb8ad4562c24def718665646142f0e。
- 原 15/s 的 900 笔已逐原 ClOrdID、OrderID、确定性 MatchKey 和 ExecID 核对。execution-2902d25c-readonly-after-order-a.json 证明 900 taker 与 900 maker 成交明细、原已观察 169 笔成交身份、双方各 0.900 持仓、900 条公共成交及财务游标均一致，残余 maker 正常取消且资金冻结清零。ClickHouse 表为 MergeTree，核对物理原行无重复。原压测窗口 NO_GO 保持，后续恢复不能计作窗口内通过。部分恢复发生在 A 替换之前，恢复效果由原角色变更重放与候选集成共同完成，待新负载验证预防能力。
- 10:00:01.541 对 Trade A 执行原计划 SIGKILL，B 最终 255 分区 READY LOCAL，P143 保留 E2 严格角色并长期拒绝。t554-p143-readonly-observer-20261113-102326 保存只读附加观察，P143 closed=false、poisoned=true、retired=false、pendingAsyncReplication=false，驱动拒绝 Common retained LOCAL source must be its live original primary。WAL 约 12 KiB。原始栈明确 CashIn 第 7 条严格调用在 INDEPENDENT_WAL_FSYNC_RECEIPTS 阶段遇到备节点连接拒绝，未成功确认。未伪造 ACK、Epoch 或 READY，未删除或改写尾部。
- 全局默认 LOCAL_DURABLE_ASYNC 下，TradeStateCoordinator 未携带成交回执封装的 prepared mutation 仍走 strict commitThenApply。Common 原恢复分支仅看默认客户端策略，因而对该已隔离严格尾部误选健康本地主路径。10:26 通过 SIGINT 退出本轮演练，原脚本保存 KeyboardInterrupt NO_GO，父控制器保存 trade-a-kill failed，后续容量阶段取消。
- Common9effc47389a56306f1ec076294b9f3cb3243c2e8 为候选。既有边界增加一个瞬态严格提交未完成标记，在进入物理追加前设置，双端认证完成后清除。严格入口已先排空此前异步复制，因此对未完成严格提交只选原认证前缀，并沿用原退休回执的严格语义。原始严格未确认尾部保留。新增验证沿用原256分区进程用例，同时验证本地异步确认保留与另一分区严格未确认尾部排除，再校验恢复后可写及 Home。未新增账本、恢复框架或业务专用 Common 分支。
- 候选 JAR SHA256 为 72ea1f7fca91595870b12cbcda0ab29761367552678043a5552296cc24a40bf5。t554-retained-strict-p0-controller-20261113-1035 正在执行安全及完整物理门禁，尚未集成部署。旧 JAR 加增强故障用例的对照运行也在保存原始失败现场，当前观察还出现 P105 临时 WAL 安装文件缺失，需结合候选结果继续核查，尚不能报告该增强用例通过。
- t554-p143-preserve-maintenance-20261113-102909 记录维护窗口。暂停 Robot/Liq，保存核心容器身份与重启策略，6 个核心/见证容器正常停写，故障 A 已停。原083209业务数据完整保留，停写后 fstrim 完成，host_free_after=17247145984 字节。当前 Robot/Liq 仍为受控暂停，需在后续部署恢复阶段解除。未开启平行业务环境。


### 2026-11-13 11:24 混合确认组合演练通过，完整 P0 收尾中

- 9effc473 的第一次完整运行通过 210 安全及 12 个原生用例，增强的第 13 个场景在回主阶段失败。原始 NO_GO 保留于 t554-common-verifications/20261113-103322。a-async-survivor-preserved 已证明两类前缀均完成单节点恢复，失败发生在夹具后置读取遭遇暂时恢复拒绝后，测试循环对已成功增加的 COMMAND 再次执行了写前断言，得到 expected.length=12/actual.length=15。该次失败不能报告完整 P0 通过。
- 仅修改测试夹具并提交 f1649ede21e2bd0667f772594d2e84cd801f191f，生产源码与9effc473一致。回主写成功后分别记录本地测试标记，后续只读检查暂时失败时继续验证同一笔，另将 Q 分区回主就绪检查放在 P 写入之前，防止附加检查交错导致测试重复尝试。没有修改生产 ACK 或恢复门禁。
- f164 精确候选 JAR SHA256 为 11eacdf419334d67c82934faa45aad9da462db4402707ca7c4c101c324574683，candidate 20261113-1100、verification 20261113-105824。210 安全通过，13 原生故障用例在1181.987秒全部通过。T554_NORMAL_DUAL_ASYNC_BACKUP_EXPIRY_PRESERVES_ACK_AND_EXCLUDES_STRICT_TAIL_PASS 证实原异步 P000 已确认尾部保留，Q/P001 严格失败尾部排除，对端经过退出78/监督重启后两者回主可写，旧严格第2条物理尾部继续保留。原始主节点本地确认后 SIGKILL、短时备节点失联、双冷节点严格尾部、多个分区 poison 及其重启场景也通过。
- 当前继续运行双向全256分区、中断回归、第三次崩溃及再次Home的最后门禁。尚未生成最终 PASS seal，业务镜像尚未构建部署。维护窗口及原083209数据保持，不能将此阶段进展写成生产恢复完成。


### 2026-11-13 12:00 完整精确 P0 通过，新代基础业务恢复，开始容量复测

- f1649ede/11eacdf419334d67c82934faa45aad9da462db4402707ca7c4c101c324574683 的 verification 20261113-105824 已生成 PASS seal。210 安全、13 原生故障通过，最后全256用例1859.036秒通过。A接管199021ms/Home419638ms，B接管203218ms/Home372218ms，equalWal=256/equalSnapshot=256。中断LOCAL到STRICT续接、第三次SIGKILL、重复Home、跨Epoch退休前缀与本地匹配均通过。
- Root f8fd606 同步增强证据封存校验。含混合严格尾部测试标记的新fixture必须提供 EXCLUDES_STRICT_TAIL_PASS 与两个额外原始证明文件，旧fixture继续按其原精确格式验证，不能用旧标记替代增强证明。Root 64 项 Mac 单测通过。
- build mac-demo-build-20261113-115212 用精确受测 Common 重建最新业务源码，耗时67.686秒。Shared52、Order198含2环境依赖跳过、Trade226、MD207均无失败；Projection沿用受验证的history构建，镜像产物正常。实际Shared JAR SHA为7bbf922805830451207399df42db3730f8946e7011972a72e12e51d55286b883。
- 11:53:20开始原Mac顺序fresh，mac-demo-20261113-115320于11:59完成基础物理与业务校验，耗时340秒。重新走真实E1双RSA出生、独立Witness、E2和512分区运行准入。资金模式与ORDER_ONLY签名SDK成交各自的两条客户ExecID均映射到唯一公共成交，53笔Tape执行、51组成对财务事件，资金持仓与认证财务游标0差异。基础业务通过不代表新代HA故障演练完成。
- 维护责任已解除，旧Robot/Liq在fresh前正常unpause后由新部署正常替换，当前新Robot/Liq及4核心与2Witness均运行。原083209故障代与全部数据离线保留，未恢复旧Epoch写权。t554-mixed-recovery-verified-deploy-20261113记录源SHA、构建和新代身份。
- Root7e4dede将固定速率测量上限扩展为100/s、60至300秒、最多6000笔、仍最多16个HTTP在途与无写请求重试。新测量账户每个100000资金通过正常cashIn及余额投影核对准备，最大maker6.001、名义量按11%预留后小于该资金。既有调用仍默认10000。63项单测包括上下界、正常入金与旧调用兼容通过，后续加固封存后共64项通过。Root8d6ae18在失败行仅保留安全API错误码，便于区分限流与业务拒绝。
- t554-mixed-recovery-capacity-then-business-20261113已自动衔接新代干净异步容量。将执行下撤单、10Robot、1/5/10/15/25/50/100逐档固定速率及50Robot，超出完成边界时先正常清理与对账并保留界限。其后衔接新代真实异步RPO与4方向持续Robot业务故障。严格模式同构建对照仍待后续阶段，当前总体生产NO_GO。


## 2026-11-13 13 时 25 分，高负载边界及原数据业务恢复

- 当前 115320 代、Common f1649ede、Order55234c2、固定原 10Robot 的异步压力已测到 50 笔每秒。1/5/10/15 的最终成交 P99 分别为80.760/261.737/430.571/683.793毫秒。25 笔每秒1500笔全部在限定排空内完成，但60秒窗内仅855笔，最终P99为29.538秒。50笔每秒计划3000、实际2819接口确认、181调度丢弃、窗内327最终、限定排空907最终，原报告NO_GO，100档未执行。详细口径与下撤单六组结果已汇入集群机制审阅文档。
- 高压结束后读现场线程栈证实撤单锁反转死锁。Orderdfa4dfb统一先分区屏障、再订单锁，确定性回归测试旧版重复失败、补丁通过，完整199项无失败且2项环境依赖跳过。第一次原数据冷替换前，256真实认证水位、零待复制及256对物理WAL字节核对通过。原A死锁需强制退出，B正常退出，保留旧容器与数据，两端已于13:07恢复，原10Robot全部RUNNING。
- 原maker自动Cancelled并解冻，但1882笔Suspended未推进。找到现有PendingNewOrderReconciler无调度调用的实际接线缺口，8e1de5e接入原Spring调度，使用已有scanMillis默认5秒和所有既有门禁。新增回归旧版失败，完整200项无失败且2项既有跳过。两项Order修复均已推送GitHub研发分支。
- 精确新Order镜像sha256:3a9f093033e0246aeed22ef5e61befd3f365a0b1a6641f030faad39d0af73933，Common11eacdf4与Shared7bbf9228保持精确受测版本。后续构建mac-demo-build-20261113-131933同时保留源码、编译类、打包JAR、镜像及完整200项测试记录。13:24再次以256认证水位与256对WAL停写核验后，在原115320数据上受控替换Order，尚待原业务恢复与资金成交核对。
- 新增只读精确成交核对入口reconcile-mac-demo-execution-capacity.py，从原测量匹配确定性MatchKey/ExecID、两侧明细、真实数量与持仓、原已观察私有成交及ClickHouse MergeTree原始公共成交行。重复行、缺失私有身份与错误持仓回归覆盖，Root67项Mac测试通过。原压力失败结果不会被事后恢复覆盖。

13 时 29 分补充。新接线同数据启动完成，正常调用与既有恢复器将原2819笔已确认taker推进至935 Filled、1884 Cancelled，maker另为Cancelled。两账户冻结保证金与手续费归零。execution-90adc885-md-reconciliation-20261113-052654-287124核对935组确定性双侧ExecID、原已观察私有成交、持仓及935条原始唯一公共成交通过，财务游标0差异。两端Order线程转储无死锁，原10Robot均RUNNING，维护暂停责任已全部解除。原50档测量仍为NO_GO。t554-order-newing-cold-maintenance-20261113-132424保存前后256物理证明与同数据恢复记录。

13 时 45 分维护补充。已将113个停止容器日志文件逐文件完整压缩、解压SHA核对后清空原日志，原始约3.842GB、压缩约343MB，容器和业务卷保留。t554-stopped-container-log-compaction-20261113-133331保留清单与归档。11月12日旧原生物理证据已全量压缩校验后收回原目录内容，最新f164完整P0及先前223437基线原始证据保留，位置t554-inactive-native-compaction-20261113-133229。主机约9.2GiB、Docker卷约8GiB空闲。134201新部署预检因本次手工叠加构建目录缺少order/image/lib而失败，发生在原业务停写之前，原失败记录保留。已克隆为134409构建并恢复精确Common/Shared JAR，镜像字节保持受测3a9f0930。134411严格模式顺序新部署已经开始，旧115320的已核对业务数据随原代保留。

严格134411代基础部署与业务364秒通过，最新Order8e1de5e、精确Commonf164、Tradeaefad60d。下撤单六组89e1106d全部通过，OO并发1/4/8完整闭环每秒17.026/24.381/22.513，资金模式9.420/16.392/17.570。各组P99及口径已补入集群机制文档。正式测量前，旧174426-ready全722605文件、路径元数据、逐文件SHA、完整gzip复核通过，6.30GB分配数据压缩为867249279B，归档SHA ba68c462dff02f7121848f457601b1564beb87e3caaa236fe68ae42514b07a0b后回收旧卷内容。最新严格固定速率与50Robot将先测容量，再单独以JFR采集25/s热点瓶颈，诊断样本不会混入正式压力对照。
