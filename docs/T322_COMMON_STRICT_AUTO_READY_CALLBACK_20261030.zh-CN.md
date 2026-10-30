# T322｜Common 严格 RF2 自动 READY 回调与返回副本识别（2026-10-30）

## 结论与门禁

**Common 本地新 commit `446d256`：真实 T293 原始 A/B RSA 退役、原 E4 WAL、E5 双恢复回执驱动的通用自动 Watch + STRICT READY 回调通过内存 CAS 认证单测；真实三 ZooKeeper 完整无人值守 A→B→A、正式 Order/Trade 交易仍 NO-GO。**

这次只修改 Common 本地源码；T321 隔离业务容器仍使用之前 T319 Common JAR，**没有替换镜像/注入故障/写正式数据**，GitHub Actions 未使用，正式 `dc-saas-*` 未改。

## 具体 Common 实修（完全业务无关）

- 源码仓库：`~/.opentradingcore/t177-common-saas-crypto-integration-20261027`，分支 `codex/t177-common-saas-crypto-integration-20261027`，commit **`446d256`**。
- `src/main/java/com/app/common/replication/CommonCertifiedFailoverCoordinator.java`：故障 CAS **前**继续要求旧 Primary ZooKeeper ephemeral lease 真正消失；恢复进入 **已经签名/精确匹配的 RECOVERING** 阶段后，只有 `STRICT_QUORUM` 的原旧主以 **不同 ZK session** 重新出现且成为新 `replica` 时，恢复及 Ready 状态检验才不把它误拒。LOCAL 模式仍要求旧主 lease 消失。这个判断**不是 READY 授权**，不存在依据超时自行选主。
- `src/main/java/com/app/common/replication/CommonCertifiedStrictCrashReadyCompletion.java`：实现 Common 现有 `CommonCertifiedFailoverWatch.CertifiedRecoveryCompletion` 接口；精确匹配 service、partition、原/新 Epoch、A/B 角色互换。从各自物理持久化目录**只读**取原 A/B 独立 RSA 撤权回执及新 B/A 独立 RSA 恢复回执，然后直接调用已有 `CommonCertifiedStrictCrashReadyPublisher.publish`。只有该旧严格发布器验证原 WAL、CommitIndex、双 custody、两个退役 SHA256、两个新恢复签名、独立 ZooKeeper lease 和 CAS 才能 READY。**不生成、不复制、不代签、不覆盖任何物理证据**。
- 新单测 `src/test/java/com/app/common/replication/CommonCertifiedStrictCrashReadyCompletionTest.java`：离线读取原始 T293/T298 真实 RSA、公钥、WAL、signed stage、退役回执和恢复回执；用隔离的 **in-memory ZooKeeper Ops** 做版本化 CAS，完整驱动 Common Watch 的 `resumeDurableStage → strict completion → READY → requirePublishedReady`。另外验证原 A RSA 退役证明缺失，以及 A/B lease 非独立会话时，绝对不能发布 READY。

## 已执行回归

- T322 原始真实 RSA 单测：**3/3 PASS、0 skipped**，标记：
  - `T322_ORIGINAL_RSA_E4_TO_E5_AUTO_WATCH_STRICT_READY_PASS`（`zkCAS=in_memory_fixture`，不是新的真实三 ZooKeeper）
  - `T322_MISSING_RSA_PHYSICAL_RETIRE_FAIL_CLOSED_PASS`
  - `T322_NONINDEPENDENT_ZK_REPLICA_SESSION_FAIL_CLOSED_PASS`
- Common 全量离线 Maven 且传入原 Demo 现有 RSA 目录与 T293 原始证明：**151 suites / 650 tests / 645 passed / 5 skipped / 0 failed / 0 errors**。此前未提供现有 RSA 时同一 650 tests 56 skipped；以本轮具有真实 RSA 的回归为正式统计。全量测试有一个遗留 `ATSConfig.ini` 的 Java 日志噪声，但 Maven 退出码 0，无 JUnit failure。
- `mvn -o -q -DskipTests install` **PASS**。新 Common JAR：`target/com.app.common-3.0.22-t143-durable-signed-crossjvm-handoff-20261026-SNAPSHOT.jar`；SHA256 **`b46d6842bc41cfd21eb0941b5eb5765dde98cdcd683d6a9cef9169f1c80517f8`**。这与运行 T321 候选镜像里的旧 JAR SHA256 `d2ce7f87241d2154362e14485b73e9f1269ddb350bbb9019f04454aa7ae7ee7c` 不同；不可混称已部署新 Common。
- T321 只读业务启动验收脚本 `bash tests/verify-t321-isolated-boot.sh` 再次实际通过：四个 Spring 完整启动、独立正确 ZK 注册、每个活动 v4 根 256 Common E2 WAL、4 个 Netty TCP open。仍未注入真实交易。
- 最后一次正式 Demo 只读查询：`dc-saas-ordersvr` **RestartCount=197**，`dc-saas-ordersvr-b/c`、`dc-saas-tradesvr-b` 和 `dc-saas-robotsvr` 停止；正式 MySQL/ZK healthy。旧 Order A 的 `receipt ledger head != physical custody` 认证不一致不能通过抹除签名绕开。

## 尚未完成（按次序）

1. **Common P0 真正三 ZooKeeper 连续切换**：要在全新且自洽的 RSA/物理 WAL/真实 ZK 命名空间，使用**常驻** Common Watch 从 A SIGKILL 后自动产生、fsync 两份退役证明和完整业务恢复、双签下一 Epoch 恢复回执，自动 E2/E3 或相邻严格新 Epoch READY，并在 A/B 返回后恢复真实物理 2/2 ACK。T322 新类目前只**消费**已签证据，不会让已宕机旧节点自己签署证明，更未替代真实安装/恢复程序。缺证明时必须 RECOVERING/非 READY。
2. **生产自动注册接线**：要由 Common runtime 持有严格 recovery callback 和冷控制线程，而不是依赖 T301/T306 独立测试 `--publish` 命令；业务进程只注入 `byte[]` 状态机接口。需要检查全 256 分区与节点级旧物理 socket 关闭、别把单分区故障扩大影响全服务。
3. **Order/Trade P1**：等 P0 PASS，四业务候选镜像统一重新构建绑定同一新 Common JAR，在独立实际 Gateway/Robot/MD/数据库运行真实事务与 A/B互切，要求无重复成交、无丢已 ACK 数据、余额持仓订单一致。
4. **正式 Demo P2**：待真实 E2E GO，按 Mac 现有部署脚本替换当前旧镜像；若仅需清空可丢开发数据，应使用新的完整且可签名 Genesis/READY 流程，不能假造旧 `custody` 或把旧 WAL 的不一致视为恢复成功。不使用 GitHub Actions。

**当前状态：Common 通用回调与原始签名材料单测 PASS；真实 3-ZK 无人值守严格 A→B→A NO-GO；正式 Order/Trade NO-GO。**
