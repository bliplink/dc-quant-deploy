# SaaS OrderSvr B Full GC 与 Robot CPU 配额诊断（2026-10-10）

## 关键结论

**当前生产 Demo 仍不能开展 50/200 租户压力测试。** 既有 12 租户浏览器盘口均有数据，但 Tape 仿真成交持续性不足。后续只读性能排查发现：

1. Docker VM 实际为 **8 CPU / 15.58 GiB**。原 RobotSvr 配额 `0.75 CPU`，原 OrderSvr B `1.50 CPU`；首次 8 秒 CFS delta 显示 Robot **86/86 个周期（100%）被限流**，Order B **52/86（60.5%）被限流**。Docker VM CPU PSI `some avg10` 约 **51–59%**，IO PSI 约 0.15%，不能归因于磁盘写入。
2. 对 JVM PID 7（Robot）、PID 7（Order B）做 **4 秒、只读线程 CPU 差值**，Robot 主要是 `robot-tape-*` 工作线程；Order B 的两个 HotSpot `GC task thread#` 合计约 **5.07 CPU 秒**。这只是 CPU 消耗证据，不是精确 Stop-the-World 最长暂停值。
3. 用 `scripts/observe-order-jvm-gc.py` 的 HotSpot PerfData 只读计数器：**约 15 秒内 Order B 4 次 Full GC、累计约 12.28 秒 Full GC / Safepoint 时间**；同窗口 Order A、C 均为 **0 Full GC**。另一次约 8 秒内 B 3 次 Full GC、累计约 **5.06 秒**；GC 高密度现象可复现。
4. JVM 参数：Order B `-Xmx2048m -Xmn512m`，老年代上限约 **1536 MiB**；只读观察 **1535.8–1535.9 MiB / 1536 MiB（约 99.99%）**，反复 Full GC 后仍接近满载。Order A 老年代曾达 1439.7 MiB/1459.5 MiB，后约 91%（亦需关注）；Order C 仅约 33–36 MiB，属于较小容量状态。**绝不能靠持续加 CPU 宣称根治此状况。**
5. Order B `ORDER_PERF_STATS` 显示活跃订单约 **350–430**（按样本变化），与 1.5 GiB 老年代几乎占满并不直接吻合。但仅凭该数无法证明内存泄漏，仍须排查 idempotency reservation、持久化 Journal/缓存、异步复制、最近成交及对象生命周期，并区别主从复制状态和实际对象保留。
6. 全量 Tape 日志只读聚合：旧 Robot `0.75 CPU` 时 23:49–23:53 每分钟约 4–9 次全体租户点价指令；调整后 23:55–23:59 为 10–14 次/分钟，**仅属时间相关观测，未建立因果，也未证明实际成交 TPS 提升**。ClickHouse `dc.market_trade` 是行情落库，不能代替权威订单、成交或资金流水。某些租户最近 5 分钟仍只有 0–1 条市场成交。
7. 正在运行的 OrderSvr A/B/C、RobotSvr、TradeSvr、Web 等关键服务均 **未重启、无 OOM**。本轮未进行租户注册、撮合故障注入、路线/Placement 变更、真实签名交易或数据清理。

## 唯一在线配置改动：Robot CPU 配额

在已有配置调整授权范围内，只调整 `dc-saas-robotsvr`：

- `docker update --cpus 1.25 dc-saas-robotsvr`：从 **0.75 CPU → 1.25 CPU**，**在线生效，无容器重建/重启**。
- Colima 上已同步在受保护、未入库的 `/Users/kong/.opentradingcore/dc-saas-fresh2-20261005.env` 中设置 `ROBOTSVR_CPU_LIMIT=1.25`，并保存仅用于本地回滚的 `.bak-robot-cpu-075-20261010` 备份；绝不将环境文件/密钥提交 GitHub。
- 调整后 12 秒 Robot 用掉约 **15.38 CPU 秒**，但 CFS 仍有 **124/124 个周期限流**。Robot 从额外核数受益，但仍受配额限制，且 Order B Full GC 未解除。**不应进一步盲目放大 Robot 并发和 Tape 输入流量**。
- 原配额回滚：先运行 `docker update --cpus 0.75 dc-saas-robotsvr`，再在受保护 `.env` 中只将 `ROBOTSVR_CPU_LIMIT` 改回 `0.75`（勿用旧备份覆盖其它新增镜像标签/密码）。原镜像、订单、Trade、Robot 均未升级。
- **OrderSvr B CPU、JVM、堆内存、GC 算法均未调整**；扩大 `Xmx` 需要单独 HA 滚动部署验证，不能直接改线上 JVM 或调整 Placement 绕过故障。

## 只读复核及新增保护

```sh
# 不使用 JVM attach/jcmd/jmap、不发送 SIGQUIT/SIGKILL、不执行 heap dump
python3 scripts/observe-order-jvm-gc.py --samples 4 --interval 5

# 自动判定：真实租户活动、CPU PSI、容器内存、Robot 配额利用率、
# Order B 最近 3 秒 Full GC，以及老年代超过 95% 都会触发 NOT_READY
python3 tests/check-tenant-ramp-readiness.py --output /tmp/otc-ramp-gc.json
```

上述命令均只读取 Docker `inspect/exec/stats`、HotSpot PerfData、VM PSI 和 ClickHouse `SELECT`。新增**自动探测运行 Java PID**，避免 A 的 PID 6 与 B/C 的 PID 7 不一致；采集 GC 次数、累计时间、Safepoint、老年代 MiB/百分比。GC PerfData 不存在、计数异常或无法确认当前 Java 进程时，压测门禁应 fail closed。

最近一次新增门禁真实运行返回 **`NOT_READY`**：Order B 在 3 秒窗口 `1 Full GC / 2634.2ms`，老年代 **99.98%**，CPU PSI `54.11%`，Order B Docker 内存 `82.77%`，Robot 使用约 `101.27%` 的当前 1.25 核配额；13 户中 4 户未达最近 5 分钟 2 条市场成交。**即使采样恰好出现 0 次 Full GC，老年代 >95% 仍单独阻止扩容。**

## 下一步实质性处理

1. **定位 Order B Old Gen 长期驻留对象**：优先审核 Order Svr `saas-crypto` 最新代码中 `OrderClientIdempotencyRegistry`、`OrderPartitionJournal`、异步复制 pending 队列、历史执行缓存等对象容量/淘汰边界。必须在**离线克隆数据或隔离测试环境**中安全分析对象分布；不要在当前 Demo 直接 `jmap -dump`（堆转储常伴随 STW 和大量磁盘 IO）。
2. **建立真实事件闭环计量**：区分 `tape instruction`（尝试）→ OrderSvr 请求结果 → `ExecID`（成交）→ Projection 水位。对每租户记录单位时间真正成交数和 P95/P99 延迟，而非 ClickHouse 总行数。
3. **验证修复后的 GC/HA/容量门槛**：先在隔离环境复现 B 的老年代增长，完成有界缓存修复或可证明的内存策略；确认 Order/Trade 双副本权威一致性与故障注入合格后，才考虑 10→20→50→100→200 阶梯。当前阶段不可将在线资源调整视为 200 户容量证明。

**未修复 Order B GC 前，请勿把租户批量扩容任务标记完成。**
