# T539｜Mac Fresh Robot 自动初始化与行情阻塞（2026-11-07）

## 最终状态

**Robot 专用 Gateway 身份、AdminSvr Trial Worker、Maker/Tape 用户与资金和 Robot 任务初始化已在 Mac 隔离 Demo 恢复；双边报价、Tape 真成交、业务 HA 最终验收仍 NO-GO。**

不修改 Common/Order/Trade/MD 集群机制，不清理业务数据，不虚构价格、订单或成交。

## 真实根因与证据

1. T529 fresh MySQL 原有 6 条 dc_tenant_liquidity_bootstrap，全部 PENDING/CREATE_MAKER，dc_tenant_robot 为 0。现有 TrialLiquidityBootstrapWorker.java 使用 @Service/@Scheduled，并以 TRIAL_LIQUIDITY_BOOTSTRAP_ENABLED=true 开启完整 Maker、API Key、资金、Tape、Robot、VERIFY 工作流，无需再写一套初始化实现。
2. 原 T529 fresh Admin 容器没有任何 TRIAL_LIQUIDITY_* 环境键，虽然受保护的 .env.prod 已经启用该 Worker。该特定隔离部署绕过了正规 Compose 环境注入；正式 compose.yaml 已设置这些变量。
3. 原 T535 fresh Robot 容器因 ROBOT_GATEWAY_USER is required 退出。T538 已建立 PLATFORM/robotsvr 与 ROBOT_RUNTIME API Key（均启用）；旧容器没有注入 Robot 环境变量。
4. T535 自定义 Broker 价格测试专用 APSSvr 配置 enableBinanceFlag=false，而 Trial Worker 为新租户创建的默认 Robot 源是 APSSVR_BINANCE_TICKER，两个模式不一致。Canonical generate-saas-configs.sh 默认 enableBinanceFlag=true；这是隔离测试配置不匹配，不是标准一键部署主脚本关闭 Binance。
5. 恢复隔离 APSSvr 的 enableBinanceFlag=true 后，日志持续出现 java.net.UnknownHostException: fstream.binance.com，实际无可靠 BookTicker/Depth/Mark 发布。Mac 直接 Binance HTTP 超时、现有本地代理返回 HTTP 451；普通 Cloudflare 访问 HTTP 200。不能绕过上游限制，更不能使用空盘口/过期价格对外报交易成功。

## Mac 真实恢复动作

- 保留旧 T529 Admin 的原镜像和数据卷，停止旧容器；以原镜像、数据挂载和受保护原配置新建并启动 otc-t539-fresh-adminsvr，补齐 TRIAL_LIQUIDITY_* 环境及真正 Gateway 地址 http://127.0.0.1:43002/httpapi/。Spring Worker 已开始领取并执行持久任务。
- 保留退出的 T535 Robot 及挂载卷，复用其镜像，通过专用 PLATFORM/robotsvr Gateway/Runtime 凭据及 TCP 43000、HTTP 43002 启动 otc-t539-fresh-robotsvr。实际日志有 ROBOT_MD_FILTER_RECEIVED 和 ROBOT_T420_PHASE，证明 Gateway 登录后已开始收行情/运行策略。
- 为隔离 APS 复制只读应用配置，启用 Binance BookTicker、Depth、Mark 取价并启动 otc-t539-fresh-apssvr；保留原 T535 自定义 Broker 配置用于回退。源地址 DNS/连接失败，订单因此正确拒绝过期价格。
- 临时私有配置存放在 Mac 用户的 ~/.opentradingcore/t539-fresh-robot-resume，目录 0700、环境文件 0600；未提交仓库、未打印密码/API Secret。没有执行 SIGKILL/删除持久卷。

## 业务只读数据

2026-11-07 Mac fresh 现场：

| 指标 | 实测 |
| --- | ---: |
| Trial bootstrap jobs | 6 |
| Maker 资金确认 | 4 |
| Tape 开启/资金确认 | 4/4 |
| 已创建并启用 Robot | 4 |
| Robot 30 秒内健康且双侧挂单至少 2 笔 | **0** |
| Robot STALE_MARKET_DATA | **4** |
| Trial 完成全部 VERIFY | **0** |
| 真实 Tape 成交/Projection 对账 | **未通过最终验收** |

因价格源缺失，部分任务在 VERIFY 阶段重试或失败。完整交易恢复仍为 NO-GO。

## 防复发工具

新增 tests/check_trial_robot_live_readiness.py：对指定 Admin/Robot/APS/MySQL 容器进行**只读**检查，验证实际容器环境、同一 Robot 身份、正确 Gateway 端口、有效 APS 源、Binance DNS 故障证据、初始化记录、持续双边报价数量。脚本不输出密钥或业务用户数据，不执行 SQL 写入。发现缺失直接返回 exit 2/NO_GO；即使基础检查通过，也**不能替代真实订单、Tape 和 HA 验收**。

tests/test_trial_robot_live_readiness.py 的 6 项 unittest 均 PASS。现场预检为 NO_GO/exit 2，原因 BINANCE_DNS_UNAVAILABLE 和 NO_LIVE_TWO_SIDED_QUOTES。

下一项必须先恢复**合法、持续更新的 Binance 上游价格**，或明确经产品配置切换为受租户隔离、具备 TTL 的自定义 Broker 价格源，不能把租户私有价格伪装成公共 Binance 价格。其后让现有 Trial Worker 完成 VERIFY，核对盘口、Tape、真实成交、资金/持仓/Order/Trade/Projection。继续复用既有 Mac 一键部署流程，不新增第二套集群/Robot 初始化框架。

## T539 后续复测与安全回退（2026-11-07 14:48 后）

继续执行持久任务后：6 条 Trial bootstrap 记录均有 Maker 资金确认，其中 5 条 Tape 资金确认，5 个 Robot 已创建启用，但没有任何一个拥有双边挂单。1 条仍在资金权限收尾；VERIFY 因价格源无效进入 RETRY/FAILED。实时进度会变化，不应把上表早前 4 个 Robot 的中间值当成最终进度。

启用 Binance 的 T539 APS 实际连续报 UnknownHostException，连接数快速增长；为避免 DNS 重试风暴和日志资源浪费，**已停止 otc-t539-fresh-apssvr，并启动原 otc-t535-fresh-apssvr-custom**。原 Broker 自定义数据源测试配置恢复；T539 新 APS 容器及文件保留可审计，不作为当前有效的 Binance 源。T539 Admin 与 Robot 仍在运行。

对实际恢复后的旧自定义 APS 重新运行只读门禁，返回 exit 2：BINANCE_SOURCE_DISABLED_OR_NOT_RUNNING、NO_LIVE_TWO_SIDED_QUOTES。当前仍未获得合法公共 Binance 行情和任何真实 Robot 双边委托、Tape 成交。标准一键部署的用户初始化/环境门禁与公网行情可用性是两项独立要求，后者不能被前者 PASS 代替。
