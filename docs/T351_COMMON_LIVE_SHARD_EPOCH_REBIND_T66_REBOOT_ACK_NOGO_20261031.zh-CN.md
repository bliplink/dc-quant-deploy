# T351｜Common 分区物理运行时原位换 Epoch + RF2 Demo 重启 ACK 阻塞（2026-10-31）

> **状态：部分 Common 单测 PASS；真实自动 A/B HA 和在线 Order/Trade 交易仍 NO-GO。** 遵循已定稿 `COMMON_AB_HOME_PRIMARY_AUTO_FAILBACK_ARCHITECTURE_20261031.zh-CN.md`：每个服务 256 分区，A/B 常态 128/128 主备，故障自动接管，回归先追平后自动回 Home。不能叠加第二套选主或业务 HA。

## T351 Common 修改与安全边界

此前正式 `CommonCertifiedNodeRuntime` 将 256 物理分区和 Primary writer 映射、Netty dispatcher 绑定为**启动时只读快照**。即使某一分区已合法完成新 Epoch 恢复和 READY，原 JVM 也不能在不关闭共享 Netty 的情况下由 Replica 转 Primary；这违反健康分区不受影响及后续多次互切。

本轮只在原 Common 类中增加对**单目标分区的内部换代**：
- `CommonCertifiedNodeNettyDispatcher`、`CommonCertifiedRecoverySourceRouter`、`CertifiedBusinessCommandRegistry` 使用 copy-on-write 分区快照，保留同一个 Netty listener，原签名恢复 handlers 在该分区换 Epoch 时失效。
- `CommonCertifiedNodeRuntime.installCertifiedRecoveredPartition` 当前为 **package-private 内部原语**，不是业务可调用的 READY/恢复接口。仅接受已存在分区、同一个 service/node、严格提高的 Epoch，要求当前签名 READY 分区授权、实际新物理 WAL/角色可验证，原物理分区的旧角色不得仍可用，先关闭旧物理句柄、再替换共享路由和写入口；任何失败保持该分区隔离，不替换健康分区。
- 设计上此内部原语还须由**既有** Common 签名 Stage / Snapshot+WAL 恢复 / 业务状态机 replay / 两物理节点 recovery receipt / 已认证 READY 生命周期调用。**目前尚未将上述全套在线回调接入，绝不能由合成 grant 单测推出线上接管通过。**

定向 `CommonCertifiedNodeRuntimeTest` 用原 Demo A/B RSA 密钥和真实 Netty listener 检查 Replica 在测试用新 Epoch grant 下重新安装为新 Primary，旧 E1 实际句柄无权且端口不变。**14/14 PASS，0 skipped**。该测试的新 ZK 控制面是明确标记的**测试用模拟授权**，没有自动 real ZK CAS，也未发送客户端严格 ACK（测试未构建真正新 Epoch Replica）。

- 完整 Common Maven 指定真实 E4→E5 RSA 与 P193 原始 WAL 路径，**153 suites / 660 tests / 0 failures / 0 errors / 6 skipped**（exit 0），新 Common 本地 commit **`171eee4`**。测试套件结果不是实际线上主备自动切回证明。
- 新 Common JAR 在 Mac Maven 本地安装，随后 Order/Trade saas-crypto 源码兼容 Maven 执行 exit 0，之前复核为 Order 137 项/2 跳过、Trade 207 项/0 跳过，均没有失败。正式 Order/Trade 镜像未在此轮构建与替换。

## T66 原隔离 RF2 真自动 HA 故障重新复验

独立源码 `tests/run-common-rf2-ab-auto-e2e.py` + 原 v19 隔离多 JVM（三真实 ZooKeeper，A/B 两份 WAL），新的 Compose project `otc-t66-7b31a9fc6`，与当前 `dc-saas-*` 容器/目录完全隔离。
- A 初始 E1 严格提交 seq1 通过；SIGKILL A，B 自动 E2 LOCAL READY，seq2 单节点 ACK 且明确 `quorumDurable=false`；A 恢复并追平，B 自动 E3 STRICT READY，seq3 物理双副本 ACK；反向 SIGKILL B，A 自动 E4 LOCAL READY，seq4 ACK；B 追平，A 自动 E5 STRICT READY，seq5 双副本 ACK。至此双向 A/B epoch 和状态摘要一致。
- **失败点**：完整停启两个 JVM/三 ZK 后同 requestId `t66-accept-06` 的 seq6 请求连续超时，脚本退出码 **1 / FAIL**。通过保留的独立 Docker 容器重启并只重试同 requestId，取得真实 TCP 响应 `503 RF2_STRICT_ACK_NOT_DURABLE: remote dual receipt fsync failed`。A 本地日志明确停在 `phase=remoteCustody`，**缺少** `phase=twoPhysicalReceiptArchives` 及 `phase=finalACK`；不得把 WAL 已落盘或 ZK E5 READY 误认为 seq6 客户端成功。
- 只读检查旧实验 Common `DurableWalCustodyReceiptLedger`：跨重启其 `load()` 要求 receipt quorum 头与当前 custody 头精确一致；当前测试的 `seq6` 情况应调查物理 Custody 已推进而旧 receipt quorum 尚未跟进的合法崩溃/重试窗口。Common 已有 `openForCertifiedCrashCompletion` 依原前序证书和独立保全文件核验，不得通过删除旧 ledger、降低 2/2 严格门禁或伪造 fsync 来修复。本段是**可疑根因**，不是已经证明唯一原因。
- 证据项目停掉所有 A/B 和三 ZK 实验容器，但**没有删除独立数据卷/旧现网 P193**，可以继续审计。旧实验本身仅验证单分区 P000，不能当成最新 Common 256 分区自动 Home failback。

## 替换 Order/Trade 的明确门禁

- 继续在**唯一 Common** 修复签名 E3 物理恢复和 crash-safe receipt 续传，原位切换后由同一常驻 Watch 自动下一轮切主/回 Home；不要再做额外恢复子系统。
- Demo+Common 必须：256 分区 A/B 各 128 主→A SIGKILL B 接管全部→A 追平自动回 Home→B SIGKILL A 接管全部→B 追平自动回 Home→全量重启→还能继续下单，明确 LOCAL vs QUORUM ACK 和水位、一致性。
- 只有这些**实测 PASS**，才本地重建/替换正式 Order/Trade，启动自动审批 Robot、持续报价/Tape、下单成交、结算与连续 HA 验收。T330 原始 P193 A22667/B22668 未签尾原样保留，不得凭非认证尾部强行 READY。

**当前绝不能宣布交易系统恢复；正式容器仍沿用旧 T335/T336 镜像，Robot 暂未启动。**
