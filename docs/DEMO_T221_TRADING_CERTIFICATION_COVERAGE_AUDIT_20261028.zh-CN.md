# T221｜Demo 新租户、自动 Robot、自定义价格与真实成交认证链路审计（2026-10-28）

## 测试基线

固定现有镜像，不重新部署 Order/Trade/Common：
- Trade A/B: local/otc-t220-tradesvr:push-only-md-topic，running，重启次数 0。
- Order A/B: local/otc-t209-ordersvr:certified-newing-cancel，running。
- APS: local/otc-t219-apssvr:binance-mark-1s；既有配置开关 broker.price.publish.enabled=true（仅启用已有 VerifiedBrokerPricePublisher，无业务代码变更）；原配置备份于 /Users/kong/.opentradingcore/dc-saas-runtime-clean-20261016/control/overrides/APSSvr/config/application.properties.pre-broker-e2e-20261028.bak。
- R0F6CC/t199-signed-live 保持 RUNNING；前一轮受控人工恢复的 Common P246 证据位于 ~/.opentradingcore/trade-ha-forensics/T220-P246-20261028-105400。

## 真正执行的 E2E

正式入口：python3 -u tests/test-custom-product-live-e2e.py --endpoint http://127.0.0.1:33002/httpapi/ --execute --with-traders

| 运行 | 新租户 | 通过 | 首个阻塞 |
|---|---|---|---|
| 第一轮 | WSI1WX | 自动审批、管理员登录、自定义源和产品、匿名可见、租户隔离、切换数据源、Broker Key 与签名登录 | APS Broker price 9000；当时既有发布开关未显式启用 |
| 第二轮 | U6ZAMX | 前述全部 | APS 9000；请求发生在 APS 重启完成之前（11:15:20），Spring 11:15:42 才启动完成 |
| 第三轮 | G6IQ8E | 前述全部，**Broker 价格发布返回 code=0 / ACCEPTED** | TradeSvr.setLeverage 返回 1003：TRADE_COMMON_DURABLE_WAL_ACK_NOT_CONNECTED |

三租户均为 TRIAL，**自动产生并启用 trial-liquidity-BTCUSDT Robot，各 RUNNING，open_order_count=40**；正式 MD queryPublicMarket(BTCUSDT) 每租户均有 10 档 Bid + 10 档 Ask 及有效标记价格。以上为三份真实 Gateway / MySQL / MD / Robot 的核验结果，不是隔离单元测试。

## 单一业务集成缺口，不要再修改 Gateway/MD/Robot

Trade 在 Common nodeRuntime READY 时严格禁止旧 mutate-first WAL 路径，这是正确的防护：
- src/main/java/com/app/dc/service/state/TradeStateCoordinator.java 的 requireWritable() 在 Common 启用时一律拒绝 executeMutation()。
- src/main/java/com/app/dc/handler/SetLeverageHandler.java 仍调用 executeMutation() + DataFacade.updateSymbolLeverage() + TradeConfigurationStateRecorder.recordLeverage()，因此 1003。不能为通过测试而打开旧 mutate-first。
- src/main/java/com/app/dc/service/order/OrderFacade.java 的认证模式只允许 Newing/OPEN 和 Trade_Cancel/Cancelled/OPEN；撮合成交产生的 ExecType=Trade 走 TRADE_COMMON_UNCERTIFIED_BUSINESS_PATH_DENIED，故 Maker/Taker 成交尚无法获得正式 Common 认证 ACK。
- CashInHandler 已有 TradeCertifiedCashInAdmission，且 Common 认证写入要求 Info1 稳定幂等请求号；已修复 test-custom-product-live-e2e.py 的现金测试参数（仅测试脚本更改，无生产代码更改）。
- CashOut、SetAccountConfig、SetPositionType 等旧 mutate-first 管理写路径同样需在上线前逐项盘点，不得当作已验收。

