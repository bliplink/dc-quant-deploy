# Trade Projection 事务隔离验收

日期：2026-09-29。源码：正确 ProjectionSvr 仓库本地提交 `0a8ccfeb5851d083d9137c73df539c2622153764`，分支 `feat/trade-config-projection`。未推送、未部署、未重启运行服务、未开展线上故障/压测。

## 本轮修复与证据

| 问题 | 修复 / 验证 |
| --- | --- |
| 原代码回滚失败后仍 `setAutoCommit(true)`，存在部分提交风险 | 只有确认 commit/rollback 后才重置并归还连接；不确定提交、回滚失败或重置失败丢弃 Druid 物理连接，普通 JDBC 使用 abort，不进行 auto-commit 转换 |
| 原代码只捕获 Exception | Error 也走回滚并保留原错误；清理错误附在原错误上。测试注入的是 AssertionError，不是真实 OOM |
| 并发重复消费初始化 watermark 时发生共享锁升级死锁 | 隔离 MySQL 已复现 `INSERT IGNORE` → `FOR UPDATE` 死锁；改为先获取排他锁的 upsert，最终同一代码连续 3 轮通过，每轮 8 次并发重复消费 |
| 数据库已提交但响应确认丢失 | 真实 commit 后注入确认丢失，完整归档/余额/watermark 已提交；重试按持久 watermark 去重，不把“接口报错”误判为必然未落账 |
| 非事务表或跨租户唯一键破坏原子性/更新归属 | 启动验证归档表，以及已开启物化切片的业务表：InnoDB、完整主键及每个唯一索引包含完整实体键。拒绝非事务表及 user-only 唯一键 |

单元测试：10 个类 / 48 个用例，0 failure/error/skip。最终版本真实 MySQL 8.0.36 演练：18 项 × 3 轮全部通过，包括事件/完整批次失败回滚、四表物化、重复/过期事件、epoch 衔接、十进制精度、非归属列保留、租户隔离和移除。完整机器可读汇总见 [证据](evidence/trade-projection-transaction-20260929.json)。

演练只有独立临时 MySQL：无宿主机端口、无外网、无生产配置或数据卷；数据库在 tmpfs。Java 测试只共享该临时容器的 loopback。入口拒绝任意 JDBC 地址和非空数据库；退出按 exact container ID + ownership label 清理。临时测试数据已删除，JSON 和依赖副本保留供核对，不属于业务数据清理。

复现入口位于 ProjectionSvr 仓库：`bash scripts/run-trade-projection-mysql-offline.sh`。它断网运行完整单元测试并把 Maven 实际依赖复制到唯一新目录，不复用可能残留多版本 JAR 的 `target/dependency`。`ensureSchema()` 仍有既有 CREATE/ALTER，**不可当作线上只读诊断调用**。

## 构建来源修正

最终 3 轮的 class/dependency SHA-256 一致。当前使用 common 3.0.14（SHA-256 `542d25a3c7345c2d25806fc7c975465e96ff21ac5151dd8c35f13520c006396c`）和 bridge（SHA-256 `8a22afe1bd404ca5a2613a189df9133025ebc77cca990f9a202cfcaccc899329`）。没有混入另一个 generic common 3.0.13-SNAPSHOT 恢复执行器构建。

核查旧 Projection 候选 `sha256:f3cf8b70...`，实际包含 common 3.0.13（`e92a09ea...`）及旧 bridge（`46421a3b...`）。因此撤回其作为当前验收镜像的资格；保留仅供历史比较，未删除/部署。新版本需从干净且来源核对过的依赖目录重新构建，再做完整镜像运行验证；没有在本轮生成“已验证可发布”的新镜像。

只读容器核查：Order A/B、Trade A/B、MD A/B/C、Projection 共 8 个容器仍沿用既有镜像，状态 running、restart=0、OOM=false。这里只证明进程状态，没有新增业务 API 探针、分区晋级或可写证明。

另用只读 `information_schema` 查询核对当前 MySQL 的上述四张业务表和三张 Trade 归档/watermark 表：7 张表均为 InnoDB，全部唯一索引包含所需完整实体键；event 表另有与主键同列的 `uk_trade_projection_seq`，不构成跨租户冲突。只读取表引擎/索引元数据，没有读取客户余额、调用 `ensureSchema()`、执行 DDL、回填或业务写入。该项通过仍不代表精度/collation/历史基线已验收。

## 不能因此宣布完成的内容

- 配置/余额/持仓物化开关仍默认关闭。启用前需历史投影重建、逐表对账、旧写入方退场，以及真实消费器重启/GAP 收敛验证。
- 本轮唯一键/引擎检查不是全量 schema 验收；精度、collation、升级兼容、后续 DDL 保护仍是独立门禁。
- 未覆盖 POSTING、funding 去重、保险/ADL 状态，未补写旧本地日志或从 SQL 制造权威事件；CashRequest 幂等键仍缺失。
- 未完成真实故障切换、Replica committed-prefix 证明、B 接管 A 全量容量、跨宿主机 HA、持续 TPS 或长稳。

下一步按 [底座计划](REUSABLE_CLUSTER_FOUNDATION_PLAN_20260929.zh-CN.md) 推进：先补核心提交中稳定的请求/流水身份与完整资金事件，建立可证明的本地历史基线和 Projection 重建；然后接入三服务恢复调度与隔离故障演练，门禁通过后再测交易 TPS。不能跳过这些步骤直接关闭 Trade SQL 或强制切主。
