# T457｜Order/Trade 256 分区 Common HA 接线与 P060 故障现场审计（2026-11-03）

## 结论

**Common Demo T456 单分区 A→B→A 及 B E3 TCP fsync：PASS；真实 Order/Trade 256 分区：NO-GO。**

本轮使用 Mac Demo 上四个仍在运行的 Order/Trade 容器、真实 ZooKeeper 三节点、业务物理 WAL，以及当前业务源码进行只读审计。未强行重置 P060、未修改 ZooKeeper Epoch、未撤销旧主、未复制未确认的 WAL 尾部，也未重启或替换四个真实业务服务。

## P060：根因链与可复核证据

1. Order A 在 **2026-11-02 20:18:10** 对租户订单提交时，`DirectNettyCertifiedBusinessTransport.collectSignedWalFsyncReceipts` 访问 `127.0.0.1:45323` 返回 `Connection refused`。当时提交日志精确记载 `COMMON_COMMIT_PHASE partition=P060 epoch=2 seq=188531 phase=INDEPENDENT_WAL_FSYNC_RECEIPTS walWriteStarted=true`；失败后反复出现 `Common poisoned primary Epoch cannot renew`。
2. 四个业务容器当前均在 Docker **host** 网络，因此 `127.0.0.1` 的写法在此部署模式下本身并非跨容器地址错误；当天核查时 `45222/45223/45322/45323` 均已恢复开放。**后续端口恢复不等于旧 Epoch 已被认证恢复**。当时 B 端口未接收连接是触发故障的事实，为什么当时没有监听须与当时进程生命周期日志核对，不能仅据拒绝推断具体重启原因。
3. 真实 ZooKeeper Order manifest：**256/256 分区 READY、严格 `STRICT_QUORUM`、A/B 各 128 Primary**。其中 `P060|2|OrderSvrA|OrderSvrB|STRICT_QUORUM|READY`，与 A 实际 poisoned、不允许业务写入构成**控制面 READY 与物理业务可写状态不一致**。
4. 物理 P060 E2 WAL：Order A `285670877` 字节；Order B `285669623` 字节；相差 **1254 字节**，在 B 长度内执行 `cmp -n` **退出 0、字节完全同前缀**。A 可见最高认证提交文件 `commit-00000000000000188530.bin`，下一次 `seq=188531` 不具备成功提交凭据。**禁止把 A 多出的 1254 字节当作已提交订单、直接复制到 B 或强行使用旧 Epoch 续写**。
5. Order B 持续存在 `ORDER_COMMON_CERTIFIED_BUSINESS_STARTUP_DENIED`（根因 `Common poisoned primary Epoch cannot renew`）；不能以容器 `Up` 判定业务 READY。

## 256 分区控制面与真实自动恢复的差距

- Trade manifest 同样是 **256 分区 READY、A/B 各 128 Primary、全部 STRICT_QUORUM**；这只是 ZK 控制面快照，**不是**真实故障切换成功证明。
- 业务源码 `OrderCommonNodeRuntimeWiring.certifiedCommonNode` 和 `TradeCommonNodeRuntimeWiring.certifiedCommonNode` 仍调用旧的 `CommonCertifiedNodeBootstrap.openAndStartWithZkFencingAndReplay`。它们没有向 Common 的 `openAndStartWithCertifiedAutomaticRecovery` 提供 **完整的每个本地 Replica 的 `AutomaticReplicaRecoveryPlan`**，也没有安装对应认证的 CatchupProof、签名 READY Publisher 与业务 WAL/Snapshot Install 回调。
- 现场对四个 Java 容器执行 `jstack 1`，匹配 `common-failover-cold-* ` 的线程数均为 **0**。T456 所验证的自动 Watch 尚未被真正部署到 Order/Trade，不能依赖脚本代替常驻自动接管。
- 当前 Common 的完整自动启动入口会在真正启动 WAL/Netty 前核对全部 Replica 计划，并在启动失败时 fail-closed；不能通过向其传入空 Map、无证明回调或无业务恢复的成功桩冒充上线。

## Common JAR 一致性（正式集成硬性门禁）

四个真实容器的 Common JAR **同名但字节不同**：

