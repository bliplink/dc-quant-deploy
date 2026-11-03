# T456｜Common Demo 真实双向自动故障切换与持久化复制验收（2026-11-03）

## 结论与严格边界

**Common Demo 的单分区完整 A→B→A 自动切换、恢复后继续写入和最终 B 重新加入的 TCP WAL fsync：PASS。** 实验是在 Mac 的隔离 A/B/C JVM、真实三节点 ZooKeeper 和现有 RSA 材料上进行，绝非仅跑模拟器或手动脚本替代自动接管。**正式 Order/Trade 256 分区 HA：依旧 NO-GO**；降级期间 ACK 明确为 `LOCAL_DURABLE_ASYNC`，`quorum=false, rpoRisk=true`，不得冒充严格 2/2 物理 ACK，也不可推断 B 回归后已自动升级为未来严格 2/2 ACK。

共同的源码版本来自 `bliplink/com.app.common` 的 `saas-crypto-latest`。本轮修复和测试脚本正式提交：`baaa73c5e91ef6e8b3876f859217313dddfceb5a`（`[skip ci]`，没有使用 GitHub Actions）。

## 真实执行环境

- 测试入口：`examples/common-only-demo/scripts/verify-real-auto-sigkill-genesis-replay.sh`，在隔离运行时开启 `OTC_T125_ENABLE_DEGRADED=1`、`OTC_T126_ENABLE_REJOIN=1`、`OTC_T127_ENABLE_REVERSE=1`、`OTC_T128_REQUIRE_E3_INSTALL=1`、`OTC_T129_REQUIRE_E3_WRITE=1`、`OTC_T130_AUTO_C=1`、`OTC_T270_ENABLE_E3_B_REJOIN=1`、`OTC_T272_ENABLE_TCP_AFTER_REJOIN=1`、`OTC_T275_COMMON_LIFECYCLE=1`、`OTC_T276_COMMON_E3_LIFECYCLE=1`。
- 固定 Common candidate：`3.0.22-t143-durable-signed-crossjvm-handoff-20261026-SNAPSHOT`，执行期间拷入独立只读固定 JAR（没有动态替换）。
- 真实 ZooKeeper：T84 三节点集群，隔离 path `/dc/cluster/t117-<run>`；隔离测试容器名带 `otc-t124-* / otc-t126-* / otc-t130-* / otc-t270-*` 唯一运行号。
- 现有 RSA：原 A/B/C 独立私钥及公共证书，测试不在本轮生成新的伪造证书或签名。
- 最终成功证据目录：`~/.opentradingcore/t124-live-kill-runs/20261103114912`，包括 `genesis.log`、`bootstrap.log`、固定 `common-tested-pin.jar`，以及留存的三个容器完整输出 `t456-survivor-b.log`、`t456-returned-a.log`、`t456-witness-c.log`。
- 测试 A/B/C 与现网 Order A/B、Trade A/B 是不同容器。现网 Order/Trade 没有被 SIGKILL/重启；测试清理仅删除隔离容器，保留证据目录。

## 验收进程原始 PASS 证据

| 阶段 | 实际证据 |
|---|---|
| 独立签名 Genesis | `T124_REAL_INDEPENDENT_RSA_DUAL_GENESIS_REOPENED_PASS` |
| A 初次提交 | `T124_REAL_E1_BUSINESS_UNDER_A_B_RSA_QUORUM_ACK=PASS`，业务值 40 |
| B 在 A 停机前已启动 Common 自动 Watch | `T124_COMMON_WATCH_ARMED_BEFORE_PRIMARY_FAILURE=PASS` |
| 故障注入 1 | `T124_REAL_SIGKILL_OLD_A_FULL_COMMON_DEMO_JVM=PASS` |
| B 自动接管 Stage | `T124_B_AUTOMATIC_OLD_LEASE_TO_E2_RECOVERING_PASS` |
| B 签名恢复 | `T124_COMMON_AUTOMATIC_SIGKILL_TO_DURABLE_REPLAY_COMPLETE_PASS epoch=2 seq=2 total=40 customerReady=false` |
| 独立 C 自动证明 | `T130_CONTINUOUS_C_INDEPENDENT_E2_WITNESS_ISSUED_AUTONOMOUSLY=PASS` |
| Common 控制线程通过 E2 READY 且完成物理客户 WAL | `T275_COMMON_WATCH_THREAD_VERIFIED_E2_RSA_READY=PASS`；`T125_B_CONTINUES_AFTER_A_SIGKILL_LOCAL_DURABLE_ACK_PASS epoch=2 seq=2 total=60 quorum=false rpoRisk=true` |
| A 恢复为 B 的 Replica | `T126_REAL_A_RETURNED_REJOINED_B_E2_RSA_PREFIX_PASS seq=2 total=60 originalBQuorum=false independentAReplicaFsync=true` |
| 故障注入 2 | `T127_REAL_SIGKILL_E2_PRIMARY_B=PASS` |
| A 自动反向接管 | `T127_B_REAL_SIGKILL_A_AUTO_E3_RECOVERING_PASS`；`T128_REAL_B_KILLED_A_COMMON_E3_FORMAL_REPLAY_COMPLETE_PASS committedGlobalSeq=4 restoredTotal=60 customerReady=false` |
| 独立 C 自动 E3 证明 | `T130_CONTINUOUS_C_INDEPENDENT_E3_WITNESS_ISSUED_AUTONOMOUSLY=PASS` |
| A E3 READY/客户业务继续 | `T276_COMMON_WATCH_THREAD_VERIFIED_E3_RSA_READY=PASS`；`T129_REAL_B_SIGKILL_A_RESUMES_E3_BUSINESS_LOCAL_ACK_PASS epoch=3 seq=2 total=74 requests=6 quorum=false rpoRisk=true` |
| B 作为 E3 Replica 再加入 | `T277_COMMON_GENERIC_E3_REPLICA_RSA_INSTALL_PASS head=2 applied=2`；`T270_REAL_B_E3_ONLINE_RSA_REPLICA_REJOIN_PASS total=74 requests=6 e3Seq=2 historicalLocalRpo=true` |
| 再加入后的真实 TCP WAL | `T272_A_E3_COMMON_TCP_SIGNED_B_FSYNC_PASS seq=3 total=85 localAckNotRetroactiveQuorum=true`；`T272_B_E3_COMMON_TCP_NEW_WAL_FSYNCED_PASS seq=3 total=85 requests=7` |
| 测试最终退出 | **exit 0**，`T272_REAL_A_E3_NEW_BUSINESS_TO_REJOINED_B_TCP_RSA_FSYNC=PASS` |

