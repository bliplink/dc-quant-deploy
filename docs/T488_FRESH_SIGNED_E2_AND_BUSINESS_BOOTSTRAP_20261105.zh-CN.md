# T488｜独立开发集群签名 E2 READY 与业务 JVM 首次启动（2026-11-05）

## 总结

**真实控制面签名 E2 READY：Order 256/256、Trade 256/256，已通过独立 ZooKeeper 读回。** 全新 T488 Order/Trade 业务 JVM 的启动已推进到三个 Spring 应用成功启动（Order A/B、Trade A），Trade B 容器已启动但尚未拿到 Spring 完成的独立确认。**不代表真实交易、Robot 和自动 A→B→A HA 通过。最终仍 BUSINESS HA NO-GO。**

本轮严格保留旧 T398 数据、ZooKeeper namespace 和现有四个旧容器，不伪造 READY，不覆盖原始 A/B RSA 出生文件。所有 T488 数据都创建在新的开发命名空间与 Docker 卷上。

## 1. 全新物理与签名控制面：实测 PASS

- 全新真实 ZK 路径 `/otc/t488-fresh-20261105-r1/order` 和 `/otc/t488-fresh-20261105-r1/trade`。新会话票据、新 manifest，E1 初始 version=0、256 行 `STRICT_QUORUM|RECOVERING`、READY=0。
- 全新 Docker 管理卷 `otc-t488-born`（原始出生）、`otc-t488-data`（恢复事务），使用同一真实三节点 ZooKeeper。原 `otc-t398-born` 和 `otc-t398-ready-data` 没有挂载。
- 真实 Order A/B、Trade A/B 四个独立 JVM 各自使用原物理 RSA 身份，在真实 ZK 的 E1 RECOVERING 状态生成 256 个本地持久签名 Genesis：全部输出 `COMMON_FIRST_BOOT_ONLY_LOCAL_RSA_E1_VOTER_FLEET_FSYNC_PASS`，四节点共 1024/1024，业务 READY=false。
- `tests/T488OriginalE1DualPhysicalGenesisSeal.java` 在无网络容器中重新打开两物理出生源，核对原始 Genesis 字节、两个不同 pinned RSA-2048 签名、两份原零 ACK WAL，Order 256/256、Trade 256/256 两轮核验后 sealed：`T488_ORIGINAL_E1_DUAL_RSA_PASS`，没调用 READY。
- 对四个真实独立节点的 RECOVERING 事务打开真实 ZooKeeper 会话，保证 A/B 原始零写入证据，执行实际 business baseline 的 fenced INSTALL；每个节点 256/256 的 `*.recovery` 账本 `phase=REPLAY_COMPLETE`、`replaySeq=0`，合计 1024/1024。旧 A 的临时 ZooKeeper 会话确实终止，B 的独立会话仍在。
- Order 和 Trade 原始 A RSA 签名分别执行原生 `CommonOriginalE1FirstReadyActivation`，两边均输出 `COMMON_ORIGINAL_FIRST_E2_READY_CAS_PASS service=... partitions=256 signedGenesis=true businessServing=false` 且退出码=0。
- 新独立只读 ZK 会话运行 `tests/T488SignedE2ZkReadback.java`：两份 Manifest **version=1、generation=2、Epoch2 256/256 严格 READY，A Primary=P000–P127（128），B Primary=P128–P255（128）**，各互为 Replica，逐字段独立匹配。证据 `T488_INDEPENDENT_SIGNED_E2_ZK_READBACK_PASS`。**此 READY 是 Common 原始签名控制面，绝不是客户业务健康声明。**

## 2. 全新业务数据库：DDL 隔离、无旧交易数据

- 使用正在运行的 MySQL8 容器实例，但**新建** `dc_t488` 和 `event_t488` 两个数据库，只把 T398 的 `dc` 55 张表的 DDL 拷贝到 `dc_t488`，没有复制任何旧业务行。旧 `dc` 保留且没有 DDL 变更。
- 正式业务账户对新库有被验证的授权。新连接目标是 Docker 网络 `otc-t398-mysql:3306/dc_t488`、`.../event_t488`，不是旧库。
- 复用已有 ClickHouse 服务器进程，但新建独立 `dc_t488` 数据库。原 `dc` 的 `kline`、`market_trade` 表结构和 `kline_view` 视图逻辑复刻到新 `dc_t488`，不复制任何行情/成交数据；3/3 对象 PASS，应用账号访问已通过测试。新 JDBC 指向 `otc-t398-clickhouse:8123/dc_t488`。
- 新 `otc-t488-ready-data` Docker 卷专用于新 E2 业务 WAL、业务数据库本地状态和快照，不挂旧 4 容器。
- 新宿主配置 `~/.opentradingcore/t488-ready-20261105-r1` 包括四服务各自私有 `application.properties` 以及控制 `DBPoolConfig.ini`、`jaas.ini`。**这些文件含敏感私有认证，不能上传 GitHub/复制到答案中。**

