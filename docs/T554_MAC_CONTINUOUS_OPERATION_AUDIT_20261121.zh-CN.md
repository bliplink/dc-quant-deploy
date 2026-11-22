# T554 原 Mac 连续运行审计

2026-11-21 晚。检查对象为原 Mac 的 `mac-demo-20261121-205353`，严格确认模式。从原 Demo 的网关、业务容器、MySQL、ClickHouse、ZooKeeper 及实际挂载卷读取运行证据。原 10 个 Robot 持续运行。

## 自动处理和可恢复归档

| 对象 | 现行配置与观察 |
|---|---|
| Order、Trade、Gateway、Robot 等服务的 Docker 日志 | `json-file` 每 50 MiB 滚动，每个容器保留 5 份。滚动后较旧文件会被覆盖。交易 Web 容器本身未设置这一上限。 |
| 已检查的 Order、Trade、Gateway 应用日志 | 启用 Log4j 文件滚动，单文件 50 MB，5 个历史文件。部分常态业务日志同时写文件和标准输出。 |
| MySQL binlog | 约 1 GiB 轮转，自动清理开启，过期配置 30 天。当前 `sync_binlog=1`，InnoDB 提交刷盘为 1。已关闭日志的压缩归档由人工执行。最新检查时仅有当前打开的一段；已归档的旧段通过校验后用 MySQL 的原生命令清理。 |
| Common WAL 和签名快照 | 当前 Order、Trade 已配置定期快照并有实际快照文件。未找到运行中的 WAL 自动归档任务，也未验证按可恢复水位安全回收的流程。现役 READY 卷约 15.2 GiB，其中 `business.wal` 约 6.48 GiB，快照相关文件约 5.21 GiB，其余包含复制、认证和恢复资料。 |
| MySQL 业务表、投影与完整备份 | 三张投影历史表在 MySQL 中报告约 5.24 GiB 数据和索引，实际表文件分配约 5.5 GiB。未确认有连续自动外送的完整快照、配套 binlog 目录与通过的时间点恢复演练。 |
| ClickHouse 行情 | `market_trade` 有两天 TTL，由 ClickHouse 合并过程执行。K 线表及已检查的系统查询和分区日志表无 TTL。 |
| ZooKeeper | `autopurge.snapRetainCount=3`，`autopurge.purgeInterval=0`，定期自动回收未启用。现场约 10 MiB。 |

已抽样解压校验一段 1.0 GiB 的 MySQL binlog 与一份 50 MB 的旧 Docker 日志，两份均与归档时 SHA-256 一致。这个检查验证了归档介质的字节，完整服务恢复和时间点恢复还要独立演练。现有归档在同一台 Mac 上。

本轮把 11 月 16 日已停用 Demo 的三份恢复交换目录压缩归档，逐包与原目录做完整比较并登记 SHA-256 后，释放原位置的旧副本，净回收约 3.2 GiB。归档校验清单为 `old-20261116-020105-recovery-exchange-archive/checksums.jsonl`。原 10 个 Robot 和现役服务持续运行，现役 WAL、快照和业务表仍在各自的运行卷。23:02 Mac 可用约 7.1 GiB，Colima 数据盘可用约 10.1 GiB。

## 当前增长和运行状态

北京时间 22:54:42–22:55:43，无主动压测，原 10 个 Robot 运行。该分钟内 MySQL binlog 新增 26.8 MiB，三张投影文件新增分配约 28.0 MiB，Gateway 日志新增约 1.6 MiB。同期宿主可用空间减少约 232 MiB，Colima 可用空间减少 128 MiB。两侧文件系统和运行中的独立 Common 验证均可能影响这些数值。单个分钟窗口适合识别持续增长，不能作为全天增长率。

现役 Order 和 Trade 各 256 个分区 READY，控制代数均为 2。只读复查中，10 个 Robot 全部运行，10 个租户的盘口、最近成交、价格与历史 K 线通过。严格模式当前业务版本在此前的多租户千笔发单窗口中完成 61.90 笔最终成交每秒，P99 为 11.40 秒。现有 A/B 和 Witness 共用同一 Mac 与 Colima，Mac 或其存储整体失效的场景没有独立故障域保护。

## 优先改进

