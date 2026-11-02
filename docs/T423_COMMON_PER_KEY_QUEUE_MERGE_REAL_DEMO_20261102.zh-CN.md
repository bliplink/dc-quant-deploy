# T423｜Common 同 Key 原子队列合并、统一镜像及 Demo 真实验收（2026-11-02）

## 工作原则与来源

- 用户要求先查清原因、对照验证，再合并修复；本次优先集成已隔离验证的 Common `b0be90c`，不借机改业务或 HA 架构。
- 来源：`.work/app-common-queue-fix-20261020`，分支 `fix/common-single-key-worker-20261020`、原提交 `b0be90c`，交接文档 `docs/COMMON_PER_KEY_QUEUE_FIX_HANDOFF_20261020.md`。其根因是 `synchronized(className + id.intern())` 不保证同一锁对象，且锁内未重新查 Worker。
- HA 目标：`.work/t374-demo-common-ha` 的 `saas-crypto-latest`。先核对 source/target 及原补丁适用性；目标工作区干净，无冲突。

## 真实合并与测试

1. 将隔离分支本地 Git 对象引入 HA 工作区，再执行 `git cherry-pick b0be90c`，成功生成本地 `63fc5d0`，三文件：`AsyncSingleSeqThreadGroup.java`、`AsyncSingleSeqThreadGroupConcurrencyTest.java` 与原单 Key 修复说明。T421/T422 的先前 Common 认证 Census 和有界冷恢复源码/提交保留。
2. 实施 per-Key `ConcurrentHashMap.compute` 原子 Worker 创建/入队，失败 Worker 未消费队列恢复，生命周期写锁防止 dispose 后入队；不同 Key 并发保持。未更改 HA 的 WAL/选主/ZK/Epoch/签名/持久证书。
3. Java 8 手动源码编译 PASS；第一次独立 JUnit 运行缺少 `commons-lang3` classpath，补全本机原依赖后同一源码 **8/8 PASS**；再与 T421/T422 Common 源码一起编译及运行 **29/29 PASS**：Queue/AsyncCache 8、NodePartitionGrantTable 17、签名 E2 冷回放 4。
4. 新候选 JAR 用 T422 原始候选 JAR 追加重新编译的 `AsyncSingleSeqThreadGroup` 主/匿名内部类，SHA-256 `e7fe2fe519421632dac4080d6903ff23e6108f35ef13f4fb879efb994431ee72`；**从该候选 JAR** 再运行 29/29 PASS。此为离线定向编译和分层 JAR 构建，**未执行完整 Maven 全模块测试**。
5. Common GitHub `bliplink/com.app.common` 的 `saas-crypto-latest` 非强制提交 `0738755047a5853db07ce32acf0dbe1a86460ff0`（`[skip ci]`），保留先前已同步的 T421/T422。未触发 GitHub Actions。Mac 本地 `63fc5d0` 和远端提交哈希不同，是本地 Git 正常 cherry-pick 与远端 GitHub Tree API 提交实现差异，补丁内容相同。

## Docker 部署的实机证据

- 离线构建镜像：`local/otc-t423-ordersvr:common-per-key-worker` 与 `local/otc-t423-tradesvr:common-per-key-worker`。
- 四容器重建前逐一比对：与各自上版环境变量、6 个数据/配置挂载、3 个 ZooKeeper `ExtraHosts`、host network 相同；旧容器及原签名数据卷保留。
- 滚动更换：`otc-t423-trade-b-host` 13.69s、`otc-t423-trade-a-host` 14.127s、`otc-t423-order-b-host` 60.134s、`otc-t423-order-a-host` 72.046s，四个均记录 `Started ...` 与 `COMMON_GATEWAY_CERTIFIED_PARTITION_ROUTING_PASS ... partitions=256`。Order A 首次 72 秒轮询门限结束时尚未观察到启动，但随后实机日志证明已完成启动。
- 在**四个运行容器内部**使用 `sha256sum` 检查 Common JAR，四个均等于 `e7fe2fe5...431ee72`。Spring 启动和初步认证路由通过，**不等于业务成交或双向 HA 已通过**。

## 恢复交易的只读诊断（仍 NO-GO）

- `otc-t420-robotsvr` 两个租户 `HXIAAM`、`J1P4BK` Robot 仍记录 `ERROR`，没有证明成功的最新 Maker/Tape 真实成交。
- 在两个服务重启过后，Gateway 曾对 `queryTradePosition` 和 `queryOpenOrder` 返回 `9000/INTERNAL_ERROR`、近 0–2ms；T398 ZK 路由根各有 256 分区，抽查 P000/P128 均为 E2 READY。仅对 Gateway 做诊断重启，之后部分查询开始恢复，未变更 Gateway 源码。
- LoginSvr 的 `ApiKeyService.getApiKey` 只读进程内 `htApi`，新租户 Key 创建晚于 LoginSvr 原启动时间；T398 MySQL 有 13 启用 Key、两个租户 Maker/Tape Key 均存在且启用。LoginSvr 诊断重启后日志 `getAllApiKey size:13`，后续 Robot 重新有 `POSITION_OK`/`OPEN_ORDERS_OK`，J1P4BK 曾返回 12 活动单。尚不能把所有认证问题归因为 Key 缓存。
- Order A/B 后续真实 Newing 响应出现 `5000` 与 `5003`：Trade 真实日志 `TRADE_BALANCE_NOT_ENOUGH`、`MARKPX_NOTEXIST`。查阅 `ProcessOrder.planOpenNewing` 与 `MarkPxCheck` 源码，分别对应资金/冻结风险计算与真实租户标记价格缺失/过期校验，需独立排查，不应关闭风控。
- **不得重新入金**：T398 MySQL `dc_users_balance` 显示 HXIAAM/J1P4BK 两租户 Maker/Tape 四交易员各 10,000、used_margin=0，`dc_users_posting` 四条各 10,000 的 `COMMON_CERTIFIED_CASH_IN`，含稳定 `E2CASH-` 幂等 ID；`dc_users_cash_log` 为空不是未入金。Common 模式 `AccountBalanceFacade.init()` 故意跳过 MySQL 重载、应从认证 WAL 恢复内存账本。需要核对当前 Trade 主节点有效余额与冻结保证金，不能以 DB 值代表内存权威余额。
- 读出当前账号权威状态的一次临时只读探针准备进行时，调用涉及敏感 API Key/secret 传递被执行环境安全检查拒绝。未绕过该限制、未泄露密钥；已转为仅阅读日志与源码的诊断。
- 本轮未向正式 A/B 业务容器执行 SIGKILL 互切；也未拿到两个交易员近同时下单、真实成交、持仓资金对账的 E2E PASS。

## 交付结论与下一关

**PASS**：Common 同 Key 补丁集成、29/29 定向测试、统一 JAR 内核与四容器部署、256 分区启动检查。

**NO-GO**：真实 Maker/Tape 流动性持续报价、风控允许下单并成交、资金/持仓/订单一致性、Order/Trade A/B 双向 SIGKILL 自动互切。

下一关优先用不泄露用户秘钥的正式只读接口核对当前 Trade WAL 恢复的余额/冻结保证金及 MD 标记价格是否持续，精确区分 5000 和 5003，定位后再进行小范围源码修复；再走真实近同时两交易员撮合与数据一致性，最后跑业务 A/B 自动互切。
