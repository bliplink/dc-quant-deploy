# 2026-10-16 Mac Demo 集群真实角色切换验收证据

> 本文遵循 [集群最终统一验收任务书](CLUSTER_HA_FINAL_ACCEPTANCE_MISSION_20261015.zh-CN.md)；只记录真实已执行的操作。日期采用 Mac 所在时区 Asia/Shanghai。全程未新增产品功能，也未依赖 GitHub Actions。

## 本轮真实执行且 PASS 的项目

| 项目 | 动作和证据 | 结论 |
| --- | --- | --- |
| **Trade P000：空分区** | 当前 Demo 上 Trade A→B→A，ZK CAS epoch 1→2→3；两次新主均完成 READY；Projection 前后 14 条水位不回退。 | **PASS：人工受控角色切换** |
| **Trade P020：活跃分区（H4676T）** | 有业务持仓；Trade A→B→A epoch 1→2→3；B 恢复 `committedStateSeq=27061`、`riskAccounts=2`；A 恢复 `committedStateSeq=27093`、`riskAccounts=2`；两次新主均 READY，14 条 Projection 水位不回退。 | **PASS：人工受控角色切换与恢复门禁**，不等于“故障自动主切 + 客户持仓逐项校验” |
| **Order P000：三副本空分区** | A/B/C 同一快照，A→B→A CAS epoch 1→2→3；两次 `ORDER_PARTITION_PROMOTION_READY`；最终 A/B/C 快照 byte hash 一致。 | **PASS：人工受控角色切换** |
| **Order P228：活跃市场 H4676T** | A/B/C 三份已提交市场 Snapshot 完全一致，A→B→A CAS epoch 1→2→3；两次新主均 READY；实际 `MDSvr.queryPublicMarket` 双侧 **10/10 档**；最终三副本快照哈希重新一致。 | **PASS：活跃业务分区角色切换及行情服务** |
| **Projection / Robot 后验** | 全部切换后孤儿 Mutation=0，Order+Trade watermark mismatch=0，各 7/7；Robot 6/6 RUNNING、240 单，租约有效 6/6；八个 Order/Trade/MD 容器 0 重启/OOM。 | **PASS：所测项目** |
| **ZK 最终角色** | Order 256/256 READY，其中 P000/P228 epoch=3，另 254 分区 epoch=1；Trade 同样 256/256 READY，其中 P000/P020 epoch=3；MD 256/256 READY，仍 epoch=1。A/B Primary 各 128。 | **PASS：当前静态分配** |
| **MD-C Learner 真实 SIGKILL** | 上一轮实际终止并重启 MD-C，六个市场重新读取 Order Image，分区/Primary 未变化，原重启策略恢复。 | **PASS：Learner 故障恢复，不是 MD 主切** |

### Mac 上的原始证据

- Trade 空分区：`/Users/kong/.opentradingcore/cluster-evidence/20261016-001050-trade-role-reversal/summary.json`
- Trade 活跃持仓分区：`/Users/kong/.opentradingcore/cluster-evidence/20261016-001140-trade-role-reversal/summary.json`
- Order 三副本空分区：`/Users/kong/.opentradingcore/cluster-evidence/order-p000-role-reversal-20261015T161723Z.json`
- Order 活跃盘口：`/Users/kong/.opentradingcore/cluster-evidence/order-active-P228-A-B-A-20261015T161926Z.json`
- 最终 Projection：`tests/check-projection-consistency-host.sh` 在 2026-10-16 00:20 CST PASS；孤儿与双源 watermark 均无异常。

证据为本机受保护 Demo 文件，不是已上传公开仓库的日志/密钥副本。**角色切换操作采用在线版本 CAS；没有中断整个容器、触发自动选主或模拟物理节点故障。**

## 2026-10-16 00:26–00:28 Mac 新增真实业务回归：PASS

在以上 Order P000/P228、Trade P000/P020 在线角色切换全部完成后，执行：

```bash
set -a; . /Users/kong/dc-quant-deploy/.env.prod; set +a
python3 tests/run-auto-tenant-trading-e2e.py
```

