# T269｜Demo+Common E3 反向切换后旧 B 副本物理追平验证（2026-10-29）

## 结论

**离线原始 WAL 字节追平、A/B 独立 RSA 签名与 Demo 状态一致：1/1 PASS。在线 B 自动重连/恢复 READY 尚未执行，P0 仍 NO-GO。**

T268 使用相同 Common Jar 和真实三 ZK、独立 A/B/C RSA 完成两次 SIGKILL：A→B→A，A E3 单节点继续写入使业务总值达到 74。后续要确认旧 B 可以按相同 Common 泛型 `byte[]` WAL 机制追平 A 的 E3 本地新记录，而不是添加 Order/Trade 专用恢复协议。

## 实际测试方法（只读证据、独立临时盘）

- 输入 T268 原始隔离证据目录 `~/.opentradingcore/t268-common-only-sigkill-runs/20261029085859`；原始 A/B RSA 按 T268 只读挂载。**不创建新身份，不修改任何原始 WAL、HEAD、快照或证书。**
- 从原 B E1 的 `business.wal` 和 E2 的 `local-async-business.wal` 按 Common WAL 帧重放 Demo 业务状态，独立重建总值 **60**。
- 从原 A E3 `local-async-business.wal` 读取两条实际 fsync 的新记录，复制至 B 的临时独立 E3 WAL；使用现有 `CommonFileBusinessWal` / `DurableWalCommitQuorum` 接口验证与源端**原始 WAL 整体二进制完全一致**，A/B 分别持原始 RSA 签名且得到同一 E3 前缀 SHA256。
- 重放 E3 两条新业务后两端 Demo `stateDigest()` 完全相同，业务总值均为 **74**。独立 B 物理目标 WAL 只存在单测临时目录；测试完成即清理。
- Docker 正式 Netty 依赖 + 原始 RSA 环境执行 `CommonE3FormerPrimaryBReplicaCatchupTest`：**JUnit 1/1 PASS**。
- 使用的是 T268 Common 候选 Jar SHA256 `73de80a0725208b3fde88b04c8f8f8b0601ffeb6d71b4de36f7e98cd018b1282`；Common 单测补充提交 `9d6fb69`。此前 Common runtime Watch 接线提交 `14d1b08`。

## 严格保证边界

- 此验证仅确认**可基于现有 Common 对旧 B 恢复原始 E3 已落盘字节、签名及业务状态一致**。没有把测试产生的 A+B 离线 RSA 收据当作历史 E3 客户端 Quorum ACK；原 E3 单节点写入仍是 `LOCAL_DURABLE_ASYNC`，仍有 RPO 风险。
- 本测试没有在存活的 A 主节点旁启动 B 的 ZooKeeper 会话，没有验证业务路由、Netty 在线复制、Replica READY、后续持续追平，更**不是无人干预的自动重新加入通过**。
- E3 源数据所在原 A WAL 在验证期间严格只读；为了使用 Common 的已有可写校验 API，在临时独立盘复制后核验，**没有放宽任何认证边界**。

## 下一 P0 唯一工作

在正常运行的 Demo+Common A E3 主节点旁重启 B，以现有 Common 统一成员/角色与 WAL 恢复 API 自动恢复到 Replica，持续追平新写入，确认切回正常双节点复制和签名 ACK。随后将 Demo 测试程序中仍负责串联恢复、C 证明核验和 READY 发布的通用动作收归 Common 正式节点运行时。通过后才允许 P1 Order/Trade 直接原样集成。参考 `docs/T268_DEMO_COMMON_DUAL_SIGKILL_A_B_A_REAL_EVIDENCE_20261029.zh-CN.md`。