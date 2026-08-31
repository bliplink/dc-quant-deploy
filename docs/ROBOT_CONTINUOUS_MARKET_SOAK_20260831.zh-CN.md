# Robot 持续报价与混合交易运行报告

日期：2026-08-31  
环境：`18.140.45.126`  
租户：`WEB_E2E`  
品种：`BTCUSDT`  
状态：常驻运行中

## 1. 结论

Robot 已在 `WEB_E2E` 启动持续 10 档买价与 10 档卖价，并由四个模拟用户循环执行双向 IOC 点价、价差内 GTC、被动挂单及批量撤单。服务器安装了分钟级守护任务；负载进程异常退出时自动拉起，Web 浏览器监控容器使用真实 WebSocket 登录并以 250ms 频率检查用户实际看到的盘口。

最终组合版本 RobotSvr `e1c3e5b`、OrderSvr `fe6960a`、MDSvr `08ee283`、Trade Web `a265617`、部署脚本 `e36547a` 的干净观察窗口通过：Robot 权威状态为 `RUNNING`；数据库每侧始终不少于 10 个不同价位，换价时仅短暂保留有限桥接报价；MDSvr 在内存中维护完整深度，Web 严格只展示前 10+10 档。真实浏览器连续 2,400 次 250ms 采样中，档位过少/过多、页面错误均为 0；同窗口四用户混合请求拒绝和负余额均为 0。任务在报告生成后继续运行，本报告不把 10 分钟观察窗口等同于长期稳定性或容量极限结论。

## 2. 实施内容

- Robot：`continuous-depth10`，API 用户 `robotsoakmaker`。
- 模拟用户：`robotsoak01` 至 `robotsoak04`。
- 行情源：APSSvr 的 Binance Futures book ticker。
- 盘口：10 bid + 10 ask，租户 tick size `0.1`、qty step `0.0001`。
- 报价刷新：200ms；行情过期保护：3 秒；偏离熔断：500 bps。
- 用户流量：每轮并发 4 个订单，包含买 IOC、卖 IOC、价差内 GTC 和被动 GTC；周期性撤销用户剩余活动单。
- Web 监控：真实浏览器、真实 GW/LoginSvr/MDSvr、250ms DOM 采样，每 10 分钟更新健康截图。
- 守护：root crontab 每分钟执行 `start`，文件锁保证只有一个负载进程。

## 3. 首轮发现与修复

首轮运行真实发现并修复了以下问题：