1. **先让连续运行有磁盘余量。** 宿主和 Colima 分别监测可用字节、写入增长与可运行时长。约定告警和降载阈值，先缩小新单准入保留撤单。短期迁移已校验的冷归档到独立介质。当前多个 10 GiB 级旧 READY 卷仍在同一虚拟盘上。
2. **实现可恢复的自动归档。** MySQL 先以一致性快照加连续 binlog 建立备份链。Common 以分区为单位做可滚动 WAL 段，记录签名快照、ACK 提交水位、备节点追平、历史重放和投影消费所需的下限。归档外送、字节校验及恢复演练完成后，才回收经判定可退休的段。保留 Epoch、Fencing、签名和实际落盘 ACK。
3. **先减写入，再调资源。** 审查投影历史表重复保存的完整事件和变更、Trade 快照重复数据以及应用文件与 Docker stdout 的重复日志。明确可重建投影和应长期保留的交易及资金凭证。给交易 Web 标准输出补齐滚动上限。归档前抑制会话标识与完整请求体进入常态日志，并对旧归档控制访问。
4. **修结算热路径与可见回执。** 按独立资金分区并行，在单分区内保序批量提交，分别量锁等待、本地刷盘、备端 ACK、最终通知与 SQL 投影延迟。保持真实盘口、较冷品种、主改备、单节点和 Robot 持续报单覆盖，按严格和异步各跑到最终回执。
5. **完成故障域与业务验收。** 在独立节点与存储上验证备份恢复和 A/B 自动追平，补齐平仓、出金、旧订单和客户端最终回执。独立 Common 故障验证仍在原 Mac 运行，以跟踪已验证的故障场景。

## Common 现役版本的镜像和归档

23:31 复核现役 Common `f90d8f3`。库已经有 `JournalArchiveRotationPolicy`、`JournalArchiveSealCoordinator`、持久封存账本、`JournalArchiveRetirementCoordinator` 和 `SnapshotRetentionFence`。代码中构造并执行封存协调器的入口在测试里。当前 Order、Trade 的认证运行接入了 Common 签名镜像周期任务，仍按节点、分区和 Epoch 打开原 `business.wal`。未发现现役启动入口把该物理 WAL 接到自动切段及回收流程。需求 C33–C35 的约两天是 Demo 的设计保留期。

现有镜像带分区、Epoch、提交序号和哈希，当前指针文件叫 `opaque-v2-current.pin`。Common 发现同一认证水位已有可读镜像时会跳过重建。水位推进后，新镜像会生成独立文件。23:31 时，Trade B 的 P181 主镜像目录留存 **114 份镜像文件，合计 514.2 MiB**，单份最大 8.76 MiB。全 READY 卷当次逻辑文件大小约为 **6.73 GiB WAL、6.60 GiB 主备镜像目录、3.32 GiB 其他文件**。

接入时优先复用已有封存与回收判据。当前运行时、见证、历史回放、回主和投影读取须能连续访问已确认历史。先独立验证新写入段切换、旧段重开重放和断电续办，再以主备可恢复镜像、认证提交水位、消费进度及恢复引用判定何时回收 WAL 段和旧镜像。拿持续写入、多次滚动、重启、接管和回主检验磁盘空间是否稳定在上限以内。23:31 盘点只读取现役卷。

23:35 复查发现 10 个 Robot 中 4 个 RUNNING、6 个 ERROR。22:57 左右 Order A/B 与 Trade A/B 都在约 40 秒未续租后执行隔离退出，配置租约为 15 秒。四个容器均由原策略重新启动，Order B 记录了累计 14 次重启，启动日志显示缺少符合认证要求的 LOCAL 物理分区和 Epoch 目录。Trade 已回到 256 个严格 READY。Order 清单有 249 个 LOCAL READY、3 个严格 READY、4 个 RECOVERING，部分 LOCAL READY 分区也实际拒写。未证实 WAL 增长与这次续租超时之间的因果关系。现役证据保留，独立 Common 候选的完整物理门禁仍在执行。

本机分钟采样为 `~/.opentradingcore/mac-demo-20261121-205353/growth-60s-passive-2255.json`。行情复查为 `t554-order-a-stall-20261121-LSxSMI/readonly-join/public-demo-storage-audit-market.json`。部署与浏览器证据见 [T554 原 Mac 公网 Demo 验收](T554_MAC_PUBLIC_DEMO_ACCEPTANCE_20261121.zh-CN.md)。

## 2026-11-22 凌晨续查