以上表示新的业务提交确实通过 Common TCP 从 A 传送到重新加入的 B 并 fsync；**不代表这笔客户端 ACK 已获得严格 Quorum 证明**。

## 本轮发现、对照和修复

1. T275 完整测试曾在 B E2 READY 后退出 12。真实回调堆栈明确显示 `IOException: Common lifecycle recovery did not run on owned control thread`；Demo 期待 `common-certified-failover-control-*`，实际 Common 共享 Watch 线程为 `common-failover-cold-*`。这不是 ZooKeeper 丢数据，也不是 RSA 失败。
2. T276 同样沿用错误的线程名前缀，使 A E3 READY 后未继续执行业务写入，扩展测试退出 29。两个 Demo 测试接线均统一检查真实 Common 控制线程名称。
3. 单个 lambda `CertifiedRecoveryCompletion` 会缺少 READY 之后独立检查物理业务安装的回调。两个 Demo 测试接线改为具名 `CertifiedRecoveryCompletion`，实现 `recoverAndPublish` 和 `requireInstalledAfterReady`；后者要求当前 signed READY 和对应 E2/E3 `local-async-business.wal` 已持久化且达到最小非空长度。不能仅凭 ZK READY 令 Watch 报成功。
4. 实际脚本中 `set -o pipefail` 与 `docker logs | grep -q` 配合存在假阴性：一个失败运行中的 B 确实记录了 `T275_COMMON_WATCH_THREAD_VERIFIED_E2_RSA_READY=PASS`，但检索返回失败 57。现已将 22 个流式 `grep -q` 改为消费完整日志的普通 `grep ... >/dev/null`，保持每条断言原样；退出前保留 B/C/返回 A 的完整原始日志，防止循环排障。
5. T125 **旧**非 T275 控制链在相同 RSA、Common JAR 和 ZK 环境下通过真实 E2 本地写入作为对照。T275 修复后的测试同样退出 0，E2 值由 40→60。T276 修复后的完整链最终退出 0，E3 值 60→74，B 追平 74 后 TCP 新写使 A/B 同为 85。

## 回归与代码提交

- 本机 `mvn -o -q test` 运行 Common：161 个 Surefire 测试报告，**706 tests / 0 failures / 0 errors / 72 skipped**，进程退出 0；日志含个别非致命缺省 `./control/ATSConfig.ini` 输出，不是测试失败。
- Demo `mvn -o -q test`：4 tests / 0 failures / 0 errors / 3 skipped。
- Common 分支 `saas-crypto-latest` 新提交 `baaa73c5e91ef6e8b3876f859217313dddfceb5a`，文件：
  - `examples/common-only-demo/src/test/java/com/opentradingcore/demo/DemoCommonLiveZkProcess.java`
  - `examples/common-only-demo/src/test/java/com/opentradingcore/demo/DemoCommonRejoinProcess.java`
  - `examples/common-only-demo/scripts/verify-real-auto-sigkill-genesis-replay.sh`
- GitHub branch 已使用原始 `d2f545649a71e0fb5185afc1a0ae9e541c3033c2` HEAD 的精确 expected SHA 完成非强制快进更新，远程读取回证新 HEAD `baaa73c`。3 个修改 blob SHA 均与本地 `git hash-object` 精确一致；没有触发 GitHub Actions。

