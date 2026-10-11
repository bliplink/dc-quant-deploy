# Mac 本地集群：Common 来源认证协议与真实 Order 归档核对（2026-10-11）

## 执行约束与部署结论

- **仅源码开发和真实归档离线检查**：没有清理 Demo 数据，没有替换运行镜像，没有执行新的 Order/Trade/MD SIGKILL；原 10 个租户继续运行。
- 代码全部在独立 Git worktree 修改和测试。Common/Order 两个仓库的新增代码均已提交并快进推送 `saas-crypto`。
- **Common 统一恢复正式接管还没有完成**。本次实现认证 HEAD 协议并通过真实 Netty 控制通道往返，尚未实现生产来源的签名/水位证明、Snapshot 与 WAL 数据流的会话绑定、恢复外部门禁 READY 接线，不能把协议专项验证冒充全系统 HA 成功。

## 1. Common：认证来源证明新增及实测

GitHub `com.app.common/saas-crypto` 新提交 `7b6d1d6`：`RecoverySourceAttestation`。

已有的 `DirectNettyReplicationTransport.control` 和 `DirectNettyReplicationServer` 不新增第二条恢复 TCP 通道，新增可通过现有 exact-node 控制端口使用的、有版本号及严格长度限制的证明报文。

- 接收端发出 **SecureRandom 256-bit Challenge**，包含由验证者产生的时间戳。
- 由当前 Primary（**后续真正的生产源端实现还需落地**）用该物理 Primary 专属的、至少 256 bit 的 HMAC-SHA256 密钥签署恢复 HEAD 声明。
- 明确绑定：随机 Challenge、Primary 身份、ZooKeeper assignment 版本、分区、源端 Snapshot SHA256、Snapshot Epoch/序号、提交水位、Committed HEAD Epoch/序号、恢复模式和快照大小限制。
- 验证端按自己的原始 Challenge + 预期 ZK/分区/业务水位**重新构造报文并进行常量时间对比**；不信任 TCP endpoint 名称或客户端自报水位。5 分钟是硬性最大窗口，并要求按配置使用更短过期窗口。
- 测试包含错误物理节点、不同节点密钥、ZK 版本变化、Snapshot SHA/HEAD 篡改、旧 Challenge 重放、未来/过期请求、传输帧截断及 HMAC 字节篡改。
- 通过真实 Netty loopback replication control 请求/返回 HMAC 证明；源码 **Common Maven 全量 176/176 PASS**，其中新增 6/6 测试。
- **当前仅为密码学的认证报文基础**：生产源端不能照抄测试 Fixture、不能签署未经自行证明的客户端水位；验证端仍需确保 Snapshot、Committed WAL 数据来自**同一已认证会话**，需要单节点保密密钥配置、轮换和恢复控制日志防泄漏。普通明文 TCP 报文不能直接算作证明。没有打开任何 `commonBinding.enabled`，没有发布 Maven Central 或替换本地镜像。

## 2. Order：真实 CQ 归档离线顺序扫描与跨节点内容一致性

GitHub `com.app.dc.ordersvr/saas-crypto` 新提交 `417ee24`，增加可选 JUnit：
- `OrderRealArchivedCqReadOnlyTest`：只允许环境变量指向**已复制**的 `offline-order-archive-samples` 测试目录，不允许读取线上 `/journal/` 路径；Chronicle Queue `.readOnly(true)`，逐条检查分区 ID、严格连续 WAL 序号、Epoch 不回退。
- `OrderRealArchivedOverlapTest`：在两个隔离目录上打开两份 `.readOnly(true)` CQ，逐序号比较重叠区间的完整 `OrderJournalRecord.encode()`，包括 Epoch、seq、event type、event ID、timestamp 与 payload。
- 普通 Maven 构建不指定 `ORDER_ARCHIVE_OFFLINE_COPY` / `ORDER_ARCHIVE_OFFLINE_A` / `ORDER_ARCHIVE_OFFLINE_B` 时自动 skip；本次 Order 全量回归 **325 项、0 失败、0 错误、3 skip**。

