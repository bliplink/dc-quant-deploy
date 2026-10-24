# T71 — Common ACK 策略公共接口与严格故障恢复验收（2026-10-24）

## 结果概览

**Common 公共接口提取及本地代码提交 PASS；已启用 STRICT_QUORUM 策略的自动故障恢复至 Epoch3 严格 READY 尚未通过。**

从先前 T70 仅供 V19 演示使用的策略，抽取为正式业务无关 Common 代码：
- `com.app.common.replication.DurableWalAckPolicy`：只允许 `STRICT_QUORUM` 和 `LOCAL_DURABLE_ASYNC` 两种枚举；封装 ACK durability、quorumDurable、possibleDataLoss 风险契约；禁止同一已安装 writer epoch 内更换策略；输入含空格、未知模式及 AUTO_DEGRADED 别名都直接拒绝。
- `com.app.common.replication.DurableWalAckPolicyBinding`：提供底层持久存储 `Store` 的创建/核验接口，要求原子 create-if-absent、绝不覆盖已有策略；客户端 ACK 完成实际 durable gate 后还需核对策略证据。Common 不直接实现某一业务的 ZooKeeper 路径；业务适配层提供安全的真实 ZK 存储。
- V19 Pilot `DemoV19AckPolicy` 不再定义私有枚举，而是使用 Common 的共享定义/Binding；`DemoPrimaryWriter` 在严格单笔、严格批次、本地异步回复成功前用共享 Binding 核对返回契约。
- Common 真实 Git 源代码仓库 `com.app.common`，分支 `saas-crypto`，**本地提交 `4058188`**（含 `[skip ci]`），只有两份生产包源码和两份 JUnit 测试。该 Git checkout 的 POM 为 `3.0.13-SNAPSHOT`，而隔离 Netty Pilot 的 Common 二进制仍是 `3.0.22-SNAPSHOT`；本轮**没有做 Maven 中央仓库发布、没有发布镜像，也没有把这个历史 checkout 冒充成已整合全部最新 Common HA 实现的版本**。

## 本地/真实隔离回归

- Java8 `javac` 编译通过；Common 实际源码 checkout 与 Pilot 均使用 JUnit4 新增 **9/9 测试 PASS**（未知/混淆模式、RPO错误分类、重复启动、并发创建不覆盖、已运行策略切换拒绝）。本地 Maven 可执行文件不可用，因此没有声称执行完整 Maven 测试套件。
- 保留原 T70 异步 ZK+WAL：按 `LOCAL_DURABLE_ASYNC` 模式恢复3ZK+2JVM，**30/30 次单笔本地持久 ACK**，59.536 WAL/秒，单笔 P95 159.983ms；使用原卷尝试改为严格模式，启动返回 `ACK_POLICY_CHANGE_REQUIRES_AUTHORIZED_EPOCH_CUTOVER`，退出码 1。
- 保留原 T70 严格旧卷：曾在备用A停止后留下旧的本地已fsync但未严格认证尾部；测试30次请求，**0/30收到成功ACK**，返回 `previous WAL tail not strictly ACK certified`。这是必须拒绝的安全条件，不能统计为新功能的可用性 PASS。

## 新隔离故障验收（关键剩余故障）

在全新 `otc-t71-strict` Compose 项目、三 ZooKeeper、两个真实 Common JVM 和新 WAL/ZK 数据卷上使用 `DEMO_V19_ACK_POLICY=STRICT_QUORUM`：

1. Fresh A 作为 Epoch1 Primary 正常启动，第一笔老路径客户端 ACK 标为 **`QUORUM_DURABLE_SINGLE_HOST_TEST`**、seq1，属于同 Mac 的旧试点测试认证，不等同正式生产物理跨主机故障域。
2. **SIGKILL A**，B 自动在 ZooKeeper 进入 Epoch2 `RECOVERING`。在 strict 固定策略下，不允许经 `AUTO_DEGRADED_LOCAL_DURABLE` 写入客户订单；真实 Netty APPEND 明确以 503 `STRICT_QUORUM_POLICY_REQUIRES_AUTHORIZED_MODE_CUTOVER` 拒绝，**未产生伪造的严格 ACK**。
3. A 恢复后，两独立 JVM 的 WAL seq1、`committedPrefixSha256=904c87320adbda91ac5d1584eabd1964758acf0fe89bf5daf02b562b9420f4ba` 和 state SHA `401a65dce05eae93d51b5ac2487d88968561335f1f9325982f536f5892a0f4ce` 完全一致；但 B 的严格 Cutover preflight 连续返回 `physical WAL or replayed business state mismatch`，A 报 `untrusted new owner image`，**没有拿到新 Epoch3 READY**。
4. 说明数据摘要相同不等于已取得旧主撤权、当前 Epoch 可信 Image、二份 Custody、ZK CAS 完整授权。严格策略目前还缺“**无客户降级 ACK 的恢复期内部 genesis/证书重组**”，须在此条件下自动 A/B 恢复并确保不丢已确认数据。**这是真正的下一步开发阻塞，不应再次通过允许 B 单副本给客户成功 ACK 来掩盖。**

## 下一步验收关口

1. 在 Common 中设计并实测 **严格持久模式下的安全新 Epoch 内部恢复/新证书建立**，恢复期间拒绝外部写入，备用重新上线后自动 2/2 READY；无须一个被客户确认的 epoch2 单副本写入作初始化前提。
2. 解决已有 WAL 存在未认证尾部时的恢复安装/隔离、幂等重试与最后一次确认水位一致性；不得自动清除或授权未证明 WAL。
3. 完成 `ACK_POLICY` **授权模式迁移**：独立证明旧主撤权 + 新 Epoch CAS + 写入者签发证明 + 权威 WAL 水位，不允许通过在线环境变量更改绕过严格认证。
4. 对真实 Order/Trade 状态机接入 Common ACK 接口、做故障中下单/撤单/撮合/资金及持仓权威对账。现阶段未做业务集成，也未上线。

## 环境与代码证据

源工程：`common-ha-netty-v19-control-cache`，隔离测试卷保留。两个相关隔离栈已停止；`dc-saas-*` 正式 Demo **24 个容器继续运行**。无 GitHub Actions、无推送、无正式 Demo 变更。
源码归档：`tests/patches/common-rf2-ack-policy-common-t71-20261024.tar.gz`，逐文件 SHA256：`tests/patches/common-rf2-ack-policy-common-t71-20261024.sha256`。
