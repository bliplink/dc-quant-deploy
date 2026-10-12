# Mac Robot Tape 精度修复与十租户性能恢复（2026-10-12）

## 现场问题

完整 HA 冷部署后 10/10 租户、各 40 笔 Robot 委托与双边
十档盘口一直健康。但运行约一小时后，Robot 只有 0.75
CPU，资源门禁反复报告 CPU PSI 约 55%，Robot 配额
使用率超过 100%。原 RobotSvr.log 在约一小时中增长至
270MB 以上；深入检查发现约 3181 条
`RobotSvr tape diagnostic` 消耗约 **262MB**，
最长单行约 **183,503 字符**。

源码追踪：`TradeReplayEngine.capBacklog()` 用
18 位小数比例反复乘 `pendingBuyNotional` 和
`pendingSellNotional`，每轮没有精度上限；随着 1000 条
行情一批进入引擎，BigDecimal 小数精度逐轮增加。
诊断代码使用 `stripTrailingZeros().toPlainString()`
输出这些异常长小数，引发字符串转换和日志写入负载。

## 开发和测试

原仓库 `bliplink/com.app.dc.robotsvr`，独立分支
`codex/robot-tape-bounded-scale-20261012`，
提交 `1a4aaae028a5dd01a57a4f9bcccbead69d8f123c`：

- 在 Tape 回放金额加有界小数 scale=16，
  对 ingest、backlog 按比例裁剪、减去消费金额、
  droppedNotional 合计都施加精度上限。
  精度约束只针对 **模拟 Tape 计算内部状态**，
  不修改真实持仓、撮合或用户订单的精度协议。
- 诊断日志中待成交和丢弃金额以四位小数输出，
  不再序列化无界字符串。
- 新增 5,000 次循环的多方向模拟 Tape 事件测试，
  验证金额不超过容量上限、精度不继续增长、
  买卖方向的 pending 数量保持有界，最终仍可成交。
- Java8 Maven 全量 **125/125 单元测试 PASS**。

源代码已经 push 到上述分支。原 Dockerfile 依赖的
`eclipse-temurin:8-jre` 在 Mac Docker 缓存中缺失，
联网 Docker Hub 超时；为了不改变运行基础系统，改用
**缓存中的原 GHCR Robot 镜像为离线 base**，
只覆盖完整测试的新 `target/classes`，
保留原运行入口、Java8 和其依赖：

`dc-saas/robotsvr:cluster-dev-local-robot-tape-precision-1a4aaae-20261012`

**仅 Mac Demo 本地镜像，还未通过 GitHub Actions 构建
正式 GHCR ARM64/amd64 多架构镜像。**

## 真实替换与回滚

只替换 `dc-saas-robotsvr` 一台容器；
Order A/B/C、Trade A/B、MD A/B/C、Gateway、MySQL、
ZooKeeper 均不重启。

私有文件：
`~/.opentradingcore/local-ha-clean-20261012-v1/`

- `robot-bounded-precision-overlay.yaml`：候选镜像；
- `robot-rollback-overlay.yaml`：旧
  `ghcr.io/bliplink/robotsvr:sha-6afbf32dd49a55a9769c6e8bd62971605eccc531`；
- `fresh-release.env` 和 `fresh-images.env`：
  新不可变镜像锁已更新，**这两份包含私有环境细节，
  不提交 Git**；
- `robots-after-tape-precision-rollout.json` 和
  `tenant-ramp-after-robot-decimal-fix.json`：
  实际只读验证数据。

候选容器重建一次，先两次租户审计未 Ready，
第三次恢复，最终
`PASS_10_TENANT_SNAPSHOT`：10 户 Robot
`RUNNING`、各 40 活动委托、十档盘口。
新容器 Running、RestartCount=0、OOM=false。

新日志最后 15 条 Tape diagnostic
**单条 245–249 字符**，原版本可增长到
**超过 18 万字符**。没有删除旧业务 WAL 或日志历史。

## 调整后运行指标

新镜像上线后只读
`tests/check-tenant-ramp-readiness.py`：

- `gate=BASELINE_READY_ONLY`，`reasons=[]`；
- **CPU PSI some.avg10=6.65%**，
  修复前实测约 54.89%（不同采样时刻，不是标准化压测）；
- Robot CPU quota=0.75 核，
  使用率约 **30.91%**，修复前约 103.89%；
- `tenantLocations=10`，
  `inactiveTenants=[]`，没有不健康 Robot；
- Order B 3 秒 full GC=0，
  未观测最近180秒分区恢复信号；
- 5分钟 market trade 282条，
  **这些 ClickHouse 行数不是权威订单 TPS**。

`nextRampAuthorized=false`：
**不可把此检查当成 50/100/200 租户扩容许可，
仍需分批增长与真实成交/资金一致性测试。**

WAL 自动删除继续关闭，Trade SIGKILL 和 MD
自动主切尚未完成真实有持仓注入验收，Gateway
业务透传始终未改动。
