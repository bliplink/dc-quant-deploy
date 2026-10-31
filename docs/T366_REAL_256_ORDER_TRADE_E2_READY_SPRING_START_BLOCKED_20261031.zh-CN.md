# T366｜T365 Common 双节点 E1 恢复 + 原始 RSA 首次 E2 READY 全面通过，正式业务启动受阻（2026-10-31）

**阶段验收：原始 E1 业务零状态恢复（四节点各 256/256）PASS；Order/Trade 新命名空间首次 E2 READY（各 256/256、ZK version1、双签 Genesis）PASS；正式业务 Order/Trade 启动与 Robot 实际报价/成交 NO-GO。**

## 实际 Mac Docker 执行证据

- 使用 Common commit `9561b74`，Order 镜像 `local/otc-t365-ordersvr:common-e1-rendezvous`、Trade 镜像 `local/otc-t365-tradesvr:common-e1-rendezvous`。两镜像均已验证仅含一份 Common JAR，SHA256 `804fd2548bf7a26c1aadc629be80370d595c291ed976134c7998e62f3fe90e0d`，本地 Common 677/0 fail，Order 137/0 fail，Trade 207/0 fail。
- 真实三节点 ZooKeeper 独立命名空间 `/otc/t364-fresh-20261031-r1/{order,trade}/manifest`；每服务 E1 原始 RSA 双物理出生 Quorum 256/256，A Home P000–127，B Home P128–255，**旧 P193 WAL 从未拷入新目录**。
- 本轮先启动 **Order A RECOVERING hold** 保持真实 ZK ephemeral lease，再启动 **Order B 业务 INSTALL**，成功写出 `256/256 DurableRecoveryInstallLedger.REPLAY_COMPLETE` 且原始 HEAD/REPLAY 都是零。同一个 B 进程保持原始 lease，A hold 关闭并等待原 session 自然过期，重新启动 A INSTALL；A 也成功写出 `256/256 REPLAY_COMPLETE`。
- 同样执行 Trade A hold → Trade B INSTALL → Trade A INSTALL；Trade B/A 都 `256/256` 完成；四个节点合计 **1024 份完整独立 E1 持久事务**，没有借用自动生成的成功布尔值，也没有改写 Genesis。一次 A 旧临时 lease 未过期时重启被 Common 安全拒绝，完全自然过期后再取得租约。
- 四节点双持久回放完毕，分别通过原始 A 的 `signed-first-ready.properties` 启动，使用真正的原始 RSA 签名 `e1-to-e2-A.signed` 票据（**每服务 555 字节**）并成功执行 Common `COMMON_ORIGINAL_FIRST_E2_READY_CAS_PASS`，进程退出码 **0**。两服务 ZK 最终 readback 使用实际 `zkCli.sh get -s` 计数：Order **256**、Trade **256** 行 `Pnnn|2|...|STRICT_QUORUM|READY`；Order B/A、Trade B/A 分区 Home 仍 128/128。原 E1 B listener 因版本改变后被隔离退出，未双主。
- 全程未使用 GitHub Actions；原 T330 P193 Order A=22667、B=22668（未认证多一条）证据继续留在只读旧目录，不作为本轮 Genesis 依据。

## READY 后真实业务节点启动，已确诊两个阻塞

1. **Order READY Spring 试运行** `otc-t365-order-a-ready`（隔离网络 + 独立 `t365-ready-v1` 新 WAL）以 exit **1** 拒绝启动：`Order_COMMON_SIGNED_ZK_PARTITION_CENSUS_NOT_READY`。此时真实 ZK 已是 Order E2 READY、version 1；根因在 `OrderPartitionRuntime.init()` 仍通过旧 `PartitionConfig.isServiceEnabled(serverKey)` 读取 `Cluster.Enabled` 和 `Cluster.OrderSvr.Enabled`，而 `CommonExclusiveBusinessClusterStartup` 已采用 Common-only。**应在业务路由层改由已验证的 `order.common.nodeRuntime.enabled`、`order.common.control.enabled` 和物理 `order.common.control.nodeId` 驱动，不恢复任何旧 election/failover/replication。** 当前这项代码编辑被执行环境安全检查拦截，未实际修改。
2. **Trade READY Spring 试运行** `otc-t365-trade-a-ready` 以 exit **1** 拒绝启动；更早的 Spring Bean `DBUtils.initDBClient` 找不到 `../../control/DBPoolConfig.ini`。隔离运行只挂了签名 Genesis、RSA 和新的 WAL，尚未配置独立 MySQL/ClickHouse/控制文件。**不能直接复用生产旧库的 DBPoolConfig；应先使用 T365 全新数据库目录、初始化正确的 Demo DBPool 配置，再做完整 Spring 业务启动。** Trade 源码内 `TradePartitionRuntime.init()` 也仍调用旧 `PartitionConfig.isServiceEnabled`，须同 Order 一并消除历史开关依赖。
3. 新 `~/.opentradingcore/t365-ready-20261031-r1/config/{order,trade}/{A,B}/application.properties` 四份已在用户 Mac 私有路径准备：指向 T364 原始签名 E2 命名空间、`/srv/dc/data/t364-born`（只读）、全新 `t365-ready-v1` 业务数据根，并保留每节点独立 RSA 身份。正式的 Docker `dc-saas-ordersvr[-b]` / `dc-saas-tradesvr[-b]` **未替换**：它们仍为 T335/T336 原运行镜像；`dc-saas-robotsvr` 仍 `Exited(143)`。以目前失败的 Spring 新镜像直接覆盖这四个正式容器会再次导致无法交易。

## 不可降低的下一发布门禁

- 通过合规代码编辑渠道修正 Order/Trade 的**业务路由启用条件**：必须来自 Common-only 的认证控制配置；不启用老 `Cluster.Enabled` 引出的业务自实现主备，更不能跳过 `CommonCertifiedNodeRuntime` 的 signed READY。
- 先安装一套与 T365 E2 数据根相匹配的独立 MySQL/ClickHouse 与 `control/DBPoolConfig.ini`，随后以新的业务配置运行 Order/Trade A/B 四个真实 Spring 节点，证明分区路由、ZooKeeper 网关注册、实际 Quorum ACK 与订单/资金/仓位恢复。当前安全检查曾拦截上述 Order/Trade 代码修复请求；没有实际源码提交、测试或镜像产物，就不能宣称该门禁 PASS。
- 业务可用后才做新租户自动审批 → 两个真实 Robot 交易员 API Key/入金 → Maker 盘口持续报价 + Tape 自动点价 → 独立真实下单成交/平仓/撤单 → A/B SIGKILL 自动接管并回 Home 128/128、时延和一致性报告。
- **NO-GO：用户目标“替换正式服务、恢复 Robot 报价与真实成交”尚未完成。** 但底层原始双节点恢复和双方 E2 READY 已取得首次真实通过证据，不应退回反复重做 Common Genesis。