### 实际取证来源（2026-10-11 早先故障分区 P200）
- Mac 源：`~/.opentradingcore/dc-saas-runtime-zkfix-20261011/data/OrderSvrA/journal/.archive/P200-epoch2-seq22014-1791714943397/`
- Mac 源：`~/.opentradingcore/dc-saas-runtime-zkfix-20261011/data/OrderSvrB/journal/.archive/P200-epoch2-seq22015-1791715909739/`
- **仅执行过一次复制**，不写源目录；测试目录：
  `~/.opentradingcore/local-common-protocol-20261011/artifacts/offline-order-archive-samples/order-a-p200`
  `~/.opentradingcore/local-common-protocol-20261011/artifacts/offline-order-archive-samples/order-b-p200`
- 用 JDK8 Maven Docker 执行（测试目录只读挂载）。复现命令需要在 `com.app.dc.ordersvr` 的源码目录下执行：
  ```bash
  ARCHIVES="$HOME/.opentradingcore/local-common-protocol-20261011/artifacts/offline-order-archive-samples"
  docker run --rm --cpus=2 --memory=2950m \
      -v "$PWD:/workspace" -v "$HOME/.m2:/root/.m2" \
      -v "$ARCHIVES:/offline-order-archive-samples:ro" \
      -e ORDER_ARCHIVE_OFFLINE_A=/offline-order-archive-samples/order-a-p200 \
      -e ORDER_ARCHIVE_OFFLINE_B=/offline-order-archive-samples/order-b-p200 \
      -w /workspace maven:3.8.8-eclipse-temurin-8 \
      mvn -q -Dtest=OrderRealArchivedOverlapTest test
  ```
- **Order A**：22,011 条，序号 `4..22014`，Epoch `2..2`，`STATE_COMMIT` 9,634 条；`Order B`：22,015 条，序号 `1..22015`，Epoch `1..2`，`STATE_COMMIT` 9,634 条。两份 Chronicle 原生只读扫描均 PASS。
- 两节点 WAL **重叠 22,011 条完整记录逐条相等**，Junit `OrderRealArchivedOverlapTest` 退出码 0。`Order A` 与 `Order B` 归档文件**整体 SHA 不同**是自然的：B 含比 A 更多的边界记录与较早 Epoch，不能用整体哈希差异误报业务复制不一致。
- 之前已对两份文件通过 `manifest-order-archive-segment.py` 生成 SHA256 清单：`~/.opentradingcore/local-common-protocol-20261011/artifacts/archive-samples/`，并确认文件在清单生成时未变化。两份归档均 `deletionAuthorized=false`，继续 `HOLD`。

## 尚未完成：明确区分离线 WAL 一致与在线 Archive Catch-up

1. 目前实测的是**封存 Archive 的真实历史记录可读且 A/B 重叠前缀完全一致**；并未从 Archive/Active CQ 联合读取给一个新落后 Replica 执行 Apply、Snapshot 校验并恢复 READY。
2. 下一步需要构建隔离 Learner，在可信源端已经有新 Epoch Snapshot + 归档+活动日志的前提下，验证 `Archive → Snapshot_BEGIN → STATE_* → Committed HEAD` 连续性，逐记录比较权威 MySQL/Projection，并检查重放发生故障时是否保持 NOT_READY。
3. 只有所有消费者、冷备、副本和 Projection 最小水位得到权威确认，并有外部备份可恢复证明后，才可考虑安全归档删除；本轮任何源 Journal/Archive 均未被删除或迁移。
4. Common 还需要完善生产双向来源认证、每节点密钥轮换、在真实 Netty 控制器上采集带签名的权威 Head、Snapshot 与 committed WAL 数据流的整体 SHA/会话绑定，最后才可能在单分区灰度 `VerifiedTransport` 与 `StateMachineRecoveryCoordinator.recover`。
5. MD 自动故障接管仍被权威 Order 全市场快照/Publisher Fencing 门禁阻止，不因此轮证明而开启 MD 自动 failover。
