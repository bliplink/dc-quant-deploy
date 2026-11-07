# T541｜Mac Demo 真正恢复 Binance WebSocket → APS → Robot → Order/Trade Tape（2026-11-07）

## 验收结果

**真实交易业务验收：PASS_LIVE_BUSINESS_NOT_HA**。本轮未执行 Order/Trade 双节点 SIGKILL，不能标注完整 A/B HA PASS；更不能把这套 Java8 编译类叠层的隔离 Docker 镜像当作完整正式 Maven Release。

在 T529 fresh MySQL + T531 Order A/B + T532 Trade A/B + T533 Projection + T535 Gateway/MD + T539 Admin/Robot 的真实 Mac Demo 中，已启动 T541 APSSvr Binance SOCKS5 候选镜像；自动新租户初始化、Maker/Tape Trader API Key、入金、双边报价、Tape IOC 成交和认证 Trade 结算投影已实际跑通。原 T535 Broker CUSTOM APS 容器保持停止但未删除，可作安全回退。

## DNS / VPN / Binance REST 与 WS 的区别

- 旧 Mac DNS/Colima 对 fapi/ fstream 域名返回异常 IP，裸连 WebSocket 失败。Xray Mac SOCKS5 监听 10808，容器使用 host.lima.internal:10808；T540 已在 bliplink/com.app.dc.apssvr:saas-crypto 增加 Binance Futures SDK 专用 SOCKS5（非全 JVM 代理），在 dc-quant-deploy:saas-crypto-latest 的 compose.yaml 单独注入这两个环境变量；本地私有 .env.prod 已设置且移除了指向 SOCKS5 端口的错误 -Dhttp(s).proxyHost 参数。
- 经同一 Mac VPN，Binance Futures REST fapi.binance.com/fapi/v1/time 仍 **HTTP 451**，但 Binance Futures WS fstream.binance.com/ws/btcusdt@bookTicker 返回 **101 Switching Protocols**。不能把 REST 451 错误推广为 WebSocket 不可用；也不得将 REST 451 冒充 REST 功能 PASS。
- 在真实 APSSvr 容器中接收 9 秒实际公共 WS 二进制帧：**86,380 bytes / 517 个有效 BTCUSDT bookTicker**，实测 bid=76094.90、ask=76095.00，所有解析报价 bid>0、ask>=bid。不是模拟造价或回放假数据。

## 构建和镜像证据（隔离候选）

本机没有 mvn，但 JDK8 可用。基于 T540 本地 APSSvr 源码、现有 Maven 依赖缓存及隔离 Lombok 1.18.34 注解处理器，javac 编译修补后的 BNFuturesImpl.class，JUnit 11/11 PASS。对比旧 T242 已安装镜像中的类方法签名，新类仅增加 6 参数 SOCKS5 解析方法，旧方法签名保持一致，Java class version 52。

镜像由原 local/otc-t242-apssvr:aggtrade-health 叠加上述 class 文件，使用 Docker legacy builder 构建：

- image: local/otc-t541-apssvr:socks5-validation
- sha256:8868f4ea2bdd2beaba590f3b9c0f78a5aebfd8c3a1af9f7de094789dfd166765
- 编译类和镜像内类 SHA256：32e29e6b053a51124ec0e849d7ffd12bf8dcc1dd56c7f86430270ca780feebd2
- 标签显式说明 only experimental / not production release。必须用仓库 saas-crypto 完整源码重新 Maven package 后才能制作正式 GHCR/一键更新镜像；不要把叠层复制当作统一正式部署流程。
- 不使用 GitHub Actions，不覆盖用户其他未提交代码。

实际从隔离镜像 Java 进程中调用 SDK REST/WS 共用 OkHttp SOCKS5，验证 shared client PASS；通过代理访问 Cloudflare HTTP 200、Binance REST HTTP 451。证明 SOCKS5 真实注入了 Java SDK，而非仅 curl。

## 真实运行切换与回退

配置保存在 Mac 用户目录 ~/.opentradingcore/t541-apssvr-socks-validation（私有、环境文件 0600，不上传 GitHub）。复用 T535 配置与数据卷，仅把隔离候选配置 enableBinanceFlag=true，binanceSymbolList/binanceSymbolAliasList 限定为 btcusdt，保留 BookTicker、Depth、Trade、Mark 流。env 注入 APSSVR_BINANCE_SOCKS_HOST=host.lima.internal、APSSVR_BINANCE_SOCKS_PORT=10808，并清空错误全局 Java HTTP 代理。

停止 otc-t535-fresh-apssvr-custom，启动 otc-t541-fresh-apssvr；旧容器保留用于回退，其他 Order/Trade/Gateway/MD/Robot 无需重启。新 APSSvr 的真实 Java 日志：

