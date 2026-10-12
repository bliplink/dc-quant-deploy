# Mac Demo：Trade 自动温缓存 Epoch 边界修复与离线镜像验证（2026-10-13）

## 结果（实际执行）

Trade 仓库：`bliplink/com.app.dc.tradesvr`，验证分支
`codex/trade-safe-wal-archive-canary-20261012`。

- 代码提交 `16bca98ec5b08f931182d6db8a25256cbd781504`：
  `TradeReplicaWarmSnapshotScheduler.isReplicaSnapshotUpToDate`
  只有在本地完整 Snapshot 与可信 Manifest 的 **epoch 相同**
  且本地序号不低于源端时才跳过温缓存。
  旧 Epoch、未来 Epoch、无效 Epoch 不会被序号比较误判为已同步。
  该判断不是业务 READY 或 Replica 可接管授权。
- 测试提交 `3ed6e973f3434ae6af49b4d0a9900b01798704e1`：
  覆盖同 Epoch、跨 Epoch、空快照、无效序号。
- Mac mini 将最新 GitHub 分支通过本地代理拉到独立检出目录。
  使用 `maven:3.8.8-eclipse-temurin-8` Docker Java 8
  以及本机隔离 Maven 依赖链编译，专项 **5/5 PASS**，
  完整 `mvn -o clean test` **294/294 PASS**，0 失败/错误/跳过。
- **重要构建边界**：仅检出目录的 `pom.xml` 本地替换
  `com.app.dc` 依赖成
  `0.0.4-dev6b8fe7d20261012-SNAPSHOT`；
  Trade GitHub 原始 POM 仍引用 `0.0.4-SNAPSHOT`。
  Common 本地验证版本为
  `3.0.17-dev6b8fe7d20261012-SNAPSHOT`，
  JAR SHA256：
  `34a6ee05db748eb2990f68b1dc86188a41ca52c320e1838b9cd82fd3c77a0363`。
  **不能把本地测试视为 Maven Central/GHCR 的可重现正式构建**。

## 本地候选镜像

初次依照 Trade Dockerfile 构建时，访问 Docker Hub
`eclipse-temurin:8-jre` 超时。改为以本机**已缓存**的旧 Trade
Java 8 镜像为运行基础，用临时本地 Dockerfile 先清除
旧 `/srv/dc/dc/TradeSvr/{classes,lib}`，然后完整覆盖
`target/classes` 与 `target/dependency`。
没有修改正式 Dockerfile，也没有引入 TLS。

- 候选标签：
  `dc-saas/tradesvr:cluster-dev-local-c6b8fe7d-20261013-epochwarm-3ed6e97`
- image ID：
  `sha256:0e84c7c60e8d0bd859147e4a7a3b43777693e1354b7fee79a95312ca1e35ae4c`
- 架构 `linux/arm64`，JRE 为 `Temurin 1.8.0_392`。
- 镜像 `dc.source.revision` 和 Common SHA256 labels 均核对；
  通过隔离容器实际检查类文件、Common JAR 的 SHA256 和 Java 版本。
- **只构建/静态核验，尚未替换正在运行的 Trade A/B，也未发布 GHCR**。

## 上线门禁与未完成项

当前 Mac Demo 的 256/256 Trade ZK assignment 只读读取完成，
但 **Trade A/B 均不具备安全滚动重启授权**：
A→B 快照预检 4 个异常，B→A 7 个。
最新版认证恢复功能虽然已有通过的 Netty 端到端单元/集成测试，
在现有 10 租户进程上仍未启用自动温缓存，因此不得将单元测试
等价为真实持仓 SIGKILL、role reversal、日志追平的在线证明。

Projection 数据库内部水位/事件表最新审计通过
（Order 10、Trade 10）；和**权威业务 WAL** 的头部水位
仍需要独立对账。此前只读孤儿 mutation 审计
10,000 条、0 orphan，但只是一段未封存 live 范围，
不构成全量一致性证明。

WAL 自动物理归档、隔离删除仍须等待
Snapshot/Replica/Projection 消费水位、48 小时保留期、
所有 Chronicle Reader generation 已释放以及 durable seal ledger
一致性全部成立。当前删除授权 0，故 **GC 继续关闭**。

下一轮安全执行顺序：
先在隔离/受控新部署中让新 Trade 镜像带签名 Snapshot/WAL
温缓存开启，并证明可恢复 Replica，再测试带持仓切换、
恢复节点和反向切换；完成 Order/Trade/MD 和 Projection 权威
一致性证明后方可上线定期轮转及 GC。该顺序不修改 Gateway
纯透传，不启用 TLS，不削弱同步 ACK。Demo 数据可在受控
重建时清空，但不能以数据删除替代恢复机制验证。
