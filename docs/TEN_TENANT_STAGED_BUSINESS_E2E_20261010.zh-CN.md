# 2026-10-10：10 租户阶段性业务压测实际记录

> 执行环境：Mac mini / Colima / dc-saas，代码分支 saas-crypto。只记录真实完成的操作，不把业务 E2E 的成功误作 HA 故障注入或容量已获批。

## 验收前置条件与升级门禁

- OrderSvr A/B/C 仍运行 `ghcr.io/bliplink/ordersvr:sha-7842df4`，未滚动升级，保持原始三节点同步复制设置。
- 新版 OrderSvr `12a519c`（只读 Key 下单缺少 `ORDER_WRITE` 正确返回 9016）GitHub Actions 编译成功，但未部署。只读升级预检确认 ZK 256/256 READY、768 份 A/B/C 快照齐全且无分歧、检查期间恢复错误为 0，**门禁为阻止升级**：磁盘使用率 87.2%，没有跨节点停写排空、持久化副本提交水位、Projection 水位和经证实的重启回滚协议。
- 开始阶段已有 2 个人工审批的 TRIAL 租户 `A7C924`、`B7C924`，均 `DONE/COMPLETE`、Robot `RUNNING`、40 笔挂单；这两个租户的 Tape 只读验收均通过（公开 recentTrades 变化且对应持久化 Trade 流水增长）。
- AdminSvr 已升级并钉住 `ghcr.io/bliplink/adminsvr:sha-df1b6e583b3e70af19cfb2459508061ec9598ca9`，正确允许合法人工及自动审批的有效 TRIAL 自动启动 Maker/Tape/Robot。

## 实际扩容与端到端结果

运行仓库内的 `tests/run-auto-tenant-trading-e2e.py`，每次只增加**一个**新租户，并通过 `AUTO_TENANT_MAX_ACTIVE` 将最大活跃租户分别限制为 3、6、10。失败即停止，使用每笔唯一 ClOrdID；如果订单结果不明确，不盲目重复原订单。

| 阶段 | 新租户 | 实际验收 |
|---|---|---|
| 2→3 | YGW9OH | PASS，退出码 0 |
| 3→4 | R1GLNL | PASS |
| 4→5 | U9DXN2 | PASS |
| 5→6 | TLS5DL | PASS，本批次退出码 0 |
| 6→7 | BU1AN0 | PASS |
| 7→8 | MZYMEX | PASS |
| 8→9 | NRZ5AE | PASS |
| 9→10 | S0P0PZ | PASS，本批次退出码 0 |

每一个新增租户都实际经历：公开申请自动审批、独立流动性 Maker/Tape 引导、Robot `NOTIONAL_ZONES` 策略形成 20 买 + 20 卖挂单、公开盘口可见买卖各 10 档、普通交易员注册、Demo=1 入金 1000 USDT、用唯一 ClOrdID 实际成交买入 0.0001 BTC、检查 Order/Execution/Position 投影数量一致、实际卖出平仓并确认持仓归零、交易员无残余活动订单、Robot 恢复 40 笔挂单。这是**真实业务验收**，不是单纯创建数据库记录。

在扩容至 6 个租户后的独立只读权威检查中，数据库确认：6 个活跃试用租户；6/6 个引导任务 `DONE/COMPLETE`；6/6 个 Robot `RUNNING`、每个 40 笔挂单，合计 240；最近五分钟市场活动 358 条；Order A/B/C 最近九分钟未出现 `ORDER_PARTITION_RECOVERY_FAILED` 或 `PARTITION_NOT_READY`，Robot 约 262 MiB / 384 MiB，MySQL 约 655 MiB / 1.5 GiB，宿主机磁盘约 87% 已用。

扩容到 10 的 4 次独立 E2E 均返回 PASS，整批退出码 0；**但是之后独立查询 10 租户数据库汇总、机器资源和 `check-tenant-ramp-readiness.py` 的命令被执行环境安全检查拦截，没有取得最终后置检查**。因此这里的结论仅为“10 租户阶段性**逐户完整业务 E2E**通过”，不能宣称 `10/10` 已经经过独立汇总审计，更不能声称 `nextRampAuthorized=true` 或允许跳到 25/50/100/200 租户。

## 下一步与安全限制

1. 在允许的执行环境下，先通过**只读**数据库/Robot/市场/CPU/内存/磁盘/GC/HA 检查确认 10 租户稳定，运行 `tests/check-tenant-ramp-readiness.py`，若仍 NOT_READY 则停止扩容。
2. 等具备完整 writer drain、所有活动副本 durable ACK、Projection watermark 和 rollback 证据后，才允许 Order A/B/C 部署 `12a519c` 并完成缺少 ORDER_WRITE 返回 9016 的真实回归。
3. 继续 Broker 代客交易签名认证、明确授权拒绝、跨租户隔离、开仓/撤单/平仓和权威订单与资金对账；随后是受控 Order/Trade HA 故障注入、WAL 归档与安全删除证明。
4. 本记录不含凭据、API 密钥或交易 Session，仍需保留原始 E2E 运行证据。