00:05 对原运行卷和授权清单复查时，Order 有 253 个单副本 READY 及 3 个严格 READY，Trade 有 249 个严格 READY 及 7 个 RECOVERING。10 个 Robot 中 1 个 RUNNING、3 个 DEGRADED、6 个 ERROR。Order B 当时已自动重启 47 次。它被指派的 P128 E3 单副本主位缺少本地 Epoch 目录。Common 的冷启动无法据此证明该 Epoch 的已提交边界，拒绝打开写入器。P181 和 P036 的 Trade 缓存诊断分别报物理退役未完成及旧物理证据注册表已关闭；两侧 JVM 仍在线。采样文件为 `post-genesis-fix-live-status-20261122.json`，分区观察记录位于当前部署目录的 `recovery-observation-*`。

Common `91f138b` 把空 WAL 和签名零水位的持久化移到 LOCAL READY 之前。仍要求独立见证、原持久化证明及当前租约，并对新 WAL 已有尾部的情况拒绝发布。Common `1a36ecf` 把现有的对端离线校验移到 LOCAL 接管者关闭旧备盘之前，使在线严格角色切换由严格恢复路径处理。两项改动已各自通过定向回归，其中包括独立 JVM、真实 ZooKeeper 与物理 WAL。完整门禁按最终 JAR 重新运行，原 Demo 继续保留现役数据。

此次额外归档了已关闭的 MySQL binlog、11 月 16 日退役实例的两份 Trade 快照目录，以及 11 月 14 日退役实例的三个投影表文件。逐包比较或逐文件 SHA-256 比较通过后才释放原位置的旧副本。00:13 Mac 可用约 11.35 GiB。现役 Common WAL 与快照归档闭环仍待接入和验证。

00:17 原 10 个 Robot 均转入 ERROR。随后在同一 Mac 先停故障实例，再用已通过完整 Common 故障门禁的 `f90d8f3` 严格版建立 `mac-demo-20261122-002050`。原容器、租户数据库及 Common 运行卷保留，可按 `retired-containers.json` 回退和取证。新实例启用了新的控制命名空间和租户数据，共补齐 10 个 Robot。

新实例验证了 Order-only 与资金模式的成交、未成交撤单、公开成交匹配及资金和持仓游标；Order、Trade 各 256 分区均为严格 READY，四个 JVM 各有 128 个可写主分区。00:25:31–00:30:31 的 10 Robot 样本完成 4,268 次报价请求、1,128 笔成交，成交发布延迟 P99 为 59.31 毫秒，资金过账差错为 0。十个租户的公开行情均通过。公网主站桌面与移动端入口均到达当前活跃租户，渲染历史 K 线并收到实时 WebSocket 更新。证据为新实例的 `physical-runtime-8dt8116v/proof.json`、`verification.ef6Irp/`、`robot-steady-10-163031.json` 和审计目录的 `restored-public-demo-browser-20261122/observations.jsonl`。

本次恢复保留的是已验收的严格基线。Common `1a36ecf` 的定向回归已通过，最终 JAR 的独立完整物理门禁仍在运行。上述 10 Robot 实盘采样不代表每秒 1,000 笔、P99 不超过 20 毫秒的性能验收。

## 恢复后的 TCP 下撤单与磁盘复测

10 个 Robot 持续运行时，在原 Mac 的严格基线上分别用一个已认证的 TCP 会话运行 30 秒。两种模式都逐笔核对了 New、Pending_Cancel、Cancelled 和最终余额与挂单。Order-only 完成 1,071 个完整下撤单循环，每秒 35.68 个，New P99 为 21.54 毫秒、Cancelled P99 为 25.54 毫秒。资金模式完成 843 个完整循环，每秒 28.10 个，New P99 为 39.59 毫秒、Cancelled P99 为 38.28 毫秒。

恢复后对四个写入 JVM 进行两次各 20 秒的内核刷盘采样，单次调用耗时 P99 约 1.70 毫秒。一次按稳定文件描述符归类的样本共 5,057 次调用，业务 WAL 和提交／保管证明各归类 2,496 次，余下 65 次未可靠归类。采样范围为四个 JVM，Docker 日志守护进程在范围之外。代码核对显示，Trade 现有的有序结算 RPC 会在窗口内逐条调用资金结算，每条都经过独立的 Common 提交。当前结果支持优先测量和减少每笔交易的独立提交轮次，再用同一负载分别复测严格与本机落盘异步模式。

下撤单证据在新实例目录的 `order-cancel-capacity-ba4e60d4.json` 与 `order-cancel-capacity-5f9163aa.json`。刷盘证据在审计目录的 `restored-strict-fsync-by-file-20261122-attribution.json`。