| 容器 | SHA-256 |
|---|---|
| Order A `otc-t432-order-a-restored` | `5b3aa4055b5424980198705ee9dda6ab6b76de534636c368651540705e7611d0` |
| Order B `otc-t453-order-b-standby-parent-watch` | `22b4b74213af025656cb9af47519a13325a6202bc39bc0f014d1e2ba5b4eb7b8` |
| Trade A `otc-t436-trade-a-margin` | `e7fe2fe519421632dac4080d6903ff23e6108f35ef13f4fb879efb994431ee72` |
| Trade B `otc-t452-trade-b-windowed` | `1c4765f603098bfed848b72144c7d6ebd9a6d7dfed59f3bac2db41ede6edef1a` |
| T456 验证的独立 Common JAR | `0e9205761029f2f616f65b42359606b0cdea79cc634bb8e10a147632c6b7f024` |

**不能仅凭版本名 `3.0.22-t143...` 相同即认为四个业务进程在运行相同 Common 状态机。** 替换镜像前必须统一代码来源、构建输入与二进制 SHA，不允许在旧 Epoch 上覆盖重启以绕过失败。

## 本轮新增验证与实测

- 新增只读发布前门禁 `tests/t457_readonly_common_ha_preflight.py`：读取真实 ZK NPC1 256 分区 manifest、四个运行容器中的 Common JAR SHA、共享 Common Watch 线程数及实际 Docker 网络模式。只用 `docker inspect/exec` 与 `zkCli.sh get`，**没有变更任何集群、业务或密钥数据**。
- 本轮执行门禁获得 JSON `verdict=NO_GO`，精确五项原因：`COMMON_JAR_SHA_MISMATCH`、`ORDER_A_AUTO_WATCH_ABSENT`、`ORDER_B_AUTO_WATCH_ABSENT`、`TRADE_A_AUTO_WATCH_ABSENT`、`TRADE_B_AUTO_WATCH_ABSENT`。
- 新增 `tests/test_t457_readonly_common_ha_preflight.py`，**6/6 Python 单元测试通过**，覆盖 256 分区/128:128、缺失分区、重复分区、错误布局、不同 JAR 及 Watch 缺失时 fail-closed。
- 由于当前 WebCodex Shell 的 `mvn` 不在 PATH，本轮未把 Maven 执行当作新鲜测试。使用原本经 Surefire 编译的 Common 测试类及其 Surefire classpath，直接 `java org.junit.runner.JUnitCore CommonAutoRecoveryPlanCoverageTest CommonCertifiedNodeRuntimeTest` 重新执行，**23/23 通过，退出码 0**。这验证了 Common 的计划完整性逻辑，而非正式 256 分区故障切换。

## 进入下一阶段的安全工作顺序

1. **Common + 256 Replica 计划的同源接线**：Order/Trade 只提供自己 `byte[]` Snapshot/Apply 和已经存在的认证业务恢复绑定；统一向 Common 自动恢复入口提供 128 个本地 Replica 的真实物理恢复依赖与固定 256 Home 拓扑。缺任何证明时拒绝 READY，不能加业务私有的选主或第二套 WAL。
2. **统一 JAR 和构建来源**：四个新镜像使用同一个 SHA-256 的 Common JAR，核对 Java API、启动入口、常驻 Watch、物理 TCP source 和 Replica CatchupProof；先在**新独立数据命名空间**验证，不复用 P060 的 poisoned Epoch 或不确定尾部。
3. **真实多分区故障注入**：分别执行 SIGKILL Order A/B、Trade A/B；检查 256 个分区全量角色、E2/E3 签名、Home 128/128 自动安全切回、真实 TCP WAL、Snapshot 及业务状态一致性。单节点降级必须按 `LOCAL_DURABLE_ASYNC` 明确披露 `quorum=false, rpoRisk=true`，不能在严格 `STRICT_QUORUM` Epoch 失败时无签名更改 ACK 级别。
4. **产品 E2E**：新租户自动审批、Robot 自动报价/Tape 点价、真实下单成交、持仓/余额/流水/委托、MD QuerySymbol/APS 价格及 Projection 对账后，才允许判定业务 GO。

本轮 **没有执行新旧 Order/Trade 镜像替换**。现网为 NO-GO；脚本仅确认了集群发布基础条件未满足，不能用它代替正式自动 HA 验收。
