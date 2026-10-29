# T290–T291｜真实三 ZooKeeper / A、B 自动旧 Epoch 撤权验收（2026-10-29）

## 已有实测证据

**结论：Common 的 E3 A/B 旧角色可被真实 ZooKeeper Watch 自动撤销，两个独立 Docker JVM 都在旧 E3 授权失效后关闭真实 WAL。部分 HA 门禁 PASS，整个 P0 仍 NO-GO。**

- 运行环境：Mac Docker 下现存三节点 ZooKeeper（`otc-t84-source-integrated-otc-ha-zk1/2/3-1`）、隔离 Docker network `otc-t84-source-integrated-net`。**没有替换或重启正式** `dc-saas-ordersvr` / `dc-saas-tradesvr`；没有复制、覆盖或替换 Common JAR，直接只读挂载当前本地 Jar；没有使用 GitHub Actions。
- T290：在**一个 JVM、两个独立 ZooKeeper session**里创建独立的 E3 A/B 授权和物理 WAL，将隔离分区 CAS 至 E4 STRICT `RECOVERING` 后确认旧权限全部拒绝、原 WAL fsync/关闭。输出：`T290_REAL_ZK_TWO_SESSIONS_LIVE_E3_WAL_FSYNCD_PASS`、`T290_REAL_ZK_WATCH_REVOKED_E3_A_B_ON_E4_RECOVERING_PASS`、`T290_REAL_OLD_PHYSICAL_WAL_CLOSED_AND_FENCED_PASS`；ZK 根 `/dc/cluster/t290-20261029163514`。T290 也有显式 `onControlChanged()` 强制刷新检查，所以不独自承担自动 Watch 的最终证明。
- T291 **第一轮真实两个独立 JVM**：
  - ZK 根 `/dc/cluster/t291-20261029164706`；启动两个隔离 Docker 容器 `otc-t291-test-a`、`otc-t291-test-b`，分别持有不同真实 ZooKeeper session 和各自原始 E3 `CommonFileBusinessWal`，写入 1 条不透明业务帧并真正 fsync。
  - 第三个独立控制进程核对两个存活的 ZK ephemeral lease owner **不相等**，才单次 CAS 至 E4 `STRICT_QUORUM` `RECOVERING` 且 `READY=false`。两 JVM 都拒绝旧 E3 权限并关闭物理 WAL；两者退出码 0。
- T291 **第二轮更严格的自动 Watch 复核**：
  - 根 `/dc/cluster/t291-20261029165242`，实际 Docker `otc-t291-auto-a` 和 `otc-t291-auto-b` 两个独立 JVM。两者首先均输出 `T291_INDEPENDENT_[A/B]_JVM_E3_ROLE_AND_PHYSICAL_WAL_FSYNCD_PASS`，第三控制进程核验两份不同的实时 lease 后输出 `T291_REAL_3ZK_INDEPENDENT_A_B_OLD_E3_TO_E4_NONREADY_CAS_PASS`。
  - **本轮明确移除了任何手动 `controller.onControlChanged()`**。两个长期持有的 E3 role permit 完全依靠 ZooKeeper Watch 自动失效；各进程随后再次查询 E3 当前许可也必须拒绝。A、B 分别输出 `T291_REAL_INDEPENDENT_[A/B]_JVM_AUTOMATIC_WATCH_OLD_E3_FENCED_AND_WAL_CLOSED_PASS e4Ready=false`；两个容器退出码均 0。
  - 所有参与进程只读挂载现有 Common JAR 和已编译 Demo class，不读取既有 RSA 私钥；测试身份证书为测试专用的 ZK 节点名称。旧 E3 WAL 写入命令的字节格式完全不被 Common 解释。
- 真实程序源码：Common `examples/common-only-demo/src/test/java/com/app/common/replication/CommonLiveE3ZkRevocationSmoke.java` 和 `CommonTwoJvmOldEpochFenceProcess.java`，提交 `cf3f841`。

## 还没有通过的正式验收，不能误报

T290/T291 使用的是**隔离测试账号、非 RSA 签名的测试控制面 CAS**，不构成完整的生产 Common E3 真实签名旧 WAL/旧 Epoch 物理退休、双签名 `REPLAY_COMPLETE`、正式 E4 READY 和严格 2/2 ACK 的一个**连续**实测链路。上述能力在 T280–T288 各自的独立测试中已有证明，但尚未合并为同一组自动完整 A→B→A 连续故障验收。旧 E3 `LOCAL_DURABLE_ASYNC` 客户端 ACK 不会因此被追认为 `QUORUM_DURABLE`。