已有 TradeStateMutation.ACCOUNT_CONFIG、SYMBOL_PARA、ACCOUNT_BALANCE、POSITION、OPEN_ORDER、DEDUPE_RESULT、POSTING 模型和 TradeRecoveryApplier typed replay；不必再造状态机/复制协议。

## 集中修复范围（唯一可接受的实现）

1. **Trade 配置写入**：纯函数准备杠杆变更后的 SYMBOL_PARA + 受影响 POSITION/ACCOUNT_BALANCE；使用 TradeStateCoordinator.commitPreparedState，由 Common 完成真实双物理 WAL/Custody/RSA ACK 后才 apply，持仓状态和幂等重放要同一来源。
2. **Trade 成交回报**：将 ExecType=Trade 的开平仓财务结算、Maker/Taker 费用、持仓、余额、原委托剩余量、成交去重和必要 Posting 改为先准备一组完整、租户隔离、确定性 AFTER-state，然后经同一 Common 提交，再执行 apply；绝不在 Common fsync/custody 之前 mutate。
3. **正式业务回归**：全新租户自动审批+Robot 10x10→ Broker API 自定义价格 publish/MD TTL→两名交易员注册/入金/设置杠杆→Maker GTC 新单→Taker 撮合成交→订单/成交/余额/持仓/Projection 完全一致→撤单/平仓。必须检验异常、部分成交、重复回调的无双扣/漏扣。
4. **HA 故障注入**：在持续实际撮合的情况下真实停止 B、恢复追平、A/B 双向自动主切；认证 Writer poisoned 后不能简单清 flag，也不能人工修 WAL 算自动恢复。严格核对 ZK epoch、旧主隔离、签名提交、授权、资金/持仓/订单/执行与 projection 一致。

整个业务适配层都归 Trade，Common 仍是唯一集群机制。未通过真实两人撮合与自动 HA 前，整体 Demo 维持 NO-GO。

## 操作边界

测试没有重建 Order/Trade/Common，没有修改真实生产密码，也没有运行 GitHub Actions。三次自动审批测试会留下独立 TRIAL 租户及其 Robot，这些是正式业务证据，清理前需先完成验收并判断是否还需要复用。Broker E2E 临时 Key 已由脚本在 finally 中撤销。禁用任何绕过授权的方式，不用空密码或改租户注册策略来造成功记录。
## 补充：当前全部订单写路径验收门禁（P0）

| 业务写操作 | 当前认证状态 | 依据/限制 |
|---|---|---|
| OPEN Newing | 已接入 Common，Robot 真正运行 | TradeCertifiedNewingAdmission 只接 OPEN |
| OPEN Trade_Cancel | 已接入 Common | TradeCertifiedCancelAdmission 只接 OPEN/Cancelled |
| CashIn | 已接入 Common | 需要 Info1 稳定、唯一的幂等请求 ID |
| 设置杠杆 | **未接入** | SetLeverageHandler 仍走被禁止的 executeMutation |
| OPEN/CLOSE 的实际成交回报 ExecType=Trade | **未接入** | OrderFacade 认证模式直接拒绝，影响手续费/余额/持仓与真实成交 |
| CLOSE Newing、CLOSE Cancel | **未接入** | 当前 Newing/Cancel 认证 Admission 明确只接受 OPEN |
| CashOut、账户配置、持仓模式 | **未接入** | CashOutHandler / SetAccountConfigHandler / SetPositionTypeHandler 仍走旧业务写入 |

**不能只修 setLeverage 然后继续发布镜像**。上述所有必需写命令必须在同一轮 Common 确定性 AFTER-state + typed replay、签名双节点 ACK、幂等业务回归内闭环；否则 Demo 不具备可真实成交和安全平仓的上线资格。

## 补充：多租户持续运行与真实 WAL 一致性（11:20 后）

