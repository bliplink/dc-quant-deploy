# Mac Demo 本地统一 Common 361e3e3 镜像滚动升级与 WAL 归档进度（2026-10-12）

## 结论与执行边界

本轮是用户批准的 Mac Demo 实机开发、编译及滚动替换；**完成了 Order A/B/C 和 Trade A 的真实镜像替换**，其余服务因真实 Trade HA 恢复耗时高和备用能力不足，未继续实施危险重启。本轮没有开启正常交易期间同 epoch WAL 自动封段，也没有删除任何真实历史 WAL。不得称“全量镜像替换或自动归档链路上线完成”。

Common 状态机接口、归档判定、持久化 `PREPARED/WRITER_SWITCHED/ARCHIVE_SEALED` 已存在并通过测试；但目前 Order/Trade **没有**在后台调用 `JournalArchiveSealCoordinator` 来物理轮转 Chronicle Queue，也没有完成源数据连续读取、Replica/Projection 历史保留门禁或封段半事务自动对账。恢复时 WAL 归档仍沿用旧逻辑，定时快照调度保持开启，真正的归档自动删除保持关闭。

## 不发布 Maven Central 的本地隔离构建

私有构建根目录：
`~/.opentradingcore/local-ha-wal-seal-20261012-v1`。
源码以提交 SHA 固定，不含原始 Order 工作区未提交改动：

| 类型 | 源码 SHA | 构建验证 |
| --- | --- | --- |
| Common | `361e3e3` | 228/228 |
| com.app.dc | `2fa8047` | 编译 / 本地 SNAPSHOT 引用 |
| Order A/B/C | `4c7df72` | 323 tests，0 failure，1 skipped |
| Trade v1 | `787a211` | 233/233 |
| MD 原候选 | `bcdec888` | 125/125 |
| Gateway（业务源码不改） | `6a84739` | 16/16 |

四种服务镜像：
`dc-saas/{ordersvr,tradesvr,mdsvr,gw}:cluster-dev-local-c361e3e3d-20261012034946`
全部使用相同公共依赖：
`io.github.bliplink:com.app.common:3.0.17-dev361e3e3d20261012034946-SNAPSHOT`
JAR SHA-256：
`0ed677b3c57bf65664c209c150570a598b1a9db7a82e63a694e1fe926bf003f3`。

额外针对 Trade 恢复大批量去重 JSON 写入性能修复，Trade commit：
`1a007a1ca699f367f1b6e416442bf38c1efcbec1`，
将 `save/saveStreamingDedupe` 流式输出以 256 KiB buffer 写入，再 flush、fsync、atomic replace；Trade **233/233** 全量测试通过。
候选镜像：
`dc-saas/tradesvr:cluster-dev-local-c361e3e3d-20261012034946-tradebuf-1a007a1`，
相同 Common JAR SHA，**已构建但未部署**，不能宣称线上速度改进已验收。

## 真正运行中的镜像与风险

| 线上实例 | 当前镜像 | 本轮是否替换 |
| --- | --- | --- |
| dc-saas-ordersvr A/B/C | `dc-saas/ordersvr:cluster-dev-local-c361e3e3d-20261012034946` | **已** |
| dc-saas-tradesvr A | `dc-saas/tradesvr:cluster-dev-local-c361e3e3d-20261012034946` | **已** |
| dc-saas-tradesvr B | `dc-saas/tradesvr:cluster-dev-local-tradeempty-a8fc334-20261011` | **未**；承载全部当前活跃 Trade 分区，不能直接重启 |
| dc-saas-mdsvr A/B | 旧镜像 `cluster-dev-local-c3e1d45c6-20261011075101` | **未** |
| dc-saas-mdsvr C | 原有独立最新 `cluster-dev-local-md-epoch-fence-dff97ba-20261012` | **未**；原候选 MD 源码 `bcdec888` 会回退 C 的独立修复，禁止用同一旧候选覆盖 |
| dc-saas-gateway | 旧镜像 `cluster-dev-local-c3e1d45c6-20261011075101` | **未**，仍是透明转发；不改 Gateway 业务逻辑 |

私有回滚清单：`~/.opentradingcore/local-ha-wal-seal-20261012-v1/artifacts/previous-container-images.json`；
预构建全候选 override：`wal-seal-images-override.yaml`。**注意原始 override 包含 MD-C 的旧业务 SHA，不能用它执行无条件整组 `compose up`；必须按实例确认源码。**

