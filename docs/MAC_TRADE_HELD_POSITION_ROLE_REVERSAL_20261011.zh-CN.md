# Mac Demo Trade A/B 角色反转与真实持仓验收（2026-10-11）

## 发现与修复
现有全新 Mac 一键部署虽然生成 256 个 Trade READY 分区，但 `ensure_trade_cluster_assignments` 一直创建没有 `assignmentVersion`、`protocolVersion`、`replicas` 的旧格式元数据。正式的 `trade_cluster_transition_host.py` 需要协议 v3，导致第一个 P000 角色反转在写入前被拒绝。不能通过不验证 epoch、ZK version 或放宽防双主机制绕过。

本次修正：

1. **今后的新部署**生成 `assignmentVersion=1`、`protocolVersion=3`、显式单同步副本、`nodePool=trade-ab` 的分区元数据，保留现有交错 A/B Primary 规则。
2. **当前遗留部署**的单个 `epoch=1`、`READY`、仅含五个旧字段的分区，允许明确指定 `TRADE_CLUSTER_UPGRADE_LEGACY=true` 后，在同一次 ZooKeeper **dataVersion CAS** 切换里升到协议 v3；默认仍 fail closed。非初始分区和未知扩展字段禁止按旧格式迁移，避免覆盖未识别状态。
3. 保持 `--confirm-root` 和单次显式分区选择，目的分区仍须先经 `TRADE_PARTITION_READY` Epoch 匹配后才放行。

## 已执行结果

- `tests.test_trade_cluster_transition_host`、`tests.test_trade_cluster_assignments`：**9/9 PASS**。
- P000 空状态双向角色反转 A→B→A：CAS、两个新的 `TRADE_PARTITION_READY` Epoch、原拓扑恢复、Projection 水位连续：**PASS**。证据目录 `artifacts/20261011-163747-trade-role-reversal/`。
- 新建独立租户 `DNMA1P`，自动审批和 Robot 40 单；注册交易员、入金 1000 Demo、IOC 买入 **0.0001 BTC**，Order execution 与 DB 多仓一致。
- 该租户 `Trade=CRC32(DNMA1P)%256=P160`；实际持有仓位时切换 P160 A→B（epoch 1→2）再 B→A（epoch 2→3），分别经过 Epoch 匹配 READY，Trade API 读持仓以及 DB 的 0.0001 BTC 持仓保持一致，Projection watermark 没有回退。
- P160 `TRADE_PARTITION_READY` 日志：B epoch=2 `committedStateSeq=227`，A epoch=3 `committedStateSeq=361`。
- 随后 IOC Reduce-Only 卖出平仓至 0，用户活动订单为 0、Robot 补齐 40 单。E2E **退出码 0**。
- `tests/check-projection-consistency-host.sh`：Trade、Order watermark/tail mismatch 均 **0**；Trade orphan mutation **0**；cross-partition event IDs **0**。现场 24 容器仍在运行，Trade A/B 无重启，无 OOM。
- P160 的 Projection 水位（前→后）：**Trade epoch 1 seq 155 → epoch 3 seq 421**。其他分区的 watermark 也未回退。
- 持仓反转证据目录 `~/.opentradingcore/local-ha-zkfix-20261011-v1/artifacts/20261011-164547-trade-role-reversal/`。原始 Demo 数据根目录保留。

## 未完成 / 不能推定

- 以上是**存活节点之间显式 CAS 角色反转**，不是 Trade Primary 实际进程 SIGKILL。需要单独执行进程故障自动接管、故障期间请求审计和持续持仓恢复验收。
- 尚未见到 Trade P160 明确的 Archive Catch-up/旧 Epoch 日志归档及完整追平证明；不能仅凭 A/B/A READY 和持仓一致就宣称归档机制通过。
- 尚未执行 10 租户长稳及 200 租户分批压力测试；也不能据此声称零丢单、零重复成交全覆盖。
- 本地代码提交和远端 GitHub 推送状态需分别核实，不可混同。

本轮修改在 `saas-crypto` 来源工作树隔离开发，不覆盖其他并发会话或已有部署数据。
