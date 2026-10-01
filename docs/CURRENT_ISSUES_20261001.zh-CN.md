# OpenTradingCore 当前问题与验收清单（2026-10-01）

> 本文只记录当前已确认/用户已观察到的问题、复现方式和验收标准。不要把“怀疑点”当成根因。修复前先重新复现并补证据。

> 2026-10-01 更新：下文黑屏章节保留故障分析，但黑屏已由同次完整构建镜像修复，随后真实交易 Web E2E、300/16 和集群恢复验收通过。不要把旧快照中的“待修复”误当成当前线上状态。API 独立文档站已上线，细节见 `OPEN_TRADING_CORE_HANDOFF.md` 第 0 节。

> 2026-10-01 Demo 业务补测：新租户 `T17QGO` 自动审批/Robot 金额分档盘口/注册交易员/模拟资金成交/Reduce-Only 平仓已通过。曾发现数字开头 location 令自动初始化卡在 `CREATE_MAKER`，本地 Manager/Admin 已修复并验证旧任务自动续接；详见总交接第 0 节。该单次通过不关闭下面的 Robot 长稳、PlaceOrder timeout 或公网匿名盘口问题。

## 1. 优先级总览

| 优先级 | 问题 | 状态 |
|---|---|---|
| 已修复 | Trade Web 黑屏：index.html 与 JS/CSS bundle 不属于同一次 build | 完整镜像修复并通过 Web E2E；下方仅保留历史根因 |
| P0 | 未登录 `E2E001` 交易页盘口为空，登录后可见双侧各 10 档 | 2026-10-01 公网浏览器复现；待查匿名行情订阅/授权/状态路径，不预设根因 |
| P0 | PlaceOrder timeout | 用户已观察，待端到端计时定位 |
| P1 | Robot 按金额维持盘口不稳定，大单吃掉后不能立即补齐 | 用户已观察，待量化恢复时间 |
| P1 | Web 发布流程存在多会话本地补丁叠加风险 | 已确认，需要统一 GitHub Actions 完整构建 |
| P1 | 公开前浏览器全站回归 | 交易 Web 完整 E2E 已通过；主站/租户/独立 API 文档站已抽查，匿名盘口与租户表格等仍需修复后重验 |
| P1 | API 文档公网偶发连接重置/超时 | 2026-10-01 GHCR 切换后首次抽样出现 2 次连接错误；本机 origin 连续正常，重试后公网正常，根因未确认 |

---

## 2. P0：Trade Web 黑屏

### 现象

访问：

`https://trade.opentradingcore.com/#/trade?location=E2E001`

HTTP 返回 200，但页面 body 为空，浏览器控制台报 JS/CSS MIME type 错误。

### 已确认根因

当前运行容器中：

```text
index.html
  -> res/main_2026_09_30_01_57_13.js
  -> res/main_2026_09_30_01_57_13.css

但 res/ 实际只有：
  -> main_2026_09_29_16_40_54.js
  -> main_2026_09_29_16_40_54.css
```

缺失的 JS/CSS 请求被 nginx SPA fallback 返回成 index.html，因此浏览器收到 `text/html`，拒绝执行脚本/样式。

### 原因归类

这是发布一致性问题，不是交易后端问题，也不是 WSS 问题。

多个会话曾在本机对已有 Web 镜像做单文件/衍生镜像补丁，导致 index 与 bundle 版本错配。

### 正确修复

必须从 `dc-trade-web@saas-crypto` 最新合并代码重新完整 build，一次性生成并发布同一次 build 的：

```text
index.html
main_<build>.js
main_<build>.css
TradingView assets
favicon
nginx config
```

不要把 index 指回旧 bundle，也不要继续拼不同 build 的静态文件。

### 验收

- HTML 200；
- JS/CSS 200；
- Content-Type 正确；
- body 非空；
- WSS 建立成功；
- console error = 0；
- Playwright 能看到交易主界面、盘口、下单区、Positions/Open Orders。

---

## 3. P0：PlaceOrder timeout

### 用户观察

实际下单过程中出现 `placeOrder timeout`。

需要特别区分两类情况：

1. 订单确实没有进入 OrderSvr；
2. 客户端/GW 已超时，但订单随后在后端成功创建（late success）。

第二种情况风险更高，因为用户/Robot重试可能造成重复下单。

