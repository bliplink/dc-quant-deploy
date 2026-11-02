# T421｜Common 认证路由快照续租竞争修复及 Demo 真实替换审计（2026-11-02）

## 目标及原则

- 使用 `saas-crypto-latest`，Mac 本机 Docker，不调用 GitHub Actions。
- Common 独占 ZK 认证控制、WAL/CommitIndex/双 Custody、Epoch/READY、主备切换；Order/Trade 只复用 Common 与各自业务状态机。
- 用户允许 Demo 证据保留后的全新数据/namespace 重部署；不可通过跳过签名、假 READY 或忽略 ACK 重建正常状态。
- 不以容器 `running`、Robot `QUOTE` 或浏览器接收时间冒充真实成交/HA 全通过。

## T421 当场观察（实机）

1. 现运行 Order A/B 是 T417 控制调试容器；Trade A/B 是 T411；MD T413 三节点；Gateway T399；MySQL/ClickHouse T398。三 ZooKeeper 当前 Docker IP `.5/.8/.6`，Order/Trade 四节点当前 `ExtraHosts` 和 Common ZK 属性均绑定三 ZK 名称。
2. T398 MySQL `dc_tenant` 有 10 个 `TRIAL` 租户，`HXIAAM`、`J1P4BK` 均 SYSTEM 流动性；`dc_tenant_robot` 两条启用 Maker/Tape Robot 配置。
3. 原 `otc-t420-robotsvr` 退出。重新执行 `docker start otc-t420-robotsvr` 后，两个租户均有实时行情、查询 Position/OpenOrders 日志；数据库状态从 `STOPPED` 转为 `WAITING_MARKET_DATA`，后来 `DEGRADED/ERROR`，真实挂单数 0。错误包括 `ORDER_COMMON_CERTIFIED_CENSUS_UNAVAILABLE`、`gateway rejected queryTradePosition: INTERNAL_ERROR`。
4. `dc_orders` 旧证据：HXIAAM 8175 Rejected（大量 `SERVER.TradeSvr is not Online`），J1P4BK 272 Suspended + 4 Rejected。**历史数据不得当作本轮成功成交**。
5. Trade B 2026-11-02 08:27 日志明确 `TRADE_COMMON_CERTIFIED_CENSUS_UNAVAILABLE`，根因 `java.io.IOException: Common node routing census replaced while reading`。T398 ClickHouse `EXISTS TABLE dc.market_trade` = 1；Trade Web `127.0.0.1:18088/healthz` = ok。

## Common 代码与测试：PASS（限于该修复）

- `NodePartitionGrantTable.requireCertifiedCensus()` 对合法认证节点续租时的 State 原子替换竞争执行至多 4 次本地重读，**每次**先验证 State 未撤权、原租约未过期、Common `hotpathFence`，并仅在 `current.get()==certified` 时返回。失败继续 fail closed；不增加 ZK 热路径 RPC。
- 新增正常认证续租读取及读取期间立即撤权两项 JUnit，完整 `NodePartitionGrantTableTest` 17/17 PASS。以 T401 原始 JAR 加入重新编译的唯一类后在新候选 JAR 再执行 17/17 PASS。
- Common GitHub `bliplink/com.app.common` 分支 `saas-crypto-latest` GitHub 原子树提交 `c02647e2e664b146df70a7c9bb30ffd46d06699f`，含 `[skip ci]`，没有覆盖旧分支或强制推送。Mac 本地提交 `a0fefb3` 内容相同但 Git 对象 SHA 不同（Mac git push 超时，远端使用 GitHub API 创建正常后继提交）。
- T401 原 JAR SHA-256 `135ec1c31d15b3992aa3fb69ae10b733aa0e48ab762928db236f55831f9b87bb`，T421 候选 JAR SHA-256 `3397b84966cfe517ce4e9b7d770c12b1180536a0a35e3fbc83a858dab44c7e74`。

## T421 Docker 真构建与真实节点替换

- 本地镜像成功：`local/otc-t421-ordersvr:t401-certified-census-retry` 和 `local/otc-t421-tradesvr:t401-certified-census-retry`。用 `docker run --entrypoint sha256sum` 复核两个镜像内 Common JAR 均为 `3397b849...`。
- 四个新容器 `otc-t421-{order,trade}-{a,b}-host` 均已创建。与其各自旧容器逐一比对环境变量内容、6 个原挂载、3 条 ZK `ExtraHosts`、host network、镜像，全部吻合；旧容器及原数据卷保留。
- **Trade B**：停止 `otc-t411-trade-b-host`，启动 `otc-t421-trade-b-host`；实机产生 `COMMON_GATEWAY_CERTIFIED_PARTITION_ROUTING_PASS ... partitions=256`，Spring `Started TradeSvr in 14.183 seconds`。仅证明当前新镜像启动/路由，非真实可交易性及跨故障一致。
- **Order B**：停止 `otc-t417-order-b-control-debug`，启动 `otc-t421-order-b-host`；冷启动 **FAIL**（exit 1），根因为 `CommonCertifiedE2ReplicaHistory.openExistingReadOnly`: `cold E2 history exceeds bounded payload; snapshot required`。
- 尝试恢复原 `otc-t417-order-b-control-debug` 原镜像也得到**同一** cold E2 历史上限错误（exit 1），确认不是新 T421 JAR 造成。
- **未切换 Order A/Trade A**：保护还在运行的两个 A 及旧证据，亦未向正式业务节点执行 SIGKILL。Robot 在复查时仍 `ERROR`，挂单数 0。不能宣称系统已经恢复交易或 HA 全通过。

## 当前结论与下一关

- Common 此次认证路由快照读取竞争的代码及针对性测试 **PASS**；T421 镜像构建 **PASS**；Trade B 新镜像 Spring 启动/初始路由 **PASS**。
- 实际 Order B 冷恢复 **FAIL**，机器人连续报价及真实 Tape 成交 **NO-GO**，业务双向 A/B SIGKILL、Snapshot+WAL catchup、账务/成交/Projection 一致、iPhone Safari 实机权威 `MDEntryTime` **NO-GO**。
- 下一步优先**保留故障原 WAL/日志并全新 Common 签名 namespace + 空业务卷部署**，按 T398 原双物理 RSA E1 Genesis、A/B 1024/1024 安装、E2 READY 真实控制面流程重建；同步重新部署完整服务数据并经**正式新租户注册自动审批→Robot Maker/Tape→真实成交→MD→账务一致→业务双向 HA**。如选择保留旧数据，必须先实现/核验 Common 的带原签名的 Snapshot 加增量 WAL 冷恢复，不能提升内存上限或绕过可信恢复证据来假启动。
- 本轮没有删除 T398/T417 数据卷，没有调用 GitHub Actions。