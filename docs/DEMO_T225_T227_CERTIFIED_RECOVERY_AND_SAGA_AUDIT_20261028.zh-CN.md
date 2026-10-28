# OpenTradingCore T225–T227｜Common 4096 帧修复、Demo 恢复和跨服务认证一致性门禁

日期：2026-10-28（Mac Asia/Shanghai CST）。工作区：saas-crypto；仅 Mac 本地编译镜像，未使用 GitHub Actions。此文件记录**已执行**与**尚未通过**的客观证据，不是 HA GO。

## 1. 原因及共同修复

- 原版 Common `CommonCertifiedPartitionRuntime.pollCertifiedReplicaApply()` 使用 `readCertifiedFrames(...,4096,64MiB)`，且 `CommonFileBusinessWal` 检查 signedHeadSeq <= maxSlots。Order P119 超过 4096 帧后触发永久副本 Apply fence，并引发全部 Robot 报错。
- Common 源码：`/Users/kong/.opentradingcore/common-batch-official-release-20261013/common`，该工作树的 target/classes 与部署 JAR 关键类 SHA256 一致，不是过时 t177 源文件。
- Common saas-crypto `d2f98a1`：追加经完整 RSA/Custody Head 约束的有界增量 WAL 窗口、CRC 校验、连续 Apply 游标，每次最多 256 帧；没有改动旧严格双物理 ACK 规则。
- Common saas-crypto `6d3a117`：冷启动 `CommonCertifiedE2ReplicaHistory` 也改为 256 帧认证窗口遍历，仍要求双 RSA、精确 Head 和总 64MiB 安全上限；超过内存上限仍 fail-closed 等待可信 Snapshot。4105 帧双 RSA 实际签名恢复实验及 Common 33/33 相关 JUnit PASS。
- Trade saas-crypto `f2daf04`：去除 Trade 业务冷回放自身的 4096 条错误门槛，保留 epoch/序号/全量完整性；Java 全量编译及相关 14/14 PASS。**这笔 Trade 业务源码改动未叠入本轮镜像**，只替换 Common JAR；当前 Trade 最长分区冷回放小于此门槛。
- 统一 Common JAR SHA256：`8198a926c39859f359ddd13f7e6f15cb926ff13b228e592871ab04a36be855cd`，Order/Trade T225 镜像内验证一致。对打包 JAR 重跑相关 10/10 JUnit PASS。

## 2. 原始认证故障取证及人工安全恢复

- Order P119：旧状态 B 4105 帧、A 4104，B 仅 1..4104 commit index，双方 Custody 相同（4104）。脚本 `tests/t225_recover_order_p119_signed_tail_host.py` 校验两节点退出、ZK 两租约消失、epoch2 原始分配、255 个其它分区无 WAL 差异、CRC、提交区间及两份物理证据；分别封存两次未认证尾部：
  - `/Users/kong/.opentradingcore/order-ha-forensics/T225-P119-20261028-124032`
  - `/Users/kong/.opentradingcore/order-ha-forensics/T225-P119-20261028-124324`
- 恢复后 Order B 活动 WAL 回到 A 的可信 4104 帧前缀。先启动 Order A、确认 READY，再启动 B、最后启动 Robot，避免未有副本时 Netty 复制失败永久 poison Writer。真实新订单将 P119 增长到 4122 以上并保持 A/B 字节相同。两节点均运行 `local/otc-t225-ordersvr:certified-common-window`。
- Trade P178：A/B WAL 各1251 帧，但**双方持久化的双 Custody 回执账本均只到1250**；A 单独本地 Custody / CommitIndex 到1251不等于双 Custody 完成，不能向客户端 ACK。脚本 `tests/t226_recover_trade_p178_quorum_1250_host.py` 只在 A/B 都退出、ZK Trade 租约消失、CRC/认证水位/全部其它分区一致时，先封存原始文件、A 单独索引及双节点回执，再将双方活动 WAL 和 A 额外证书、索引退回安全1250前缀：
  - `/Users/kong/.opentradingcore/trade-ha-forensics/T226-P178-20261028-124952`
  - P178 A/B 恢复 WAL SHA256 `8c44b9cbb7cc797d091248e0dcdcc25c79a088397d585cc67d7067cdf02f82f5`。