### 必须采集的端到端时间点

针对同一个 request_id / cid / order_id，至少记录：

```text
T0 Web/Robot 发出 placeOrder
T1 GW 收到请求
T2 OrderSvr 收到请求
T3 OrderSvr -> TradeSvr 请求
T4 TradeSvr 返回/回调
T5 OrderSvr 状态进入 New/Rejected
T6 GW 返回响应
T7 Web/Robot 收到响应
```

同时记录：

- GW keyed client 是否 Online；
- 是否发生重试/退避；
- OrderSvr -> TradeSvr 首次连接/租户账户初始化耗时；
- GW / OrderSvr / TradeSvr 线程池队列长度；
- GC / CPU / event-loop 阻塞；
- timeout 后该 request_id 是否最终出现订单。

### 已知历史线索

历史曾定位到 keyed TradeSvr client 未 Online 时的退避：

`100 + 200 + 400 + 800 + 1600 ms = 3100 ms`

首单冷启动还可能叠加租户/账户/持仓首次初始化。

这只是历史线索，当前 timeout 不能直接归因于此，必须按本节重新采样。

### 客户端行为要求

- timeout 不能简单等价于“订单一定失败”；
- timeout 后应按 request_id / clientOrderId 查询并重新同步；
- 重试必须具备幂等保护，避免重复订单；
- UI 按钮可恢复，但迟到订单必须能重新同步显示。

### 验收

- 正常稳定环境连续下单无 client timeout；
- 若人为制造延迟，late success 能被识别并同步；
- 相同幂等键重试不会产生重复订单；
- 记录 p50/p95/p99 placeOrder 端到端延迟，并能定位每段耗时。

---

## 4. P1：Robot 按金额维持盘口不稳定

### 用户观察

Robot 当前按金额提供盘口时不够稳定。

直接下约 1000 金额的可成交订单后，会出现：

- Robot 盘口被明显吃掉；
- 目标档位/目标金额出现缺口；
- 缺口不能立即补齐；
- 盘口恢复速度不稳定。

### 期望行为

Robot 的目标不是一次性挂一批单，而是持续维持目标流动性。

当用户成交、撤单或行情移动导致 live orders 偏离 desired book 时，应快速执行：

`desired book -> live orders diff -> cancel/new/replace -> restored book`

盘口应在可控时间内恢复目标总金额和档位结构。

### 重点检查项

1. Robot quote loop / refresh loop 周期是否过长；
2. 是否有固定 sleep / throttle / cooldown；
3. 大单成交后 pending fill/pending cancel 状态是否阻塞重新挂单；
4. desired book 与 live book 的 diff 计算是否只在下一个行情 tick 才触发；
5. 每档金额分配后，总 bid/ask notional 是否达到目标；
6. 部分成交后是否按剩余数量错误判断“该档仍存在”，从而不补；
7. cancel + new 是否串行导致空窗；
8. GW/OrderSvr placeOrder timeout 是否反向导致 Robot 无法快速补单；
9. OrderSvr / GW 限流、令牌桶、并发上限是否限制补单 burst；
10. Binance bookTicker 到 Robot 的行情更新与内部订单回报是否存在竞态。

### 建议量化测试

预热 Robot 后记录目标盘口，然后重复至少 50 次：

1. 记录成交前 top N 档及 bid/ask 总 notional；
2. 发出约 1000 金额的可成交订单；
3. 从成交开始每 100ms 采样盘口，持续 5 秒；
4. 记录被吃掉的档位、恢复的第一个时间点和完全恢复时间；
5. 比较恢复后总 notional 与目标 notional；
6. 同时关联 Robot placeOrder/cancel request_id 和 GW/OrderSvr 响应。

需要输出：

- replenish latency p50/p95/p99；
- 每侧目标金额 vs 实际金额；
- live/pending-new/pending-cancel 订单数；
- placeOrder/cancel timeout 次数；
- 是否出现重复档位、过量挂单或长时间空档。

### 验收方向

- 一次 1000 金额成交不能造成长时间盘口缺口；
- 盘口恢复时间稳定且可量化；
- 恢复后总金额接近配置目标；
- 不因快速补单产生重复订单/超额流动性；
- Robot 补单失败时必须有明确日志和重试状态。

---

## 5. Robot 与 PlaceOrder 的关联必须一起看

当前两个问题可能独立，也可能相关：