## 3. 正式 Spring 业务首次启动：取得真实阶段进展

- 使用已经通过 Java 8 全量编译和回归的 T485 ARM64 离线镜像 `local/otc-t485-ordersvr:full-source-no-go` 和 `local/otc-t485-tradesvr:full-source-no-go`；新服务连接原签名 T488 Genesis、独立 E2 真实 ZK 和独立数据库。
- 新 JVM：`otc-t488-order-a-ready`、`otc-t488-order-b-ready`、`otc-t488-trade-a-ready`、`otc-t488-trade-b-ready`。`Order A/B` Spring 分别输出 `Started OrderSvr in 10.714 seconds`、`10.599 seconds`；`Trade A` 输出 `Started TradeSvr in 11.001 seconds`。Trade A 还明确输出 `TRADE_COMMON_SIGNED_BALANCE_STATE_OWNS_STARTUP`、`TRADE_COMMON_SIGNED_POSITION_STATE_OWNS_STARTUP` 和旧全局委托重载被禁止。Trade B 容器已启动，但最后一次只读日志请求被执行环境阻止，Spring 完成状态尚未确认，**不可把容器 UP 当作业务 READY**。
- 这些业务测试节点明确设置 `order/trade.common.nodeRuntime.automaticRecovery=false`，临时使用已有 `CommonOriginalFirstReadyBusinessGate` 做首轮 E2 签名业务状态验收；**没有**通过空假 `DurablePhysicalRecovery` Bean 绕过自动 HA 认证。
- 新 Gateway discovery 保持关闭，防止未经完整业务核对的新测试节点抢占旧系统交易路由。仍须完整核对 Netty A/B 对端、物理 E2 分区 WAL 双签 CommitIndex/Custody、租约与新数据库。
- 首次运行新服务时，Common 正确拒绝了缺失的 E2 WAL 根目录（`Common warm E2 signed physical WAL root absent`），只在新 `otc-t488-ready-data` 卷创建 4 个空节点根后重启，Order A/B Spring 正常启动；**未放宽 Common 的拒写逻辑**。
- 新容器通过 `-Dzookeeper.sasl.client=false` 与当前明确没有 SASL 的三节点开发 ZK 通信；配置文件 `jaas.ini` 仍作为只读现有启动依赖存在。没有发明身份或者替代实际 ZK 授权。

## 4. 未完成与不可越界项目

- **正式 Order/Trade 自动 A→B→A HA 仍 NO-GO**：`OrderCommonAutomaticRecoveryDependenciesWiring` 需要真实 `orderCommonCertifiedPhysicalRecovery`，Trade 对应 `tradeCommonCertifiedPhysicalRecovery`，生产级 `DurablePhysicalRecovery` 真实来源与 256 分区 AUTO Watch / C 外部 witness / 签名 WAL/Custody、Epoch 回切尚未全部接通。
- 本次应用启动没有证明新租户能注册、自动审批、Robot Maker/Tape 报价、入金、委托/成交/资金/持仓/Projection 正确，也没有对 T488 业务容器真实注入两次 SIGKILL。绝不混淆 Demo 的早前 PASS。
- 初始 E2 证据全部为 **零客户 WAL 的真正原始 signed birth**，当前不能拿来证明非空交易期间故障重放、严格双副本 RPO0。
- 当前 T488 仅是独立开发测试；旧容器 `otc-t432-order-a-restored`、`otc-t453-order-b-standby-parent-watch`、`otc-t436-trade-a-margin`、`otc-t452-trade-b-windowed` 及其 T398 ZooKeeper/卷均未停机/改动。
- 最后一次实时读取四服务日志与 ZK 租约的执行调用被平台安全检查阻止，**没有绕过**。因此需要在获准的执行环境中完成物理租约/业务就绪检查和下一步业务 E2E。

## 5. 后续 GO 门禁

1. 四个 T488 JVM 均实际 Spring STARTED；新 ZK 256 物理授权读回，A/B 128:128，真实 Netty WAL、CommitIndex、Custody 2/2 物理签名；新库所有需要的迁移与 E2E 准备。
2. 接入独立 Gateway，进行新租户→自动审批→两个 Trader API Key→入金→Robot Maker/Tape→真实下单成交；资金、持仓、订单、成交、Projection 逐项一致。
3. 以 Common 为唯一 HA 驱动接通真实 `DurablePhysicalRecovery` 和第三方 C 签名外部 local RPO transition（不能假签已 SIGKILL 的 A），真实 A SIGKILL→B 自动接管继续交易→A 追平→B SIGKILL→A 接管→B 追平。
4. 严格模式 256 分区双副本 fsync 证据、故障期 LOCAL ACK 的真实 RPO 风险披露及 10/50/200 tenant 压测和故障注入之后方可宣称 GO。

**进度结论：新 T488 物理 Genesis、持久恢复 1024/1024、双签 E2 READY 256/256 与至少三台业务 JVM Spring 启动实测有效；正式机器人交易+自动双向 HA 仍未完成。**
