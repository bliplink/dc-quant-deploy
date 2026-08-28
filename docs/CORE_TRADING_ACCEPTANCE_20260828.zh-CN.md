# DC SaaS 永续合约核心交易最终验收报告

首次验收：2026-08-28

最终复验：2026-08-29

环境：`172.16.97.64` / `location=CORE_E2E`

分支：`saas-crypto`

## 1. 最终结论

单租户、单品种永续合约核心交易闭环在 64 环境通过最终复验，完整验收退出码为 `0`。覆盖 Web、GW、LoginSvr、OrderSvr、TradeSvr、MDSvr、LiqSvr、MySQL 和 ClickHouse，包含登录、测试入金、下单、撤单、撮合、行情、资金、持仓、手续费、风险档位、资金费、条件单、部分强平、最终强平、保险基金和事务型 ADL。

源码共执行 140 个服务级测试，失败 0、错误 0。六轮压力与稳定性测试累计提交 17,100 个订单请求，生成并精确核对 11,400 条双方执行记录和 11,400 条成交资金流水；无异步拒单、无重复记录、无残留交叉盘口、无 OOM。

本结论表示核心功能可供产品验收和继续产品化开发，不表示系统已经达到承载真实资金所要求的安全、合规、高可用、灾备和交易所级容量标准。

## 2. 访问方式

- Web：`http://172.16.97.64:18088/#/login?location=CORE_E2E`
- 用户：`corebuyer`、`coreseller`
- 密码：`WebE2E!20260827`
- 品种：`BTCUSDT`
- 业务数据库：MySQL 8.0.36
- 行情/K 线：ClickHouse 25.9.3.48
- 服务发现：ZooKeeper 3.8.4

当前页面使用 HTTP，浏览器显示“不安全”属于测试环境预期。Deposit 是内部测试记账，不是链上充值，不得投入真实资金。

## 3. 最终核心版本

| 模块 | 源码提交/镜像 | 说明 |
|---|---|---|
| OrderSvr | `e675577` / `ghcr.io/bliplink/ordersvr:sha-e675577` | 撮合单写序列、Trade 超时重试且不伪造拒单 |
| TradeSvr | `d79e39b7f68e37615368e1ab5d410fac0ec7cde9` / 同 SHA 镜像 | 平仓费用、翻仓、资金流水批量落库和优雅排空 |
| LiqSvr | `0c0aa56d3cf3c3a1b789afa4dfcbef54c4633880` / 同 SHA 镜像 | 部分/最终强平 Market IOC ReduceOnly |
| 部署与验收 | `c093946` 之后的证据提交 | 完整验收、压力测试和证据捕获 |

最终容器检查：13 个核心容器全部 running，`RestartCount=0`，`OOMKilled=false`。

## 4. 完整功能验收

| 验收域 | 结果 | 硬断言 |
|---|---|---|
| 容器与数据库 | PASS | 13 个容器；MySQL 34 张表、21 张表有 location；Web 健康 |
| location 隔离 | PASS | MySQL/ClickHouse 双 location 数据独立，外租户对照记录不变 |
| 登录 | PASS | 正确 location 登录；错误 location 拒绝 |
| 品种过滤器 | PASS | tick、qty step、最小数量、最小名义金额、最大价格、市场保护 |
| TIF | PASS | GTC、IOC、FOK、Post Only 和 Market/IOC |
| 撮合 | PASS | 价格优先、同价 FIFO、maker 价成交、成交后无交叉盘口 |
| STP | PASS | 默认 Cancel Taker；源码支持 Cancel Maker/Both |
| 幂等 | PASS | 相同 ClOrdID 同指纹重放；不同指纹冲突拒绝 |
| 订单管理 | PASS | 普通撤单、Replace、Batch Cancel、Mass Cancel |
| Web 闭环 | PASS | 双会话登录、测试入金、挂单、撤单、成交、最近成交、历史、持仓 |
| 市价平仓 | PASS | Market + IOC + ReduceOnly，最终仓位和占用归零 |
| 资金与手续费 | PASS | maker/taker 费用、余额、保证金、冻结和流水精确核对 |
| 风险档位 | PASS | 杠杆范围、档位名义上限、最大杠杆和维持保证金规则 |
| 资金费 | PASS | 唯一结算、重放幂等、余额/持仓/流水同事务 |
| 条件单 | PASS | TP、SL、OCO 核心触发/互斥语义 |
| 部分强平 | PASS | 25% step 对齐，真实 Market/IOC/ReduceOnly 成交 |
| 最终强平 | PASS | 负余额形成亏空并进入保险/ADL，而非仅创建待处理事件 |
| 保险基金 | PASS | 1 USDT 保险覆盖入账 |
| ADL | PASS | 2.0036 USDT 穿仓按候选排名完成分摊，流水/余额/持仓同事务 |
| 多候选 ADL | PASS | 同租户同品种反向盈利持仓按盈利率和有效杠杆排序 |

最终完整日志：`/root/core-trading-acceptance-FINALCORE-R2-20260829045001.log`。

## 5. 源码测试

