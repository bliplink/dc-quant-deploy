# T327｜Common 非空 E2 签名重启、Projection 读取接线与测试资金缺口（2026-10-30）

## 目标与边界
按用户要求先恢复正式 Demo 交易功能，Gateway 继续读取原有 `/MDTService/{OrderSvr,TradeSvr}` ZooKeeper 注册。所有真实 Epoch/Primary/Replica/WAL/CommitIndex/Custody/恢复位于 Common，Order/Trade 只承担其业务状态读写与既有 Projection 协议；不恢复私有 HA、旧 Chronicle Journal 或新订单类型限制。本轮未使用 GitHub Actions、未清理签名 WAL、未推送分叉远端。

## T326 已完成代码与构建
- Common `CertifiedBusinessCommandBoundary.readCertifiedCommittedWindow` 暴露受界限保护的物理认证字节窗口（对调用方仅 opaque `byte[]`）：确认当前 Primary/ZK/Epoch、物理 WAL、CommitIndex 已签 HEAD、双独立 Custody 签名回执、Grant；尾部未提交、未授权/撤权、未来水位全部拒绝。没有业务格式或第二份状态机。
- Order/Trade 原有 `FetchCommitted*ProjectionEventsHandler` 不再固定返回 `*_COMMON_PROJECTION_COMMIT_INDEX_NOT_CONNECTED`，改为读取 Common 签名窗口，解码原业务 `OrderJournalRecord`/`TradeJournalRecord`，保持已有 Projection Wire 协议；BINARY FETCH 不是第二套存储。
- **Common 全量：152 suites / 652 tests / 0 failures / 0 errors / 9 skips**（首次只读改动后）；物理 Netty/RSA/Custody 的读取测试 6/6 PASS。Order 39 suites /126/126 PASS，Trade 52 suites /203/203 PASS。
- 本地镜像 `local/otc-t326-ordersvr:certified-projection` 和 `local/otc-t326-tradesvr:certified-projection` 已构建，同一 Common JAR SHA256 `1054745a0f1822debd9ecb0f1ce67b43fd0723fe78d6a4fad79cd39fc1b207f9`。保留 T319 原业务镜像基底，不重建 Gateway。

## T327 Common 非空 E2 有条件恢复
正式替换 B 时发现既有物理签名 WAL 非空的正确拒绝：`Common virgin E2 cannot certify nonzero or linked existing WAL`。此前 Common 原始首次 E1→E2 空 WAL Replica 工厂误用于后续 **同一 Epoch2 签名 WAL 冷启动**。仅在 Common 拆分准入：
- Virgin E2 仍只能空 WAL；
- **Warm E2** 必须先由原 `CommonOriginalFirstReadyBusinessGate` 完成真实 Spring 业务冷回放，并已重新校验原 RSA/Gateway ZK 成员、双物理原始 WAL 签名 Custody、同一 Epoch 和 SHA；再次打开只读物理签名 WAL 验证无变化；`CommonCertifiedStrictReplicaAdmission` 出具精确成员/角色的 Replica 恢复提示，节点物理层仍独立重验 ZK Grant；
- 有非零 WAL 的 Replica 又强制检验原始 `custody-ledger` 内的双物理 fsync Receipt，而非仅检查 WAL 或 Custody 目录；E3+ 仍只允许已有严格恢复票据。

T327 相关 Common 物理测试 **23/23 PASS、0 失败**；Common 新 JAR SHA256 `0a2ca0e3096dfec6daf68d4867fe840b0117a944d52139275cb2f1ef2e433cc2`。两套本地 T327 镜像 `local/otc-t327-ordersvr:signed-warm-e2`、`local/otc-t327-tradesvr:signed-warm-e2` 仅覆盖同一 Common JAR 和 FETCH 处理器，保留原 T319 业务程序其余文件。`compose.t327-signed-warm-e2.yaml` 与 T325 原符号/原 RSA 只读挂载文件叠加。

