# T533｜Common 消费者 JAR 一致性、真实 512 分区路由和行情 DNS 故障排查（2026-11-06／Mac 本地 11-07）

## 结论

**新独立环境（T529–T533）的四个 Order/Trade E2 业务 JVM 仍运行，重启 0、OOM 0；各节点存在 256 个本地 `business.wal` 文件。** T533 对 Projection 的旧 Common JAR 做版本统一，验证了真实四节点 TCP 连接和全部 512 分区的 ZooKeeper 权威路由与 Gateway 物化记录完全一致。新增部署前静态拒绝脚本并推送到 `saas-crypto-latest`。

**仍然 NO-GO：** 没有新租户审批、正式资金入账／限价或市价成交、非零 Projection 消费水位、真实价格流、SIGKILL 自动 HA 证据。业务节点启动和 WAL 文件数量不是写入 ACK、成交或者 A/B 复制成功的证明。

## 一、Projection 旧 Common 版本不一致：查证、真实替换与回退

- 新 T532 Projection 镜像 `local/otc-t454-projectionsvr:common-zk-rejoin` 自带 `/srv/dc/dc/ProjectionSvr/lib/com.app.common-3.0.15.jar`，而 Order A/B 和 Trade A/B 实际加载相同 SHA256 `b170df0dffd6d8cbeeb64ff3ac9865fe5a89aa803d49580bf0d78eae123801b2` 的 T523 Common。
- 原 `otc-t532-fresh-projectionsvr` 已停止但保留，供回退。新候选 `otc-t533-fresh-projectionsvr-common` 使用原业务镜像、原隔离 MySQL、ZK、Gateway、日志与数据目录，**只以只读挂载方式**将上述 T523 Common Jar 覆盖原 JAR 路径。候选 Spring 正常启动、监听 `43042`、无 OOM、重启 0。
- 新候选 JVM 的真实 `/proc/1/fd` socket inode 与 `/proc/net/tcp*` 交叉核查：连接 OrderSvrA `43036`、OrderSvrB `43041`、TradeSvrA `43037`、TradeSvrB `43046` **各 2 条 ESTABLISHED**。这证明客户端真实 TCP 已连通，**但不代替 Fetch RPC 成功**。
- 候选启动时有首批 `CodeException:[1015] SERVER.OrderSvr is not Online partition=Pxxx`，随后不再持续出现同类 GAP 重试；在没有交易事件、无非零消费水位的情况下，不能确认是否已成功读取认证 WAL。**Projection 持久化及财务读模型 E2E 仍 NO-GO。**
- 为避免下次更新 Common 后留下旧 Projection 客户端 JAR，加入可复用 `tests/check-common-jar-consumer-parity.sh`，可检查任意数量的单机／集群消费者 JVM 内 Common JAR SHA，实际 T533 五个 JVM **5/5 PASS**。脚本不会改变运行态，也不修改 HA 权限。

## 二、512 分区 ZK 权威与 Gateway 只读投影：512/512 PASS

使用新隔离 ZK `otc-t529-fresh-zk`、端口 `42181`，通过真实 `zkCli.sh` 批量读取：

- Order 权威 `/otc/t530-fresh-20261106-r1/order/manifest`：`NPC1|2` 的 **256** 个 `STRICT_QUORUM|READY` 分区；物化 Gateway `/dc/cluster/ordersvr/partitions/P000…P255` 也有 **256** 条。
- Trade 权威 `/otc/t530-fresh-20261106-r1/trade/manifest` 和 `/dc/cluster/tradesvr/partitions/P000…P255` 同样各 **256** 条。
- 每个分区逐项比对 `partitionId`、`epoch`、`primary`、`replica`、`state`、`assignmentVersion`：**Order 256/256，Trade 256/256，不一致 0**。
- 该检查仅是当前静态路由一致性；没有 SIGKILL、实际客户 WAL 写入，也没有证明复制 ACK 与主切；没有手工改写 Epoch、路由或 RSA。

## 三、行情 APS 数据源网络故障的两层证据

