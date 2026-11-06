# T526｜Common 通用 STRICT E(n)→E(n+1) 原始 Genesis/WAL 恢复实证（2026-11-06）

## 结论

**已完成 Common 业务恢复入口通用化、使用真实 E4 物理 RSA 证据进行 E4→E5 正向恢复、Common HA 回归 114/114 PASS，并用新 Common JAR 重新完成 Demo 三 ZK 双 SIGKILL A→B→A；生产 Order/Trade 自动 HA 仍 NO-GO。**

### 这次改动只在 Common

- 旧 `CommonCertifiedOpaqueGenesisSurvivorInstall` 被固定为 E1 STRICT→E2。它本来就是正确的通用恢复事务，实现原始物理 A/B 双 RSA Genesis@0 + 认证原始 WAL@1..N + snapshot 原子封存 + 业务 byte[] replay + REPLAY_COMPLETE，不需要新 WAL、Watch 或第二套交易状态机。
- T526 将成员身份 `oldMembers.epoch` 作为真实历史 Epoch，统一核对恢复 Stage 为 E(n)→E(n+1)、旧 READY/新 RECOVERING 都是 STRICT、签名原始 Home/物理成员/原始 WAL/custody 均同 Epoch。Snapshot 选择原始独立双 RSA `genesis-e<n>.snapshot`，恢复提交 Ledger 使用实际签名 n；不再用硬编码 1/2。
- Stage 不接受服务自造：调用 T525 已有的 `CommonCertifiedFailoverCoordinator.reopenSignedRecoveringPredecessor`，从**同一 Common 协调器自身的签名账本**重开真实 ZK RECOVERING 阶段。
- 不对 Order/Trade 添加任何选主、ZK、Snapshot、WAL、复制、READY 或 ACK 代码；业务只实现已有的状态机 restore/apply/snapshot 接口。
- 所有持久化来源不匹配都先撤销易失业务 replay 证明并保持 NOT_READY；成功业务恢复**不能**发布 READY，也不等于已恢复两物理签名的新 Epoch 严格 ACK。

### 实证 1｜真实旧 E4 RSA + WAL → E5 业务恢复

- 原始只读档案：`~/.opentradingcore/t293-live-rsa-20261029181500`，含两个独立物理节点签名的原始 E4 Genesis/quorum、真正 E4 A/B 原始 WAL、CommitIndex、双 Custody、签名 E5 Stage。
- 新测试：`CommonCertifiedOpaqueGenesisAnyEpochTest` 使用**实际 E4 原始已签名文件**，独立读出 2 条客户已提交的 WAL 记录，将原始 E4 Genesis 作为业务 snapshot 并顺序重放到真实 Common `DurableRecoverySnapshotSeal` + `DurableRecoveryInstallLedger`；对比恢复的业务 Snapshot 字节、提交水位与 REPLAY_COMPLETE 均 PASS。
- 缺少 E4 双 RSA Genesis 时，在业务 apply/restore 前拒绝，0 次业务突变。测试 ZK 是与签名原始 E5 Stage 核对的内存夹具，故**不声称这项测试是新的 3ZK E5 STRICT 生产切换**。

### 实证 2｜全量编译与 Common 回归

- 基于 T525 源码工作树全量编译：Java 8 主源码 **336/336**，测试源码 **194/194**。
- 生产/恢复相关 HA/WAL/Snapshot/跨 Epoch/RSA JUnit **114/114 PASS**，0 failures，包括 T526 E4→E5 真正物理证明正向恢复与缺失 Genesis 负向拒绝，耗时约 144 秒。
- 同目录 JAR：`~/.opentradingcore/t526-build-20261106/t526-common-all-main.jar`；SHA256 `f08c59a291849b6c3bb635bc451a2706642af8e017d90381749af4d21dcb433a`。

### 实证 3｜T526 全新三 ZK / Docker 双 SIGKILL

- 隔离归档：`~/.opentradingcore/t526-real-demo-double-kill-full/20261106165425`。
- A Primary E1 双 RSA ACK → 实际 SIGKILL A → B 通过 Common 自有 Watch 进入 E2 RECOVERING、重放签名 WAL；C 独立签发 E2 LOCAL 证据后 B 继续业务写入 → A 重启，恢复为 Replica，原始 E2 WAL 追平。
- 再 SIGKILL B → A 自有 Watch 完成签名 E3 RECOVERING、Genesis+E1/E2 原始 WAL 原样重放；C 独立签发 E3 LOCAL → A 继续交易；B 真实重新加入 E3，Common 自动 Replica Watch 追平；A 后续 WAL 经 TCP 发送给 B 真实 fsync。
- 最终 A/B 业务状态 `total=85`，请求数 `7`，退出码 `0`，不遗留此轮 Docker fault-injection 容器；**E2/E3 客户端 ACK 是 LOCAL_DURABLE_ASYNC、有 RPO 风险，不得宣称 E2/E3 客户端 QUORUM_DURABLE PASS。**

### Github 提交与代码版本

- 本地测试提交：`a6d8294`（因本地到 github.com 443 不通，不能声称该本地 Git SHA 已直接推送）。
- 已通过 GitHub 连接器将 T526 生产类更新到 `bliplink/com.app.common:saas-crypto-latest`，远程提交 `33fcb03dbc6735edf13688f682ae9f522eb16f5a`；新真实 RSA JUnit 提交 `dd8a84c03fa501d30f4dd198da74022f5ccc40ea`。远程独立提交 SHA 与本地提交 SHA 不同，禁止强推。

### 仍未通过的真实生产门禁

1. `CommonCertifiedProductionPhysicalRecovery` 当前仍绑定**原始 E1** `OriginalE1` 和单独的 E1 Genesis 来源。它的 256 分区当前 Epoch 完整性检查仍正确拒绝缺少 E2 证明的 Replica；生产 `CertifiedPhysicalRecoveryPlanFactory` 尚未面向真实 E2 完整接线。
2. T523 Order/Trade 的实际隔离 Docker 盘核查：四个服务节点各有 256 个空 E2 `business.wal` 文件和 Custody 目录，但无非空业务 WAL/真实快照。不能用空分区 readiness 冒充新租户实交易恢复。
3. 需在 Common 建立当前 Epoch 的实际双 RSA Genesis/Snapshot 与原始 WAL 认证安装，并让 Common 的 256 分区生产工厂从已经打开并验过物理 WAL 的节点自动装配。随后真实 SIGKILL、旧主隔离、自动恢复、租户 Robot/成交/余额/持仓/Projection 验收。
4. Demo 的降级 LOCAL 写入可在独立 C 策略授权后持续服务；严格 2/2 ACK 恢复必须另行取得 A/B 目标 Epoch 两份物理恢复证明，**不能用 LOCAL 历史 ACK 补签成严格 ACK**。

最终状态：T526 通用原始签名 Epoch 恢复 PASS；**Order/Trade 生产 256 分区自动 HA 仍 NO-GO；不得替换正式交易节点或自行添加业务集群实现**。