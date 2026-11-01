# T395｜MD 成交价/最近成交时间与 Order B 冷启动阻塞（2026-11-01）

## 实时行情证据
- 直接解码公网 NWQYBB/BTCUSDT 的 gzip WebSocket `dc.md.trade.BTCUSDT.NWQYBB` 与 `dc.md.orderbook.BTCUSDT.NWQYBB`。
- 最优 Bid 连续为 77857.7，Ask 三次观测为 78013.7 -> 77998.1 -> 78013.7；成交价 77998.1 确实短暂出现在 Ask，并非绝不会出现在盘口。不能据此证明每笔成交订单都曾显示在用户采样的 10 档盘口。
- MD 的 LastPrice=77998.1，最近一条 NoMDEntries MDEntryPx=77998.1，带唯一 ExecID；MDEntryTime 缺失。

## 时间字段根因
- MD `Utils.executionReportToMarketDataSnapshotFullRefresh()` 将 ExecutionReport.TransactTime 原样复制成 NoMDEntries.MDEntryTime，其自身没有填时间的缺陷。
- Order Common 认证原子撮合计划 `OrderCertifiedCrossPlan` / `OrderCertifiedPartialMakerPlan` 生成成交后的业务 after-state 时只设置 LastPx/LastQty/OrderStatus/ExecType，未在该原子状态写入新的成交时间；`OrderCertifiedMatchSettlementEnvelope` 又从 Order 的 TransactTime 构建执行报告，因此真实交易时间在源头丢失。
- 在两条撮合计划中用同一个撮合时刻写入 Maker/Taker 的 `Order.transactTime`，并将其包含在签名 WAL 的两个 after-state 中。重放不会生成新时间；未修改 Common 签名和授权协议。
- 已添加认证撮合 Maker/Taker 同时间、冷重放同时间回归；MD `MarketTradeConversionTest` 补了 TransactTime→MDEntryTime 及 JSON 往返一致性断言。
- Order 全量 Maven 离线 `mvn -o -q test`：137 项，0 失败，2 跳过。MD 定向 2/2 PASS。

## 镜像与部署结果
- 基于原 T368 Order 镜像仅叠加两个新 Java class 构建 `local/otc-t395-ordersvr:certified-match-transact-time`；原 Common JAR、运行配置、其它类不变。
- Order B 预创建候选容器，校验原有 6 个 mount、16 项 env、host 网络一致后执行滚动重启。新容器启动退出 1，错误 `cold E2 history exceeds bounded payload; snapshot required`。
- 已回退容器名称、旧镜像与原 B 数据挂载，旧 B 重启也因相同 Common 恢复门禁退出 1；并非这次新撮合类的启动报错。
- 实际 B 原始 256 个 E2 WAL 文件总约 1425 MiB，4 个最大的 WAL 分区 P158 388.82 MiB、P164 370.79 MiB、P048 367.17 MiB、P168 298.3 MiB。现有 `CommonCertifiedE2ReplicaHistory.openExistingReadOnly` 最大载荷 64 MiB，Common Gate 需要可信快照及之后的 WAL 才能安全恢复。未删数据、未提升阈值、未跳过签名校验。
- 最新 Docker：旧 Order B `otc-t371-order-b-signed-recovery` 已退出 1；Order A、Trade A/B、Robot、MD、Trade Web 均运行。Order A 仍是旧 T368，改造时间字段尚未上线。

## 最新业务健康复核与本地源码提交
- Order A 容器虽然运行，但日志出现 `Common poisoned primary Epoch cannot renew` 和 `Common physically certified partition writer unavailable: P048`；Robot 出现多个租户报价 `ERROR`。因此 Demo 交易能力属于降级/不可验收状态，不可只根据容器 RUNNING 宣告业务恢复。
- MD 历史查询另有 ClickHouse `UNKNOWN_TABLE market_trade` 错误，影响部分最近成交历史查询，但实时 MD 帧依然传出成交价与执行 ID。
- 已在 Order 源码本地提交 `00eaf33`（签名原子撮合 Maker/Taker 成交时间）；MD 测试本地提交 `6ad0105`；均未推送远端，未运行 GitHub Actions。
- 尚无可用于这些大分区恢复的已验证可信快照；不能通过擅自清空 B 的 WAL、虚增 64 MiB 限制或关闭签名校验来宣告恢复。

## 下一步门禁
1. 在 Common 中实现和验收带可信快照的 E2 认证恢复/流式分批回放，让 Order B 可从原始持久化数据安全追平，不能扩大内存硬限制掩盖问题。
2. 在业务仍运行的条件下先恢复 Order B 并证明安全路由、真实写入与可回放，再分节点部署 T395 Order 镜像，不可在 B down 时强行停止 Order A。
3. 对新执行 ID 检查 MDEntryTime 是 `yyyy-MM-dd HH:mm:ss.SSS`，确认 iPhone 13 真实成交时间显示不再带 ~；旧记录不能凭空补真实成交时间。
