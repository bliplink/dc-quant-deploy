# T318｜全新 Order/Trade 原始 Common E1 创世至 E2 READY 实测

日期：2026-10-29｜Mac 本地离线 Maven + Docker + 真实三节点 ZooKeeper。**结论：Common 首次创世、双签名原始 Genesis、业务零状态 E1 安装、首次 E2 READY 已 PASS；正式交易与 HA 自动互切仍 NO-GO。**

## 坚持的架构边界

- HA 仅在 `com.app.common`：原始 256 分区分配、同一 ZooKeeper 会话的 ephemeral Lease、两独立 RSA 身份、物理 fsync Genesis、出生时零 ACK 签名、持久恢复、首次 E2 READY 的 RSA 签名/CAS 都只使用**已有 Common API**。Order/Trade 只提供原代码中的 `canonicalEmptySnapshot(partition)` 不透明业务 `byte[]`，并实现原有业务 `snapshot/apply/restore`；不加业务命令类型限制、不新增 Order/Trade 选主/复制/WAL。
- 从项目旧公共实现恢复 `CommonOriginalE1LeaseBoundBirth.java` 和 `CommonOriginalE1FleetBirthProvisioner.java`，只在 Common `CommonRecoveryOnlyProcess` 中重新连接 `provisionOriginalBirth=true` 的原有**首次出生专用阶段**。与 `inspectFencedBusiness`、`installFencedFreshGenesis`、`stageOriginalFleet` 明确互斥；签署原始根目录后即退出，不允许自动 READY、不重试已有物理出生根目录。Order/Trade 恢复的是原已有零状态业务序列化代码而非集群机制。
- 前次所有真实 T181 历史签名材料仅用于 T317 只读审计；本次**没有复制、重签或复用旧命名空间的出生签名与 READY 票据**。

## 代码、镜像及单测结果

| 模块 | 本地 commit | 验收 |
|---|---|---|
| Common | `f384f91` | 149 suites，646 tests，**641 PASS / 5 skipped / 0 failure / 0 error**，沿用已有 Demo RSA 源测试 |
| OrderSvr | `b96bd26` | `mvn clean package` **126/126 PASS** |
| TradeSvr | `f9a0e9f` | `mvn clean package` **203/203 PASS** |

Common 在本机 `mvn -DskipTests install`，Order/Trade 通过对应新 Common/JAR 完整构建并装配相同运行时依赖。新隔离镜像 `local/otc-t318-ordersvr:virgin-common`、`local/otc-t318-tradesvr:virgin-common`；两者仍为 `dc.release.gate=NO-GO`、`authorized=false`。没有 GitHub Actions 或原容器覆盖。

## 全新真实隔离环境与物理凭据

- ZK 使用现有真实三服务器 `otc-t84-source-integrated-otc-ha-zk{1,2,3}-1`，全新根 `/otc/t318-virgin-20261029-r1/`。临时原始安装脚本只创建 E1 **generation=1、ZK version=0、全部 256 分区 `RECOVERING`/非路由**的初始清单，各服务按奇偶分配 A/B 互备，未冒充签名或 READY。
- 物理文件全在 `~/.opentradingcore/t318-virgin-20261029/`；Order A/B、Trade A/B 每个 JVM 在真实 Common ZK 会话及自己独立的 RSA `node.pk8` 下调用旧 Common 原始出生签名器，分别打印 `COMMON_FIRST_BOOT_ONLY_LOCAL_RSA_E1_VOTER_FLEET_FSYNC_PASS`，各 **256/256**，退出码 0；合计 **1,024 份新出生零 ACK 凭据、1,024 份原始 RSA 回执**。两个原始节点采用 Mac Docker 不同逻辑数据槽/钥匙/容器，**不是跨两台真实物理主机的生产容灾测试**。
- 临时的只读预审使用 `CommonCertifiedGenesisQuorum.verify`、`CommonOriginalE1ZeroAckBirthEvidence.requireOriginalPhysicalZeroAckWal` 验证与新的 exact ZK namespace 一致。全部 512 对快照的 A/B 实际字节相同、原始 RSA 签名有效、原物理 WAL 根目录只有对应 birth 凭据。随后正式使用 `CommonCertifiedGenesisQuorum.sealAndVerify` **持久写入 Order 256、Trade 256 个全新双 RSA `genesis-e1.quorum`**，输出 `T318_REAL_DUAL_RSA_GENESIS_QUORUM_FSYNC_PASS totalPartitions=512 realReceiptCount=1024 noREADY=true`。