01:19:50–01:20:52，两个业务控制清单保持第 2 代，10 个 Robot 均为 RUNNING。运行卷中业务 WAL 增加 25.7 MiB，快照目录增加 27.6 MiB，其他 Common 文件增加 11.6 MiB，MySQL binlog 增加 19.3 MiB，投影表分配增加 24.0 MiB。这是正常报价和成交下的单分钟实测，证据为 `restored-demo-storage-growth-20261122.json`。

## 修复版上线

02:04，Common `1a36ecf` 的最终 JAR 通过完整物理门禁。独立 Demo 的双向掉电、第三次掉电后的降级写入、再次追平与回主均通过，主备各 128 个主分区归位，256 个分区的 WAL 和快照逐一匹配。双向全量接管分别为 182.0 秒和 194.9 秒，全部回主分别为 504.6 秒和 492.4 秒。物理凭据位于 `local-ready-and-live-strict-20261122-0013/verification.seal.json`。这些耗时仍需优化。

02:11，使用同一 SHA-256 的 Common JAR 在原 Mac 启动 `mac-demo-20261122-020700`。当班的上一代容器、数据库和 Common 运行卷保留回退。Order、Trade 的四个 JVM 均通过实际写入器和角色验证；Order-only 与资金模式经真实成交、IOC／FOK 撤单、行情与资金持仓核对。

02:12–02:17，新的 10 个 Robot 五分钟内发出 2,700 次报价请求、完成 1,337 笔成交，资金过账差错为 0，成交发布 P99 为 47.82 毫秒。所有租户公开行情及桌面、移动端从主站进入交易页的 K 线和实时 WebSocket 通过。独立模拟账户初始 10 USDT，同一出金请求以 1 USDT 重复提交两次，最终余额为 9 USDT，认证资金流水只有一条。相关文件为 `robot-steady-10-181746.json`、`qualified-common-1a36ecf-market.json`、`qualified-common-1a36ecf-public-browser/observations.jsonl` 和 `qualified-common-1a36ecf-simulated-cash-out.json`。

## 原 Mac 业务节点滚动验证

以下接管时间从脚本开始等待全部分区可降级写入计算，回主时间从等待替换节点归位计算。每次回主均核对 256 个分区在两台物理进程中的原单副本 WAL 和恢复镜像。

| 故障 | 接管 | 回主 | 业务证据 |
|---|---:|---:|---|
| Trade B 正常终止 | 142.4 秒 | 647.4 秒 | Trade A 单节点处理资金和持仓。两端均收到带单副本风险标记的最终成交回执，Robot 在降级期间和回主后均有新成交，资金游标一致。 |
| Order A 正常终止 | 127.8 秒 | 654.4 秒 | 原脚本因普通成交日志已精简而未通过。独立认证重放读回了单节点期间的两条订单成交，核对最终订单状态、公开成交与资金不动。修正后的查询直接核验 Common WAL，代码为部署仓库 `27389cc`。 |
| Order B 强制退出 | 188.0 秒 | 705.3 秒 | Order A 单节点 WAL 中有两条精确匹配的成交回执，回主后可重读，256 个分区的 WAL 和恢复镜像均一致，资金游标通过。同期外部行情暂停，Robot 降级阶段门禁仍保留失败。 |
| Trade A 强制退出 | 207.4 秒 | 739.7 秒 | 退出码 137，Trade B 接管 256 个分区。两账户收到明确带单副本风险的最终成交回执。同一 Robot 降级期间成交 7 笔，回主后成交 3 笔，过账逐笔成对。Trade A/B 各归位 128 个主分区，所有分区的物理 WAL 和恢复镜像、资金游标均匹配。 |

对应原始证据位于当班部署目录的 `ha-trade-b-term-4pp12r29/`、`ha-order-a-term-*/`、`ha-order-b-kill-et7h73b2/` 和 `ha-trade-a-kill-2jzn7ghq/`。

03:00:01.972 至 03:02:24.004，APSSvr 的 BTC 标记价输入中断约 142 秒，其他已订阅品种也出现断流重连。Robot 按陈旧行情保护暂停报价，连接由 APSSvr 自行重建。仅凭应用日志无法确认是外部行情源还是其网络路径中断。随后 Order B 回主时，在签名路由刷新或分区未就绪的窗口观测到挂单查询拒绝。对照在运行镜像的源版本 `4384fd1`，挂单查询已在分区检查前过滤租户和品种，故障仍受 Common 控制授权可用窗口影响。

