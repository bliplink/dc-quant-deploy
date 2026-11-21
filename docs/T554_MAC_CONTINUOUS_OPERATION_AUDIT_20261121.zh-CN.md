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