## 正式 Demo Order/Trade 的剩余必过门禁

1. 当前 Order/Trade Spring 接线仍调用 Common `openAndStartWithZkFencingAndReplayAndSources`，并没有传入完整 256 分区的 `AutomaticReplicaRecoveryPlan`；需要由业务侧提供真实 byte[] Snapshot/Apply，以及 Common 物理源、认证追平、签名恢复和 READY 安装依赖，改为既有 `openAndStartWithCertifiedAutomaticRecovery`。不要另写业务选主、删除 WAL 或把无授权的 Epoch 改为 READY。
2. T455 的 Order P060 原始故障：ZK 仍显示 `epoch=2 READY primary=OrderSvrA`，但 Primary WAL 的序号 188531 失败后触发同 Epoch Poison，B 的 WAL 与 A 的前缀一致、A 多 1254 字节未认证尾部；真实 Order B 无自动 Watch 线程。**此 P060 不可就地强行恢复旧 Epoch**。需要 Common 正式签名 Epoch3 接管和物理业务恢复后再恢复投影。
3. A/B 自动互切必须在真正的 Order/Trade 多分区中再做两次真实 SIGKILL，验证 **256 分区全量角色/副本变化、无双主、余额/持仓/委托/成交一致性、财务 Projection 水位、MD QuerySymbol + APS 价格源不混用 Order**。
4. 另需专项验证 B 恢复后新交易客户 ACK 是否切回严格 2/2；任何本地降级 ACK 都需显式标识其 RPO 风险。

**结论：Common Demo 自动 A→B→A 与新 WAL TCP 复制 PASS；正式 Order/Trade HA 仍 NO-GO。**

## T456 追加复测｜B 独立 fsync 日志与磁盘字节验收（2026-11-03）

前一次 11:49 的 T456 清理只存了生存 B、C 与回归 A 的日志，未单独保存回归 B (`BR`) 的 stdout。为避免 A 侧成功输出被误用为 B 独立证据，现已在标准测试脚本退出清理中增加 `t456-returned-b.log` 留证，源码增量提交 [`8938388`](https://github.com/bliplink/com.app.common/commit/893838815d57dd09460dd03303899e8af67583d4)。只增加日志采集，不修改 Common WAL、签名或复制协议。

- **重新运行证据目录**：`~/.opentradingcore/t124-live-kill-runs/20261103130830`；控制台：`~/.opentradingcore/t124-live-kill-runs/t456-20261103-recheck-130830.log`；进程 **exit 0**。同一隔离 A/B/C、原有 RSA 和 Common 候选 JAR；JAR SHA-256 `0e9205761029f2f616f65b42359606b0cdea79cc634bb8e10a147632c6b7f024`。
- **双向故障注入**：A E1 双签名状态 40；SIGKILL A 后 B E2 持续写入至 60；A E2 认证追平成为 Replica；SIGKILL B 后 A E3 经 C 见证与 Common Watch READY 持续写入至 74。
- **B E3 在线重加入**：B 独立日志 `t456-returned-b.log` 含 `T277_COMMON_GENERIC_E3_REPLICA_RSA_INSTALL_PASS head=2 applied=2`、`T278_COMMON_AUTOMATIC_E3_REJOIN_WATCH_SIGNED_RSA=PASS`、`T270_REAL_B_E3_ONLINE_RSA_REPLICA_REJOIN_PASS total=74 requests=6 e3Seq=2 historicalLocalRpo=true`。
- **新 WAL TCP 复制**：B 独立接收器打印 `T272_B_COMMON_TCP_REPLICA_LISTENING=PASS port=29301`、`T272_B_E3_COMMON_TCP_NEW_WAL_FSYNCED_PASS seq=3 total=85 requests=7`；A 打印 `T272_A_E3_COMMON_TCP_SIGNED_B_FSYNC_PASS seq=3 total=85 localAckNotRetroactiveQuorum=true`。控制台终止断言 `T272_REAL_A_E3_NEW_BUSINESS_TO_REJOINED_B_TCP_RSA_FSYNC=PASS`。
- **物理文件交叉验证**：A `a/CommonHaDemo/CommonHaDemoA/P090/epoch-3/local-async-business.wal` 和 B `b/CommonHaDemo/CommonHaDemoB/P090/epoch-3/rejoined-E3-business.wal` 均为 178 字节，`cmp` 完全一致，两份 SHA-256 均为 `0935a4241ce2a5d1ab17137d29d2d8e5cec8c000e30346c69dbc0094a62ce689`。B 文件写入时间晚于 A；隔离容器清理，证据卷保留。

**验收判定**：T456 单分区 Demo+Common A→B→A、B E3 追平、TCP WAL 及 fsync 复测 PASS。降级客户 ACK 仍是 `LOCAL_DURABLE_ASYNC / quorum=false / rpoRisk=true`；正式 Order/Trade 256 分区 HA 与业务一致性并未在 T456 中验证通过，继续 **NO-GO**，不得据此替换现网。
