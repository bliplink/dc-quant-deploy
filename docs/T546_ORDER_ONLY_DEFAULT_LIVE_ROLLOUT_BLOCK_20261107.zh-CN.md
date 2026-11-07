# T546｜ORDER_ONLY 真实成交 E2E 与 Common 生产滚动恢复阻塞（2026-11-07）

## 当前结论：局部业务回归和镜像构建 PASS，真实 E2E / HA NO-GO

**严禁把 Docker Up、ZK READY、订单 Filled 或 JUnit 全绿当成交易、K线及自动 HA PASS。** 此次通过 Mac 上真实的 Docker/Gateway/MySQL/ClickHouse 实测，发现 E2 STRICT 部署当前 `automaticRecovery=false`，一次真实 Order B 滚动停止会触发 A 物理 WAL/ACK Poison，同一 Epoch 无法自动解除。候选容器启动失败已撤回，但旧 A/B 内的物理授权仍不完整。

### 1. 用户确认的业务边界

- `ORDER_ONLY` 走已有 `DefaultExecOrder`，订单撮合成交、Maker/Taker 报告、Order 成交历史、MD 最近成交、Web K线全部与 `TRADE` 共用一套管线；区别仅是不会通知 TradeSvr 资金/持仓结算。
- 不新增业务自建 ZK/主备、WAL、Ack、Snapshot、Election 或私有 OrderOnly 成交通道；Common 完全不识别业务模式。
- `DefaultExecOrder.Trade` 必须生成 `ExecType.Trade`，但认证 Common WAL 已应用双订单 after-state 后不得再调用旧 `Trade(List)` 二次修改订单状态。

### 2. 业务 E2E 真实失败重现

执行现有正式 Gateway 独立新租户脚本 `OTC_E2E_MYSQL_CONTAINER=otc-t529-fresh-mysql python3 tests/test-order-only-product-live-e2e.py --execute --endpoint http://127.0.0.1:43002/httpapi/`。

实际注册测试租户 **Y1AM7U**，创建自定义 `BTC003USDT`、`ORDER_ONLY` 模式，两个真实 Trader（12位 ID）、Broker API Key 签名认证、APSSvr 自定义价、MD 标记价和 Maker Sell/Taker Buy。两张订单都到 **Filled**，但 `dc_orders_execorders` 真实查询 **0**，`Missing/duplicate order-only execution reports: 0`，脚本 exit 1。测试 Broker Key 在 finally 中已撤销；没有伪造历史数据。

### 3. 完整源码构建和候选修订

- 干净隔离 GitHub 分支 `bliplink/com.app.dc.ordersvr:t545-default-exec-unified-candidate`，没有合并生产 `saas-crypto-latest`。
- 原本离线 Maven 使用旧 Common transitive API，生产 Order 主源码编译失败，缺 `CommonCertifiedNodeBootstrap.CertifiedPhysicalSourceFactory`、`CommonCertifiedOriginalHomeLedger`、`CommonPinnedRecoveryHmacKeyRing` 等；定位为 **构建依赖与实际运行 Common JAR 不一致**。不修改生产 pom，使用临时、不提交的 `pom.t546-common-validation.xml`，仅在独立镜像构建中引用从真实 Order 进程复制的 **Common JAR SHA256 `b170df0dffd6d8cbeeb64ff3ac9865fe5a89aa803d49580bf0d78eae123801b2`**。
- 完整 Maven Java8 `mvn -o -DskipTests package` **123 个主源码、56 个测试源码编译并 BUILD SUCCESS**。旧 `OrderCommonAutomaticBootstrapGateTest` 已过时：仍要求 Order 提供 Common 的 Replica physical plan Bean。更新测试为 Common 真正提供的 `CertifiedPhysicalRecoveryPlanFactory`，并使 `OrderCommonNodeRuntimeWiring` 对缺少真实依赖 fail-closed，不再空指针。
- Maven 针对性实跑 **21 tests，0 failures、0 errors、0 skipped，BUILD SUCCESS**（含 Default 全部/部分成交、COMMON签名原始 pair、TRADE 不变、没有 Finance ACK、DAO失败、真实 Common 启动边界）。
- `IOrderDao.insertExecOrderConfirmed` 复用现有 `dc_orders_execorders` SQL/主键，使认证后的 Maker/Taker 每条 MySQL SQL 完成才发布；第二条 SQL 失败拒绝通知。默认旧路径 `insertExecOrder` 仍异步，不影响其他交易模式。
- Docker 候选 `local/otc-t546-ordersvr:default-verified-maven`，image SHA `sha256:101550c48d99487258dd75247ed2e2bfde1df81b8104978f77b49ebc06e4c5ba`。这是**隔离候选镜像，不是正式发版，绝无 HA 签署**。

### 4. 一次可回滚 Order B 真实切换及失败

备份旧 B 原容器，候选 B `otc-t546-order-b-default-e2` 采用与旧 B 一致的 8 个数据/config/RSA mount、host 网络、CPU/内存/Java 环境，唯一新增业务启动 flag `-Dorder.orderOnly.certifiedDefault.enabled=true`，保留原 Common JAR 和全部旧数据。

