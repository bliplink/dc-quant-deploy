# 2026-10-11 Mac Demo：Common 恢复传输 HEAD 与 Snapshot/WAL 数据帧绑定阶段验收

## 范围与结论

本阶段**仅开发和测试 Common 公共接口，不更改原有 10 租户运行集群**。不使用新的 Maven Central 版本，也不改 Order/Trade 运行镜像或擅自启用 `commonBinding.enabled`。没有任何归档删除、未做新的真实 SIGKILL。

本轮 Common `saas-crypto` 最终 commit：**`91ecb57`**（前置 commits：`7b6d1d6` 来源认证，`eb508ad` 带签名 Snapshot/WAL 传输帧）。增加公共 `RecoveryTransferFrame` 和 `RecoverySourceHeadControlHandler`。

## 真实已通过的范围

- `RecoverySourceAttestation` 在恢复请求开始前签署来源身份、分区、ZK Assignment 版本、Snapshot SHA256/序号与 Committed HEAD，并加入恢复会话随机 Challenge。验证者在接收任何字节前必须持有有效源端 HEAD 证明；签名错、换节点、错 Epoch/水位、Challenge 重放都会拒绝。
- `RecoveryTransferFrame` 在**恢复数据控制平面而非正常下单热路径**引入严格上限为 **256 KiB** 的帧。每帧使用节点专属 256-bit HMAC-SHA256 密钥绑定同一 Challenge、物理 Primary、ZK 版本、分区、Committed HEAD、帧类型、偏移或日志序号、Epoch 和帧载荷。
- `Verifier` 构造时再次强制校验源端 HEAD 证明；无法跳过该步骤，仅靠随机 Challenge 创建“已认证”流。
- Snapshot 分块必须从 offset=0 无重叠、连续传输，同一个 chunk 无法重放，按接收序列计算 SHA256 并在完成前检查完整数据长度不得超出 `RecoveryRequest.maxSnapshotBytes` 和用户指定的附加上限。
- Snapshot SHA 完整验证前禁止接收 WAL 数据帧；随后仅允许 seq=`snapshotSeq+1..committedHeadSeq` 严格逐笔递增、Epoch 非递减、最后 Epoch 与 HEAD 一致。更换源 Primary/ZK 版本/分区/HEAD/Challenge，已签署的数据帧将失效。
- `RecoveryTransferFrameControlTcpTest` 使用 Common 已有 `DirectNettyReplicationTransport.control` / `DirectNettyReplicationServer` 在真实本地 TCP 上传回多份完整帧，并按同一会话验证。服务端数据由**明确标注为 fixture 的模拟权威生产者**提供，不能误称已接入真正 Order/Trade Journal。
- `RecoverySourceAttestation` 的**V2 语义只签源端权威 `SourceHead`**：包含 Snapshot/Committed HEAD 的分区、Epoch、commit marker、序号和 SHA，但不让 Primary 替副本签本地 Epoch、Seq、恢复路径或恢复策略。测试证明不同落后进度的副本可独立验证同一份源端 HEAD。
- `RecoverySourceHeadControlHandler` 是**默认不安装、不注册**的公共 Netty control handler；源服务必须注入 `DurablePrimaryAuthority.requireCurrentDurableHead(partitionId)` 与节点专属密钥提供者，处理器要求当前物理 Primary ID 和分区匹配、Challenge 不过期才签名。缺少 durable proof、Primary 改变、请求过期或服务名称不匹配均失败关闭；新增真实 TCP 控制端口往返测试。
- Common Java 8 Maven **全量 187/187 测试通过，0 失败、0 错误、0 跳过**。

### 安全边界：仍未完成的关键生产接线

1. 虽然 Common 新增了独立的、默认不注册的`RecoverySourceHeadControlHandler`，但**Order/Trade 尚未提供真正的 `DurablePrimaryAuthority` 实现**，因此没有从业务服务的 ZooKeeper 当前 Primary、Durable Snapshot、Committed WAL 生成真实带签名的业务流。本轮 TCP 是真实 socket/协议，但业务提供者仍是测试 Fixture。
2. 尚需给协议接入可靠的每物理节点密钥管理、轮换、实际 ZK 角色与 Epoch 认证、真实 Committed HEAD/Commit marker 证明。Common 处理器不会默认提供这些证明，缺失必须拒绝。对开放网络还需 TLS/mTLS 或等效的双向网络认证；**单独的 HMAC 证明不能等同已启用 TLS 的生产通道**。
3. 验证器要求 Snapshot 分块写入独立 staging 文件，所有 Snapshot 数据必须校验完成并**重新校验 staging file** 才能调用现有 `StateMachineRecoveryCoordinator.recover`；WAL 载荷依然必须经过 `OrderCommittedLogSource` / `TradeCommittedLogSource` 的服务级累积提交、状态机业务记录/Commit Pair 检查。
4. 仍需在 **`ZkReplicaRecoveryAuthority` + `DurableRecoveryTransactionControl`** 下完成同一来源证据、独占恢复屏障、持久化 INSTALLING / BASELINE_DURABLE / REPLAY_COMPLETE、失败保持 NOT_READY 和外部门禁 READY 的真实单分区联测；仅验证这些通用数据帧**不代表**已完成 Common 正式恢复切换。
5. MD 自动接管仍因 Order 权威全市场镜像和 Publisher Fence 证明不足而被禁止；本轮不改变 MD 状态。Archive→Active CQ 联合追平及日志清理安全条件也未因本轮 Common 协议工作而自动满足。

## Mac Demo 验收

最后只读巡检：

- `tests/check-demo-tenants-readonly.py`：**PASS_10_TENANT_SNAPSHOT**，10/10 Robot RUNNING，各保留40单、双边盘口10档。
- `tests/check-projection-consistency-host.sh`：Order 与 Trade watermark-tail mismatch=0（10 watermarks）、orphan mutation=0、cross-partition event IDs=0。
- 24 个 `dc-saas` Docker 容器运行，Order A/B/C、Trade A/B 均无 OOM。
- 保持运行镜像不变：Order A/B/C `dc-saas/ordersvr:cluster-dev-local-orderepoch-4c7df72-20261011`，Trade A/B `dc-saas/tradesvr:cluster-dev-local-tradeempty-a8fc334-20261011`。
- 原始最后一次巡检证据：`~/.opentradingcore/local-common-protocol-20261011/artifacts/post-attested-transfer-10tenant.json`。

## 下一阶段最小可执行闭环

1. 在独立源码分支给 Order/Trade 实现**只读且默认禁用**的 `DurablePrimaryAuthority`，再把 Common 的公共 control handler 注入其既有 Netty 服务端：必须从最新 ZK Primary + durable snapshot + committed journal marker 推导精确 SourceHead，而不是签客户端自报的 HEAD。
2. 使用上述真实来源提供者和 Netty 控制通道，将 Snapshot chunk + WAL 帧传输到隔离恢复 Staging，检查完整 Snapshot 与 WAL 证明，先**影子验证**同一数据，不恢复在线分区。
3. 再将真实已认证流连接 Common 状态机 `restore + apply(byte[]) + finishReplay()`，先选单测试分区；READY 前必须单独证明旧发布者 Fence、Gateway 路由和所有副本/Projection 权威一致。
4. 完成实际 Archive→Active CQ 联合恢复、跨 Epoch GAP、重复/脏尾、落后副本不丢单无双主的集成测试；再讨论归档 retention/删除。
5. 10 租户长稳及实际失效注入均通过后，分批进入20→50→100→200租户。
