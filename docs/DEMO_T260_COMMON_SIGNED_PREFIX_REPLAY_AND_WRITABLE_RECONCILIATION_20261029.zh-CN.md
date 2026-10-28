# T259–T260｜Common 业务无关的认证 WAL 前缀恢复与剩余门禁（2026-10-29）

## 真实结果

- T259 源码提交 `4e35e58`：`CommonFileBusinessWal` 只读历史认证前缀允许物理文件保留未认证尾部。它对原始字节重新计算 SHA256，**不修改、不删除**尾部，不能成为新的写入 ACK。
- T260 源码提交 `83f1601`：`CommonCertifiedE2ReplicaHistory` 冷恢复不再要求 `certified.seq == physicalLastSeq`，而使用 `certified.seq <= physicalLastSeq`，仍须检查两个独立 RSA 签名、证书成员和认证前缀。
- 使用新编译 Common 的 JUnit：**14/14 PASS**，包括本地 RSA 2048 双独立签名、双签名 HEAD 只含 2 条但磁盘有 3 条、连续窗重放、伪造 SHA 拒绝、可写旧纪元拒绝脏尾。
- 两处**真实 Demo 原始 WAL 数据**经只读副本 Java 实测：Order P045/B 的认证头为 `9303`，物理尾 `9304`；Order P180/A 的认证头 `21563`，物理尾 `21564`。新 Reader 只读取认证前缀，且所有原始 WAL SHA 在测试前后不变。
- T260 Order/Trade 镜像已使用统一 Common SHA256 `9d5a7944c25981245fe80d5df15d4287331e9e914392124e82dcec51d14dd401`，完整保留先前 T258 Order PostOnly Maker 业务代码与 T255 认证业务开关。
- 真实只替换 Order A 后，**仍不 READY**：先前的历史数据检查已通过，但构造可写 `CommonCertifiedPartitionRuntime` 时 `DurableWalCertificateCustody.highestVerified` 调用 `CommonFileBusinessWal.requireFsyncedPrefix` 拒绝本地额外一条 WAL：`Common physically fsynced WAL head mismatch`。
- Order A 的容器已停止以避免重启循环。Robot 仍停止；Order B、Trade A/B 保留运行。Tape 最近成交与 A/B 自动互切仍 **NO-GO**。

## 下一个必须真正完成的机制

`readCertifiedWindow` 与 `CommonCertifiedE2ReplicaHistory` 已只读安全。**不能把可写 `requireFsyncedPrefix` 放宽到“小于物理尾”**，否则旧纪元 WAL 可能从未经认证的 seq 继续写，破坏原签名提交点。

下一关是在 Common **可写 Primary/Replica 初始化之前**实现认证恢复事务：

1. 先确认本机原始 WAL 没有在被另一个进程写入；认证 ZK Epoch/撤权和两独立节点的签名 CommitIndex、Custody 与 Receipt Ledger。
2. 保留原始全量 WAL 及未经提交的尾部作为只读证据，记录 SHA256、认证提交头和原路径；恢复事务必须支持崩溃重启续行，不能无记录地截断/覆盖。
3. 从**已验证的唯一认证前缀**构建新的可写 WAL 视图或新 Epoch WAL 文件，并原子安装、fsync。新可写对象的序号/签名水位必须完全对应认证 HEAD。
4. 重新通过 Common 双节点授予、业务状态机恢复和物理 writer、TCP 复制及真实 ACK 检查，才可以对外 READY。
5. 检查 B 恢复到 A 再次失效的连续自动互切，接着恢复 Robot/Tape 真实成交、Trade 资金持仓与 MD 公开 recentTrades。

**Common 对业务内容完全不透明：上述工作不得增加或识别 GTC/IOC/PO、下单、资金、持仓事件类别。** Order/Trade 继续各自拥有状态机和业务验证。

## 可复现补丁

- `tests/patches/t260-common-signed-prefix-recovery.patch` 为从已提交的 Common 代码生成的两次 commit 补丁，无密钥。
- Common 工作区：`/Users/kong/.opentradingcore/t177-common-saas-crypto-integration-20261027`，提交 `4e35e58` 和 `83f1601`。
- Demo Compose 覆盖文件：`compose.t260-e2-signed-prefix.yaml`，当前 **仅 Order A 试启动失败后停止**，未完整滚动四个服务。

### 不得误报
T260 的 14 项测试及真实 read-only 前缀检查 **不代表**可写自动恢复、成功成交、两节点自动互切或业务一致性达标。