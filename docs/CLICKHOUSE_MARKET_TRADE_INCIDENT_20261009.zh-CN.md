# MDSvr ClickHouse MarketTrade 缺表事故与验收 — 2026-10-09

## 问题与影响

在 12 个 SaaS Demo 租户的只读验收中，发现 MDSvr 不断记录：
`ERROR BatchClickHouseTask:market_trade`、`Code 60 Unknown table expression identifier market_trade`。故障排查时 5 分钟内观察到 18 次相关错误。

根因是部署仓库的 ClickHouse 初始化目录只创建了 `dc.kline`、`dc.kline_view`，**未创建 MDSvr 通过 `CommonDataManager` 异步批处理写入的 `dc.market_trade`**。MarketTrade Java 实体包含 location、transactTime、securityID、marketIndicator、execID、price、quantity、amount、createTime 共 9 个字段。

**重要风险**：`CommonDataUtils.BatchClickHouseTask` 读取并执行一批数据，失败后只写异常日志，不做持久化重试或重新入队。因此在缺表时失败的旧批次**可能已经丢失**，修复新表不会自动重放或恢复先前未成功存储的行情成交记录。

此表是 MDSvr 的 ClickHouse **行情成交副本**，不是 MySQL 的撮合成交权威表，也不是资金/持仓的权威状态。不能以 `market_trade` 记录数代替 Order/Trade TPS 或 Tape 实际成交成功数。

## 修复

- 添加 `clickhouse/saas-init/15-market-trade.sql`：`CREATE TABLE IF NOT EXISTS dc.market_trade`；字段与 Java `MarketTrade` 对齐，`MergeTree`，按月份分区，`TTL createTime + INTERVAL 30 DAY DELETE`，避免 Demo 长期无限累积。
- 添加 `tests/test-clickhouse-market-trade-schema.sh`：字段/DDL/TTL/不含删除操作的静态校验，**PASS**。
- 添加 `tests/check-clickhouse-market-trade-host.sh`：只读检查表存在、实际持久化记录、最新写入年龄、最近 MDSvr 批处理错误、可选最少租户覆盖数。
- 已提交到 `bliplink/dc-quant-deploy:saas-crypto`（DDL 提交 `4ba223c`）。在 Mac mini 上直接使用 `clickhouse-client --multiquery` 执行幂等建表，不重启 ClickHouse / Robot / MDSvr / Order / Trade，不重置数据，不更新现有租户路由与 Placement。

### 对已有持久化 ClickHouse 的部署要求

Docker 的 `/docker-entrypoint-initdb.d/` 初始化 SQL **通常只在首次初始化数据目录时执行**，不能因为代码中加入新文件就假定已有实例自动迁移。对已有卷，需明确受控执行：

```bash
bash tests/test-clickhouse-market-trade-schema.sh
docker exec -i dc-saas-clickhouse clickhouse-client --multiquery \
  < clickhouse/saas-init/15-market-trade.sql
MARKET_TRADE_MIN_TENANTS=12 bash tests/check-clickhouse-market-trade-host.sh
```

验收工具不修改交易数据，最少租户覆盖默认值为 1；本次 12 租户 Demo 才显式设置为 12。其他部署不应硬编码为 12。实例恢复后 30 天保留期仅针对新 `market_trade` 表。

## 实际验收证据

- 建表前：MDSvr 连续 `market_trade` 缺表报错；`dc.market_trade` 不存在。
- 建表后，ClickHouse `EXISTS TABLE dc.market_trade = 1`，ClickHouse 25.9.3.48 正常运行。
- 成交行情新记录逐步增长：**80 条/9 租户 → 150 条/10 租户 → 328 条/11 租户 → 455 条/12 租户**。后期检查最新写入仅数秒，90 秒内 `market_trade` 批处理错误数为 **0**。
- `DPGR6B` 之前一轮完整浏览器 E2E 在等待实时 K 线更新时超时；建表后再次运行 **PASS**：买卖各 10 档、最新价正常、24 条历史 K 线、实时至少 2 次更新。这里只能说明时间相关且重测恢复，**不能直接把缺表定义为 K 线超时的唯一根因**。
- `T6X2PT` 首次专项验收也发生实时 K 线更新超时，单次短采样看见双边盘口短暂 0 行、成交停留较久；随后 11:56:38 观察到该租户 `market_trade` 新写入。它的再次完整 Chromium E2E **PASS**：买卖各 10 档、最新价 82388.0、45 条历史 K 线、实时更新 2 次。仍需持续观察该租户的间歇性行情停顿。
- RobotSvr 同期持续输出 Tape instruction，但指令 != 权威撮合成功。尚未核验每笔指令在 Order/Trade/MySQL 权威执行记录中的一一对应。
- 修复后重新跑 `check-projection-consistency-host.sh`、`verify-order-cluster-state-host.sh`，**PASS**：orphan mutations 0、Order/Trade watermark mismatch 0、Order HA 分区/快照一致。

## 后续必须完成

1. **修复失败批次不可恢复的问题**：研究为 MDSvr 成交行情持久化增加有限重试、有界队列和可回放来源；网络失败重试需以业务 `execID` / 去重键保证幂等，不能盲目重放导致重复记录。
2. **权威成交闭环核对**：Order/Trade 执行量、MySQL Projection、`market_trade` 仅作行情侧辅助对比，区别 Tape instruction 与真正被撮合的执行；旧批次历史缺口需要单独记录，不能宣称自动补齐。
3. **专项长时间行情监控**：针对 `T6X2PT` 和其余租户，按分钟记录盘口档位、最近成交时间差、实时 K 线更新时间、Robot 心跳与 MDSvr topic 订阅；间歇性空盘/超时不能被一次 PASS 抹除。
4. **容量验证**：当前仍只证明 12 租户环境的局部验收，未测 200 租户，也未测真实下单 TPS 或延迟分位数；在确认 CPU 调度压力和实时行情稳定性后再分档扩容。
5. 用户约束持续生效：**暂不进行现有租户路由修改/回滚或集群 Placement**。平台手动 `APPROVE` 的实际写入验收继续保留未完成状态。

## 日志与截图路径

- Mac mini `/Users/kong/.opentradingcore/dc-saas-runtime-fresh2-20261005/e2e-artifacts/acceptance-followup-20261009/`，其中 `post-market-trade-fix/` 为 DPGR6B 修复后 E2E，`T6X2PT-recheck/` 为专项恢复后 E2E。
- 原始日志保留在当前容器卷及 Docker 日志中，报告只记录非敏感的数值摘要，不包含 API Keys、密码或资金密钥。
