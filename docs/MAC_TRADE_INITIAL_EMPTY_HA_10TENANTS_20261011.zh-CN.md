# Mac Demo Trade 初始空分区 HA + 十租户阶段验收（2026-10-11）

## 实际源码及部署状态

- Trade 空分区恢复：`a8fc334`（只对初始 Epoch=1、可校验的持久化空 Snapshot、journal/commit watermark 全 0 启用严格的零业务提交证明；已有提交、缺快照、脏尾、后续 Epoch、降级 health 均不得使用该证明）。Trade 源码原始基线 `0ad5191`；在独立 worktree 编译，250/250 Maven 测试通过。
- 两个 Trade 服务已针对性滚动部署 `dc-saas/tradesvr:cluster-dev-local-tradeempty-a8fc334-20261011`，其内置 Common SHA256 `45ea321a89b44639310f6dd10ac043df144b2be05e8d8c087c0ccba2c01ea6c7` 与目前其余核心镜像一致。只替换 Trade A/B，未迁移/清空 MySQL 或其他服务镜像。环境仍在 `~/.opentradingcore/dc-saas-runtime-zkfix-20261011`。
- 验证中同时发现 Trade 的自动故障元数据从旧版本 `protocolVersion=0` 自动提升后仍保留 0，会妨碍后续 v3 角色反转；新增 `36707b7`，令后续旧分区提升时在**同一次 ZooKeeper CAS** 中规范化协议版本 3（并设置缺失的 `trade-ab` nodePool），保留 Epoch 和数据保护检查。
- Trade 远端 `saas-crypto` 在验证期间已前进至 `1e0c959`，为避免覆盖新的 Recovery/Snapshot 修复，以上两笔提交已从最新分支干净 cherry-pick 为 `94f4b4e` 和 `aa26d0d`；全部 **228/228** 最新基线单测通过，GitHub `saas-crypto` 正常快进到 `aa26d0d`。**当前运行中的镜像仍是 `a8fc334`，不含额外规范化修复，也不含上游较新的代码**。正式 GHCR/Central 均未因此轮修改而手动发布。

## 空分区真实故障结果

- 空分区 P010：故障前 A Primary、B hot replica、Epoch=1、READY；B 持有真实空 Snapshot（snapshotSeq=0、committedStateSeq=0、committedStateEpoch=0，列表为空）。
- 真实 `SIGKILL dc-saas-tradesvr` 发生在 UTC 09:41:01；B 自动选主并恢复至 Epoch=2 / READY，记录时间 UTC 09:42:21（约 **79.7 秒**，含整个 A 故障所触发的多分区恢复压力）。没有直接修改 ZK 分区。
- 证据：`~/.opentradingcore/local-trade-empty-proof-20261011/artifacts/trade-empty-p010-20261011T094101Z.json`，状态 `PASS_EMPTY_INITIAL_PARTITION_AUTO_TAKEOVER`。
- Trade A 已启动、`unless-stopped` 重启策略恢复，A/B 均无 OOM；24 个 dc-saas 容器仍在运行。Order/Trade Projection watermark-tail mismatch 均为 0，orphan trade mutation 为 0，cross-partition event ID 为 0。
- 历史初始分区原 ZK 数据不带 v3 标志，故本轮提升后的 P010 `protocolVersion=0`；最新源代码 `aa26d0d` 能阻止**未来**新提升继续产生此差异，但不会自动篡改已存在的运行数据。现有旧元数据若需重新角色反转，必须先进行独立的 CAS 受控兼容性升级，不能跳过验证。

## 十租户验收