Robot `e8602dd` 复用现有有限退避，仅为带路由键的挂单查询识别精确的签名路由暂不可用回包。请求仍使用原认证会话和目标分区，且只有正常查询回包才解除本次查询失败。126 项测试通过，03:19 只替换 Robot 镜像，约 22 秒内核对十个既有租户均重新运行。Order、Trade、Gateway、APSSvr、MDSvr、MySQL 的进程身份没有变化，Order 和 Trade 的严格控制代数分别保持 2562 和 1282。本次改动覆盖短时路由刷新。完整故障窗口的连续 Robot 成交仍待复验。

另外将当班 MySQL 已关闭的两个 binlog 压缩归档，逐字节 SHA-256 校验后由 MySQL 清理源文件，当时正在写入的 binlog 保留。两段原文件约 1.00 GiB，压缩归档约 123 MiB。归档索引为 `closed-qualified-demo-020700-binlogs/sha256.jsonl`。Common 现役 WAL 和镜像仍在运行卷中，自动归档及可恢复回收未通过验收。

03:20–03:25，Robot 修复版下，10 个既有租户持续发出 1,840 次报价请求并完成 1,448 笔成交。认证过账差错为 0，成交发布 P99 为 102.09 毫秒。行情无额外压测，此 P99 是正常运行采样。证据为现役目录的 `robot-steady-10-192517.json`。

## 行情连续性复查

03:24，十个租户的行情只读门禁发现九个租户 03:00 的 BTCUSDT 一小时 K 线，开盘价落在实际高低价区间之外。ClickHouse 原始行已存在同样的问题。MDSvr 生成无成交区间时会沿用前收价，第一笔真实成交原来只清除占位的高、低和收盘，留下占位开盘价和时间。MDSvr `d8d2cea` 让首笔真实成交建立该区间的四个初值和开盘时间，208 项测试通过。

03:30，仅替换 MDSvr 镜像。修复前，将九个受影响的租户行和原恢复镜像留存。根据现有行情成交记录中的首笔真实成交修复开盘价和对应时间。ClickHouse 通过原版本机制写入校正后的行情投影，只在 MDSvr 停止时原子替换对应恢复镜像。Order、Trade、Robot、Gateway、APSSvr、MySQL、ClickHouse 保持原进程。盘口追平后，10 个租户的盘口、近期成交、价格和四个 K 线周期全部通过。证据为 `md-kline-real-open-d8d2cea/repair-result.json`、`md-kline-real-open-d8d2cea/live-replacement.json` 与 `md-kline-repaired-10-tenant-market-final.json`。

额外冷归档了 11 月 16 日 06:50 已退役 Demo 的四份 Common 历史数据目录。原目录合计约 2.32 GiB，压缩件约 0.61 GiB。逐包与原文件比较并登记 SHA-256 后释放退役目录，证据为 `old-20261116-065052-certified-data-archive/checksums.jsonl`。

## 公网入口恢复

当班主站重建时暴露了镜像仍含旧版入口代码和已停用网关端口的问题。首次覆盖的配置文件也因镜像内权限无法由 Nginx 读取。最终镜像固化主站已审阅的 `780cc69` 页面代码、可读配置和版本化资源，公网目录通过本机的固定交易 Web 入口访问当班网关。当前 Demo 链接选用已验证的 `BB0201`，仍由公开目录核验租户可用性。安装及权限检查均保存在本机运行证据目录。

03:41–03:42，桌面和 iPhone 13 的真实公网浏览器均从主站进入 `BB0201`，加载 19 根 BTCUSDT 五分钟 K 线，并收到实时 K 线更新。两个浏览器均无脚本错误。对照前一代镜像，重建后主站配置、公网目录和新页面资源均由最终运行容器提供。原始网络状态、图表数据和截图见 `public-demo-live-reviewed-entry/`。

## 双副本恢复后的运行状态

04:00，Trade A 演练验证完成并停用当次创建的临时 Robot，既有十个 Robot 继续运行。Trade A 追平时的 35 秒样本中，两个 Trade JVM 均未触发 CPU 限流，ZooKeeper 在 351 个周期中有 72 个被限流。04:00:50 将 ZooKeeper 从 0.75 调整至 1.5 核并写入当班部署配置，运行进程和内存配置保持原样。耗时表使用调整前配额，调整后的完整故障时延待独立复测。证据见 `trade-a-recovery-resource-sample.json`、`trade-a-return-progress-and-robot-health.jsonl` 和 `trade-a-post-test-zookeeper-cpu.json`。