1. `WEB_E2E` 租户品种的精度字段为空，Robot 回退到 0.01，而 OrderSvr 使用全局 0.1，导致价格被拒绝。常驻脚本现在从全局品种补齐租户规则并按租户 tick 生成测试订单。
2. 新建模拟账户已写 MySQL，但 TradeSvr/OrderSvr 内存缓存未热加载。脚本仅在首次安装时停用 Robot，重载 LoginSvr/OrderSvr/TradeSvr/GW，路由恢复后再启用。
3. 旧 Robot 换价采用“先撤全部旧价、再逐笔报新价”，Web 250ms 采样捕获到 0–9 档窗口。RobotSvr `1a95cfe` 改为按行情方向分侧切换：上涨先确认新卖盘再换买盘，下跌相反；新报价未全部活动前不撤旧侧。
4. Robot 过去以“期望报价数”上报 `open_order_count`。RobotSvr `2e39933` 改为查询实际活动委托，数量不符时进入降级/错误，禁止虚假 `RUNNING=20`。
5. 守护脚本早期 PID 文件可能被并发启动覆盖。现使用 `flock` 单实例锁，`stop` 会检查并终止所有同类残留进程。
6. Web 监控与下单用户曾复用会话，且价差单未使用租户 tick，产生测试工具自身的拒绝噪声。最终监控使用 Robot 专用账号，所有模拟价格按数据库 tick 量化。
7. 高并发时 OrderSvr/GW 的活动单查询可见性偶尔晚于下单响应。旧逻辑连续三次确认超时会撤掉全部报价，真实 Web 因此出现缺档。`a1ec57a` 将这种情况改为可重试的 `QUOTE_RECONCILIATION_RETRY`，保留已有盘口，不再因查询延迟主动清空。
8. 仅用“下单前总数 + 缺失数”确认换价会因部分成交和延迟可见而失真，中间版本一度留下 1,377 笔活动测试报价。最终 `387bdf7` 按不同价格档位控制每侧深度：优先保留本轮目标价格，不足时保留距离目标最近的旧价格，其余分批撤销，从而同时满足不缺档和不无限累积。
9. 大量活动报价一次性提交 `cancelBatchOrder` 会超过实际处理能力。`9470bd3` 将停机/恢复撤单固定为每批 50 笔，一批失败仍继续其他批次；生产验证把 1,377 笔遗留活动单清理为 0。
10. OrderSvr 已能查询到新单不代表 MDSvr→GW→Web 已处理对应新增行情。真实浏览器曾在一个 250ms 样本中看到卖盘从 10 降到 6，而 MySQL 采样仍为 10+。RobotSvr `e1c3e5b` 增加 750ms 传播宽限作为桥接保护；后续实测证明固定延时不是最终一致性边界。`45a9101` 同时修正 Web 监控，使分钟汇总包含所有健康后的异常样本。
11. OrderSvr 的 Docker JSON 日志在持续查询下增长到 3,894,878,094 字节，原配置没有轮转。部署提交 `ab0b5f9` 为全部 SaaS Compose 服务和 Web 监控设置 `max-size=50m`、`max-file=5`；生产只重建 SaaS OrderSvr 后参数已生效，量化容器未改动。
12. MDSvr 兼容订单簿原发布节拍为 1000ms，慢于 250ms Web 观察频率。MDSvr `08ee283` 与 SaaS 配置 `11ebe78` 将租户订单簿调整为 200ms（5Hz）；生产同时核对生成的 override 和容器内实际配置均为 200ms。5Hz 本身没有消除缺档，反而证明问题在本地簿输入完整性而非 Web 刷新频率。
13. OrderSvr 的撮合订单按 `algoName` 分组，但租户对外只有一个 `location + symbol` 盘口。OrderSvr `ae1a831` 将公开深度状态、异步合并键和数量汇总统一为跨算法聚合，避免不同内部算法状态发布到同一 topic 时互相覆盖。
14. OrderSvr 原先把给 MDSvr 的内部恢复快照也裁成 Top10。顶档成交或撤销后，MDSvr 没有第 11 档可立即递补，只能等待下一次全量快照，因此真实 Web 会短暂只剩 5–9 档。OrderSvr `fe6960a` 改为向 MDSvr 发布完整聚合深度；Top10 裁剪只放在 Web 展示边界。修复后 250ms 浏览器连续采样不再出现缺档。
15. 完整恢复快照上线后，严格监控发现旧 Web 会把收到的深层档位全部渲染，最新截图一度出现 193 bid / 17 ask；原监控的 `>=10` 判定错误地把它算作健康。Trade Web `a265617` 在排序后仅渲染最优 10 档；监控 `1b5ac6f` 改为买卖两侧必须同时 `==10`，并同时记录最小值和最大值。
16. 常驻脚本原 `cancelAllOrder` 调用不受当前 OrderSvr 支持，且失败被静默忽略，四个模拟用户的被动 GTC 一度累计约 268 个活动价位。部署脚本 `6ec4041` 改为先查询各用户活动单，再按每批 50 个 `orderIDs` 调用 `cancelBatchOrder`；只清理 `SOAK-` 前缀，启动时先回收旧数据，运行中周期清理，避免长期压测污染订单簿。
17. GW 使用 Java 堆外/直接内存并维持大量 WebSocket 连接，原 384 MiB 容器上限下最终快照达到约 97%，存在被 OOM killer 终止的风险。部署提交 `e36547a` 保持 JVM `-Xmx256m` 不变，仅把 GW 容器总上限调整为 512 MiB；重建后干净窗口占用 360.9 MiB（70.49%），为堆外和本地内存保留余量。

## 4. 干净窗口结果

最终干净窗口开始：2026-08-31 23:41:44（Asia/Shanghai）。启动预热、受控镜像切换及网关资源调整前的数据已分别归档到 `archive/pre-full-depth-20260831T150638Z`、`archive/pre-web-top10-20260831T153150Z` 与 `archive/pre-gw-headroom-20260831T154141Z`，不进入本表。

