# 2026-10-10 十租户 Robot 对 MDSvr 不必要依赖的修复及回归

## 故障根因核对

在十租户 MDSvrB Primary 故障注入时，四个市场曾出现盘口丢失、Robot 进入 `ERROR / RUNTIME_FAILURE`。研究 RobotSvr 源码发现：即使 `sweep_user_orders_enabled=false`，`RobotWorker.sweep()` 调用 `LiquiditySweepEngine.select(...)` **之前**，Java 仍然先求值 `repository.bestUserOrders()`；该调用会发出 `MDSvr/queryPublicMarket`。所以“关闭主动扫单”并没有真正移除 Robot 对 MD 的周期性依赖。实机数据库逐租户配置核对：**十个租户的 `sweep_user_orders_enabled` 均为 false**。

- 修复 [RobotSvr 6afbf32](https://github.com/bliplink/com.app.dc.robotsvr/commit/6afbf32dd49a55a9769c6e8bd62971605eccc531)：在 `RobotWorker.sweep()` **开头**检查功能开关，关闭时直接返回、绝不访问 MDSvr；开启时原有盘口过滤、最优价格检查、仓位/余额约束及真实扫单逻辑保持不变。**124/124 Maven 测试 PASS**，其中新增回归测试模拟 MD/交易客户端根本不存在，确认关闭扫单时仍不会触发查询，而开启扫单时不会错误绕过依赖。[GitHub Actions 38048164940](https://github.com/bliplink/com.app.dc.robotsvr/actions/runs/38048164940) SUCCESS，发布 ARM64 和 AMD64。
- 另已修复 [MDSvr 4181ec5](https://github.com/bliplink/com.app.dc.mdsvr/commit/4181ec527479be1b875dae905d4fefea4796db25)：旧 Primary 或市场快照尚未 Ready 的节点不能通过 `queryPublicMarket` 返回旧缓存报价；在深度增量模式禁用 Legacy 原始快照的 READY 旁路。**68/68 Maven 测试 PASS**，[GitHub Actions 38047866336](https://github.com/bliplink/com.app.dc.mdsvr/actions/runs/38047866336) SUCCESS。**此 MD 镜像仍未部署**，不构成主节点自动故障接管。

## RobotSvr 单服务发布

1. 以 CI 成功的不可变 SHA tag `ghcr.io/bliplink/robotsvr:sha-6afbf32dd49a55a9769c6e8bd62971605eccc531` 作为唯一目标；Mac Docker 是 `linux/arm64`。`docker pull` 最后阶段曾超时，未对正在运行的容器做任何操作；随后通过已安装的 `crane pull --platform linux/arm64` 经过本机代理取得完整 OCI/Docker 镜像并用 `docker load` 导入，验证 `linux/arm64` 与本地 image ID。
2. 先对比正在运行的 Robot Compose 配置 hash 与仓库生成配置：**完全一致**。保留旧 GHCR tag 镜像并在本机证据目录准备只针对 robotsvr 的单服务回滚命令，不携带 API Key 或密码。
3. 执行 `docker compose ... up -d --no-deps --pull never --force-recreate robotsvr`，**仅 RobotSvr** 创建新容器；不改 ZK 分区、不重启 OrderSvr A/B/C、TradeSvr A/B、MDSvr A/B/C、MySQL 或 ZooKeeper。
4. 部署后实机 `docker inspect`：RobotSvr 使用目标 SHA tag、`running=true`、无重启循环；MySQL 立即确认 **10/10 Robot RUNNING，400 笔挂单**。对比发布前保存的关键容器 `StartedAt` 列表，与发布后 **完全一致**，证明除 RobotSvr 以外的交易节点并未重新启动。
5. 发布后另开 **只读持续稳定性观察**：每隔 30s 检查十租户 TRIAL/DONE/COMPLETE、Robot RUNNING/40、BTCUSDT 公共盘口买卖至少十档、成交 ID 增长、Tape 持久化 postings、主节点错误信号、核心容器健康与磁盘水位。本观察结果以最后确认的 `summary.json` 为准。
6. 统一镜像发布锁 `release/saas-crypto-images.env` 的 `ROBOTSVR_TAG` 已设为新 SHA tag；旧镜像仍是有效回滚目标。当前运行环境原始 `.env` 文件如独立维护，后续操作者应通过统一锁或显式新 tag 部署，避免单纯不带新 tag 的 Compose 命令把 Robot 退回旧版。

## 风险及未完成

- 本轮只证明关闭扫单时 Robot 不再被 MDSvr 无效依赖牵连；**不代表 MD 自动故障切换已实现**。若用户开启主动扫单，Robot 仍需要从 MDSvr 获取盘口；且交易页自身仍依赖 MDSvr 实际 Primary。
- 当前 MD 分区 256/256 均只有一个指定 Replica，尚缺权威 source/durable watermark、完整 snapshot 追平证明、唯一领导者 CAS epoch 和旧主发布栅栏的跨节点验收。**禁止再次直接 SIGKILL MD/Order 主节点来宣称 HA 通过**。
- 磁盘使用率约 88%，不得因用户不需要 Demo 数据就随意删除 WAL/回滚归档证据。先完成高可用安全回归，再考虑隔离环境 clean rebuild。

## 本机审计文件

`~/.opentradingcore/evidence/ten-tenant-soak-20261010/after-robotsvr-6afbf32/`：版本变更后的只读观测日志与最终统计；父目录保留原 MD 故障前后证据及旧版 Robot 回滚脚本。**不上传本机凭据或订单会话信息。**

## 已完成的部署后连续稳定性验收结果

**正式结果 PASS**：自 RobotSvr `sha-6afbf32` 切换后单独运行 **302 秒、11/11 个有效采样、0 个错误采样，监控进程退出码 0**，10 个租户在每个采样点均满足 TRIAL/DONE/COMPLETE、10/10 Robot `RUNNING`、每个 40 笔合计 **400 笔挂单**、公开盘口至少十档买卖报价，磁盘 88%。单轮最慢市场查询延迟指标区间约 **8.7–20.0ms**，无订单分区恢复异常。

实际业务继续推进：**全部十租户最近成交 ID 均增长**；逐租户 Tape 持久化 Trade postings 增量分别为 `A7C924 +61`、`B7C924 +69`、`BU1AN0 +77`、`MZYMEX +77`、`NRZ5AE +80`、`R1GLNL +74`、`S0P0PZ +75`、`TLS5DL +81`、`U9DXN2 +72`、`YGW9OH +78`，总计 **+744 条**。这表明主站行情变化有与之对应的持久化执行流水推进。

再次比较 Order A/B/C、Trade A/B、MDSvr A/B/C、MySQL、ZooKeeper 的 Docker `StartedAt`：**10/10 完全未变化**。Robot 容器仍是预定 SHA、`running=true`、重启计数 0；三个 Order 节点最近六分钟未产生 `ORDER_PARTITION_RECOVERY_FAILED` 或 `PARTITION_NOT_READY`。

**限定结论**：本测试验证单服务新 Robot 版本在十租户正常运行场景下稳定，并验证已关闭扫单的 Robot 不会发起多余 MD 查询；不能证明主动 MD Primary SIGKILL 下业务连续可用，不能证明跨节点安全晋升，也不授权 25 租户扩容。MD HA P0 继续开放。
