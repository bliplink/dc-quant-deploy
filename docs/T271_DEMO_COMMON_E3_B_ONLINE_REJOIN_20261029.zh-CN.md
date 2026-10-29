# T271｜Demo+Common E3 旧 B 在线回归阶段实测（2026-10-29）

## 结论

**独立 JVM 的 B 在 A 仍持有 E3 PRIMARY 租约期间重新加入、验签并恢复 E3 Replica：真实 PASS。P0 仍 NO-GO。** 这超出了旧 T269 离线 WAL 拷贝，但还不是自动节点重启发现、TCP 持续复制或恢复严格双节点 Quorum 客户端 ACK，因此不能写成完整 HA GO。

## 本次真实隔离运行

- 源码工作区 `~/.opentradingcore/t177-common-saas-crypto-integration-20261027`，Common 本地提交 `3abab18`，前置测试移动 `6a521f2`。
- 候选 Common Jar SHA256：`a9011280cd8f378cc540b3f0af5fac59a0d6ecb58eb93ead33fc947892b1d0df`。Demo A、B JVM 固定使用同一候选 Jar，A/B/C 原始 RSA 只读加载；C 在第一次 SIGKILL 前已运行，后续两次见证自主产生。
- `OTC_T125_ENABLE_DEGRADED=1 OTC_T126_ENABLE_REJOIN=1 OTC_T127_ENABLE_REVERSE=1 OTC_T128_REQUIRE_E3_INSTALL=1 OTC_T129_REQUIRE_E3_WRITE=1 OTC_T130_AUTO_C=1 OTC_T270_ENABLE_E3_B_REJOIN=1`，使用 `examples/common-only-demo/scripts/verify-real-auto-sigkill-genesis-replay.sh`。
- 原始本机证据目录：`~/.opentradingcore/t124-live-kill-runs/20261029105910`，运行总结：`~/.opentradingcore/p0-20261029-evidence/t270-e3-online-b-rejoin-r5.log`，测试控制进程退出码 **0**。测试创建的隔离 JVM 已按脚本关闭。

## 实际证据（非推断）

1. A 被真实 `SIGKILL`，B E2 C 见证后 LOCAL READY，继续写总值 40→60；A 回归 E2 Replica 并物理追平：PASS。
2. B 被真实 `SIGKILL`，A E3 C 见证后 LOCAL READY，总值 60→74、6 个去重业务请求：PASS。
3. **在 A E3 JVM 和 ZooKeeper EPHEMERAL 主租约仍在线时**，新 B JVM 使用只读 A 证据卷、独立 B 私钥及固定 A/B/C 公钥验证 E1 Genesis、E2 WAL/A 实体回归收据、A E3 签名 Stage 与独立 C RSA 见证：`T270_B_VERIFIED_A_E3_RSA_GENESIS_AND_C_WITNESS=PASS`。
4. B 通过现有 Common `CommonCertifiedLocalReplicaCatchup` 的单节点历史 WAL 签名接口，将 A 原始 E3 fsync WAL 的两条记录安装到 B 自己的磁盘，再经独立 B RSA 签名，并应用六条 E1/E2/E3 Demo `byte[]` 业务：总值 **74**、**6 请求**、E3 序号 **2**。
5. B 获得 **E3 Replica** Common 角色，未获得 E3 Primary，确认 A 原 PRIMARY 租约仍存活：`T270_REAL_B_E3_ONLINE_RSA_REPLICA_REJOIN_PASS` 及 `T270_B_E3_ONLINE_REJOIN_RSA_PHYSICAL_AND_COMMON_ROLE=PASS`。
6. Common 更改仅放宽**受同一 A/C 签名证明约束**的 E3 旧 B *Replica* 验证，并允许 B 以历史只读方式验证旧 A 的原始 WAL。未经独立 C 见证不得授权，不能让 B 得到 Primary。E1/E2 验收的测试重放使用隔离副本，不修改原始 WAL。**不增加任何订单类型或业务类别判断。**

回归：本次候选 Common `mvn -q test` 共 139 suites / 616 tests，567 PASS、49 skipped、0 errors、0 failures；Demo 状态机 + 原始 RSA E3 测试均 PASS。没有变更正式 Order/Trade 镜像、业务数据、RSA 身份或 Gateway。

## 严格保证边界与剩余 P0

- E2/E3 故障后新增写入是 `LOCAL_DURABLE_ASYNC`，历史客户端 ACK 有 RPO 风险，B 后来落盘不能倒签或追认历史 `QUORUM_DURABLE`。
- **还未做**：B 通过 Common 正式节点进程的常驻生命周期自动发现和自动重加入；同一主副本之间的真实持续 TCP WAL 流复制/后续新业务连续追平；重新满足严格 2/2 时未来写入的真实签名 ACK；无测试进程恢复/READY 编排的生产通用 Common 运行时自动 A/B 互切。以上全部有实测证据前，P0 不得标记 GO。
- 通过这些之后，才允许 P1 同版 Common Jar SHA 和同一 Bootstrap/Watch/恢复生命周期替换 Order/Trade。Demo/Order/Trade 不实现自己的 HA，不按业务类型做集群存储准入。

> **后续 T272（本日）**：B E3 在线回归之后，A 新增真实业务并通过 Common Netty TCP 增量复制给 B，B fsync/RSA 签名，双方总值 85、7 个请求，阶段 PASS；历史及本次本地 ACK 均不追认严格 2/2。详见 [T272](T272_DEMO_COMMON_E3_POST_REJOIN_TCP_RSA_20261029.zh-CN.md)。P0 正式全自动生命周期仍 NO-GO。