- Binance connector SOCKS proxy configured host:host.lima.internal port:10808
- WebSocketConnection [1] bookTicker、[2] aggTrade、[3] depth10@100ms、[4] ticker、[5] markPrice@1s **全部 Connected to Server**；收到了真实 BTCUSDT markPriceUpdate。
- Gateway 记录 book ticker fanout delivered=1，Robot 行情 age 从数百万毫秒降至个位或几十毫秒。

## 初始自动初始化 + 机器人

- T539 AdminSvr 原持久化 TrialLiquidityBootstrapWorker 自动从 MySQL 继续运行，**6/6 条任务 COMPLETE/DONE**，各自 Maker/Tape API Key 和入金链路完成。
- Robot **6/6 RUNNING**，每个租户 BTCUSDT 双边挂单 **40**，总计 **240**；T539 只读 live gate 此时返回 PREFLIGHT_PASS_NOT_E2E，6/6 live，0 stale。
- Robot 持续从真实 Binance aggTrade 生成 Tape instruction，下单 Trader 是独立 tape user，IOC 在与 Maker 相同的订单簿撮合，未修改 Order/Trade/Common 的业务/持久化边界。

## 真实成交与认证 Trade 资金核对

独立读取 Order A/B 真实业务发布的 Terminal=RobotSvr-Tape / TimeInForce=IOC / ExecType=Trade / OrdStatus=Filled，解析 ExecID 和 location；一轮实际统计 **520 个 Filled IOC、520 个不同 ExecID、重复 0**，覆盖全部六个 location，Order A/B 都有实际 Filled 发布。

Trade Projection 同窗口记录 **510 个原子匹配事件**、**1,020 条 POSTING**（每事件恰好 2 条）；invalid pair=0，posting locations=6，余额表最近更新 locations=6，projection age=5s。来源为 TRADE_ATOMIC_MATCH_PAIR_PREPARED，不是仅构造订单或入金。另一实时采样则有 411 个原子匹配事件 / 822 posting，校验始终 2/2。

本地只读 E2 脚本：
    python3 tests/check_trial_robot_trade_e2_readonly.py \
      --mysql otc-t529-fresh-mysql \
      --order-a otc-t531-order-a-e2-abcontrol \
      --order-b otc-t531-order-b-e2-abcontrol \
      --minutes 10 --min-locations 6

实际返回 **PASS_LIVE_BUSINESS_NOT_HA**，无 reasons；它检查 6 Trial complete、6 live Robot、双边订单、Order Tape IOC 真正 Filled 和 ExecID 去重、Trade 原子 POSTING 双边一致性、6 地点余额表更新以及 Trade 投影水位新鲜度。不打印秘密或账户 payload；所有操作只读。配套 7 项 unittest PASS，并已接入 tests/test-mac-colima-saas.sh 的离线单元回归。静态测试 PASS 不能代替调用以上现场脚本。

瞬时资源采样：APSSvr 2.64% CPU / 295 MiB，Robot 19.04% CPU / 236 MiB，AdminSvr 0.85% CPU / 307 MiB，ProjectionSvr 5.31% CPU / 229 MiB。非标准化压力基准，不作为 50/200 租户指标。

## 仍需完成/不可误报

1. **正式发布**：完全使用最新版 saas-crypto APS 源码通过完整 Maven package/测试生成正式多架构镜像，更新 Compose 镜像版本；本轮只有本地隔离验证镜像，旧 Broker CUSTOM 配置和容器仍保留。
2. **A/B HA 故障注入**：本轮无 Trade/Order 主节点 SIGKILL、连续双向自动接管、恢复/追平与一致性实测。Common E2/严格签名存储机制不得由 T541 的业务 PASS 代替。后续应在可控备份和真实机器人持续交易时独立执行，检查完整 WAL、资金/委托和无重复成交。
3. **Binance REST** 仍为 HTTP 451，依赖 REST 的交易所元数据/其它 Broker 功能不可据此验收；实时行情 WS 实测可用。不要通过更换隐蔽地区或虚构价格规避权限问题。
4. **旧 dc_orders_execorders 查询表** 本轮没有新增行，虽然 Order A/B 发布真实 Tape Filled，Trade 认证 Projection 持续更新；这可能是旧 MySQL 只读查询表未接入认证事件，Web 的最近成交/时间显示仍需另外核查。不要为了看起来 PASS 人工补历史数据或改写权威 WAL。
5. 保留日志/配置/发布受保护，继续执行长时间稳态、50/200 租户和 HA 测试，不要在未验证前关闭已恢复的 Robot。

失败后回退 APS：停止 otc-t541-fresh-apssvr，启动原 otc-t535-fresh-apssvr-custom（原 Broker 自定义行情隔离环境，不提供新租户默认 Binance 行情）；不要破坏现有 Order/Trade/MySQL 业务数据。