- Order A/B、Trade A/B 每节点均有 256 个 P*/epoch-2 业务 WAL 文件。
- 第一次非原子顺序读取时，Order P210 发现 A 一条新增 WAL 正在向 B 复制，随后三轮间隔复核 P210 分别达到 A/B 1222、1224、1226 帧，全部逐字节一致；Order P089 1953/1953、Trade P246 247/247 均一致。该瞬时差异不能误判为持久分叉，也不构成 HA 故障注入验收。
- 最近 8 分钟真实 Newing 回调（两套 Order 合并，仅为日志窗口观察）：WSI1WX 638 条中成功 597、失败 41；U6ZAMX 455/455 成功；G6IQ8E 362/362 成功；R0F6CC 22 条成功 20、失败 2。
- WSI1WX 失败 41 条和 R0F6CC 失败 2 条全部是 APS 11:15 重启窗口的 5003；11:16 完成重启之后，四个租户在随后检查窗口中均未新增 Newing 失败。
- 三个新租户的 Robot 当前各有 40 个活动委托，服务状态 RUNNING，最近错误码 NULL；不是仅靠 Web 盘口假数据。自动 A/B SIGKILL 主切仍 **NO-GO**。

## 后续源码实做（同日，未替换 Demo）

- TradeSvr 本地 saas-crypto 源码已提交：
  - edea43d：新增 TradeCertifiedLeverageAdmission，SetLeverageHandler 在 Common 模式下仅调用新认证适配；准备 SYMBOL_PARA 后状态，通过 commitPreparedState 认证提交后应用；带同值幂等、租户/产品/风险门禁。带持仓重算暂严格拒绝，不伪造完整财务认证。
  - 7077f11：新增 TradeCertifiedCloseNewingAdmission 和 TradeCertifiedCloseCancelAdmission，分别为已有持仓的平仓订单生成 POSITION + OPEN_ORDER + DEDUPE_RESULT 的确定性后状态，以及未成交平仓撤单的 POSITION 释放 + OPEN_ORDER REMOVE + DEDUPE_RESULT；在 OrderFacade 的认证路径中挂接，仍由 Common 完成 WAL/签名/复制。
  - 严格补齐 TradePreparedStateValidator 对 ACCOUNT_CONFIG、SYMBOL_PARA 的内部租户、用户、产品和杠杆值校验，避免仅检查实体 Key 前缀而接纳错误内嵌身份。
- 新适配分别由 trade.common.certifiedLeverage.enabled、trade.common.certifiedCloseNewing.enabled、trade.common.certifiedCloseCancel.enabled 显式控制，**默认关闭**；不允许缺失认证 Bean 时回退旧 mutate-first 路径。
- 全量 Trade Java 源码经本机 JDK8 javac 编译 PASS；JUnit 4.13.2 相关回归 **24/24 PASS**（新适配及已有 CashIn/OpenCancel/Reserve 相关测试）。由于本机系统 Maven 不在 PATH，直接复用项目已构建的 classpath/JAR 和 javac，不使用 GitHub Actions。
- **未完成/NO-GO**：真正 ExecType=Trade 成交资金和持仓结算，部分成交/重复回调、平仓实际成交、提现和账户/持仓模式写入，以及已有持仓情况下杠杆和保证金同步重算；Common Writer 故障后的自动授权恢复、A/B 双向主切也未通过。
- **未部署、不计真实通过**：上述最新 Java 源码只在本地编译、测试、提交；现有 Trade A/B 仍运行 T220 镜像，OpenTradingCore Demo 的真实新委托与 Robot 稳态保持不变。待完整成交结算认证通过后统一部署验证，避免用功能不完整镜像替换已稳定的 Demo。

## 最新运行故障追加（12:03 现场，覆盖上述运行状态）

