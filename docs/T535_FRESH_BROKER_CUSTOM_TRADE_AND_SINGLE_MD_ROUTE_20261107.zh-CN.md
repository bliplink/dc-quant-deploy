# T535｜全新环境 Broker 自定义价格、真实订单成交与单机 MD 路由修复（2026-11-07）

**结论：全新租户真实交易主链路 PASS；完整订单变更、自动 HA、外部 Binance 行情仍 NO-GO。**

本轮直接在 Mac T529–T535 完全隔离的新 MySQL（34306）、ZK（42181）、Gateway（43002）、Common 物理 E2 Order/Trade A/B、MD、APS、Projection 上运行正式 Gateway API 和自动化 E2E。旧 T523 业务容器和旧业务数据库没有被重置、覆盖或拿来提供新业务成功证据。GitHub Actions 未使用；源码由本地 Java 8 编译及真实 Docker JVM 验证后通过 GitHub API 提交。

## 1. 逐阶段的真实 E2E 证据

### T535-1｜新租户自动审批与会话
`TENANT_APPLICATION_E2E_ENDPOINT=http://127.0.0.1:43002/httpapi/ python3 tests/verify-tenant-auto-approval.py`：进程 exit 0；新租户 `CN8U7C` 自动审批、租户管理员登录、同一请求幂等重试 PASS；另一个五产品申请正确进入 `PENDING` 人工审批队列。全过程使用正式 Manager/Login/Gateway；无 SQL 手工插入或密码泄漏。

### T535-2｜Broker 初次自定义测试失败与根因
`tests/test-custom-product-live-e2e.py --execute --with-traders` 第一次创建 `BML3DA`；自动审批、管理登录、创建自定义数据源与 `BTC003USDT`、绑定新源、匿名可见与租户隔离、Broker API Key 签发/签名登录 PASS；`APSSvr.publishBrokerPrice` 返回 `9000 INTERNAL_ERROR`，测试停止并撤销 Broker Key。

**实际根因一：** 原 T533 APS 配置没有 `broker.price.publish.enabled`，Handler 默认 fail closed；原 `enableBinanceFlag=true` 仍不断对无外网的 `fstream.binance.com` 重连。本轮仅在本机隔离候选 `otc-t535-fresh-apssvr-custom` 挂载配置，显式设置 `broker.price.publish.enabled=true` 与 `enableBinanceFlag=false`，由原有 Broker API Key / TenantAPI Session 校验、源身份和 TTL 规则处理请求，**未在源代码里削弱验证逻辑、未手工写价格或 MySQL**。旧 APS 容器停止但保留可回退。候选是真实 Broker CUSTOM 测试，不是生产默认开启、也不是来自 Binance 的实时报价。

### T535-3｜APS 接收、MD 公开查询先失败后修复
测试新租户 `A2I12Z`：Broker 自定义标记价 `90001` 返回 **`ACCEPTED`**，两名测试交易员各通过认证业务接口入金 1,000 USDT；但 `MDSvr.queryPublicMarket` 从 Gateway 返回 `9000`，在 MD 内没有对应业务拒绝日志。

**实际根因二：** 新环境 `MD_CLUSTER_ENABLED=false` 运行单机 `SERVER.MDSvr`，而 `SaasGWProxy.publicMdTarget` 无条件走 `PublicMdPrimaryRoute`，强制要求 **Multi-MD 分区分配／Epoch／MDSvrA/B**，导致在单机 MD 上找不到分区证据。新代码设置 Spring 属性 `mdClusterEnabled`：
- **单机 MD**：通过已有 `MDSvr` 服务发现路由查询，不伪造分区 Epoch/证书。
- **Multi-MD**：完全保留原 `PublicMdPrimaryRoute` 的 Common ZK Assignment / Epoch / Primary / READY 严格校验。属性未设置时默认 `true`，以免旧集群配置静默降级。
- `generate-saas-configs.sh` 根据 `MD_CLUSTER_ENABLED` 生成明确的 Spring `mdClusterEnabled`，同时 `tests/preflight_saas_cluster_config.py` 检查 XML 与环境模式相符，单机和集群配置不再混用。

本地 Java 8 + JUnit `SaasGWProxyTest` 与 `PublicMdPrimaryRouteTest` **8/8 PASS**；其中单机不得捏造 Epoch，集群没真实认证分区必须拒绝；部署工具前置校验 **9 项测试 PASS**。新的 Spring XML 已由生成器为 T535 独立控制目录生成，并通过 ZK/端口/模式的只读预检。新 Gateway 真正经 `127.0.0.1:43002` 返回 `MDSvr.queryPublicMarket: code=0`。