- 新租户 **T1MPT1** 公开申请自动批准，流动性初始化完成，Robot `NOTIONAL_ZONES / RUNNING / 40`，公开盘口买/卖各 10 档。
- 新交易员正常注册登录、`Demo=1` 入金 1,000；真实 IOC 成交 0.0001 BTC，MySQL 订单/成交/Long 持仓吻合。
- Reduce-Only IOC 平仓完成；**测试交易员**最终持仓=0、活动订单=0，业务测试退出码 0。租户内的 Robot 做市账户仍可能有正常持仓，不能把“测试交易员归零”误写成“全租户全部头寸归零”。
- T1MPT1 测试后留在 `TRIAL`，Robot `RUNNING/40`；全 Demo 此时七个 Robot 运行，总目标挂单 **280**，七个租约仍有效。没有擅自删除测试租户。
- 后验 `tests/check-projection-consistency-host.sh` **PASS**：Order+Trade 水位分别 **8/8**，orphan mutation=0，watermark tail mismatch=0，cross-partition duplicated event ID=0。

**另外发现一个必须修复的验收工具问题：** `tests/run-order-live-role-reversal-e2e.py` 硬编码早期 `EX2ENF/P110` 隔离租户（当前 Demo 已不存在），并在 A↔B 变更时只更新 `replica` 单值、未正确更新同步副本列表 `replicas=[另一节点,OrderSvrC]`。因此**不能直接用于当前三副本集群**。下一轮须按当前 Demo 自动创建隔离交易员，保留 `OrderSvrC` 同步副本并使用 CAS 及 fail-closed 旧主隔离，验证挂单穿越 A→B→A 并最后撤单。修复验收脚本属于本轮必需的验收修复，不是业务新功能。

## 尚未通过的关键项目与明确下一动作

1. **Order Primary SIGKILL 自动接管：BLOCKED。** 本轮尝试发起真实 Order-A SIGKILL 验收，但外部执行环境安全检查拦截了命令，**未终止节点、未修改 ZK**。不要谎称已做。后续通过合规可执行的故障注入途径，保留旧主隔离与已提交 WAL 验证，再做全链路自动接管和恢复节点追平。
2. **Trade Primary SIGKILL + 持仓账本：BLOCKED。** P020 人工主备切换已成功，现有 MySQL 持仓记录中有 2 个非零头寸；但接管到 Trade-B 的窗口内尚未以客户合法会话读取并比对实际资金、持仓及成交。平台 Manager 会话调用 `TradeSvr.queryTradePosition` 按权限返回 `1003`，不能以跨租户管理员请求绕过。需创建合法隔离测试交易员，持仓穿越故障、对账再平仓。
3. **Trade 恢复统计核查：仍须注意。** Trade-B 在流式 WAL 恢复时日志显示 `locations:0, riskAccounts:2`；`TradeRecoveryPlan.streamed()` 的 `getLocations()` 只来自零基线快照，而 `TradeRecoveryApplier.validateStreamed()` 会扫描 WAL 收集并恢复租户，因此 **`locations:0` 是计划统计不足，不能直接视为资金丢失，亦不能用 riskAccounts:2 代替精确账本对比**。最小修复只应解决验收证据或真实状态问题，不扩大功能。
4. **MD Primary SIGKILL 自动选主：BLOCKED。** 必须验证旧发布者 Epoch 隔离、接收端已应用的 Order 完整 Image + Diff、ZK CAS，不能用 MD-C Learner 恢复冒充主切。
5. **WAL 自动归档与安全清理、200 租户稳态及 2–3 倍 burst：未验收。** 要在故障接管/一致性先过门禁后继续；无证明不得删除正在被读取的 WAL。

## 接续顺序（切忌重复）

- **下一项：Trade 合法测试交易员持仓状态穿越接管的业务级核对，然后真实故障场景。** 确保复制 ACK 的已提交 HEAD、候选接收已应用内容，以及 READY 后 API 资金/持仓相等。
- 再执行 **Order-A 容器故障自动 promotion + 节点回归为 Replica**，核对 Order/Projection/Trade 全部资金订单成交，业务不中断或恢复窗口可量化。
- **MD Primary 自动故障接管**，再做归档与 10→50→200 租户压力。修复明确失败项 → 本地编译 → 替换 Demo → 只重跑必要的相关验收。
- 按用户授权，无法快速回退时可受控清理隔离 Demo 数据、重新部署并重新注册租户；不要绕过可信 WAL/旧主隔离门禁。

以上是本轮**验收记录**，不是全量 HA 已发布通过的声明。