- **四个此前 RUNNING 的测试 Robot 均变为 ERROR / RUNTIME_FAILURE，活动委托 0；Demo 当前 NO-GO**。现有容器虽仍 running 且 restartCount=0，但不能以容器运行推断服务可交易。WSI1WX 的公开 MD 仍有旧盘口 Image（20 条），不代表有持续有效报价；其它新租户盘口已清空。
- 独立日志一致证明：真实 Order RPC 返回 ORDER_COMMON_CERTIFIED_BUSINESS_STARTUP_DENIED，根因 Common certified replica domain Apply failed；下层 IOException 为 Common survivor WAL request lacks exact signed bounded head。部分撤单又被 Common physically certified partition writer unavailable: P119 拒绝，绝不能通过修改 Robot 绕过。
- **确定性根因：硬编码 4096 帧限制耗尽。** 运行中 CommonCertifiedPartitionRuntime.pollCertifiedReplicaApply() 对 P119 调用 readCertifiedFrames(...,4096,64MiB)，且 CommonFileBusinessWal.readCertifiedFrames 同时要求 maxSlots 不得大于 4096、signedHeadSeq 不得超过 maxSlots。该调用还每次读取从第 1 帧到认证水位的完整历史，因此不仅会在第 4097 帧之后拒绝，长期成本也随 WAL 增长持续变高。
- 12:03 只读取证：Order P119/epoch-2 副本 A 的 WAL **4104 帧 / 5,365,341 字节**，Primary B **4105 帧 / 5,366,777 字节**。B 第 4105 帧属于未认证尾部；B CommitIndex 只到 4104；A 是 B 的完整 4104 帧前缀。双方 custody/head.bin 和 custody-ledger/receipt-quorum.bin **逐字节一致**。Trade 256 分区 WAL A/B 一致，Order 的其它 255 分区 WAL 相同。
- **禁止把 B 的第 4105 帧当成已提交订单，禁止在进程存活时复制/截断；也不能简单把 4096 改到 65536 当作集群完成**。真正修复只应发生在 Common：以已 RSA 验证的提交 Head 和持久化索引为边界，增量有界读取、只 Apply 未应用的连续 WAL 窗口，完成可重启的 snapshot/WAL 归档，再做已提交前缀+未认证尾部封存、安全恢复与 A/B 故障注入。保留 Common 与业务状态机分层，Order/Trade 不得自建 HA。
- 此次审计**没有**再次恢复 P119 或重启 Order/Trade，没有部署新 Trade 源码，未覆盖原始 WAL；当前 Robot 故障仍未修复，严禁声明 Demo 已完成验收。

## Common 真实源码改造（同日，未部署）

- 通过本地编译 .class 和运行中 Common JAR 的 SHA256 对比，确认精确源码是 /Users/kong/.opentradingcore/common-batch-official-release-20261013/common（saas-crypto），不是过时的 .work/app-common 或缺少实际副本 Apply 方法的 t177 源码树。
- **本地 Common 提交 d2f98a1**：CommonFileBusinessWal.readCertifiedWindow 增量有界读取当前 RSA/Custody 认证 Head 下尚未应用的连续帧，验证 CRC 和 Head，缓存偏移避免每轮全量扫描；CommonCertifiedPartitionRuntime.pollCertifiedReplicaApply 每次只读 256 帧；CommonOriginalFirstReadyBusinessGate.applyVerifiedReplicaWindow 严格验证游标、连续序号，逐窗口执行业务 Apply；旧历史完整前缀验证入口保持不变。
- 本机 JDK8 对上述三份 Common Java 源码独立编译 PASS，JUnit **31/31 PASS**，包括新 4105 帧边界测试和原有 WAL/节点 Runtime/业务 READY 门禁。没有使用 GitHub Actions。
- **不可直接部署**：CommonCertifiedE2ReplicaHistory.openExistingReadOnly 冷启动入口仍要求 maxRecords<=4096 且仍调用完整 readCertifiedFrames。超过 4096 帧的 P119 冷重放仍可能失败，须补 Common 认证 Snapshot+WAL 增量恢复；B 第 4105 帧仍未认证，须独立封存与可信恢复。Writer 自动授权重建及双向自动主切仍未完成。
- 因恢复闭环不足，没有替换任何 Demo 镜像、删除 WAL、重启 Order/Trade、清理租户或恢复 Robot；**四个 Robot ERROR 仍为最新实况**。单元测试通过不能替代真实成交和 HA 验收。