**源码跨仓库发布一致性：** `bliplink/gw` 原来没有 `saas-crypto-latest` 分支；本轮从该仓 `saas-crypto` 创建新 `saas-crypto-latest`，取其*最新远端源码*补入以上小范围修复，保留远端近期更新的 `OpenApiIngressSecurityCheck.isAnonymousPublicMarket`；以该版本的 `SaasGWProxy` 和 `OpenApiIngressSecurityCheck` 联合本地编译重新跑 **8/8 JUnit PASS**，而非拿较旧的本地源码直接覆盖 GitHub。最新 Docker Gateway 镜像：
`local/otc-t535-gateway:upstream-single-md-route`
SHA256 `a71372de32d7e5538bcda30a362ee1d79519d900edc49707acc222c1b16e146e`。
实际运行容器 `otc-t535-fresh-gateway-upstream`，旧 T535／T531 Gateway 保留可回退。修复后查询 `MDSvr.queryPublicMarket: code=0` 与 `AdminSvr.querySymbol: code=0` 都通过。

### T535-4｜正式 API 自定义价格+入金+限价撮合+Projection
**第一次完整成功：** 新租户 `J4BMAH`，原项目脚本在新环境执行 exit 0：自动审批、管理员登录、产品创建/换源、Broker Key 签名登录、价格 `90001` 经 APS→MD 公开行情实际回读、两位交易员各入金 1,000 USDT、Maker 限价 Sell 0.001 BTC @ 90000，认证 Order API 读回 `New`，Taker 对手 Buy 0.001 BTC @ 90000。新 MySQL 只读 SQL 验证**两笔订单 `Filled` + 两条实际非零执行**，并从认证 Trade API 读回：Maker 空仓方向 Short 0.001 BTC、余额 999.98200000 USDT；Taker Long 0.001 BTC、余额 999.94600000 USDT。测试退出前撤销 Broker Key。

**第二次最新源码／镜像对照成功：** 远端 GW 最新源码镜像 `otc-t535-fresh-gateway-upstream` 部署后，使用全新租户 `RU7WZO` 重复**相同正式 E2E，进程 exit 0**，全部 23 个检查点成功，包括同样的两笔 Filled/2 Executions、两个真实持仓及相同余额。只读 MySQL 再验证 `RU7WZO` 两笔订单均 Filled、2 个真实 Execution、2 个余额账户，当前新数据库的 Order Projection Event=21、Trade Projection Event=25，两个服务分别存在 3 / 4 个 Projection 水位条目。

**部署测试错误根因三：** 原 `tests/test-custom-product-live-e2e.py:readonly_sql` 把 MySQL Docker 容器硬编码为 `dc-saas-mysql`（旧 Demo），实际新环境是 `otc-t529-fresh-mysql`，导致在已经真实成交时报告 `Read-only MySQL verification unavailable`。现支持 `OTC_E2E_MYSQL_CONTAINER`＋`MYSQL_USERNAME`＋`MYSQL_PASSWORD`，以仅传继承环境变量的形式执行 `docker exec -e MYSQL_PWD ... mysql -N ... -e SELECT`，不打印密码，不改业务 SQL，不放开写权限。缺省旧 Demo 入口保留。读新 MySQL 返回原 2 条历史测试订单、任何 DELETE 被拒的负向测试 PASS。正确使用方法：

```bash
set -a; . "$HOME/.opentradingcore/t531-gateway-cluster-control/t531.env"; set +a
export OTC_E2E_MYSQL_CONTAINER=otc-t529-fresh-mysql
python3 tests/test-custom-product-live-e2e.py \
  --endpoint http://127.0.0.1:43002/httpapi/ --execute --with-traders
```

## 2. 真实 Common E2 原始 WAL 复制一致性检查

全部在**只读** Docker 数据卷 `otc-t530-ready-data` 验收。真实成交后，分别比较 Order A/B 与 Trade A/B 的各分区 `epoch-2/business.wal` 原始字节 SHA256：

- 针对非零成交/资金变动分区：`OrderSvr P217 / P147`，`TradeSvr P044 / P007 / P077`，A/B 对应文件 **5/5 字节相同**，其非空 WAL 大小依次 10,315、10,315、21,991、4,308、21,991 字节。
- 随后进一步遍历 **Order 256/256、Trade 256/256，共 512 对 WAL SHA256 全部相等**，其中 Order 3 分区、Trade 4 分区已有非零 WAL（随着新租户增加）；本次不是空目录的形式比对。
- **限制：** SHA 对比仅证明采样时磁盘字节相等，不等价于每条客户写入返回前严格双物理 ACK，不证明恢复截尾正确，也不证明断点自动重连 / A→B→A 故障切换。当前四节点 `automaticRecovery=false`，**自动 HA NO-GO**，未经授权不得拿 `SIGKILL` 直接验证这种未开启恢复的生产模拟系统。