04:02，调整后再次确认 Order 和 Trade 各 256 分区严格双副本、十个既有 Robot 全部运行、资金游标一致。十个租户行情全部通过，04:00 新的一小时 BTCUSDT K 线共十根，均满足开、高、低、收约束。证据见 `operator-final-strict-finance-state.json` 和 `final-after-trade-a-reset-public-market.json`。

另两份 11 月 15 日 18:08 退役 Order 认证数据目录在完整比对及登记 SHA-256 后释放旧副本，源约 3.74 GiB，压缩件约 1.24 GiB。证据为 `old-20261115-180803-certified-data-archive/checksums.jsonl`。当前业务卷和最新回退卷均保留。

双副本恢复后，Colima 回收文件系统中已空闲的存储块，系统报告处理约 13.1 GiB 空闲块。随后宿主可用空间约 19 GiB，Colima Docker 数据盘可用空间约 12 GiB。证据为 `post-trade-a-colima-free-block-trim-full.log`。

持续每秒 1,000 笔及最终回执 P99 不超过 20 毫秒的性能门禁仍待通过。现役 Common WAL 和镜像的自动归档与安全回收也待实装验证。

## 06:43–06:54 现役容量与归档复查

现役实例仍为 `mac-demo-20261122-020700`。Order 和 Trade 各 256 个分区保持严格双副本，10 个 Robot 运行。最近五分钟读回 1,423 笔独立成交，过账差错为 0。资金游标在第二次读取时与认证源水位一致。相关证据为 `archive-stage-20261122-robots.json` 和 `archive-stage-20261122-live-finance.json`。

当班将 MySQL 的三个已关闭 binlog 压缩、解压复核 SHA-256 后，通过 MySQL 原生操作释放源文件，保留正在写的 binlog。另将 11 月 21 日 20:12 退役实例的四份历史数据目录压缩复核。退役目录原始文件约 3.15 GiB，压缩约 0.77 GiB。Colima 回收这些空闲块后，Mac 可用约 12 GiB，Colima 数据盘约 9.3 GiB。证据为 `archive-qualified-demo-binlogs-000006.log`、`old-20261121-201216-certified-data-archive/checksums.jsonl` 与 `archive-stage-201216-colima-trim.log`。

最新现役 Common 卷的分配空间中，业务主／本地 WAL 约 5.71 GiB，主备镜像目录约 1.19 GiB，其他文件约 3.79 GiB。四个投票节点的 `commit-index/commits.wal` 合计约 2.33 GiB。备节点追平、见证和投影读取均依赖原逻辑地址与认证证明，后续切段须把业务 WAL 和对应提交索引作为同一历史范围验证。容量证据为 `archive-stage-current-common-volume-20261122.json` 和 `archive-stage-current-common-other-volume-20261122.json`。

## 退役 Epoch 归档路径验证

Common `c3107db` 新增经过认证的退役 Epoch WAL 压缩导出。它从已有签名历史读取提交边界，按原始 WAL 帧和坐标写出，回读校验压缩内容，再发布完整文件。当前 Epoch 拒绝导出。写入中断可以重试，已有归档若损坏会报错。定向测试覆盖带未提交尾部的原文件、损坏压缩件、发布前被强制终止。候选 JAR SHA-256 为 `1f129666b9ebe5a5b914f6cc6719fda05b419ac83e09900cee6a17a80230931c`。

06:50 独立进程首轮成功写出归档，测试随后用低于普通历史读接口规定的字节上限读回，失败记录仍保留。修正验收脚本后以原 JAR 重跑。07:18，在独立进程强制退出后实际重开严格 Epoch 2 的两条和 LOCAL Epoch 3 的一条记录。镜像与 WAL 的隔离组合恢复也通过。恢复目录只复制压缩镜像、压缩 WAL、公开密钥及已有签名证明，重开时从严格的双 RSA 提交索引、原签名单副本水位和认证镜像重放原始数据。证据为 `archive-detached-signed-readback/proof.log`、`archive-detached-signed-readback/snapshot-and-wal-proof.log`。同一候选包的 319 项安全检查通过，另有 3 项依赖外部历史样本的用例跳过。

07:14，新的 MySQL 关闭段也在 SHA-256 校验后完成归档并释放源文件。另对 332 份字节相同的退役构建依赖做 APFS 写时复制去重。现场没有启用运行中的 WAL 自动切段、镜像保留回收或现役文件删除。后续需要把自动切段、归档回读和回收水位接入正式运行时，并验证各类恢复路径和投影持续读取。