| 服务 | 测试数 | 失败 | 错误 |
|---|---:|---:|---:|
| OrderSvr | 47 | 0 | 0 |
| TradeSvr | 55 | 0 | 0 |
| LiqSvr | 11 | 0 | 0 |
| MDSvr | 7 | 0 | 0 |
| APSSvr | 20 | 0 | 0 |
| 合计 | 140 | 0 | 0 |

## 6. 压力与稳定性

| 轮次 | 并发 | 订单请求 | 执行记录 | 成交流水 | 结果 | 性能摘要 |
|---|---:|---:|---:|---:|---|---|
| POSTBATCH200 | 4 | 600 | 400 | 400 | PASS | 约 19 req/s |
| POSTBATCH1000 | 16 | 3,000 | 2,000 | 2,000 | PASS | 约 72–79 req/s，p99 最高 1023 ms |
| POSTBATCH3000 | 32 | 9,000 | 6,000 | 6,000 | PASS | 约 80–98 req/s，p99 最高 1765 ms，max 2.03 s |
| STABILITY R1 | 8 | 1,500 | 1,000 | 1,000 | PASS | 重启恢复、只减仓平仓归零 |
| STABILITY R2 | 8 | 1,500 | 1,000 | 1,000 | PASS | 重启恢复、只减仓平仓归零 |
| STABILITY R3 | 8 | 1,500 | 1,000 | 1,000 | PASS | 重启恢复、只减仓平仓归零 |
| 合计 | - | 17,100 | 11,400 | 11,400 | PASS | 全量精确核对 |

每轮不只检查 HTTP 结果，还等待并精确核对订单、双方 execution、双方 posting、手续费汇总、余额、持仓、保证金、撤单和订单簿；随后重启 OrderSvr/TradeSvr 验证恢复，再通过 reduce-only 对敲平仓验证占用归零。

## 7. 本轮关闭的关键缺陷

1. OrderSvr 并发请求不再产生交叉残留盘口，所有已接受订单进入每个 `location + market + symbol` 的单写撮合序列。
2. TradeSvr 请求超时时不再伪造 Rejected，而是按不确定结果重试，避免已冻结订单被错误终结。
3. 撤单先于迟到 Newing 时，以终态为准，不重新冻结资金。
4. 全量平仓手续费按整个剩余持仓的 taker 成本保守预留；空翻多/多翻空按先平后开处理。
5. 普通成交 posting 改为最多 250 条一批的多值写入，整批失败重试，停机等待队列排空。
6. ADL 从 PENDING 升级为真实事务分摊：筛选反向盈利仓、排序、按 step 减仓、更新余额/持仓/亏空和流水。
7. 重复最终强平验收会清理旧 ADL fixture，防止合法的旧盈利候选污染本轮确定性断言。

## 8. 内存与自动更新

| 服务 | JVM Xmx | 容器限制 |
|---|---:|---:|
| GW、LoginSvr、LiqSvr、ManagerSvr、AdminSvr | 512 MiB | 768 MiB |
| MDSvr、APSSvr、OrderSvr | 768 MiB | 1 GiB |
| TradeSvr | 640 MiB | 896 MiB |
| MySQL | - | 2 GiB |
| ClickHouse | - | 3 GiB |
| ZooKeeper | - | 512 MiB |
| Trade Web | - | 512 MiB |

root cron 每 5 分钟运行 `/root/dc-saas-deploy/auto-update-saas.sh`，只更新公开 GHCR 应用镜像，稳定窗口后成组部署，失败恢复上一组镜像。验收期间核心镜像使用完整 SHA 标签固定，避免 mutable tag 漂移。

## 9. 证据

### 9.1 Web 交易界面

![Web 交易界面](evidence/buyer-trading-flow.png)

### 9.2 第二用户会话

![第二用户会话与订单簿](evidence/seller-trade-history.png)

### 9.3 数据库与镜像

![MySQL、ClickHouse 和运行镜像](evidence/database-evidence.png)

截图 SHA-256：

- buyer：`7ab70d9a29fcf9e87faf7c73e6532394daade4d304bcd07c44ebcc2d8a4ef3f2`
- seller：`fde33445d2c9fb351fbe9c035e3017d27455c3f3e081cbaf1e0aa3e98894bd60`
- database：`6d94892d0f94661ed08bd5c5d0b2635bd8486974c0ac359f4e35eb55271fbdbe`

## 10. 已知限制

- 64 环境无法连接 `fstream.binance.com`，APSSvr 外部行情持续重连。核心验收使用受控标记价，不代表生产指数源已就绪。
- 普通成交流水虽已批量重试和优雅排空，但仍是进程内队列；真实资金前必须使用事务 outbox/不可变复式账本并持续对账。
- 服务端权威 location 尚未贯穿全部请求、订阅、缓存、锁和持久化边界；不能把当前双租户冒烟等同于完整租户安全。
- 当前性能是单机功能门禁，不是 Binance/Bybit 级容量承诺。
- 钱包、KYC/AML、API 签名、限流、私有流恢复、高可用和灾备尚未完成。

更完整的业务规则、数据流、多租户规划和产品边界见 `DC_SAAS_CRYPTO_PRODUCT_AND_ACCEPTANCE_20260829.zh-CN.md` 及同名 Word 文档。