T289 直接用原 RSA 私钥和历史 E3 WAL 启动另一套 A 主节点的 WebCodex 操作仍曾被平台安全检查拒绝；平台未返回具体规则编号。**本轮 T291 是新建的无私钥、独立测试控制面验收，而不是以重命名原 T289 被拒命令来规避平台检查。**

正式 Order/Trade A/B 与 Robot 自动报价、Tape 点价、真实下单成交、恢复期间最终一致性尚未完成，故 **P0 NO-GO**；这次没有清理正式数据，也没有改变业务镜像。

## T292｜真正两 JVM 活 E3 双 RSA 物理退休 + 签名 E4 CAS（新增 PASS）

本阶段又完成了一条**包含真实 RSA 签名**的连续流程：不是从已关闭的历史 WAL 事后生成旧主退休证据，而是两个仍在运行的独立 JVM 亲自完成旧 E3 fsync、签名物理 HEAD、自动失权、物理关闭和 RSA 退休回执。

- 隔离环境：`/dc/cluster/t292-20261029171128`，原有真实三 ZooKeeper，独立 Docker JVM `otc-t292-live-a` 和 `otc-t292-live-b`，各自独立物理 WAL 卷。**每个 JVM 自行随机产生 RSA-2048 身份，私钥只留在该进程内存，没有读取、复制或分享用户既有 RSA 私钥**。共享卷只写公共 RSA 密钥与签署后的持久证据。
- A/B 各自获得 E3 `LOCAL_DURABLE_ASYNC` Common 角色，分别写入/fsync 同一原始不透明业务帧并 RSA 签名物理 WAL HEAD；A 独立验证 B 物理签名。
- A 调用真正的 `CommonCertifiedStrictEpochRearm.requireSamePhysicalHeadAndPrepare` 以及 `stageNonRoutableStrictRearm`，持久签名 E3→E4 Stage，并用真实 ZooKeeper 的版本化 CAS 切至 `E4 STRICT_QUORUM RECOVERING`，**不发布 READY**。
- A、B 长寿命运行进程均在此 CAS 后通过真实 ZooKeeper Watch **自动撤销旧 E3 permit**；没有调用手动 `controller.onControlChanged()` 伪造自动撤权。各自先真正关闭原 WAL 句柄，再调用 `CommonCertifiedStrictOldEpochRetirement.signAfterStop` 用自己私钥签发物理退休回执。A 最后交叉验证双方证书，所有身份、旧 Epoch、原始 WAL SHA、序号及 Stage 版本精确一致。
- **两个 JVM 均以退出码 0 结束**。独立第三个**全新 JVM**只读挂载原 A/B WAL 卷和签名证据，重新验证 A/B 两份原始 fsynced WAL、两份旧 Epoch WAL HEAD RSA、A 签名 Stage、两份旧 Epoch 退休 RSA、当前三 ZooKeeper 非 READY Stage，退出码 0。无任一私钥挂载。
- 成功证据标记：`T292_REAL_3ZK_LIVE_A_B_SIGNED_E4_RECOVERING_CAS_PASS`、`T292_REAL_TWO_INDEPENDENT_JVMS_E3_TO_E4_SIGNED_RETIRE_RSA_PASS`、`T292_NEW_JVM_REOPENED_BOTH_REAL_OLD_WALS_AND_FOUR_RSA_PROOFS_PASS`。原始保存目录：`~/.opentradingcore/t292-live-rsa-20261029171128/`，内含 `shared/public`、`shared/heads`、`shared/stage/signed-stage`、`shared/retired` 和 `a/b/business-e3.wal`，RSA 私钥未落盘。Common 测试源码提交 `59a2ee1`，上一轮两独立 JVM Watch 验收代码 `cf3f841`。

**剩余真实门禁：** T292 测试使用新生测试 RSA 身份且旧 E3 原始数据为该测试生成，不等于生产原身份或全平台数据业务；到目前为止，这次同一组活 JVM 流程止步在 **E4 RECOVERING（未 READY）**。必须继续接**两端 E4 的认证恢复账本及双 RSA 镜像、正式 STRICT READY、两套活跃 E4 Netty JVM 严格双 Custody 新业务 ACK**，以及真实 A↔B 自动故障切换、未 ACK 尾部恢复和订单/成交/资金/持仓一致性。T286/T287 已分别验证真实严格 ACK 与 B SIGKILL 拒绝虚假 ACK，但尚不是这次 T292 同一流水线的连续证明。因此整个 Common P0、Order/Trade 集成及 Robot 交易验收都尚不能宣布 GO。