## 07:29–07:42 重复接管、归档与持续运行

独立 Common 再次完成 256 分区双向物理断电切换。A 掉电后接管用时 182.9 秒、A 回主用时 550.7 秒。B 掉电后接管用时 198.3 秒、B 回主用时 501.1 秒。第三次强制退出后，存活节点再次在全部 256 分区进入单副本可写，替换节点归位后再次逐分区比对两侧 WAL 和恢复镜像。第三次回归及跨 Epoch 历史读回均通过。独立故障用例 17 项、双向及重复回主用例 1 项全部通过。原始记录位于 `retired-wal-export-20261122-0705/home-faults.log` 和同目录的 `native-faults.log`。该次物理验收凭据 `verification.seal.json` 的 SHA-256 为 `a36b2d36dcc986954296b92031e529d2980556e2d6489cb3a11e3637152ec398`。正式门禁包括独立的中断恢复及冷启动组合，同一候选 JAR 已另行启动正式门禁。

Common `404fd6d` 把隔离归档恢复接入现有物理回归。测试仅复制压缩镜像、两份压缩 WAL、原签名水位和镜像证明到空目录，按原节点和分区坐标展开并认证，重放后逐字节比较原状态与原 WAL。同一候选 JAR 和本轮 P128 物理工件已直接运行新增验证并通过。初次在隔离目录缺少分区及节点层级被 Common 拒绝，纠正测试目录后通过。归档性能的独立样本为 1,024 条 64 KiB 记录，约 64.03 MiB 压至 32.22 MiB。导出及回读校验共 1.23 秒，验证已存在的归档约 0.44 秒。样本只有一个冷分区，正在把该量级的历史读等待纳入自动归档设计。

07:34 已核对归档 11 月 21 日 17:41 退役实例的四份认证数据目录。源数据约 7.69 GiB，压缩件约 1.95 GiB。逐包比对原目录并记录 SHA-256 后释放旧副本，可用空间回升至 Mac 约 16 GiB、Colima 约 18 GiB。现役及最近两个回退卷均保留。证据为 `old-20261121-174139-certified-data-archive/checksums.jsonl` 和 `archive-stage-174139-colima-trim.log`。

现役仍为 Common `1a36ecf`、Order 和 Trade 各 256 个严格双副本、10 个 Robot 全部运行。五分钟业务核对观测到 1,477 笔成交，资金过账差错为 0，公开行情及 K 线覆盖十个租户。资金游标首轮有 1 个分区处在投影追平窗口，复读时全部对齐，414,122 条历史前驱记录无差错。另一个五分钟的被动延迟样本有 1,448 笔配对成交，Tape 到最终成交发布的 P99 为 95.35 毫秒。该结果来自正常 Robot 流量，尚无达到每秒 1,000 笔、端到端 P99 不超过 20 毫秒的证据。复查记录为 `archive-stage-20261122-final-robots.json`、`archive-stage-20261122-exact-finance-recheck.json`、`archive-stage-20261122-final-market.json` 和 `archive-stage-20261122-passive-latency.json`。

下一阶段从 Common 的原始 WAL 读取路径接入已封存的段，保持原分区、Epoch、序号和签名提交坐标。业务 WAL、对应提交索引与恢复镜像按同一水位验证。验证场景包括在原文件不可用时重启、备节点落后后追平、见证接管与双向回主，以及投影从封存段追到活跃段。通过这些验证后，回收仍须由 Common 按可恢复镜像、备节点水位、持久消费游标及已有保留期放行。

07:46，另将 11 月 16 日 02:01 退役实例的四份认证数据目录逐包归档。源约 9.88 GiB，压缩约 2.60 GiB。逐包原件比对、登记 SHA-256 后释放旧副本。Mac 可用约 23 GiB、Colima 约 28 GiB。现役实例的一分钟只读采样测得业务 WAL 增加 23.51 MiB、签名提交索引增加 9.57 MiB。样本未覆盖快照或 MySQL 的下一次轮转。证据为 `old-20261116-020105-certified-data-archive/checksums.jsonl`、`archive-stage-020105-colima-trim.log` 和 `archive-stage-steady-growth-0745.json`。