- T532 APS 与旧 T399 APS 都在 Docker host network 下没有可用 `/etc/resolv.conf` nameserver，连 `example.com` 都无法解析。原因是 Colima 的 host-network Docker resolver 内容为空；**不是** APS/MD 的业务价格公式异常。
- 使用用户 Mac 上现有配置的**局域网 DNS** 在单独 `docker run --network host --dns ...` 内真实测试，`example.com` 解析 PASS；T533 `otc-t533-fresh-apssvr-dns` 也能解析外部域名并正常注册 `43035`，从 `UnknownHostException` 变成真实连接失败，IPv6 报 `ConnectException`。
- 进一步以 `-Djava.net.preferIPv4Stack=true` 新起候选 `otc-t533-fresh-apssvr-ipv4`，仍使用本机局域网 DNS、原有 Binance URL、业务配置与相同镜像：进程、ZK 注册、`43035` PASS，但 WebSocket 连接报 `SocketTimeoutException: connect timed out`，连续重连，无可核验成功接收的标记价格／盘口成交流。
- 因此 **DNS 配置缺陷已确认并有正常修复途径；外部 Binance WebSocket 实际连通性仍 NO-GO**。没有使用替代 DNS 绕过网络限制，没有伪造行情或放宽价格有效性；现有 `otc-t533-fresh-apssvr-ipv4` 运行以保留自动重连机会，但不能作为可靠报价来源。
- 新增 `tests/check-host-network-dns.sh`：真实新候选含 nameserver **PASS**，旧 T399 APS 无 nameserver 的反向用例被正确拒绝 **PASS**。脚本只读，不会改动宿主 DNS。

## 四、隔离环境现场和风险门禁

- 新 MySQL `otc-t529-fresh-mysql`（34306）、新 ZK（42181）、Gateway `otc-t531-fresh-gateway-cluster`（43002）、Login/Manager/Admin、Order A/B、Trade A/B、Projection、MD、ClickHouse、APS 等独立候选均已配置；ClickHouse 独立卷初始化 3 张行情表，**没有把旧 MySQL 投影水位混入**。
- 旧 `otc-t523-{order,trade}-{a,b}-hostready` 等业务容器及原历史数据库仍保留。旧 T454 Projection 和 T438 Robot 继续停止，防止历史 MySQL 水位直接消费新 Common WAL。
- T532 全新租户自动审批提交步骤被平台的执行环境安全检查**拒绝执行**，没有试图绕过，也没有提交过该测试申请。正式现金入账、Robot 创建、下单成交、资金持仓更新、Projection 同步，均没有可核验成功结果。
- E2 Order/Trade A/B 的本地原始 WAL 目录各有 256 个 `business.wal`，但没有客户写入。只读检查未观察到业务 JVM 对彼此物理复制端口的稳定 ESTABLISHED 出站连接；可能与空载惰性连接有关，**不能据此宣布复制失败，也不能据此宣布复制成功**。

## 下一关键动作（不扩大架构）

1. 使用获准的正式测试租户创建流程／现有预授权测试凭据，在新 34306 数据库下走 **自动审批→Broker/Trader API 认证入金→限价委托→实际撮合→撤单/平仓→资金/持仓/流水**。不得绕过认证或复用旧数据库原始水位。
2. 新 tenant 确认后接好自定义 APS 价格源，或在允许且真实连通的环境使用原 Binance 源；TTL 仍按原规则过期弃用。没有有效行情前不把 MD／Robot／Tape 计入 PASS。
3. 对每笔真实交易对照 Common A/B WAL／真实 ACK、Order 状态、Trade 余额/持仓、Projection 与 MySQL，禁止出现双主和重复成交。
4. 完成交易真实业务 PASS 后，执行自动 SIGKILL A→B→A（含恢复追平和旧主隔离），并区别 STRICT 与 LOCAL 写入保障；目前自动 HA **NO-GO**。
5. 未来生成正式新镜像时必须对所有使用分区客户端的业务消费者锁定同一个 Common JAR SHA，执行新增的只读版本和 DNS 检查；当前 Projection 是*临时只读挂载*候选，不是假装已更新正式镜像。

**本轮没有修改 Common 集群协议、Order/Trade 业务代码、资金状态或客户数据；没有进行任何未授权交易。**
