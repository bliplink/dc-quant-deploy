# 2026-10-08 Mac mini / Colima 资源扩容记录

状态：**ZooKeeper、APSSvr、MySQL 三项 CPU 配额已在线生效，Docker/Java 进程均未重启；整台 Colima VM 扩容和 Order HA 15 秒会话参数上线尚未进行。**

## 环境
- Mac mini：10 核 CPU / 24 GiB 内存。Colima 0.10.3 使用 macOS Virtualization.Framework，Docker VM 8 CPU / 16 GiB RAM / 150 GiB disk。
- 50 个 enabled Robot，刷新间隔均 1000 ms，正常时 50 RUNNING / 2000 活动报价记录。RobotWorker 已按实际订单价格/数量匹配，不是每秒直接全量撤单。
- 原始故障：ZooKeeper 6 秒会话超时，10 月 8 日 17:12:18 OrderSvrB 与 17:27:55 OrderSvrA 分别发生 session expiry，引起自动 failover。

## 在线调整与验证
| 服务 | 旧 CPU | 现网新 CPU | 限流时间片比例（短窗口） |
|---|---:|---:|---:|
| ZooKeeper | 0.10 | **0.50** | 88.0% → 5.6%，复测约 8%～13% |
| APSSvr | 0.50 | **0.75** | 97.9% → 23.4% |
| MySQL | 0.50 | **0.75** | 28.6% → 7.4% |

每次先备份 Mac mini 私有部署 env，然后更新 ZOOKEEPER_CPU_LIMIT、APSSVR_CPU_LIMIT、MYSQL_CPU_LIMIT；执行 docker update --cpus 在线修改容器，不清库、不重启、不改 journal 或水位。私有 env 及其备份不得提交 GitHub。

部署仓库 saas-crypto 的 compose.yaml 和 .env.example 已同步默认值，tests/test-zookeeper-cpu-config.sh 与 GitHub Actions 配置 CI 验证其不会回退。CI 运行 ID 37768013034 通过。

19:08 验证：Order A/B/C、Trade A/B、ZooKeeper、MySQL、APSSvr、RobotSvr、ProjectionSvr、ClickHouse 全部 running，重启次数 0、OOMKilled=false，Robot 50/50 RUNNING / 2000 活动报价记录；最近 5 分钟 Order/ZooKeeper 未出现新的 session expiry 或自动 failover。这是短窗口采样，不代表长稳。

## 仍未解除的门禁
- 19:08 Docker VM CPU PSI some avg60 约 76%，MemAvailable 约 925836 KiB，SwapFree 约 52 KiB：**整体 VM 容量仍不足**，不得开展 200 租户测试。
- Order A/B/C 运行进程的 ZK session 仍是 6 秒，15 秒配置虽然写入部署 env 和仓库，尚未安全滚动上线。当前 Order HA preflight 在高压主机上 NO-GO。
- Trade Projection P232、Order Projection P054 历史一致性尚未修复，Tape 保持 OFF。
- 将 Colima 从 8 CPU / 16 GiB 提升到更大规格涉及整个 Docker VM 停机，必须先准备有序暂停交易、完整数据/副本/水位验收以及恢复计划；本轮**没有**停止或重启 Colima。

## 后续
持续观察 ZooKeeper 是否再有 Expired、Order failover、Robot 50/50、各服务 cgroup CPU nr_throttled/nr_periods 的增量、Docker VM CPU PSI、MemAvailable 和 SwapFree；在隔离测试通过后评估 ClickHouse 低噪日志方案及 Order 同步批量复制，再评估 Colima 受控扩容。

## 19:05、19:06、19:10 会话再次过期——资源缓解未解决 P0

19:02:45 之后（即 ZooKeeper CPU 0.10→0.50 已在线生效之后），ZooKeeper 仍明确记录三条 6000ms session expiry：

- 19:05:01.270：OrderSvrB session 过期，Order 控制器至少迁移 P042/P044。
- 19:06:57.270：OrderSvrA session 过期，Order 控制器发生约 9 次切主（P030–P038）。
- 19:10:59.267：OrderSvrB 再次过期，控制器发生约 6 次切主（P032/P034/P036/P038/P069/P071）。

共 3 次 session expiry、17 条 ORDER_AUTO_FAILOVER_APPLIED，Order A/B/C 进程未重启。19:09:58–19:10:49 机器人七次间隔采样均显示 50 RUNNING/2000 张报价，但紧接着 19:10:59 又发生故障切换。**不能把机器人间歇性 50/50 当作 HA 稳定验收。**

19:11 VM CPU PSI some avg60=71.73%、MemAvailable=871400 KiB、SwapFree=80 KiB、load avg 1m=22.48；Order A 内存约 2.665GiB/3GiB、B 约 2.55GiB/3GiB。ZooKeeper CPU 配额修复降低了自身 cgroup 限流，却不能消除高压宿主机及 Order 6 秒会话的故障窗口。

**发布门禁继续 NO-GO。** 下阶段主要 P0 为改善 Docker VM CPU/内存争用、制定受控维护（停交易/保留持久化状态）以完成 15 秒 Order 会话参数上线和 HA 权威一致性复核。当前不主动重建 Order、ClickHouse 或 Colima；Tape 及 200 租户仍关闭。
