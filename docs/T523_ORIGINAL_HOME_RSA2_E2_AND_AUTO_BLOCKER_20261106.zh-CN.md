# T523｜真实原始 Home 双 RSA、E2 四节点启动与自动 HA 阻塞（2026-11-06）

## 验收结论

**已通过：** Order/Trade 各 256 分区双物理 E1 Genesis、双方独立业务恢复、A/B RSA 原始 Home 签发与验签、E1→E2 认证 CAS、四个 Spring JVM 启动、Common E2 本地 WAL 和 TCP 互通。

**仍为 NO-GO：** 生产 `automaticRecovery=true` 所需的 Common 自动物理恢复计划尚未连接，未做持续客户写入、A→B→A SIGKILL、真实成交及资金持仓一致性验收。控制平面 `READY` 与 `businessServing=false` 不等于客户 HA PASS。

## 代码基线及真实构建

- 全部操作使用 Mac 项目 `/Users/kong/dc-quant-deploy` 和 `saas-crypto-latest`。Common 最初本地工作树含 61 项未提交变更，且落后远程 73 个提交；**没有强推或覆盖**。
- 在独立干净 worktree 以远程 Common `a0ac037` 为基线，将 E1 Home 共用签发接口移植为 `d2d1ce0`，已正常 fast-forward 推送到 `bliplink/com.app.common` 的 `saas-crypto-latest`。
- Common 在独立干净工作树中 **335 个 Java 主源码**及 **192 个测试源码**全部 Java 8 编译 PASS；包括 HA/WAL/Snapshot/cross-Epoch 与原始 Home 的 **108/108 JUnit PASS**。
- 从这份源码生成并加载到所有四个 T523 业务进程的同一 Common Jar SHA256：`b170df0dffd6d8cbeeb64ff3ac9865fe5a89aa803d49580bf0d78eae123801b2`。四个容器内实读哈希相同。

## 真实物理证明（非模拟）

1. 独立 ZK 命名空间 `/otc/t523-fresh-20261106-r1/{order,trade}`，初始 `NPC1|1`、`RECOVERING`、version 0，各 256 分区，严格 A/B 互为 Replica。
2. Order/Trade A/B 四个独立 RSA 首次 E1 Genesis fsync：4/4 PASS；两个服务各 256 分区、phase 0/1 双签零 WAL 验证全部 PASS。
3. 四个业务进程的 E1 Journal/Snapshot/`REPLAY_COMPLETE` 恢复账本均 256/256，确有原始物理 WAL、各自业务恢复目录；原始 Home 只在仍有两份合法 E1 租约时签发。
4. 新 Common-only `provisionOriginalHome` 以既有原始 RSA 身份和原始同 ZK 会话，对实际双节点 Genesis、零 WAL、恢复账本逐分区重新验权，并独立 fsync A/B 收据；每个服务都有 `original-home.v1`、`<service>A.original-home.rsa`、`<service>B.original-home.rsa`。
5. Common `requireBothOriginalRsaReceipts` 真实重开 Order/Trade 两份 Home 均 256 分区、A/B 原始主各 128、Epoch 1。8 项反例（不同 namespace、同公钥、损坏 B 签名、缺失 A 签名 × 两服务）正确拒绝，只篡改临时副本，原始收据不变。
6. 重新经过 Common 原始 E1 真实恢复和 CAS，Order/Trade 两份 ZK 清单均达 `NPC1|2`、256/256 `STRICT_QUORUM|READY`；仅控制平面，明确 `businessServing=false`。

## E2 Order/Trade 实际 JVM 验证

- 新隔离 Docker 卷 `otc-t523-born`（原始证明）、`otc-t523-ready-data`（E2 物理 WAL），不与原 T488/T522 卷共用。
- 四个容器：`otc-t523-order-{a,b}-hostready` / `otc-t523-trade-{a,b}-hostready`，全部持续运行并有 `Started OrderSvr/TradeSvr` 日志。
- 每个节点均独立持久化 256 个 `epoch-2/business.wal`；四个 Common Jar SHA256 完全一致。
- Host 网络隔离业务端口：Order 34536/34541、Trade 34537/34546、Order Common 46522/46523、Trade Common 46422/46423，**8/8 TCP connect PASS**；Order A/B 对 Trade A/B 实际预连接 **2/2 PASS**。
- 原 T488 四容器及 T522 四容器/数据仍保留，未替换或清空。T523 业务首次运行设置 `automaticRecovery=false`，不可声称自动 HA。

## 自动 HA 真实 NO-GO

- 只停止 T523 Trade B 候选，启动 `automaticRecovery=true` Pilot，挂载真实原始 Home、独立签名源和 Reader HMAC 物理文件；没有借用或篡改旧节点证书。
- Pilot 在 Spring Bean 接线处 fail-closed：`NoSuchBeanDefinitionException: CommonCertifiedNodeBootstrap$CertifiedPhysicalRecoveryPlanFactory`，退出 1；日志保存在 `~/.opentradingcore/t523-fresh-20261106-r1/trade-b-auto-pilot-nogo.log`。
- Pilot 已停止，T523 Trade B 原有 E2 模式已重新启动；确认 T488 原容器正常。
- Common `CommonCertifiedProductionPhysicalRecovery` 已存在，但目前 E1→E2 生产恢复路径对独立 C RSA 有明确约束；跨 E2→E3 等阶段存在拒绝门禁。不能通过假造 Bean、空 Plan、绕开 Home/Watch 或把 C 签名冒充 A/B 签名来报告自动 HA PASS。

## 下一步必须按边界推进

Common 应提供**服务无关**的生产自动物理 Plan 注入和完整跨 Epoch 恢复执行器；只接收各服务的业务 `byte[]` 状态、Snapshot/Restore 接口和必要的隔离写入屏障。不能在 Order/Trade 中实现选主、Watcher、物理复制、认证恢复或 READY。

先在 Demo+Common 实证真正 A/B 两节点持续写入、单节点可工作、故障隔离、A→B→A、重启追平、严格与降级 ACK 分开标注；再同 SHA 换业务容器，进行租户/Robot/真实成交、余额/持仓/Projection 一致性和 10/50/200 压测。既有要求的 **A/B 互备** 不允许为了过关而悄悄改成第三业务副本/新集群。

本轮没有调用 GitHub Actions，没有执行 T523 业务节点 SIGKILL，没有证明真实客户 ACK，也没有将未通过项目写作 PASS。