先 `docker stop -t 15 otc-t531-order-b-e2-abcontrol`，随后启动候选 B。候选 B 在 24 秒内退出1，真实堆栈 **`COMMON_CERTIFIED_CENSUS_STARTUP_TIMEOUT` / `Common authenticated node routing census not READY`**。自动恢复的 rollback 流程立即停止候选，重新启动旧 B。旧 B 进程现在 running，但真实 Order A 的部分分区因 B 暂时不可写已经被 Common 标记 **`Common poisoned primary Epoch cannot renew`**。

ZK 真实读回：`/dc/cluster/ordersvr/partitions/P000` A主B备、P128/P198 B主A备，**Epoch 2、READY**；这是控制平面存量信息，绝非 A 的物理 ACK 恢复。A/B 原始 runtime `order.common.nodeRuntime.automaticRecovery=false`（首次 E2 Genesis 业务模式）。Common 代码 `NodePartitionGrantTable$Permit.requireCurrent` 在同 Epoch 对 poisoned Primary 持续拒绝；需要**真实 E3 认证恢复或全新 Genesis**，不是清零标记/手改 ZK READY/盲目重启 A。

滚动替换后，Demo 12 个 Robot 中只剩 **7 RUNNING / 5 ERROR**，约 280 笔已有挂单；5 个报 `ORDER_COMMON_CERTIFIED_PARTITION_BUSINESS_DENIED`。这不是成功回滚，不能声称旧 B running 就等于交易全部恢复。

### 5. 只读复测与行情范围

- 真实 10 分钟 Tape/Trade 投影统一验收 `tests/check_trial_robot_trade_e2_readonly.py` 返回 **NO_GO / exit2 / E2E_EVIDENCE_UNAVAILABLE**。
- 行情/K线 `tests/check_demo_full_market_readonly.py` 返回 **NO_GO / 6租户 3通过**，`CN8U7C`、`J4BMAH`、`RU7WZO` 的 **5M Kline 停止更新**。
- ClickHouse 历史抽样：全部 `market_trade` 不可直接按 ExecID 去重，因为公共行情 5,4xx 条中 location/execID 为空；只计算真实有 location 的租户成交，23,695 条、唯一 (location, symbol, execID) 23,695，重复 0；最近20分钟3,036条唯一3,036（T546 首次复核时点）。
- 班组不能根据过去 T541 11/11 Robot 或六租户 K线 PASS 沿用旧结论。

### 6. 防止一键部署再次重复的强制门禁

新脚本 `tests/check_order_live_rollout_preflight.py`：**只读** Docker 实际 JVM/Common JAR SHA256、两个 Order 当前 `automaticRecovery`、90秒内 Common poison/业务拒写日志以及 MySQL Robot 状态。识别旧分区 READY 但物理主不可写、手动 Genesis-only 模式、SHA不一致时 **exit2 NO_GO**；对任何异常 fail-closed，不能清除 failover 证据或自动决定滚动。

运行：
```sh
python3 tests/check_order_live_rollout_preflight.py \
  --order-a otc-t531-order-a-e2-abcontrol \
  --order-b otc-t531-order-b-e2-abcontrol \
  --mysql otc-t529-fresh-mysql
```

真实返回：`NO_GO_ROLLING_UPGRADE`，原因包括双方 AUTO_RECOVERY_DISABLED、A 主 Epoch POISONED、认证分区拒写、5个 Robot ERROR。新测试 `tests/test_order_live_rollout_preflight.py` **9/9 PASS**，已挂入 `tests/test-mac-colima-saas.sh`，Mac 离线一键回归仍 PASS。

注意：这是新的**部署前检查工具**，不是自动修复功能，也不是在 `deploy-saas.sh` 正式滚动操作中已经自动强制调用的门禁；正式运行前须由部署入口执行，不可把离线测试 PASS 冒充全链路预检。

### 7. 正确的后续动作（不得绕过）

1. **优先 Common-only 正式 E2 STRICT→E3 当前 Epoch 物理生产恢复：**使用现有双 RSA、同 Epoch 真 Snapshot/WAL/CommitIndex/双 Custody，补齐通用 `CertifiedPhysicalRecoveryPlanFactory`；对坏 Primary 签名撤权、B 物理安全重放、ZK 正确 E3 RECOVERING→READY；不能把 LOCAL ACK 假写成 STRICT 2/2 证明。T525/T526 已有通用业务恢复测试，但**当前 runtime T520 的生产256分区自动工厂不完整，不能靠开关直接生效**。
2. 若这些恢复事务无法在现有盘真实证明，**选择开发环境专用隔离全新部署**：保留旧 Docker 数据卷/证据，使用新的 ZK namespace 和空业务数据完成双物理 E1→E2 严格入场，先启用真实自动 HA 完整证据再接入 Robot；不要在原 poisoned Epoch 2 下修改 READY。
3. 完成可靠物理恢复后，再构建/替换 `ORDER_ONLY` 候选 Order 并跑新租户 Maker/Taker 的 **2 条真实历史 ExecID + MD + K线 + Trader资金/持仓不变 + 重放幂等**；随后 A/B 自动双向故障切换和 10/50/200 租户压力。

当前 NO-GO 不能因为 21 项 Maven PASS 或镜像构建 PASS 而关闭。