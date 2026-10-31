# T376｜隔离 Demo+Common 真实 ZooKeeper / RSA / WAL 自动切换验收（2026-10-31）

## 范围与安全边界

- 目标：**Order/Trade、Gateway、Projection、Robot 继续提供真实交易**；Common 集群问题只在隔离 Demo+Common JVM 修复，不再对正在交易的业务容器 SIGKILL。
- 本轮用 **完全独立的 Docker Compose 项目、三节点 ZooKeeper、独立网络、临时测试 JVM、独立数据目录与测试 RSA 身份**，没有复用业务 ZooKeeper 或旧数据卷，没有对业务容器重启、替换 Common JAR、清空 WAL。
- T375 Common 候选 JAR：`.work/t374-demo-common-ha/target/t375-common-certified-automatic-recovery.jar`，SHA-256 `6489ca9d914d722fe4fb70e799846dc93eee1af49e5fc4db827e79eb22f022ee`。业务安装的 T143 JAR 原版 SHA-256 `7cbe13f614f0abd478b02188e15660b572f1c4519866684c3b308e92593784e6` 未更改。
- 使用本地隔离 Common 分支 `fix/t374-demo-common-ha-shared-control`：`5306c41`（共享二线程 Watch），`bb19778`（完整 Replica 恢复计划前置检查及受认证启动入口）。测试脚本默认/显式指向候选的 SHA-256，而不是旧 T143 包。Demo T120 script 增加 `OTC_T120_COMMON_JAR` 精确绑定。

## 真实单测计数与签名夹具

- 原始 JUnit `OK (42 tests)` 包含 4 个 `Assume` 跳过项。新增 `tests/run-t376-isolated-common-physical-rsa.py` 固定候选 JAR 和兼容的 SLF4J 依赖，用真实独立 A/B 测试身份、C 测试公钥及 T293 签名历史夹具**隔离克隆副本**跑测试，并用 RunListener 严格统计跳过数。
- 最终：`T376_PHYSICAL_RSA_SUITE discovered=42 executed=42 assumption_skips=0 ignored=0 failures=0`。包括原 T322 签名 E4→E5 自动恢复测试；该 T322 的 ZK CAS 是 in-memory fixture，不等于生产真实 ZK。
- T293 原始签名夹具 `/Users/kong/.opentradingcore/t293-live-rsa-20261029181500` **只读源**；实际测试数据克隆在隔离 `target` 临时目录，未覆盖原始私钥、证书或业务数据。

## 独立真实 ZK / JVM 故障注入已通过的阶段

1. `T120`：三节点测试 ZK 新命名空间 E1 READY；旧 A JVM EPHEMERAL lease 存活时拒绝提前晋升；B 的 Common Watch 先启动，然后对**测试 A** 真实 SIGKILL；旧 lease 失效后 B **自动** CAS 到 E2 RECOVERING；在缺失签名外部 READY 时保持不路由、不接受客户写入。标记 `T376_REAL_ZK_SIGKILL_STAGE_PASS`。
2. `T124`：独立 A/B 真实 RSA Genesis、双签名 fsync 和 reopen；A 真实业务 2 次写入经 A/B Quorum ACK；SIGKILL A 后，B Watch 自动取得 E2 RECOVERING，认证原始 Genesis、WAL、Custody 及恢复 Ledger，得到 `epoch=2 seq=2 total=40 customerReady=false`。标记 `T376_REAL_ZK_SIGKILL_RSA_WAL_REPLAY_PASS`，**不**虚报 E2 READY。
3. `T125/T126`：测试第三节点 C 独立 RSA 见证已恢复的 E2 状态后，B 获得明确的 **LOCAL_DURABLE（非 2/2 Quorum）** 降级写入授权，产生新状态 `total=60`，`quorum=false rpoRisk=true`；B 导出签名 E2 WAL 前缀，原主 A 真实重启，认证 A 的 E2 Replica 角色及 fsync 的一致 WAL，追平 `total=60`。标记 `T376_REAL_ZK_B_LOCAL_DURABLE_AND_A_REJOIN_PASS`。这一阶段明确允许 RPO>0，绝不能声称零丢失。
4. `T127/T128`：A E2 Replica 的反向 Watch 在 B 存活时提前启动；测试 B 真 SIGKILL 后，A 自动完成 E3 RECOVERING，并从签名 Genesis 与 E1/E2 WAL 完成正式 durable replay/install。标记 `T376_REAL_ZK_TWO_WAY_SIGKILL_E3_REPLAY_PASS`。**此时尚未完成独立 C 证明的 E3 客户 READY**，不能仅凭安装 Ledger 宣布业务可写。