- 原有 4 个租户：`DNMA1P`、`FT9B21`、`OET72U`、`Y0ZJ1J`。
- 新建 6 个：`V6L43Q`、`CZUURC`、`TWLYHK`、`EGZ6T7`、`UQBUBL`、`UNV4GJ`。
- 第 5～10 个均通过完整 E2E：申请、自动审批、Robot 20 买+20 卖、盘口、入金、IOC 成交并核对真实执行记录、持仓、Reduce-Only 平仓、活动委托清零、Robot 补单；无 DB 直接篡改业务数据。
- `tests/check-demo-tenants-readonly.py` 的全量巡检 **PASS_10_TENANT_SNAPSHOT**：10/10 Robot RUNNING、每个 40 单，公开盘口各 10 买/10 卖档，报价未交叉。
- Readiness gate `tests/check-tenant-ramp-readiness.py` 结果：`BASELINE_READY_ONLY`，`nextRampAuthorized=false`，未发现禁入原因；最近五分钟 419 条市场成交记录，**不能等同 Order TPS**，10 租户均有活动。CPU PSI avg10=19.17%，Order B 内存 22.81%，Robot CPU 配额 0.2 核、当前配额利用约 47.9%，Order B 三秒内 FullGC=0。
- 租户 E2E 证据：`~/.opentradingcore/local-trade-empty-proof-20261011/artifacts/tenant-ramp/e2e-{05..10}.log`；全量盘面 `ten-tenant-audit.json`；准入门禁 `next-ramp-gate.json`。
- 连续观察证据目录：`~/.opentradingcore/local-trade-empty-proof-20261011/artifacts/tenant-ramp/soak/`。连续巡检是在**同一运行集群**上进行，没有重启服务以掩盖不健康状态。
- **连续观察已经完成**：UTC 09:54:08 至 09:59:00，10 次巡检均返回 `PASS_10_TENANT_SNAPSHOT`（每次检查全部 10 租户 Robot 40 单及 10 买/10 卖盘口），任务退出码 0；最终再次检查 Projection，Trade/Order watermark-tail mismatch=0（均有 10 个水位行），Trade orphan mutation=0，cross-partition event IDs=0。不能把约五分钟的巡检视为 24 小时稳定性证明。
- 十次采样 CPU 波动：Robot Docker CPU 5.25%～8.79%，Order B 14.84%～47.42%，Trade A 1.28%～5.51%、Trade B 3.35%～8.56%。这是 docker stats 瞬时快照，不等于长期分位数或真实订单 TPS。

## Archive / Catch-up 核验

- 在最新 Trade 源码 `aa26d0d` 基线上专门运行 `TradePartitionJournalRebaseTest`（6 项）与 `TradeReplicationManagerArchiveCatchupTest`（1 项），**7/7 PASS**；测试覆盖已归档日志 + 活动 CQ 顺序回放以及短/长范围追平，纯 Java 临时目录中执行。
- Mac 当前 Trade A 的 live `.archive` 只读盘点发现 **12 个 archive 目录、12 个 CQ4 段，文件长度合计约 960 MiB**，集中于 P023、P160、P201、P246；Trade B `.archive` 本次盘点 0 个。部分分区存在多个同一提交边界的归档目录，说明需要核对重基线/滚动重启产生的归档占用与安全保留策略。
- **这不是 live Archive Catch-up 端到端 PASS**：上述实盘记录只能证明保留了归档文件，不能证明新副本跨归档边界重放所有事件。不能直接删除归档或把本机零缺口视为证明。待独立故障注入检验哈希、边界追平、Projection 水位和旧 Epoch 归档管理。

## 尚未完成（不得以此报告宣布生产 HA / 200 租户能力）

- Trade 在真实持仓/空分区上的 SIGKILL 已通过代表性故障，但未做 256 个 Trade 分区逐一故障注入、跨分区逐笔零丢单/零重复成交审计。
- P010 空分区自动接管约 80 秒，仍需优化批量恢复速度与初始健康证明的放大负担；主分区可能高度集中于 B，长期压测前需负载再平衡。
- `TradeReplicationManagerArchiveCatchupTest` 本地 JVM 集成测试通过（archive + active CQ、长/短追平路径），但是本次生产形态的 Mac 运行尚无跨归档边界的真实恢复证据；日志归档删除与安全保留周期仍需单独验收。
- 10 租户并不等于 200 租户容量。机器人 CPU 配额偏紧，不应直接以 20 倍线程数/Robot 数放大上线；分批扩容必须独立测真实订单 TPS、响应延迟、GC、磁盘 IO、CPU PSI、恢复耗时及队列滞后。