07:48，根据独立物理运行保留的 P129 双 RSA 签名提交索引，把同一 Epoch 的前 2,048 条装入压缩段，后 2,052 条保留成 WAL 尾段。在独立目录合并读回 4,100 条，Common 校验全部原始序号、字节与最终签名水位。缺少尾段时拒绝按 4,100 水位重放。证据为 `archive-detached-signed-readback/regression/segmented-p129.T5jfXK/result.log`。原签名提交水位可验证重组后的完整日志。在线切段、持续写入、断电续办及回收仍需要运行时验证。

07:49–07:50，桌面和 iPhone 13 浏览器再次从公网主站到达 `BB0201`。两侧各渲染 68 根 BTCUSDT 历史 K 线并收到实时更新，无未捕获脚本错误。证据为 `archive-stage-public-demo-20261122-0749/observations.jsonl`。

## 07:53–08:00 归档并发与单副本回执修复

归档读锁原来以 64 个槽映射全部分区。按 256 个分区计算，只有 40 个槽被使用，最拥挤的槽共享给 12 个分区。Common `e43c9ce` 把锁改为各分区独立，保留同一物理 WAL 的文件锁和原授权检查。P128 与 P205 在旧版取到同一个锁，在新版取到各自的锁。同一分区仍串行。定向用例 23 项通过，1 项旧外部数据用例跳过。证据为 `archive-partition-lock-targeted-20261122.log`。

07:56，首轮正式 Common 门禁在单节点已落盘命令的回执路径失败。P001 在本机落盘之后、业务应用之前，遇到控制清单刷新，业务恢复门禁得到暂时为空的分区清单。旧写入器把它当作确定失败并隔离，原探针不得重发。原候选保持发布 NO-GO，证据为 `retired-wal-export-20261122-0650/qualification/live-local-published-head.log`。

Common `a3c5b1f` 先获取原分区的物理授权。在业务恢复检查失败时再次核验该授权，只有原授权也证实正在刷新，才进入原有的有限等待。返回客户确认前仍同时要求该分区的业务恢复记录、本机落盘和有效授权。授权有效而业务恢复记录确实缺失时仍拒绝确认并隔离。物理验收探针仅对确认从未编码的临时拒绝发起重试。新增回归在旧候选重现落盘后拒绝，在修复版通过，局部验证共 40 项通过、1 项旧外部数据用例跳过。

包含独立归档锁及单副本回执修复的新候选 JAR SHA-256 为 `f845ef2de23f9213d67912f71a32739866f127108ace48d78573a303efee51a5`。08:00 已在原 Mac 启动正式门禁，现役仍使用 `1a36ecf`。Order、Trade 各 256 个严格双副本，10 个 Robot 继续运行。新候选的正式证据目录为 `retired-wal-local-census-formal-20261122-0800/`。

08:01，只读盘点现役四个投票进程的周期镜像目录，共 9,347 个镜像文件，分配约 1.58 GiB。37 个当前镜像指针全部找得到对应文件，合计约 110.6 MiB。旧镜像中 Trade A 约占 1.23 GiB。是否能回收其余文件仍取决于历史恢复、主备追平和投影引用。证据为 `archive-snapshot-pin-inventory-20261122.json`。

08:05，用新候选的完全相同 JAR 单独复跑原失败场景，通过原生产路径复现物理主节点退出和单副本在原进程恢复已签名的提交头。恢复水位为 3，缺席的备节点没有参与确认。证据为 `recheck-published-local-census.Q5BrNf/result.log`。正式门禁已通过独立分区隔离和保留主节点混合隔离两个场景。

08:17，例行归档 MySQL 刚关闭的 `binlog.000007`。原段 1,073,763,056 字节，压缩件 137,041,078 字节。解压 SHA-256 核验通过后才调用 MySQL 清理关闭段，活跃段为 `binlog.000008`。证据为 `archive-qualified-demo-binlogs-000007.log`。

08:18，沿用 P129 原双签水位，把压缩前段与尾段作为一个顺序流读取。整个恢复输入目录没有合并后的原始 WAL，Common 原帧解析和连续 SHA-256 仍校验了全部 4,100 条记录。该实验验证了直接读归档段的可行性。证据为 `archive-detached-signed-readback/regression/direct-segment-stream.xBQ6KK/result.log`。

08:29，正式门禁中的 322 项安全检查、4 项单副本恢复、4 项冷启动用例、独立原生故障 17 项均通过。3 项外部历史样本仍跳过。带回主中断的 256 分区场景已通过，52 个先发生单副本写入的分区冷启动后也通过了完整归位与副本数据比对。最终双向断电、第三次断电及重复回主仍在运行。
