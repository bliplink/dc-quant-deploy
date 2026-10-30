# T349｜Common Physical WAL Poison → 分区级永久进程内撤权（2026-10-31）

## 实施内容

- 修复 `Common` WAL 物理写入及 Apply 不确定结果的通知链。此前 `CertifiedBusinessCommandBoundary` 标记 `poisoned` 后，只阻止其自己继续写入，但经 ZK 正常续约的 Node Control 没有分区级硬隔离。
- 新增 Common-only `CertifiedBusinessCommandBoundary.PoisonListener`，仅在物理 WAL 阶段或已提交业务 Apply 出现不确定结果时调用，不在健康的提交路径做 ZK 或 RPC。原有业务编码异常、纯 preflight 失败不会不可逆撤权。
- 正式 `CommonCertifiedPartitionRuntime.openWithCertifiedRecovery` 将它连接到 `NodeClusterControlManager.fencePoisonedPrimary(partition,epoch)`；底层 `NodePartitionGrantTable` 保留每分区的本进程已拒绝 Epoch 下界，签名节点租约正常续约也不会重新授权这个原主，其他 255 个分区的原 Epoch 仍然可继续 ACK。
- 保留 Common 的当前严格授权、真实物理 ACK/双签 Custody 判定：该修复不是另一个选主协议，不会自行修改 ZooKeeper manifest、Stage、签发恢复签名、删除 WAL 或冒充 READY。
- **进程内**隔离不是跨节点可验证的持久退休收据；跨重启和 E3 主切仍须 Common 原有原始 WAL/CommitIndex/Custody 和真实 ZooKeeper / RSA signed retirement 门禁。

## 已完成的回归证据

- `NodePartitionGrantTableTest` 新增 256 分区验证：P000 E2 硬隔离后，同 generation 的 ZK 心跳成功续约，P000 仍不能 ACK；P002 等其他主/备正常；仅经认证 Epoch 3 可重新赋予 P000 新角色。
- `CommonCertifiedNodeRuntimeTest` 在真实 Demo RSA/Netty 两节点流中停掉 Replica B，再对 Primary A 追加真实 WAL，确保无客户 ACK、P090 E1 被自动硬隔离、同节点租约刷新不复活旧授权。
- `CommonCertifiedPartitionIsolationTest` 的老拒绝原因 `certified` 更新为精确的 `poisoned`，仍验证失败的 P210 不可恢复写、健康 P211 继续运行。
- 上述三个定向 Suites **29 个测试，0 失败、0 跳过**。Common Maven **全量 153 suites / 657 tests / 0 failures / 0 errors / 59 skipped，exit 0**；本次明确指定原始 P193 与 T293 E4→E5 RSA 证据路径，实际进行旧双签历史验证。新代码本地 Common commit **`df1da5f`**。
- 本地重新安装同坐标 Common JAR，Order **44 suites / 137 tests / 0 failures / 0 errors / 2 skipped**，Trade **52 suites / 207 tests / 0 failures / 0 errors / 0 skipped**。Order 2 跳过项依赖原始文件路径；T343 曾单独真实跑过，T344 仍没有独立运行成功。

## 当前在线状态及后续门禁

- Mac Demo 只读验收：Order/Trade A/B Docker 容器运行、重启数 0，但还是旧 T335/T336 镜像；Robot exited。
- 原始 P193：Order A 22667 / B 22668 物理 WAL，额外终态无独立双签证明；255/256 分区匹配；不得直接纳入提交/截断修改原始数据。
- **尚未恢复交易、尚未在线完成 E3**：旧 Order B 的共享 ZK 节点级临时租约仍活着；Common `stageRecovering` 仍要求旧 lease 缺席。新的本进程分区硬隔离不能替代跨节点签名/持久撤权证明。要继续复用 Common-only old-authority lease / signed Stage / StrictCrashReadyPublisher / 双节点新 Epoch 恢复机制，再正式部署新 Order/Trade 并验收 Robot 报价、成交、MD、A/B 自动互切。
- 不使用 GitHub Actions、不改 Gateway、不引入 Order/Trade 独立 HA、不冒签任何证明，**NO-GO**。
