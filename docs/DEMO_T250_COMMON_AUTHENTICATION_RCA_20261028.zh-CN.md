# T250｜Common 频繁“认证失败”的根因与故障场景审计（2026-10-28）

**状态：Common Bug 及单分区隔离修复已通过定向回归；Mac Demo 真实双 Receipt 补齐和交易 HA 仍 NO-GO。**
源码原地保留用户的 `saas-crypto` 工作树；不运行 GitHub Actions，不清理真实旧证据、不改写 ZooKeeper READY、不伪造 RSA。

## 结论：不是单一“签名经常算错”

综合 T247/T249 真实数据、T143 运行二进制对照和 Common 代码，反复出现的“认证失败”有**三类**，不能混成同一个错误：

| 类别 | 性质 | 已证实证据 | 对运行的影响 |
| --- | --- | --- | --- |
| A. 认证提交分布式持久化存在中断窗口，恢复状态覆盖不完整 | **架构/故障场景遗漏** | P210 A/B 的 WAL、CommitIndex、Custody HEAD 为 E2/35427；A/B 双 Receipt Ledger 为 E2/35426；实际写入在 16:20:40.285–.464 完成，最后一步没有更新 | 无法证明 35427 已达到完整 ACK 门槛；重启时 Common 必须拒绝自动 READY，但现有实现没有常规可信收尾事务 |
| B. WAL 尚未开始、仅因瞬时授权预检查失败也永久 poison 分区 | **实现 Bug** | 旧版 `CertifiedBusinessCommandBoundary.commit()` 在单一 catch 里总是 `poisoned=true; physical.poison()`，无论是否调用过 WAL Writer | 普通短暂 Grant/旧 Epoch 拒绝可能升级为长期分区不可写 |
| C. 单个分区出错后，其余分区一同拒写 | **实现 Bug / 故障域扩大** | `CommonCertifiedNodeRuntime.requirePrimaryRegistry()` 旧版每次执行 `requireAuthenticatedReady()`，遍历全部物理分区；任何一个 writer poisoned 导致整体拒绝 | P210 故障波及节点上其它 127 个 Primary 分区 |
| D. 服务在 Common 首次异步授权刷新完成前读取 Census | **启动时序 Bug** | `NodeClusterControlManager.start()` 初始刷新在另一个执行线程中，旧 Order/Trade 立即读取，可能失败；见 T249 | 镜像启动摇摆/误判 Census 不可用 |
| E. 故障日志只展示二次拒绝，无法定位首个失败阶段 | **可观测性缺陷** | 16:20:43 日志连续 `Common physical primary not certified`、`writer unavailable`；但没有直接记录首次丢失的 CommitIndex/Custody/Receipt 阶段 | 反复排查 ZK、签名和 RSA，却找不到最早触发点 |

**未被证实**：P210 第一次提交失败的确切外因是 SIGKILL、GC 暂停、ZK 过期、Netty 超时还是资源调度。16:20:39–43 存在交易操作变慢及约 3 秒等待，但配置的节点租约 TTL 为 **15000ms**、续租 1000ms；不能仅凭这段 3 秒暂停断言 ZooKeeper TTL 过期、签名算法有问题。

### 物理数据证据

- T247 的三个 WAL 未认证尾部：Order P106 与 P142 各 1 帧、Trade P023 1 帧，均已在停机和独立 fsync 取证后恢复到 A/B 共识的认证 HEAD。它们属于**另一种中断窗口**，不能与 P210 一起盲目截断。
- P210 的 A/B Receipt Ledger 修改时间 **16:20:40.238–.240**，A/B 最新 WAL **16:20:40.285–.383**、A CommitIndex/HEAD **16:20:40.386–.388**、B HEAD **16:20:40.464**。两节点拥有相同的最新认证 HEAD，但旧 Receipt。旧 Epoch 被永久撤权后，**不能重新生成历史回执并冒充此前的 ACK**。
- 原始证据保存在 `/Users/kong/.opentradingcore/t248-p210-forensics/P210-20261028T095116Z`，未修改。

## T250 已实现代码与测试

1. **Common WAL 前置授权 fail-closed、但不永久毒化**：`CertifiedBusinessCommandBoundary.commit()` 的 preflight grant、authority、业务编码在真正进入 WAL Writer 前失败，拒绝当前请求且下次重新检查授权；只要进入 WAL 写入阶段仍强制毒化，连 Java `Error` 也捕获并保护脏尾部。保持严格密码学 ACK、RSA/WAL 状态机不变。
2. **提交阶段可审计性**：原异常附带 `COMMON_COMMIT_PHASE partition=Pxxx epoch=... seq=... phase=... walWriteStarted=...`，定位 `PREFLIGHT_PRIMARY_GRANT`、`WAL_APPEND_FSYNC`、`INDEPENDENT_WAL_FSYNC_RECEIPTS`、`COMMIT_INDEX_FSYNC`、`CUSTODY_INSTALL_AND_REPLICA_LEDGER`、`PRIMARY_RECEIPT_LEDGER_FSYNC`、`FINAL_PRIMARY_GRANT` 等首个失败环节；不输出原业务 bytes、私钥或签名内容。
3. **分区级故障隔离**：`CommonCertifiedNodeRuntime.requirePrimaryRegistry()` 验证一次真实节点级认证 Census，但不为一个 P210 poison 逐一拒绝其他分区；目标 writer 在本 partition 校验原始授信及认证 WAL/HEAD。正式启动 `requireAuthenticatedReady()` 仍对全部分区严格检查。
4. **Common 通用业务 Apply 和 Snapshot**：`CommonCertifiedBusinessApplyBoundary` 不再在授权预检查失败时永久污染业务分区，只有物理 WAL 写入器确实 poisoned 或已经完成物理提交后业务 Apply 失败才隔离。Snapshot 只检查目标分区授权，避免无关分区传播故障。
5. **针对性故障注入测试**：
   - `CertifiedBusinessCommandPreflightFailureTest`：租约拒绝→未写 WAL→可再次尝试；Epoch authority 拒绝；WAL 中途 IOException / JVM Error →仍必须 poison，带明确 phase。
   - `CommonCertifiedPartitionIsolationTest`：用两组临时 RSA 测试密钥和真实 Common WAL/Netty，将 P210 的副本 TCP 故意设为不可达，物理提交不得 ACK 且 P210 被毒化；**P211 的真实认证写入器仍可取得**，全节点严格健康检查仍报告 P210 故障。
   - T249 已有 `DurableWalCustodyReceiptCrashCompletionTest` 及密码学 ACK、Census 测试继续运行。
   - **Java8 + JUnit：30/30 PASS，0 failures**。包括用最终**原镜像 Common Jar 的定点补丁字节**运行的 30 项回归；不是全面 Maven 或真实跨机 HA。