### 滚动现场证据

- Order-B 无 Primary，替换成功；首次检查 P023 Snapshot 不一致（Primary 已更新，而其他副本仍在异步安装），随后副本自动收敛。Order-C / A 替换各触发 Robot 若干租户 ERROR，恢复期间存在真实交易中断，随后自行恢复。
- 最终严格 `tests/verify-order-cluster-state-host.sh` 返回 **PASS**：
  Order **256/256 READY**、`snapshot_sets_equal=256`、无 learners，
  A 130 个 Primary，C 126 个 Primary，B 256 个 Replica；
  三个 Order 容器都是新镜像且没有 OOM/重启。
  验收脚本由于认证门禁跳过了匿名 HTTP 业务内容扫描，
  **不能把这个检查等同于资金/持仓/成交的权威一致性全通过**。
- Trade-A 换新镜像后，Trade-B 被触发对全部活跃 10 分区逐个恢复；
  Robot 多次 **10/10 ERROR，活动委托 0**，部分盘口也短暂归零。
  现场确认异常主要为
  `gateway rejected queryTradePosition: PARTITION_NOT_READY service=TradeSvrB`，
  Gateway 自身无需修改。
  Trade-B **12:03:21–12:12:57** 对 P023、P054、P158、P160、P177、
  P060、P077、P201、P246、P244 逐个生成
  `TRADE_RECOVERY_CHECKPOINT_SAVED` 并恢复 READY，
  约一分钟一个分区。jstack 看到主恢复线程卡在
  `TradeSnapshotStore.writeDedupe` / fastjson2 `flushTo` /
  `FileOutputStream.writeBytes`，属于大量去重记录的同步写出性能问题。
- **2026-10-12 12:13:21（Asia/Shanghai）起恢复 10/10 Robot RUNNING**，
  每租户 40 活动委托，买卖各 10 档；随后再次检查仍 PASS。
  这证明服务最终恢复，**不证明故障期间无拒单/零停顿**。
- 为让 Trade-B 在不重启情况下完成恢复，仅动态提升 Docker 容器
  CPU 上限由 0.5 核到 **2 核**、
  内存由 2.5 GiB 到 **3.5 GiB**，JVM Xmx 不变；
  同步持久化到 Mac 私有 `local-ha-runtime.env`，原配置备份
  `*.before-tradeb-recovery-headroom-20261012-1205` 等，权限 0600。
  现场无 OOM kill。此前 Trade-B 仅 2 CPUs 都难以缩短逐分区
  1 分钟的 JSON 写出，不能夸大提升 CPU 即解决瓶颈。

私有租户证据：
`~/.opentradingcore/local-ha-wal-seal-20261012-v1/artifacts/tenants-trade-recovery-final-6.json`（12:13:21 10/10 PASS）
及 `tenants-final-partial-rollout-20261012.json`（后续再次 10/10 PASS）。

## 严格禁止误操作和剩余工作

**没有完成自动 WAL 物理封段及自动删除闭环。**
目前只有 Common 的意向/阶段持久化和真实旧恢复 `rebase`，不能绕过同 epoch Writer/Reader 交接、旧 archive GAP、金融状态恢复、同一 Commit HEAD 副本确认来调用旧 `rebase`。

下一轮必须先修复 Trade 主节点故障导致另一节点**十分钟串行重建**的业务中断，验证备用 Trade-A 确有完整有效 Snapshot/复制水位可接管，然后在完全隔离故障注入中证明订单/成交/持仓/资金与 Projection 一致；**在此之前不得重启 Trade-B 或执行全量镜像同时替换**。然后验证 buffered v2 的真实耗时，做好当前 MD-C 独立代码基线、MD/Gateway 分步骤交接；Gateway 业务消息透传逻辑不改。

本轮所有新源码已提交到各自 GitHub 验证分支（Common `361e3e3`，Trade `1a007a1`）；服务尚未全部合并正式 `saas-crypto`、发布 GHCR 或 Maven Central。新的公共版本为本地不可公开部署的开发 SNAPSHOT。保留回滚镜像及 Mac 容器运行数据，旧 WAL 自动删除继续关闭。
