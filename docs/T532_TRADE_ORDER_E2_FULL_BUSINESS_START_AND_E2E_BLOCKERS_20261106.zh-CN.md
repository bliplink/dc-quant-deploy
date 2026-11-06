# T532｜Trade A/B 真实 E2、四业务 JVM 已接入及新租户 E2E 门禁（2026-11-06）

## 本轮实测判定

**真实物理恢复、Trade A/B E2 CAS、Order/Trade 四个 JVM Common 认证 Spring 启动及 Gateway 注册：PASS。**

**真实客户交易、认证 cashIn、Robot/Tape、Projection 一致性和自动 A→B→A：NO-GO。** 本轮未发布任何真实成交成功结论；没有取消 Common 的 RSA、原始 WAL、ACK、恢复、Fencing 或 Gateway READY 校验。独立 ZK 是单节点，只作为开发/首次部署，不具备三 ZK 控制面 HA。

### 本次真正完成的操作与证据

| 验证 | Order-A | Order-B | Trade-A | Trade-B |
|---|---|---|---|---|
| 全新 E1 双 RSA Genesis 原始出生 | T530 PASS | T530 PASS | T530 PASS | T530 PASS |
| 原始业务 Snapshot + WAL baseline + `*.recovery` | 256/256 | 256/256 | **256/256** | **256/256** |
| 非空快照/基线/恢复 Ledger | 0 个空文件 | 0 个空文件 | 0 个空文件 | 0 个空文件 |
| Original Home 双 RSA 签名 | T531 PASS | T531 PASS | **T532 PASS** | **T532 PASS** |
| 实际 E1→E2 CAS | T531 PASS | 同一 manifest | **T532 PASS** | 同一 manifest |
| 原生 E2 `business.wal` 数量 | 256 | 256 | **256** | **256** |
| 正式 Spring 实例 + Common Gateway 签发 | PASS | PASS | **PASS** | **PASS** |
| 本轮最终容器 | `otc-t531-order-a-e2-abcontrol` | `otc-t531-order-b-e2-abcontrol` | `otc-t532-trade-a-e2-ready` | `otc-t532-trade-b-e2-ready` |

- 真实运行 `otc-t532-trade-a-install` 和 `otc-t532-trade-b-install`，不再被先前执行环境拦截。两个真实 Trade JVM 都记录 `T157_COMMON_ZK_FENCED_TRADE_MAIN_JVM_BUSINESS_INSPECTION_PASS ... partitions=256`；隔离命名卷 `otc-t530-born` 双方各有 **256 `*.recovery` + 256 `baseline.properties` + 256 `*.snapshot`**，没有任何 0 字节文件。证据全部保留，非模拟。
- 停止原始安装监听后，等待 ZooKeeper 旧临时 Session Lease 自然过期，不手工删除 Lease。再次启动 `otc-t530-trade-a-home` 和 `otc-t530-trade-b-home`，两边均有 `COMMON_ORIGINAL_HOME_E1_PHYSICAL_RSA_FSYNC_PASS ... partitions=256 businessReady=false`；卷内有 `original-home.v1` 6472 字节及两份不同的 256 字节 RSA 签名。
- 由 Trade-B 真实恢复会话持有 47223 监听，Trade-A 真实运行 `otc-t532-trade-a-stage` 发起认证 CAS，打印 `COMMON_ORIGINAL_FIRST_E2_READY_CAS_PASS service=TradeSvr partitions=256 signedGenesis=true businessServing=false`。A 阶段正常 exit=0，旧 B E1 Recovery 退出（预期撤权）。
- 从独立 ZK `127.0.0.1:42181` 的 `/otc/t530-fresh-20261106-r1/trade/manifest` **重新读取**：`NPC1|2`、dataVersion=1、P000–P255 共 256/256 都是 `STRICT_QUORUM|READY`，没有无效分区。Order 的清单也已于 T531 认证并达 `NPC1|2`。
- 以相同实际物理 Common JAR `b170df0dffd6d8cbeeb64ff3ac9865fe5a89aa803d49580bf0d78eae123801b2` 在新独立 Gateway 控制目录启动 Trade A/B，分别记录 `COMMON_GATEWAY_CERTIFIED_PARTITION_ROUTING_PASS`、`COMMON_GATEWAY_DISCOVERY_CERTIFIED`、`Started TradeSvr`。真实 TCP 47422/47423（Common）和 43037/43046（Gateway）4/4 通；Gateway 日志明确连接 TradeSvrA/B。四个 Order/Trade JVM 最后均 running、restart=0、OOM=false，各 256 份 E2 `business.wal`；**文件存在不等于已提交真实用户金融交易**。

## T532 补齐的全新部署配套组件

沿用 T529/T531 独立控制根 `~/.opentradingcore/t531-gateway-cluster-control`、MySQL 34306、ZK 42181、Gateway 43002，不与旧数据集混用：