**正式 Docker 实测**：Order B 原始 6 个非空 E2 WAL、对应双节点签名 Custody 均保留；T327 真实 Spring 在 **57.735 秒**启动成功，注册日志为 `COMMON_GATEWAY_DISCOVERY_CERTIFIED service=OrderSvr node=OrderSvrB endpoint=127.0.0.1:33041 exactOwnerSession=true`，ZK `/MDTService/OrderSvrB` 出现 `[OrderSvrB]`，重启数 0。Order A 原有 T319 镜像持续运行、重启数 0。本次并未执行 Order A/B SIGKILL 主切，所以严格 HA 仍 NO-GO。

## Trade B 阻塞：外部 MySQL 被测试脚本提前清除的资金 Posting

真实 Trade B 使用 T327 重启时，新 Common 签名 WAL 校验阶段已经通过，但 Trade 自身 `TradeRecoveryApplier.applyColdSignedE2BeforeServing` 正确拒绝：`TRADE_COLD_E2_POSTING_MISSING_DB`。Trade B 为避免持续重启已停止，未注册 ZK；Trade A 未替换，仍原镜像运行。

已用只读 Python 校验原 A/B 两份 P123/P196 物理 WAL **字节完全相同**。P123 原始 E2 WAL 13 帧中有 **12 条 `T325_E2E` 测试用户的认证入金 Posting**，所有 Entry 可用 SHA256 的稳定请求 ID 重新验证；MySQL 只剩 4 条（上次完整 R4 测试）；8 条被之前 R2/R3 反复执行的 `tests/run-trading-rules-e2e-host.sh` 直接 SQL 清除。原四个测试账户在 MySQL 余额均为 300000，吻合三轮每人 100000 的已签提交历史。P196 有 11662 帧，含三个 R32530 签名入金，MySQL 三条仍在；该分区非 `T325_E2E` 数据不得清除。

**尝试仅恢复 8 条已经物理一致且请求 ID 验证的测试 Posting 时，执行平台安全检查阻止 MySQL 写入**。没有绕过限制、没有修改账本、没有生成或伪造新资金 WAL，未把资金门禁放宽。为避免不小心再次执行，原临时 SQL 文件已经删除。待授权的可靠修复需要使用原签名 WAL 严格一一核对并恢复隔离 `T325_E2E` 的被误删 Posting，或以正式签名重新初始化一个全新独立 Demo 命名空间；**禁止重置旧非空签名 WAL 或继续 SQL 删除**。

已对 `tests/run-trading-rules-e2e-host.sh` 正式修复：对已经存在账号、Posting 或订单的测试租户自动 FAIL-CLOSED，不再进入破坏性 SQL fixture 重置；每次真实验收须使用全新 `*_E2E` Location 和身份，同时强制提供 Trade 认证 `cashIn` 所要求的确定性 `Info1` 请求 ID。真实旧 `T325_E2E` 再运行测试已验出 `T327_REUSED_SIGNED_FINANCIAL_FIXTURE_REJECTED_BEFORE_MUTATION_PASS`，保护 PASS。

## 截止本轮实际状态

| 组件 | 正式状态 | 结果 |
|---|---|---|
| Order A | T319 原镜像，运行，重启 0 | 仍在提供服务 |
| Order B | T327 新镜像，原非空 WAL/RSA 冷恢复后运行，重启 0 | **PASS** |
| Trade A | T319 原镜像，运行，重启 0 | 仍在提供服务 |
| Trade B | T327 签名恢复发现 8 条历史测试入金缺口，安全退出 | **NO-GO** |
| Robot | 由于 B 离线、避免严格签名 WAL 不断失败，临时停止 | **NO-GO** |
| Projection | 旧运行镜像；尚未由全新 A/B FETCH 全链路验收 | **NO-GO** |
| Gateway | 原代码未改；已对 Order A/B 注册进行验证 | PASS |
| Tape/真实成交/对账/自动主切 | 未通过完整端到端 | **NO-GO** |

正式订单/成交资金/持仓一致性和自动 A/B 互切尚不能宣布成功。只有在修复合法历史投影缺口，并让 Trade B/A 在原签名 WAL 通过冷启动，再验收 Projection→Robot→Tape→真实交易后，才能宣布业务恢复完成。旧镜像、原 T181 RSA/Genesis、T325 签名 WAL、正式 ZK 均保留。
