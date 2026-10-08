# Projection Binary 批内水位：隔离 JDBC/MySQL 事务回归（2026-10-08）

**当前状态：Projection 真正源码仓库 `bliplink/com-app-dc-projectionsvr` `saas-crypto` 的 H2 + 真实隔离 MySQL 8.0 原始 5 项 JDBC 事务测试及 Maven/amd64/arm64 镜像构建均已通过（[GitHub Actions 37785116134](https://github.com/bliplink/com-app-dc-projectionsvr/actions/runs/37785116134)）。额外新增的提交前连接故障注入测试位于源码提交 `60f1e4a0e`，也已在 H2 与真实隔离 MySQL 8.0 验证通过（[GitHub Actions 37785622644](https://github.com/bliplink/com-app-dc-projectionsvr/actions/runs/37785622644)，包括双架构镜像推送）。之后补交了 Maven runtime-scope 依赖过滤和 CI 检查，以确保测试专用 H2 JDBC jar 不会复制进生产 Docker 镜像；最终发布验收需要以最新源码 commit `216582d34` 的 CI 为准。生产 Projection 未重启、未升级，`projection.order.binary.watermarkBatchOptimized` 默认 false。**

## 改造动机

上一轮只有 `OrderProjectionService.transition()` 的 5 个纯内存测试，不能作为事务提交、回滚或持久化投影正确性的证明。为同一个生产 JDBC 路径提取了仅包内可访问的 `applyWireBatchOnConnection(batch, connection)`。生产 `applyWireBatch` 仍从原数据库连接池获取连接、调用同一个方法，并在 finally 释放；事务仍由该方法统一 begin/commit/rollback。没有新增任何 bypass journal / ACK / watermark 的路径。

`pom.xml` 新增 `com.h2database:h2:2.2.224` **test scope**，不能成为生产 runtime 依赖。新增 `OrderProjectionJdbcTransactionTest`，每个测试创建独立 in-memory H2 数据库，开启 MySQL 兼容模式，生成事件/watermark/订单/成交测试表，分别在 `watermarkBatchOptimized=false/true` 下执行同一组用例：
- demo=1 时归档 committed event、推进 watermark，但在 `projection.saveDemo=false` 时不写订单/成交投影；demo=0 必须留下订单与成交；
- 同分区三个连续事件共享一次事务，正确保存最后事件 ID、水位；
- 完全重复回放不得追加记录、倒退 watermark；正确 epoch 切换需要前驱匹配；
- 第一个事件已执行 SQL、后续出现 sequence gap 时，整个事务回滚，事件、订单、成交和 watermark 保持原状；随后可重新补拉；
- 重复 event ID、跨 partition 的批次、错误的业务 payload 在写入中途发生错误时，全事务回滚。

**这些测试不能替代 MySQL/InnoDB 的锁语义验证。** 因此源码 CI 配置使用 GitHub Actions 私有 runner service `mysql:8.0`，在单独步骤设置 `PROJECTION_TEST_MYSQL_ROOT_URL=jdbc:mysql://127.0.0.1:3306/` 和非生产的临时测试密码，重复执行相同 5 项事务测试。测试 Java 代码强制 URL 必须指向回环地址，且每个用例创建唯一 DB；它不会读取 Mac mini 私有 env 或连接生产 MySQL。CI 完成后临时数据库和 runner 全部销毁。

新增一项**COMMIT 之前连接异常**故障注入：通过 JDBC Connection 包装器在应用发送 COMMIT 前抛出 SQLException，要求事务捕获异常后能够 rollback，且库中订单、成交、事件、水位均无残留。该测试不会模拟 COMMIT 已在 MySQL 成功、但响应在网络中丢失的“模糊提交”；后者仍需要事件 ID 幂等与灾难恢复单独验证。

部署安全补充：`pom.xml` 的 dependency-copy 插件现在显式设置 `<includeScope>runtime</includeScope>` 并排除 `h2`。源码 GitHub Actions `Verify build output` 对 `target/dependency/h2-*.jar` 做 hard-fail，防止测试 JDBC 驱动进入生产镜像。该变更不涉及交易逻辑和在线数据。

## 明确不能由此宣布的验收

- H2 成功不代表 MySQL 8.0 成功，须以完整 GitHub Actions 的 Test ProjectionSvr / isolated MySQL test / amd64 arm64 build push 全部 success 为准；
- 即使 MySQL 8.0 测试通过，也仍缺失并发 worker 冲突、MySQL 连接突然中断（commit 前/后）、慢事务及 500 条真实 payload 对照、P054/P232 现存 GAP 的权威恢复证明；
- 只验证模拟账户 `projection.saveDemo=false` 过滤，不可用该测试跳过客户资金流水或真实成交的提交；
- 在线 Production Projection 仍为旧镜像 `ghcr.io/bliplink/projectionsvr:sha-2d54c9d3234b948a8ed0a61e9b05c22b499d6f5a`；本轮未更新 Order/Trade/Robot 镜像、未重启 Colima、未修改生产水位。仍保持 `projection.order.binary.watermarkBatchOptimized=false`。

## 发布前后门禁

1. 报告并留存每次 CI 的 commit SHA、JDK8/H2、MySQL 8.0 事务测试、两个镜像平台结果。
2. 在隔离性能基线里比对优化开关 false/true 的每批 SQL statement 数、commit latency、500 条批次、watermark 和 order/exec/event 最终行，记录每个 batch 的分区与 epoch。
3. 独立回归真实 MySQL 并发 commit 争抢、重复事件 ID、连接中断、部分提交/断电及 fetch GAP，确保 fail-closed。
4. 将运行中的 Projection/Trade 与 committed CQ watermark 权威对齐，解决 P054/P232 既有缺口，不允许盲改数据库水位。
5. 进入安全维护窗口后新镜像先以优化关闭的方式部署、确认 50 Robot 与历史查询、HA、投影追平，再考虑按独立变更启用 flag=true。投影实时 buffer reset/GAP retry 必须持续观测并量化，禁止因速度提高而隐藏 gap。