## E1 双节点实际业务恢复安装

- 配置从上述全新有效真实文件生成所需的每分区 `freshE1.P000..P255.*` 路径，指向同一已签名 Genesis、各自原物理快照、A/B 出生凭据、各自新持久化事务目录；显式 **`inspectFencedBusiness=true`、`installFencedFreshGenesis=true`、`stageOriginalFleet=false`、`provisionOriginalBirth=false`**。使用原 `OrderFencedRecoveringBusinessState`/`TradeFencedRecoveringBusinessState`，真实域状态机验证 256 原始快照，未模拟业务 ACK。
- Order A/B、Trade A/B 四个相互独立进程都在同一 Common 控制平面调用原实现 `CommonCertifiedFreshGenesisInstall`。额外使用正式 `DurableRecoveryInstallLedger.read(partition)` **逐项只读检查**，四个节点各 **256/256 `REPLAY_COMPLETE`**，`snapshotEpoch=1`、`snapshotSeq=0`、`replaySeq=0`、`committedHeadSeq=0`；总计 1,024 个完整恢复事务，期间 ZK 保持 E1 `RECOVERING`。
- Order B 更换旧持租约实例时，ZooKeeper 拒绝来自不同 session 的新节点（`recovering node lease owned by another ZK session`）；**没有手工删除/抢占该 Lease**，待旧 session 自动过期后重新启动，同样完成 256/256。证实旧主隔离边界在本机生效。

## Common 首次 E1→E2 READY 真正提交

- 在 A/B 两端均完成上述实际 E1 恢复并持有 A/B 原始租约后，仅由 **A 的 Common `CommonOriginalE1FirstReadyActivation::activate`**重新检查所有 256 分区真实双签名 Genesis、零 ACK 原始物理根、A/B 实时 ZK 租约；签署并落盘 `first-ready/e1-to-e2-A.signed`，再通过 CAS 发布 E2 READY。Trade、Order 均有实际日志 `COMMON_ORIGINAL_FIRST_E2_READY_CAS_PASS service=... partitions=256 signedGenesis=true businessServing=false`，A 启动进程退出码 0。
- 独立只读复核新 ZK manifest：**Order `generation=2`、version=1、256/256 epoch2 STRICT READY；Trade 同样**。使用原 A RSA 公钥验证两份首次 READY 票据，并验证签名内容绑定 T318 新 exact namespace 与当前 E2 manifest SHA256，两者均 PASS。
- 已退出的旧 B `RECOVERING` 监听者在观察到 E2 清单变更后以 `Common RECOVERING census changed; restart/fence control listener` 安全拒绝退出码 1；这是旧实例撤权，不是新业务 READY 或用户交易失败。

## 下一关仍是业务启动，不可冒充已通过

1. 新 ZK Common E2 原始 **控制面 READY != Order/Trade Spring/Gateway 可用**。上述日志明确 `businessServing=false`，尚未在新环境验证对外服务能完成 Common E2 认证、MySQL 8.0.33 初始化、真实租户注册、自动审批、Robot 报价/Tape 点价和真实成交。
2. 下一步只需复用相同 Common，不让 Order/Trade 私下新增集群代码；在隔离的真实业务依赖/数据库中让 Order A/B/C 和 Trade A/B 启动业务服务，并对订单、成交、余额、持仓做物理切换回归；不与正在运行的正式 Demo 旧容器混用数据根、ZK namespace 或 Gateway 节点身份。
3. Common Demo 原有 A↔B 压测和双向验收不等于这套新业务实例已经自动互切；最终 `GO` 仍要求**交易进行中自动 A→B→A 无丢单/重复成交/双主、资金持仓状态一致**，且 Robot 持续流动性和 Tape 真实点价通过。

所有 T318 临时容器日志保存在 `~/.opentradingcore/t318-virgin-20261029/evidence/`。原始出生签名、双 RSA Genesis Quorum、四节点恢复账本、首次 READY 票据及真实新 ZK 授权保持留存，**临时测试容器已清理**；`dc-saas-*` 正式容器、它们原有 WAL、配置与数据未变。未推送远端，因为本地/远端 `saas-crypto` 已存在分叉。当前业务整体 **NO-GO**。