5. `T129/T270/T272`：在独立 C RSA 签名的 E3 降级授权后，A 于 B 故障期间继续处理新业务，`epoch=3 seq=2 total=74 requests=6 quorum=false rpoRisk=true`。B 在新物理 JVM 中重新加入，验证 A 的 E3 签名 Genesis、独立 C 见证并安装为 E3 Replica，追平 `total=74`。随后 A 产生 E3 新业务，经真实 TCP 复制到 B 并在 B 实体 WAL fsync，`seq=3 total=85 requests=7`；标记 `T272_REAL_A_E3_NEW_BUSINESS_TO_REJOINED_B_TCP_RSA_FSYNC=PASS`。**这证实了两次真实 SIGKILL 后双方均可用签名凭据恢复并向已重连的副本复制，但仍属于 LOCAL_DURABLE 历史 ACK，不能追认严格 2/2。**

6. `signed-cycle` 首次执行时内层 T124/T129/T270/T272 测试成功（返回 0），而外层 T376 包装器错误要求仅在 `T129` 关闭的另一个分支才输出的 `T127_E2_B_KILLED_A_AUTOMATIC_E3_RECOVERING=PASS`，产生一次**外层误报 FAIL**。修正为验证真实 `T127_B_REAL_SIGKILL_A_AUTO_E3_RECOVERING_PASS`，随后对本轮原始日志 `otc-t376-a477c36a.log` 做独立只读验证，**5/5 阶段标记存在，JAR SHA-256 相同，且 RPO 风险标记存在**。保留这次外层失败的原因，避免删证据或伪称它从未发生。

### 测试命令

```bash
python3 tests/run-t376-isolated-common-physical-rsa.py \
  --worktree .work/t374-demo-common-ha \
  --base /Users/kong/.opentradingcore/t177-common-saas-crypto-integration-20261027 \
  --signed-fixture /Users/kong/.opentradingcore/t293-live-rsa-20261029181500

python3 tests/run-t376-isolated-common-zk-stage.py \
  --mode signed-cycle \
  --worktree .work/t374-demo-common-ha \
  --base /Users/kong/.opentradingcore/t177-common-saas-crypto-integration-20261027 \
  --expected-sha256 6489ca9d914d722fe4fb70e799846dc93eee1af49e5fc4db827e79eb22f022ee
```

测试日志位于 `.work/t374-demo-common-ha/target/t376-isolated-zk/`；RSA/WAL 及 Ledger 测试数据位于同一隔离工作树的 `target/t376-signed-replay-evidence/`。所有测试 ZK Compose 实例按脚本退出时执行 `down`，保留证据文件。实际日常业务没有热更新。

## 仍然明确未完成

- **256 分区真实故障注入**：以上物理故障注入是测试分区 P090；T359 的 256 分区 Home Return 是内存/控制面模拟，不能以其取代 256 分区物理 WAL + 签名 READY 的全量测试。
- **自动 Home 归位**：B 仍合法为主时，A 即使追平也不得抢主；后续需由 Common 执行认证撤权、按分区平稳回 Home，记录全部 128 分区回切总时间/P99 及部分已迁移时的状态。
- **严格零损失与 ACK**：E2/E3 LOCAL_DURABLE 应如实提示可能 RPO，不能代称 2/2 Quorum。真正零损失只可由相应 Quorum Durable 证明支持。
- **同一标准 Common 启动入口**：当前 T120/T124 Demo 通过 Common 认证 Watch/测试进程接口验证了真实恢复，但尚未在**真实 256 分区 Demo** 完整调用 `openAndStartWithCertifiedAutomaticRecovery` 统一启动接口并证明其 Watch 注册计数。这是下一道准入门禁。
- 验收全部通过后，才可统一构建/替换 Order/Trade 使用同一 Common Jar；Gateway 不改，业务 Robot 不受隔离测试的停机注入影响。

**当前整体状态：Common A/B 双向真实 SIGKILL、E2/E3 降级继续写入、双方追平与 A→B TCP fsync 已有分区级物理证据；但全量 256 分区、严格双副本 ACK 恢复与非故障条件下自动 Home 回切仍 NO-GO。**
