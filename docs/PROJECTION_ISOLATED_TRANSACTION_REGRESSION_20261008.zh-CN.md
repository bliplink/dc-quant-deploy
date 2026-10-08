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

## 并发死锁与 500 事件批次补充（2026-10-08）

- **CI 修复**：Projection 的 Maven lifecycle `package` 阶段已经自动执行 runtime-only 依赖拷贝，但构建脚本重复在命令行执行 `dependency:copy-dependencies`，使 test-scoped H2 再次进入 `target/dependency`。CI [37786099144](https://github.com/bliplink/com-app-dc-projectionsvr/actions/runs/37786099144) 因防护检查报错，是有效阻断；已删除重复 CLI invocation，改用 `mvn clean package -DskipTests`，保留 `h2-*.jar` fail-closed 检查，[CI 37788211405](https://github.com/bliplink/com-app-dc-projectionsvr/actions/runs/37788211405) 已全部成功。
- **独立 InnoDB 竞争测试发现真实 1213**：两个并发写入者在同一分区同一 committed event 上并行插入/锁定水位时，可能出现 `MySQLTransactionRollbackException: Deadlock found when trying to get lock; try restarting transaction`。最初测试错误地要求两个调用都立即返回成功，CI [37788374502](https://github.com/bliplink/com-app-dc-projectionsvr/actions/runs/37788374502) 暴露此问题；生产 BinaryConsumer 的 live batch 失败会转入 GAP_RECOVERING，从权威 journal watermark 补拉；隔离测试现采用**仅对 1213/SQLState 40001 有界重投递**验证原子回滚后的幂等结果，其他 SQL 错误仍 fail-closed，绝不跳过事务锁/降低隔离级别。后续仍需验证生产 GAP 重试节流，不得认为死锁已从服务器端消除。
- **模糊 COMMIT 响应**：新增 JDBC 代理在数据库 COMMIT 实际成功之后模拟响应丢失。客户端虽收到 SQLException，再投递同一批次时按已持久化 watermark 返回，无重复 `dc_order_projection_event`、`dc_orders`、`dc_orders_execorders`，且不倒退 watermark。此测试与 COMMIT 前异常回滚互补。
- **500 条真实 JDBC/SQL 批次**：`OrderProjectionJdbcTransactionTest.maxBatchOf500EventsPersistsWatermarkAndEveryEvent` 在 H2 和隔离 MySQL 8.0 的旧版/优化版分别完成测试；对 500 条事件里 50 条非 Demo 订单和 25 条成交检查最终库行、回放幂等及 watermark。通过 JDBC `prepareStatement` 实际计数验证 watermark 相关 SQL **旧版 1500 次，新版 3 次**。在 [CI 37788752951](https://github.com/bliplink/com-app-dc-projectionsvr/actions/runs/37788752951) 中，单轮隔离 MySQL 的批次耗时 **legacy 1079ms、optimized 280ms**（约降低 74%），H2 相应 **500ms/28ms**；数值是**单次不含生产负载的样本**，不能视为现网 p95/TPS 提升。该次 CI 的并发断言因上述正常 InnoDB deadlock 而失败，已专门调整重试测试。
- 包含新竞争重投递、模糊 COMMIT 和 500 条批次 SQL 计数的最新 Projection 源码提交 `623bd68ca`、[CI 37789104203](https://github.com/bliplink/com-app-dc-projectionsvr/actions/runs/37789104203)：JDK8/H2 与隔离 MySQL 8.0 测试步骤**均已通过**，后续镜像构建最终结果须查 Actions。优化开关 **`projection.order.binary.watermarkBatchOptimized=false` 默认关闭**；现网仍为旧 Projection 镜像，未启动安全上线窗口。

**剩余门禁**：真实环境 MySQL 并发冲突频率与 GAP backoff、断电后自动恢复、多个分区并行吞吐、500条 *多轮*负载统计、Order P054/Trade P232 历史 GAP 一致性，以及 Robot 50租户长时间稳定性。未经这些检查不得启用优化开关或启动 200 租户压测。

### CI 37789104203 最终发布验证

- 真正源码仓库 `bliplink/com-app-dc-projectionsvr` 分支 `saas-crypto` commit **`623bd68caccb823a61fbfa0a37f1ce80d5b71aea`**，完整 [GitHub Actions 37789104203](https://github.com/bliplink/com-app-dc-projectionsvr/actions/runs/37789104203) **success**。JDK8 Maven 测试、隔离 MySQL 8.0 重试与事务测试、生产依赖检查、amd64/arm64 buildx 推送均通过。
- 镜像 `ghcr.io/bliplink/projectionsvr:sha-623bd68`，不可变多架构 manifest digest `sha256:3dce230a0c39139fef45e32a5b563684edc63db1452802b5f62aa0fe7bfa88aa`。**仅表示 GHCR 已发布，不代表线上部署。**
- 此次成功 CI 的 500 事件独立 MySQL 8.0 同环境样本：legacy watermark SQL **1500** 次、耗时 **627ms**；opt-in batch watermark SQL **3** 次、耗时 **160ms**，单批耗时下降约 **74.5%**；H2 同次 270ms / 27ms。都是单次样本，不能等同生产 TPS、p95 或真实账本一致性。
- 该 CI 还覆盖 COMMIT 真正成功但应用层 ACK 丢失的重复回放，以及同一 partition 并发 duplicate-writer 遭遇 MySQL deadlock 后有界（仅 error 1213/SQLState 40001）重投递。事务保证事件行、订单/执行持久化和 watermark 全部最终唯一且匹配。生产 BinaryConsumer 的异常会转为 GAP_RECOVERING 回补，但**尚未验证真实生产负载下 deadlock 频率与恢复时延**。
- `projection.order.binary.watermarkBatchOptimized=false` 保持默认关闭，禁止将 GHCR 新版构建成功视为已上线或已完成 Order HA / P054/P232 历史一致性验收。