## 3. 必须显式保留的 NO-GO

1. **Order 批量撤单没有完整接入 Common 原始持久路径。** 当前项目 `OrderStateJournal.beginSynchronousBatch():275` 直接抛 `ORDER_COMMON_DURABLE_BATCH_NOT_CONNECTED`；真实 `cancelAllOrder` 从 `OrderFacade.cancelAllOrder:601` 调用它并被安全门禁拒绝，最近 T535 E2E 最终清理阶段的日志可复现。E2E 的两个用户订单全部 Filled，测试清理阶段吞掉撤单错误以不使已达成的成交测试误失败；**不能把该 E2E PASS 扩大成所有撤单/改单/业务状态写入 PASS**。修复方向：业务状态差异先由业务层编码后使用 Common 现有提交 SPI，在成功提交后应用；不能去掉抛错、改为无持久化的直接取消或在 Order 中新建 WAL/选主机制。需要专门构造未成交挂单，再认证撤单并检查资金释放、原始 A/B WAL 与 Projection 一致。
2. **Trade 读 MD 单机价格的客户端仍有误用分区路由。** `com.app.dc.utils.MDSvrClient.mdPrimary` 从 `PlacementRegistry/PartitionRegistry` 强制查询 Multi-MD `Pxxx`；T535 对 `J4BMAH` 和 `RU7WZO` 的业务日志记录 `MDSvr partition is not routable` 警告，虽未阻塞上述 API 成交，仍可能影响 mark-price image / 清算等读取；应在 Common 通用客户端根据真实 MD 模式正确接线，**不要在 Trade 实现自建 HA**。Gateway 的单机公开行情已修复，但不是 Trade 客户端该缺陷的修复。
3. **外部 Binance 行情网络无法连接。** 在 Mac / Colima 上修 DNS、优先 IPv4 后仍 `SocketTimeoutException`，连 Coinbase、Kraken 等公共 HTTPS 也不能直连；本轮验证的 `90001` 明确是**认证 Broker 自定义测试价格**，不是 Binance 官方成交或无限期有效报价。正式 Robot/Tape 持续报价、标记价 TTL 过期、真实行情恢复 **仍未验收**。
4. **Auto HA / 多节点故障切换未通过。** Order/Trade 配置 `automaticRecovery=false`；未触发实际故障，不允许称为“集群完全恢复”。
5. **财务一致性需扩大覆盖面。** 现已确认 2 实际成交、两余额／两持仓、Order/Trade Projection 非零事件和 A/B 原始 WAL SHA 完整一致；但尚未做多租户 steady/burst、各种订单类型、旧主撤权、资金压力去重等全量回归。

## 4. 新增长期防回归规则

- **GW 单机 vs Multi-MD：** 必须通过同一 `MD_CLUSTER_ENABLED` 控制 `mdClusterEnabled` Spring Property；`tests/preflight_saas_cluster_config.py` 对 XML/环境值进行 fail-closed 比对，错配时不启动，防止将单机 MDSvr 当作 Multi-MD 分区 Primary。
- **新部署测试数据库**：`tests/test-custom-product-live-e2e.py` 的 MySQL 容器不再硬编码；必须指向实际隔离代际，查询限定 SELECT，绝不使用旧历史水位虚报 Projection PASS。
- **价格源**：外部数据源断连时，Broker CUSTOM 需要正式 signed Tenant API、源身份、对应产品绑定与 TTL，通过 APS→MD 真实事件验证；严格区分测试价与生产行情；仅在明确隔离的业务验收环境开启 Broker ingress，不更改生产默认 OFF。
- **发布源码一致**：Gateway 新修复落在 `bliplink/gw:saas-crypto-latest` 远端最新源码上，与 `bliplink/dc-quant-deploy:saas-crypto-latest` 的生成器和测试脚本同步；不能只改 Mac 临时镜像。
- **依赖与证据边界**：Common、Order、Trade 的 SHA/认证、Gateway 注册、真实成交、A/B WAL 和自动 HA 仍是独立门禁，不以一个 PASS 替代所有阶段。

本轮沒有修改 Common 协议、Order/Trade 的选主/复制实现，没有绕过授权签名或安全门禁，也没有宣称生产 HA GO。