6. **镜像和 byte-for-byte Common 复用**：以 T249 Jar 为原件，仅将 `CertifiedBusinessCommandBoundary.class`、`CommonCertifiedNodeRuntime.class`、`CommonCertifiedBusinessApplyBoundary.class` 三个已测试类覆盖；严格核验其余 644 条目不变。候选 Common Jar SHA-256：
   `d75211eaec502aa6918264b0d3d39d01042f1de6f21fb25a15414340fc6f7a08`。
   Order/Trade 候选镜像均已本地构建，且实际内部 Jar SHA 一致：
   - `local/otc-t250-ordersvr:common-auth-isolation`
   - `local/otc-t250-tradesvr:common-auth-isolation`

## 仍缺少的根本机制（不得虚报已修）

**分布式 CommitIndex → 物理 Custody → 双 Receipt Ledger 不是一个原子文件事务**。任一步被 SIGKILL/断网/超时中断，下一次启动都必须能把已持久化的不可变证据分类，而不是无限重启失败：

1. `WAL > Certified HEAD`：可能是未认证尾部；必须交叉检查 2 节点实际 WAL、CommitIndex、HEAD、签名与独立 RPO 证明，封存后才可回退或续写。
2. `CommitIndex > Physical Custody`：已经有双签原始 WAL 证书、尚未双物理安装；必须完成正式认证恢复，不能当 ACK。
3. `Physical Custody > Receipt Ledger`：P210 实际案例；若旧 Epoch 仍有效且 A/B 物理安装未变，可以重新获取**新的合法安装回执**并通过 Common `persist()` 完成账本；如果旧 Epoch 已被吊销，不能事后补签，必须依照已认证新 Epoch 可信接管事务或完整 Fresh Genesis。
4. `Replica Ledger > Primary Ledger`：主节点 ACK 前失败，幸存 B 可能已保存双签；应从独立 B 的现存不可变双签恢复，而不是要求重新签发。
5. `Ledger 已写但客户端 ACK 丢失`：客户端可能重试；业务必须使用幂等命令 ID 去重，避免重复资金、成交。Common 只保存 opaque byte[] 和严格 sequence，不做订单类型策略。
6. `主节点死亡 / B 不可用 / 节点 ZooKeeper session loss`：主切前旧主 fencing、Snapshot/WAL 完整追平、真实独立 quorum proof 和新 Epoch 都必须满足。单节点降级不能用假的 STRICT 2/2 签名代替。

还需要 **10–50–200 租户运行期间**对每个阶段注入真实 SIGKILL、网络丢包、Replica 拒绝/延迟/重启、ZK 断会话、fsync 失败。验收看最终实际 WAL/Order/Trade/资金/Projection，一律不以仅有 ZK READY 或测试 PASS 当作成交完成。

## 本轮部署状态与下一步

- 最后一次 `tests/t248_audit_common_physical_certified_integrity.py` 仍然是 **2 条 P210 A/B Custody Receipt mismatch**；未改任何真实签名账本/私钥/分区 Epoch。
- Order/Trade A/B 与 Robot 仍停止；本轮没有运行真实下单或 HA 故障切换，候选镜像不等于部署完成。
- 旧节点恢复前须优先完成 P210 的真实双节点签名收尾；之前在这一步调用真实签名进程时被执行环境安全检查拦截，禁止绕过。
- 如果不可得到合法证据，用户已允许的 Demo 应按**整套 ZK/Common/Order/Trade/Projection/MySQL 清空重建**统一 Genesis，不可只改 P210 或强行赋予 READY。
- 下一轮应把五类阶段故障注入及机密数据不泄露作为 Common 的可重复 CI/本地门禁，单节点仅向业务提供已实际授权的分区，不允许故障跨分区扩散。

**Common 源本地提交**：`e3daa81`（T250，基于 T249 `2ecfaf4`）。`dc-quant-deploy` 统一引用补丁：`tests/patches/t250-common-auth-isolation.patch`。Order/Trade 原业务源码不因本轮新增订单类型检查；持续复用已生成的 T249 通用接线与同一份 T250 Common。