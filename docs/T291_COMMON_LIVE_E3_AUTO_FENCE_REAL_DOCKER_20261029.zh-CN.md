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