`大单吃盘口 -> Robot 立即补单 -> placeOrder timeout/延迟 -> 盘口恢复慢`

因此定位时不要只看 Robot 策略线程，也不要只看 OrderSvr。

必须把同一轮恢复过程串成完整 trace：

```text
Trade fill
 -> Robot receives execution/order update
 -> Robot recomputes desired book
 -> Robot sends placeOrder
 -> GW
 -> OrderSvr
 -> TradeSvr
 -> order ack/New
 -> MDSvr/book update
 -> Web sees restored depth
```

只有拿到这条链路的分段时间，才能判断慢在策略、网关、订单服务、交易服务还是行情回推。

---

## 6. P1：统一发布流程，避免并行会话再次造成黑屏

后续正式发布规则：

> **Git 是唯一源码合并点，GitHub Actions 是正式镜像唯一发布源。**

多个 ChatGPT/Codex 会话并行时：

1. fetch 最新远端；
2. rebase/merge；
3. 禁止 force push；
4. Push Git；
5. GitHub Actions 从同一 commit 完整构建；
6. 发布 immutable sha tag/digest；
7. 部署完整镜像；
8. Playwright/E2E 后才算发布完成。

不要再长期使用本机单文件 patch 作为正式发布方式。

---

## 7. Playwright 全站验收计划

在 Trade Web 完整镜像恢复后重新执行完整测试。

### 主站 opentradingcore.com

- Desktop 1536x1024；
- Mobile 390x844；
- 顶部导航；
- 租户目录、搜索、分页、排序；
- 中文/EN；
- 所有公共链接；
- favicon / title；
- console/pageerror/requestfailed；
- 全页横向溢出；
- 进入申请/交易/租户入口。

### 核心交易 trade.opentradingcore.com

- 所有 JS/CSS 资源 200；
- WSS；
- TradingView/Kline；
- ticker；
- Order Book；
- order entry；
- Market/Limit/FOK/IOC/Trigger；
- Open Orders；
- Positions；
- Account；
- PlaceOrder 成功/失败/timeout；
- Logo 返回主页；
- Apply 返回上一页；
- Desktop/Mobile；
- console/pageerror/requestfailed。

### 租户 Web tenant.opentradingcore.com

- 匿名根入口不出现 session error；
- `?location=<LOCATION>` 正确进入租户登录；
- 登录失败提示；
- 无效 location；
- Session 过期；
- Mobile；
- 中英文/品牌；
- console/pageerror/requestfailed。

---

## 8. 当前处理顺序建议

1. P0：用最新合并代码完整重建 Trade Web，先恢复黑屏；
2. P0：复现并 trace PlaceOrder timeout；
3. P1：用 1000 金额成交场景量化 Robot replenish latency；
4. 把 Robot 补单 trace 与 placeOrder trace 对齐，确认是否同一瓶颈；
5. 完成全站 Playwright 回归；
6. 再做 UI/体验类优化。

---

## 9. 记录原则

- “用户观察”与“已确认根因”必须分开；
- 每个性能问题都要保存 request_id/cid/order_id；
- 修复前后必须用同一脚本复测；
- 所有验收结果建议落到 `docs/evidence/`；
- 不以“页面看起来好了”作为交易链路验收标准。

---

## 10. P1：API 文档公网连接稳定性

2026-10-01 GHCR digest 镜像部署后，`api.opentradingcore.com` 首轮公网请求中，英文方法目录出现一次 `connection reset by peer`，英文 YAML 出现一次 15 秒超时。对应文档容器 healthy、0 restart、无 OOM；本机 origin 对英文/中文目录及 YAML 每项连续 3 次均为 200，约 1ms。随后对先前失败的两条公网 URL 各重试 3 次，6/6 返回 200（约 0.7–1.5 秒）。失败请求未出现在 nginx access log，说明问题发生在请求到达 origin 之前；不能仅凭此判定是客户端外网、Cloudflare edge 还是 Tunnel 链路。

后续用外部探针持续采样 `/en/`、`/zh/`、两版方法目录和 YAML 下载的成功率/延迟，记录失败的时间、HTTP/网络错误、Cloudflare Ray ID，并与 cloudflared 连接日志及容器 access log 对齐。验收应至少覆盖连续运行和不同网络来源，不以单次重试成功代替稳定性结论。