| 项目 | 结果 | 证据 |
|---|---|---|
| Robot 状态 | PASS | 最终采样为 `RUNNING`，无错误码；换价完成时实际活动报价收敛为 20 |
| 数据库盘口 | PASS | 294 次采样，bid/ask 均为 10–20 档；桥接报价有硬上限并持续收敛 |
| Web 可见盘口 | PASS | 真实 Chromium 每 250ms 读取用户实际看到的盘口，两侧必须严格等于 10 档 |
| Web 档位完整性 | PASS | 连续 2,400 次浏览器采样 `gapSamples=0`，bid/ask 最小值和最大值均为 10/10 |
| Web 页面错误 | PASS | `pageErrors=[]` |
| 混合请求 | PASS | 四用户每轮并发 4 单；脚本累计 accepted=1,172、rejected=0，HTTP 非 200=0 |
| 最近订单拒绝 | PASS | 最终窗口 MySQL 共 6,481 笔订单，其中 Filled=1,202、`Rejected=0` |
| 成交 | PASS | 产生 1,700 条 execution，成交量 0.17 BTC |
| 持仓守恒 | PASS | 测试账户多头合计 0.0192 BTC、空头合计 0.0192 BTC |
| 负余额/负保证金 | PASS | 0 个账户 |
| 服务错误日志 | PASS | 当前窗口 Robot/Order/Trade/MD/GW 的 error/exception/OOM 均为 0；MD 序列缺口为 0 |
| 用户挂单回收 | PASS | 周期批量撤单错误为 0；最终快照四个测试用户剩余活动单为 0，未再次累积深层价位 |
| 单实例 | PASS | 文件锁实际仅允许 PID `34434` 持续运行；cron 瞬时候选进程未获锁即退出 |
| 自动恢复 | PASS | 主动终止 PID `3160258` 后，root cron 自动拉起 PID `3202116`；恢复期间 Robot/Web 行情不断 |

Web 健康截图（SHA-256：`b0e0d425cbe56c967cc8ba530925c9bbc47cb3e7ebb9692f62c6c1f35315a7c0`）：

![WEB_E2E Robot 10+10 实时盘口](evidence/web-market-live.png)

资源快照：

| 服务 | CPU | 内存/上限 |
|---|---:|---:|
| RobotSvr | 6.18% | 139.2 MiB / 384 MiB |
| OrderSvr | 3.14% | 284.4 MiB / 640 MiB |
| TradeSvr | 1.52% | 547.0 MiB / 896 MiB |
| MDSvr | 0.40% | 334.9 MiB / 640 MiB |
| GW | 14.28% | 360.9 MiB / 512 MiB |
| Trade Web | 0.11% | 7.8 MiB / 256 MiB |
| Web 真实浏览器监控 | 31.23% | 617.3 MiB / 768 MiB |
| MySQL | 29.87% | 883.1 MiB / 1.5 GiB |
| ClickHouse | 46.09% | 1.024 GiB / 2 GiB |

主机为 8 vCPU；快照时 load average 为 6.43/5.86/5.85，可用内存约 6.3 GiB。当前是报价更新叠加四路并发业务流量的持续正确性测试，资源无 OOM、容器重启或错误日志；它不替代后续逐级提升并发的容量拐点测试。

## 5. 运维命令

```bash
cd /home/ec2-user/dc-saas-deploy

# 查看 Robot、Web 监控和最近盘口采样
sudo ./tests/run-robot-market-soak-host.sh status

# 安装/修复分钟级守护并立即启动
sudo ./tests/run-robot-market-soak-host.sh install

# 仅停止模拟流量和 Web 监控；Robot 配置保持启用
sudo ./tests/run-robot-market-soak-host.sh stop

# 查看连续运行日志
sudo tail -f /data/dc-saas-runtime/robot-soak/load.log
sudo docker logs -f dc-saas-robot-web-monitor
```

运行数据位于 `/data/dc-saas-runtime/robot-soak`。`runtime.env` 为 root-only 测试凭据，不进入 Git；旧版断档截图和修复前指标已归档在同一目录用于对比。

## 6. 当前边界

- 当前验证的是租户内部报价、撮合、盘口连续性、Web 展示和服务并发；`hedge_enabled=0`，没有真实 Binance 账户反向对冲。
- 常驻模拟用户会持续产生订单、成交、持仓、资金和 K 线数据，只允许用于 `WEB_E2E` 验收租户，不得指向真实资金租户。
- 初始窗口证明修复后的实时行为正常；仍需通过持续小时级/天级统计、服务重启、Binance 断流、价格跳变和数据库短断等故障注入，形成长期稳定性结论。
