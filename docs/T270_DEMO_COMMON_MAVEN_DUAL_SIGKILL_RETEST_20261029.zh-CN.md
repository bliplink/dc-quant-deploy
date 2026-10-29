# T270｜Demo+Common Maven 复位与双向 SIGKILL 实测（2026-10-29）

## 本轮可核验结论

**Maven/PATH 问题已解决；Common 可独立编译，真实隔离双 JVM+三 ZooKeeper 的 A→B→A SIGKILL 再次成功。P0 完整门禁仍为 NO-GO：没有 B 在 E3 下自动在线恢复并回到持续双副本复制，也未将测试进程负责的 Genesis/replay/C 见证后 READY 编排全部收归正式 Common 常驻生命周期。**

- Maven 使用本机已有的 `~/.opentradingcore/ha-unified-validation-20261015/tools/apache-maven-3.9.16/bin/mvn`（Java 8）；不是没有 Maven，只是 WebCodex 非登录 shell 的 PATH 未包含它。
- Common 源码：`~/.opentradingcore/t177-common-saas-crypto-integration-20261027`，候选 Jar SHA256 `146656434f0ac1d854889f12f7e79e108007fa5781729a570fef39c694a8ae60`，构建与本地依赖安装均成功。
- 修正测试边界：`CommonE3FormerPrimaryBReplicaCatchupTest` 原来放在 Common 的 `src/test` 却直接 import Demo 业务状态机，致使 Maven testCompile 失败；现迁入 `examples/common-only-demo/src/test`，Common 可独立执行全量回归。Common 本地提交 `6a521f2`，仅移动测试文件，未更改生产 HA 协议。
- Common 全量 `mvn -q test`：139 suites / 616 tests，**567 通过、49 skipped、0 errors、0 failures**；需注意有旧配置查找日志 `ATSConfig.ini`，但 Maven 退出码为 0，未据此认定外部业务服务可用。Demo `DemoCommonOnlyStateMachineTest` 1/1 PASS；带原始 T268 RSA 和实际 WAL 的 `CommonE3FormerPrimaryBReplicaCatchupTest` 1/1 PASS（离线物理追平，并非在线恢复）。

## 再次真实故障验证（本轮重新运行，而非转述历史测试）

运行：`OTC_T125_ENABLE_DEGRADED=1 OTC_T126_ENABLE_REJOIN=1 OTC_T127_ENABLE_REVERSE=1 OTC_T128_REQUIRE_E3_INSTALL=1 OTC_T129_REQUIRE_E3_WRITE=1 OTC_T130_AUTO_C=1`，使用旧 A/B/C RSA **只读**、固定上述 Common 候选 Jar、隔离 Docker JVM、3 个真实 ZooKeeper、真实 WAL/Netty。真实控制脚本仅负责进程创建/强制 SIGKILL/观察；其演示业务进程仍主动串联了 Common 恢复 API。

新运行证据：`~/.opentradingcore/t124-live-kill-runs/20261029103332`，总结日志：`~/.opentradingcore/p0-20261029-evidence/full-t130-sigkill.log`。退出码 0，包含：

- 独立 A/B Genesis RSA+持久化：PASS；A/B 严格 Quorum E1 两笔业务，总值 40：PASS。
- 真 `SIGKILL A`，B Watch 自动进入 E2 RECOVERING，并恢复旧已确认 WAL：PASS。
- C 故障前已常驻，独立 E2 见证自动产生：PASS；B 获得 E2 `LOCAL_DURABLE_ASYNC` READY，继续写入总值 40→60：PASS。
- A 回归作为 E2 Replica，恢复 60 并独立 RSA fsync：PASS。
- 真 `SIGKILL B`，A Common Watch 自动 E3 RECOVERING、跨 Epoch 恢复、C 自动 E3 见证：PASS；A 获得 E3 本地 READY，总值 60→74、6 个去重请求：PASS。
- **仍缺** B 在线自动重加入 E3、双方持续复制与严格 ACK 回归；不要将当前 T269 离线 B 物理 WAL 测试混同在线重加入。

故障后 E2/E3 新写入是 `LOCAL_DURABLE_ASYNC`，有 RPO 风险，绝不作为零丢失 Quorum ACK。旧主拒权/历史 Quorum 边界必须持续验证。

## P0 尚未通过的实质差距

1. Common 正式运行时必须接管 Watch→RECOVERING→可信 WAL/业务 replay→证书核验→READY 的**全自动节点生命周期**，不是测试进程 `awaitStage` 后继续手动串联；不增业务类别限制和第二套恢复协议。
2. B 在 A 处于 E3 READY 期间真实上线，自主认证当前 ZK 成员/分区、通过 Common TCP 复制 E3 原始 WAL，追平 Snapshot/业务状态，恢复正常双副本复制及后续持续写入；A/B 都要有自动 rejoin。
3. 做完整无人编排真实主备交替、故障中与故障后提交水位/哈希/ACK/去重核对，并固定唯一候选 Jar；通过后才统一替换 Order/Trade 同一 Common 运行时。业务只处理不透明 `byte[]`。

参见 `docs/ARCHITECTURE_SIMPLE_COMMON_BOUNDARY_20261029.zh-CN.md`。本轮没有替换 Order/Trade、没有清空其他容器数据、没有运行 GitHub Actions，也没有上传任何私钥或原始 WAL。
