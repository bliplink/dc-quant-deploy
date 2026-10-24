# T78 — 真实三节点 ZooKeeper 上的节点级 256 分区控制（2026-10-24）

## 交付结论与边界

已将 T77 的内存 `NodePartitionGrantTable` / `NodeClusterControlManager` 扩展为 **正式 Common 源码中的真实 ZooKeeper 节点级控制适配器 `ZkNodeScopedControlPlane`**。一个持久版本化 ZNode 包含 256 分区路由、Primary/Replica、分区 Epoch 和 `STRICT_QUORUM` / `LOCAL_DURABLE_ASYNC` 策略；节点级独立 EPHEMERAL Lease 用 ZK CAS 成功续租；业务检查仅访问本地不可变内存授权表。本轮已完成真实 3 个 ZooKeeper JVM 控制层验证，但 **未通过真实256分区 WAL/撮合，未完成 ZK 多数派恢复后的自动签名新 Epoch 切换**，生产全系统仍 NO-GO。

## 正式 Common 代码

- 源仓库：`/Users/kong/.opentradingcore/common-batch-official-release-20261013/common`，分支 `saas-crypto`，本地提交 **`5c68f5b`**，未推送、未 Maven 发布、未运行 GitHub Actions。
- 新增 `ZkNodeScopedControlPlane.java`：节点接入启动及变更才读完整路由 Manifest，通过单个版本化 `NPC1` 记录管理最多 256 分区；一轮节点续租做节点 EPHEMERAL 租约读取和版本 CAS，**正常续租不再次读256分区 Manifest**，不对每分区循环 ZK 读/写；对真实 `ZookeeperClient.readData(Stat)` 不存在 ZNode 的异常进行限定处理；Watch 变更时原授权立即撤销、重新认证更新。
- 正常 Manifest 变化必须经 `CertifiedManifestTransition` 接口提供已认证切换证明；旧 Epoch 不因变更直接复用。**这个接口是强制边界，尚未接入真实物理签名双 Custody 校验器**。
- ZK 多数派/会话丢失后的 `CertifiedRecoveryAuthority` 要求更高 Manifest generation、相关分区更高 Epoch、旧节点租约完整退休时间加安全余量以及新节点 EPHEMERAL 租约 CAS，另外必须经独立恢复方确认物理 CommitIndex、双 WAL 和双 Custody。不提供外部认证服务即拒绝自动续权，绝不因 ZK 重新连接清除撤权标记。本轮 **没有真实运行此认证自动恢复链路**。
- `NodePartitionGrantTable` 新增单分区独立、跨多次短租约保持不变的主切隔离截止时间，其他255个未变分区无需等待；授权消失后重加的 Epoch floor 防 ABA，防止 RECOVERING 中移除→恢复后冒用旧 Epoch；普通节点续租保持同一逻辑 Permit，避免长请求被每次续租误撤销；Watch/硬撤权则立即使旧 Permit 失效。
- 减少 ZK Manifest 热读取到仅首读/Watch变更（具备真实仪表字段 `manifestZkReads`、`leaseQuorumCasWrites`）。

## 实测与验证

Java 8 本地编译与新 Common JUnit **25/25 PASS**，包括两种 ACK 模式、单控制证明 256分区、数十万内存检查、真实/模拟CAS冲突、旧 Epoch 退休、Watch/CAS竞态、过期拒绝、新 Epoch 恢复钩子行为、消失/重加入ABA，以及续租期间 Permit 不失效。

独立新 Compose 项目 `otc-t78-node-zk`：**同一 Mac/DockerVM 上 3 个不同 ZooKeeper JVM**，用真实 `ZookeeperClient`，两个独立客户端会话分别模拟 NodeA/NodeB 的256分区节点控制器，并非256个运行中的市场业务JVM，也未测试双独立物理故障域。

物理 ZK 验收日志：

```
T78_REAL_ZK_NODE_256_BOTH_MODES_READY nodeA=256 nodeB=256 renewA=5 renewB=5 manifestReadsA=1 manifestReadsB=1 nodeLeaseCasA=5 nodeLeaseCasB=5
T78_REAL_ZK_UNRELATED_255_NO_EPOCH_BUMP
T78_REAL_ZK_NODE_CAS_WATCH_ROLE_CHANGE_PASS manifestGeneration=2 onlyP000Epoch=2 unaffectedP001Epoch=1 leaseVersionA=12 leaseVersionB=13 manifestReadsA=2 manifestReadsB=2 nodeLeaseCasA=12 nodeLeaseCasB=13
```

这里 `P000` 的角色变更是 **测试人员通过测试用管理端写入 Manifest ZK CAS**，采用明确标注为 test-only 的认证回调；**这不是实际自动选主，更不是双 Custody 的故障恢复验收**。真实控制数据表明从 ~5 到 12/13 次续租 CAS 期间，每个节点只读了 **2次 Manifest（初始化1 + Watch变化1）**，未随256个分区重复读取；此数量不包含 ZooKeeper 自身心跳及测试管理端 ZK 访问。

ZK 故障注入：实际停止 `zk2`、`zk3`，剩余1/3节点、等待节点租约到期。在256分区控制测试中严格/异步许可 **均拒绝**，无过期授权 ACK。此验证是本地 Permit/模式证据校验，不是真实交易客户端 ACK。

实验结束，隔离 `otc-t78-node-zk` 容器已全部停止，**7个ZK/WAL证据卷保留**。正式 `dc-saas-*` **24个容器未修改、持续运行**。

## 最终未通过项（阻塞发布）

1. **自动安全恢复**：当前控制接口需要具体物理 CommitIndex + 双 WAL + 双 Custody 已签名水位认证和旧主隔离证据。即使 ZooKeeper 多数派恢复也不得仅本地清除 `sessionRevoked`。必须将真实 Netty 物理恢复协议和独立 ZK 授权 CAS 绑定，实际故障注入通过才允许 READY。
2. **真实256业务分区**：目前 NodeA/B 是两条真实 ZK 控制会话；复制/签名/完整分区状态机仍采用 T77 真实 P000 试点，尚未将其改为256分区 Netty 实际分片复制、Order/Trade 动态路由。
3. **性能**：此轮只计控制读/CAS，不是 TPS 新压测。T77 单市场严格32组提交吞吐 ~105.7 WAL/s、异步单条~97.2 WAL/s；目标每分区1–2k、P95 5–10ms 未达到。
4. Mac 主机本轮空间使用约 **95%**，可用约 **25 GiB**，进入长时间压力测试前需要对无引用镜像/过期日志做有证据的清理，不能误删在线Demo引用镜像及持久卷。

完整源码归档：`tests/patches/common-node-zk-cas-256-t78-20261024.tar.gz`，逐文件 SHA256：`tests/patches/common-node-zk-cas-256-t78-20261024.sha256`。

下一阶段：优先实现并验证 **真实 Netty 双 WAL/CommitIndex/Custody 认证恢复→新 Epoch CAS→READY 的自动控制器**，然后将真实市场分区从 P000 扩展到256，并做严格/异步对照、A↔B 连续切换与资金/持仓/委托/成交/Projection 权威对账。