- Trade A/B 保留原 Compose 14 层配置、相同数据/认证挂载、网络和资源上限，镜像只替换 Common JAR：`local/otc-t225-tradesvr:certified-common-window`。冷回放日志均有 P126/P133/P178/P246 `TRADE_COLD_E2_SIGNED_OPEN_ORDER_REPLAY_ATTESTED`，两节点 `COMMON_GATEWAY_DISCOVERY_CERTIFIED` 且租约认证。
- 注意：上述**是人工取证/边界恢复**，不是 Common 的自动旧主撤权、新授权、自动追平和双向主切验收。

## 3. 恢复后的真实业务观测（12:55 CST）

- Docker Order A/B、Trade A/B 均为 T225 新版 Common 镜像，Robot 为旧 T212 镜像；四个测试 Robot 当前 `RUNNING`，分别：
  - G6IQ8E 40 挂单、U6ZAMX 40、WSI1WX 40、R0F6CC 2。
- Order 和 Trade 的 256/256 A/B 物理 WAL 在本轮实际复查全部相同；物理 Writer `physically certified partition writer unavailable` 近几分钟 0 次。真实 `TRADESVR_CALLBACK_PROCESS ... Newing success:true code:0` 已多次观察。
- **不等于撮合成功**：对以上四租户的真实数据库 `dc_orders_execorders.last_qty > 0` 查询结果为 0，Maker/Taker 实际成交、资金持仓和 Projection 一致性验收未 PASS。

## 4. T227 新增跨服务验收门禁：当前明确 NO-GO

执行 `python3 tests/t227_signed_cross_service_open_order_audit.py --strict`（只读 WAL；每个分区 A/B 字节完全一致后才对账；严格模式有不一致即 exit=2）。12:52–12:55 实测：

| 租户 | Order 活动订单 | Trade 认证活动订单 | Order 有、Trade 无 | 结论 |
|---|---:|---:|---:|---|
| WSI1WX | 610 | 608 | 2 | **NO-GO** |
| U6ZAMX | 937 | 937 | 0 | 当前一致 |
| G6IQ8E | 883 | 883 | 0 | 当前一致 |
| R0F6CC | 665 | 5 | 660 | **NO-GO** |

上述是独立的业务状态一致性检查，不能拿 A/B WAL SHA 相同掩盖。部分为历史残留及 Saga 阶段不一致，尚未证明对应资金、冻结额等完整状态。**未经认证证明不可删除 Order-only 单、不能把无 Trade 预留的 Order 单直接标记为已撮合或已取消、不能向客户端虚报成交。** WSI1WX 的两个 Order-only 订单 ID 包括 `1564964272058994688` 和 `1564964272180629504`。R0F6CC 有 660 个 Order-only 历史挂单。

## 5. 剩余必须完成的闭环

1. 从 Common 签名 Order 与 Trade 后状态、Saga 幂等阶段核对 Order-only 订单，按可认证业务补偿修复不一致（不得清空取证）；同时核对所有账户冻结保证金与持仓。原有 `TRADE_CANCEL_INSUFFICIENT_FROZEN_accountMargin` 曾出现，虽最新 Robot 恢复 RUNNING，不应视为永久解决。
2. 补 Trade `ExecType=Trade` 实际 OPEN/CLOSE Maker/Taker 财务结算、成交去重、部分成交与手续费/余额/持仓资金流水的一次性签名 AFTER-state Common 提交；Order match 仍有 `ORDER_COMMON_MATCH_PLAN_NOT_YET_CERTIFIED`，须补齐而不能绕过。
3. Common Writer 复制失败的持久 poison、自动旧 Epoch 隔离、安全重授权、可信 Snapshot+WAL 后续追平和 A/B 双向自动主切真实 SIGKILL 验收；日志与 Snapshot 定期归档安全删除。
4. 再跑真实租户注册→自动审批→Robot 报价→Maker/Taker 成交→Cancel/Close→Order/Trade A/B 持续一致和 10/50/200 租户压力测试。**目前总体 NO-GO。**

## 复验入口及交付

- `tests/t225_recover_order_p119_signed_tail_host.py`、`tests/t226_recover_trade_p178_quorum_1250_host.py` 为 Demo 专用具有严格条件的离线人工修复工具，不能再次盲跑 `--apply`；证据目录单独保留。
- `tests/t227_signed_cross_service_open_order_audit.py` 是只读自动 NO-GO 门禁。其结果可能随正常交易窗口变化，应在 A/B 物理一致、读取稳定的同一检查窗口反复复核，不把暂态快照认作持久分叉。
- `compose.t225-certified-common-window.yaml` 是镜像覆盖层；实际部署逐服务使用当前容器的原始 Compose 配置文件列表和 `--no-deps`，不得重新创建整套 Demo。
