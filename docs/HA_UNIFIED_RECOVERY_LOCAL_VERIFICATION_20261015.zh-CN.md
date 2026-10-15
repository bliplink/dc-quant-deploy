# 2026-10-15 Common / Trade 可信恢复统一分支：Mac mini 离线验证证据

## 结论与权限边界

**本地完整 Java 8 测试已通过；生产 GHCR 发布与 HA 故障主切仍为 NO-GO。**

本轮将原本分散的两个独立 HA 变更集合收敛到有明确依赖的一条候选链：

- [Common Draft PR #24](https://github.com/bliplink/com.app.common/pull/24)，分支 `fix/common-certified-recovery-unified-20261015`，基于原本通过测试的完整原始 WAL 区间签名分支。
- [Trade Draft PR #25](https://github.com/bliplink/com.app.dc.tradesvr/pull/25)，分支 `fix/trade-certified-recovery-unified-20261015`，依赖上述 **同一版 Common**。

Common 现在在源端 HEAD/完整 Snapshot+WAL staging 上恢复了 `CertifiedRecoverySourceAuthority`：在 Trade 的持久化安装 **之前** 与完整回放 **之后**，重新从实际物理 Primary 验证 HEAD，重新查询当前 ZooKeeper 投票成员，并从独立的 Netty 物理副本分别获取带唯一节点密钥签名的完整 WAL 区间凭据。Common 统一所有投票、范围摘要、事务门禁，Trade 只提供 ZooKeeper 实际成员读取、业务分区隔离、Chronicle WAL 及状态机业务适配。

安全/性能补丁：Common 的 `RecoveryDurablePrefixControlHandler` 修改为仅接收目标物理节点、Service、分区、挑战、完整 Snapshot SHA、WAL from/head 范围全部经 HMAC 认证的请求。**请求必须先认证，才能触发文件同步或最多 64 MiB 的 WAL 读取**。新增正/负测试，伪造、损坏、跨分区、跨物理节点请求均不能触发源码扫描。控制接口仅属于内部 Netty，Gateway 不处理任何业务。

Trade 的 `TradeCertifiedRecoveryAssembly` 则在明确授权且全部依赖提供的情况下组装 Common 事务、当前真实 ZooKeeper 成员门禁、独立投票成员密钥、受保护的 Replica 分区业务锁、已验证的 Snapshot+WAL、真实 Chronicle 安装/持久日志。这并不自动开启恢复任务，也不发布 READY；外部财务/Projection/MD 验收仍是必要条件。

## 构建与测试：已执行、非推测

GitHub Actions 最新任务无法启动 Runner，官方 Checks 注释原文：

> The job was not started because recent account payments have failed or your spending limit needs to be increased. Please check the 'Billing & plans' section in your settings.

证据：[Common failed-to-start run 38663162155](https://github.com/bliplink/com.app.common/actions/runs/38663162155) 和 [Trade failed-to-start run 38663165554](https://github.com/bliplink/com.app.dc.tradesvr/actions/runs/38663165554)。两者 Job 均在约 3 秒内失败，Runner 为空且 `steps=[]`。**不代表编译测试失败**，但也不能算 CI 通过。应在 GitHub Billing & plans 核实付款/Actions 限额。

为完成独立验证，在 `~/.opentradingcore/ha-unified-validation-20261015/` 准备了完全独立的工作副本，不修改现网 Compose 工作区。Maven 3.9.16 从 Maven Central 下载并通过完整 SHA-512 校验，使用 Mac 原有 Azul Zulu Java 8；未安装大量 Homebrew/OpenJDK27 依赖。

| 测试项 | 本地实际结果 |
| --- | --- |
| Common Maven `test` | **282/282 PASS，BUILD SUCCESS** |
| Common `install -DskipTests` | **PASS，安装到本机 Maven cache，仅用于测试** |
| `com.app.dc` `install -DskipTests` | **PASS** |
| Trade Maven `clean test` | **271/271 PASS，BUILD SUCCESS** |
| Trade `package -DskipTests` | **PASS** |
| Trade `dependency:copy-dependencies` | **PASS** |
| 运行时 MySQL Connector/J | **只有 1 个 driver，版本 8.0.33** |

整合的 Common 首轮测试曾因一处测试引用仍使用旧字段 `Prefix.snapshotSeq` 而无法编译；已经修改为 v2 正确字段 `Prefix.fromExclusive`，提交在 Common PR #24，随后的 **282 项完整测试全部通过**。

Mac 上标准 Dockerfile 的首次构建因 Docker Daemon 无法解析 `registry-1.docker.io`，无法下载 `eclipse-temurin:8-jre`。这不是 Maven 代码失败。为进行**本地、非发布**验证，使用已缓存的 Temurin Java8 Trade 镜像作为底层，先清除原有 classes/lib/config 后完整复制新构建产物，并显式设置 `otc.validation-only=true` 标签：

- 离线验证镜像：`otc-trade-unified-offline:local`
- IMAGE ID：`sha256:b171cfac26d8c2029892cae0152a22f71f9fe579014f492e2757365621bdb784`
- Linux 架构：`arm64`，实际 Java 8 启动检查 PASS。
- `mysql-connector-j-8.0.33.jar` 存在，`TradeCertifiedRecoveryAssembly.class` 存在。
- **此镜像不能用于 GHCR 发布或正式生产部署**。它没有经过标准 `eclipse-temurin:8-jre` 新基础层构建及 amd64/arm64 跨平台正式验证。继续保留当前 Demo 镜像。

## 当前 Demo 只读验收（2026-10-15 09:12 CST）

- Docker SaaS 容器：**24/24 运行**。
- Robot：**11/11 RUNNING**，合计 **440 活动挂单**。较前一轮的 10 户有所增加，不应把旧版的 10 户数量视为当前状态。
- Projection `tests/projection_watermark_tail_gate.py`（索引 + 同一 MySQL 只读一致性快照）：Order **11**、Trade **11** 分区，`PROJECTION_DB_TAIL_MATCH`，exit 0。
- Mac Data 卷：**73% 使用率，118 GiB 可用**。
- Colima Swap：总量约 **3 GiB**，Free 约 **0.96 GiB**。
- `python3 tests/order_ha_rollout_gate.py --target OrderSvrA`：仍 **NO-GO**，且仅剩 `50/50 RUNNING` 和 `2000` 挂单两个负载阻塞项；此工具本身不代替新的 Common 可信恢复与外部 READY 验证。
- 全程不执行 SIGKILL、不改变 Gateway 业务、不清除现网数据/WAL、不替换当前 Docker 容器。

## 后续 NO-GO / 必做

1. 恢复 GitHub Actions Billing/Runner，再运行正式多平台 Java8、Docker 和 Maven Central/GHCR 发布流程（不能绕过真实 Runner/安全门禁）。
2. 实际 ZooKeeper 物理多节点与**独立节点密钥**正式配置，用与当前提交 HEAD 一致的原始完整 Snapshot+WAL 区间摘要验证真实法定人数；不能只凭单个 Primary 报告的本地水位或普通 ACK。
3. 开发/验证恢复后外部资金、持仓、挂单、委托、成交、Projection 水位/孤儿 mutation 的权威对账和 READY 开放门禁；还必须验证发生源端角色变化/网络分区时旧 Primary 被隔离。
4. MD 统一 Common Snapshot/Diff 的完整恢复及旧发布者隔离仍未完成全量验收。
5. 先满足真实 50 租户/2,000 挂单与机器资源基线，再执行 SIGKILL Order/Trade 当前 Primary 的真实 HA 故障注入、原节点恢复/追平/主备反转，最后进行 200 户压力测试。

**本记录是离线候选版本的测试证据，不是生产恢复已完成或 HA 已发布的证明。**
