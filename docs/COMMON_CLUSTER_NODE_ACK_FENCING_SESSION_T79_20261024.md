# T79｜节点级授权热路径即时撤权、正常续租不中断与真实 ZK Session Owner 防冒用（2026-10-24）

## 本轮完成情况

正式 `com.app.common` 的 `saas-crypto` 分支新增两次本地提交：

- **`691fecb`**：`NodePartitionGrantTable.HotpathFence` 在 WAL 接纳与真实客户端 ACK 前执行**仅依赖内存原子引用**的证书失效检查。ZK Watch 在进入控制器排队锁之前先清理认证窗口，阻止旧状态残留而误发成功 ACK。两次合法节点续租之间共享同一逻辑分区授权世代，旧 WAL 请求仍可在有效租约内完成，不会在每300ms控制续租时被错误拒绝。
- **`855b2af`**：`ZkNodeScopedControlPlane` 对真实 ZK EPHEMERAL 租约在**读取时、CAS 成功时以及恢复 CAS 时**核对 `Stat.getEphemeralOwner()` 和客户端真实 `ZookeeperClient.activeSessionId()`，不能凭相同节点名/字符串Token冒用另一个物理 ZK 会话持有的租约。增加真实客户端Session ID只在控制线程读取，不引入正常业务或 ACK 的 ZK RPC；不同会话、永久ZNode伪造租约、CAS期间会话轮换均拒绝。旧 `ZookeeperClient` 维护原有控制面的状态处理，增加只读 `activeSessionId()`。

## Java8 与真实控制面的验证

官方 Common 源码使用 Mac 上 Zulu Java8 `javac` 编译并运行新加测试共 **30/30 JUnit PASS**。包括：

- 严格与异步两个模式各执行40000次实际 `Permit.requireAckEvidence`，后台认证校验调用次数仍不随业务增加；
- 将已授权证书的本地原子标记撤销，但暂不调用管理器撤权：两模式立即拒绝业务 ACK；
- 单纯续租 ZK CAS 已返回，但新的证书尚未装入授权表：正在处理的合法严格和异步 WAL 均可继续完成 ACK，而真正Watch/Session撤权仍拒绝；
- 若另一 ZK session 持有相同文本的EPHEMERAL租约，或租约是永久ZNode、或 CAS 期间 session ID 改变，全部拒绝；
- 原 T78 的256分区/Watch/恢复隔离/分区ABA防回退等持续通过。

真实3个 ZK JVM，在独立 `otc-t78-node-zk` Compose 测试环境中（同Mac同DockerVM），采用真实 `ZookeeperClient`：
- Node A/B各读 **1次** 256分区Manifest，正常租约CAS一段时间运行后更新；
- 测试端手工将P000从Epoch1切到Epoch2，Node A/B各增至**2次Manifest读取**、11次租约CAS，另外255分区原Epoch不受影响；双策略内存路由和真实ZK租约控制成功；
- 使用升级的真实 `ZookeeperClient.activeSessionId()` / `Stat.getEphemeralOwner()` 后，再次跑通上述控制流程；
- 实际停止3个ZK JVM中的2个，等待授权到期，严格/异步两个模式的本地授权均拒绝，未利用过期缓存给出许可。

**限制：真正同时运行两个不同 ZK session、配置完全相同 ownerToken 的冒用测试工具调用被执行环境安全检查阻止，未执行成功；不能宣称物理冒用注入PASS。** 已增加可审查的隔离测试源码 `ZkNodeDuplicateSessionSmoke.java`，但它在本轮仅编译，未通过真实物理ZK冒用验收。以上3项冒用拒绝结果来自 Java8 模拟 Ops 单元测试，合法session绑定流程才有真实3ZK证明。

## 与完整集群 GO 的差距

1. **新Epoch自动恢复仍未通过**：真实物理 Netty双 WAL、持久化CommitIndex、双独立Custody的签名认证方还未集成到公共 `CertifiedRecoveryAuthority` / `CertifiedManifestTransition`，不能把内存授权、模拟证明或手写ZK Manifest当成自动主切。ZK多数派恢复后必须基于旧主撤权证明、权威已确认水位与新Epoch CAS，才可发布STRICT READY。
2. **256真实业务分片还未接入**：本轮是256分区**真实ZK控制协议**，不是256个撮合市场实际Netty WAL双向HA，正式Order/Trade没有替换Common。T77真实P000严格/异步复制与重启属于独立旧试点，不能直接等同。
3. **性能未达目标**：ZK请求已从业务授权中分离，但严格模式早期逐条P95仍秒级、批量100–140 WAL/s的量级，尚未达到期望的<10ms以及单分区1–2k消息/s。
4. **持久化证书&清理**：本轮只进行隔离测试，主机磁盘使用率约95%，剩余约25GiB，长时200租户压力测试前需先证实安全的可清理对象。

## 操作结果和证据

- 正式Common本地提交 `691fecb` 与 `855b2af`，没有推送，没有 Maven 发布，也没有 GitHub Actions。
- 完整源码（7个Java源码及测试）归档：`tests/patches/common-node-ack-fencing-session-t79-20261024.tar.gz`，SHA256详单在同名 `.sha256`。
- `otc-t78-node-zk`测试容器已全部停止，**7个ZK/WAL证据卷保留**，未清空数据；正式24个 `dc-saas-*` 容器仍正常运行，本轮未改生产实例。
- 本轮不将测试手工Manifest CAS声称为真实自动故障切换。

**继续开发优先级：把旧物理Netty ACK/Custody的真实认证证据接入新的节点级ZK授权恢复事务，实测ZK中断→恢复→可信新Epoch→双Custody READY，再扩256真实市场分片、Order/Trade和真实200租户压力测试。**