| 组件 | 新容器 | 真实结果 |
|---|---|---|
| Projection | `otc-t532-fresh-projectionsvr` | Spring `Started ProjectionSvr`，注册端口 43042，SQL 使用新库、watermark 0、Order/Trade events 0；**消费尚无成功 E2E 证据** |
| ClickHouse | `otc-t532-fresh-clickhouse` | 独立卷 `otc-t532-fresh-clickhouse-data`，HTTP 48123、TCP 49000；实际登录查询 `SELECT 1` PASS，初始化 `dc.kline`、`dc.kline_view`、`dc.market_trade` 三张表 |
| MD | `otc-t532-fresh-mdsvr` | 使用 querysymbol 版本镜像实际 Spring `Started MDSvr`、端口 43028 在线；**未验证新租户真实盘口更新** |
| APS | `otc-t532-fresh-apssvr` | 服务启动、端口 43035 在线；Binance 价格 WS 失败：`java.net.UnknownHostException: fstream.binance.com`，新环境无法证明获得有效外部行情 |

这四个补充容器最终均 running，无 OOM/重启。旧 `otc-t438-robotsvr-session-recovery` 和 `otc-t454-projection-common-rejoin` 仍停机，历史 MySQL 投影数据未删除或覆盖。原 T523 四个 Order/Trade 仍在其旧隔离环境，未替换。

### 未通过门禁及已证实的原因

1. **真实新租户申请／自动审批未执行。** 本轮尝试通过正式新 Gateway `43002` 调用 ManagerSvr `tenantApplication/SUBMIT`，同时安全生成并本地保护独立测试管理员登录凭据，但操作被执行环境安全检查拒绝。没有提交申请、没有生成租户、没有真实余额。只读 SQL 再查 `dc_tenant` 和 `dc_tenant_application` 仍分别为 **0 / 0**；没有通过数据库直接插入伪造自动审批，也没有规避平台阻止。
2. **APS 外部行情 DNS 失败。** 日志明确为 `fstream.binance.com` 无法解析；即便服务端口在线，也不能宣称 Binance 价格可用，MD 盘口、Robot 自动报价和 Tape 点价均未验收。宿主机和容器 DNS 解析行为仍待网络诊断，无根据地更换公网 IP 或混用旧行情不能当作修复。
3. **Projection 读取证据不足。** 新 Projection 已启动但初次安全轮询日志对 P000–P015 报 `CodeException:[1015] SERVER.OrderSvr is not Online partition=...`。实际独立 ZK 里 `/dc/cluster/ordersvr/partitions/P000` 及 P128 已具有来自 Common 认证发布的 E2 路由，四业务节点 Gateway 也在线。消费者启动时可能存在初始化时序，但没有真实成交及 SQL 水位推进，**不得报 Projection PASS**。后续需要确认新消费者能按 Common 原始 Partition Primary 路由取回签名业务批次，并验证不重复回放。
4. **自动 HA 与降级 LOCAL 未执行。** `automaticRecovery=false` 的真实首次 E2 业务成功不等于自动主切成功。当前单节点 ZooKeeper 不具备 ZK 自身 HA。需要随后跑完整 A SIGKILL→B 接管→A 追平→自动原主恢复→B SIGKILL→A 接管，检查无双主、真实物理 ACK、资金/订单/持仓/Projection 一致性；不能将人工 E1→E2 首次 CAS 冒充自动切换。
5. **读取匿名 Trade Gateway 返回 `AUTHENTICATED_SESSION_REQUIRED`。** 这证实网关拒绝了无认证请求，是预期的安全限制，**不能作为真实下单或资金入账通过证据**。

## 下一阶段只做真实业务闭环

- 先在允许执行正式测试租户申请的环境完成独立新租户自动审批、创建交易员、Broker API/Trader API 认证 cashIn；所有登录凭据留在本机私有目录，不入日志、Git 或回应。
- 修复 APS 外部行情 DNS／订阅成功，或使用合法已认证 Broker 自定义价格源，先实测 MD `querysymbol` 标记/指数价格、盘口和最近成交。
- 然后部署新 Robot 实际挂价、Tape 成交，用真实限价/市价成交检查 Order/Trade A/B 原始认证 WAL 与各分区交易业务状态，资金冻结/释放/持仓和新 Projection 真正推进。
- 全部业务闭环有证据之后再启动 Common-only 自动 HA 真实故障注入和负载测试。任何 NO-GO 都不能修改业务或 Common 的签名/隔离门禁来伪造 PASS。

**本轮的可复核结论是：Order + Trade A/B 首次 Common 认证集群业务运行 PASS；真实交易、Projection、行情有效数据、Robot 和自动 HA 仍 NO-GO。**