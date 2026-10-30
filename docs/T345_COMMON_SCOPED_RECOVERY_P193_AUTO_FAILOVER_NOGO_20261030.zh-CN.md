# T345｜Common 单分区恢复隔离与 P193 自动接管接线审计（2026-10-30）

## 新优先级与范围
用户明确选择“继续修复集群”。不走无 HA 的临时单节点运行、不重置数据、不在存在 22668 未认证 WAL 尾部时强制 READY；所有 HA 代码只在 Common，不新建 Order/Trade 各自复制协议。

## 当前真实 P193 核验
- ZooKeeper 仍为 Order P193 E2 `OrderSvrB` Primary、`OrderSvrA` Replica、`STRICT_QUORUM`、`READY`；A/B 旧 ZooKeeper 节点临时租约仍然活着。
- 物理 WAL A=22667 / B=22668；B 末尾 `STATE_REMOVE` 是 CRC 完整但没有对应的双签 CommitIndex/Custody 认证，不允许把它当已提交订单终态。之前真实 A 认证前缀及全部 Order 业务回放测试已 PASS。
- **关键卡点**：Common `CommonCertifiedFailoverWatch` 只有在旧主 ephemeral lease 消失后才能 `stageRecovering`。现在 B 写入器虽已 poison/fence，但它的 Node ZooKeeper 会话还活着；因此单靠当前 watch，B→A 自动 E3 不会启动。Order/Trade 的正式 Spring READY 启动 wiring 目前也没有显式调用 `CommonCertifiedNodeRuntime.armAutomaticFailoverWatch`。
- 当前 `CommonCertifiedStrictCrashReadyCompletion` 的旧节点签名关闭回执、双节点新 Epoch 恢复回执、READY 阶段均是严格防伪门禁；在缺失证明时必须保持 NO-GO，不能直接让旧分区续写。

## T345 已修复并验证（本地 Common 代码）
- 原 `CommonCertifiedNodeRuntime.retirePhysicalForCertifiedRecovery` 在一个分区的签名 RECOVERING 后会 `server.close()` 并关闭**所有** `CommonCertifiedPartitionRuntime`，导致健康 P000…P255 分区被单个 P193 拖垮。
- 改为在 Common **真实 `requireCurrentRecoveringStage` 授权后**，只关闭目标分区的 Replica WAL/custody 物理句柄。加分区级 retired/failed-retirement fencing；同一个目标多次调用幂等；没有触碰非目标 Primary/Replica 或关共享 Netty。仍然不产生新 Epoch grant / READY。
- 新测试基于真实 Demo A/B RSA、两个独立 Common 分区和真实 Netty：P091 单独隔离后，P090 原 Primary 仍然完成物理双节点 `QUORUM_DURABLE` WAL 提交，B 复制水位从 0→1；错误隔离另一 P090 Primary 被拒绝；Netty 原端口持续存活。
- `CommonCertifiedNodeRuntimeTest` 指定密钥本地测试 **13/13 PASS（0 skipped）**；`Common` 本地提交 `2f684c7`，与之前认证原始 P193 历史分窗口修复 `04f3e25` 一起保留。完整 Maven 本地回归 **153 suites / 655 tests / 0 failures / 0 errors / 63 skipped，exit 0**。其中涉及真实 Demo RSA 的 13 项定向测试已另行指定密钥执行，13/13 PASS、0 skipped；全量 63 skipped 不能当作在线 HA 验收。
- 上述隔离测试的私有 helper 被反射调用，仅为验证在签名 Stage 之后的纯物理句柄隔离，不允许把反射测试当作在线 E3 认证证明。

## 未完成且不得冒充恢复
1. **Common 原 Primary 自我撤权**：一个分区 writer poisoned 后依然存在节点级 live ephemeral lease；必须由现有 Common node controller 提供真实旧主放弃资格及可核验 fencing，或节点失效后真实 lease 退场；不能只靠局部发现或模拟租约。不要用 Order 业务代码控制选主。
2. **Common 自动 Watch 接线**：现有 API 已提供，但正式 Order/Trade READY Spring 初始化没有调用；必须在所有必要签名源、物理证书、恢复 worker 注入完整后启动，防止 Stage 了却永远不能 READY。
3. **Common E3 非空业务恢复**：基于 E1 Genesis + A 已认证 E2 22667 状态，完成新 Epoch 业务快照、双节点实际恢复回执/授权，或明确认证 LOCAL_DEGRADED 且标记真实 RPO，按相应分区恢复策略自动申请 READY。旧 B seq22668 保留封存不能提交。
4. 真正部署新 Common/Order/Trade 镜像、启动 Robot、开仓部分成交撤单、真实 Trade 资金余额和 A↔B 故障注入仍未通过。

**总体仍 NO-GO。** 禁止 GitHub Actions；只进行本地构建/测试，保护 T330 原始磁盘证据与当前运行容器，直到 E3 真实准备就绪。
