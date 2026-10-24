# T81 — 将真实 RSA CommitIndex / Custody 验证迁入正式 Common（2026-10-24）

## 结果

**正式 Common 已本地提交 `ead6602`，Java8 64/64 项专项回归 PASS。** 已把 V19 旧隔离试点中的通用、独立于交易业务状态机的 RSA WAL 提交证明、持久化 CommitIndex、独立 Custody 证明与持久化 Custody 文件实现搬回 `com.app.common.replication`，并新增真正执行 RSA 验签的 `CertifiedSignedWalEvidenceVerifier` 实现 T80 门禁的物理证据接口。

- 源仓库：`/Users/kong/.opentradingcore/common-batch-official-release-20261013/common`，`saas-crypto`，提交 `ead6602`（仅本地，未push、未执行 GitHub Actions、未发布 Maven）。
- 原封不动复用并逐文件比较旧试点来源的4个类：`DurableWalCommitQuorum`、`DurableWalCommitIndex`、`DurableWalCustodyQuorum`、`DurableWalCertificateCustody`；一并迁入3个直接JUnit测试。
- 新增 `CertifiedSignedWalEvidenceVerifier`（及JUnit）：真实检查 RSA WAL quorum certificate 的签名、旧 Epoch/分区/旧主备的受信成员身份、候选节点本地已 fsync 的 WAL SHA256，随后检查两张 *distinct* RSA Custody 安装收据。向 `CertifiedNodeRecoveryGate` 提交分区、epoch、seq、SHA 和独立物理签名者，原门禁仍逐分区校验新Epoch旧主隔离、ACK策略不自动降级。
- 另外拒绝原 Manifest 不存在的新 READY 分区绕过 Genesis，或把 RECOVERING 直接以同一 Epoch 变为 READY。

## 测试（真实 RSA 计算，但受控的Java8单元测试环境）

Java8直接 `javac`，原来的 Common ZK控制/授权单元测试、RSA签名 WAL quorum、CommitIndex 磁盘回放/防篡改、Custody证书磁盘验证及新恢复门禁一起运行，**64/64 JUnit PASS**。正向用真实 RSA 2048 生成两份 WAL 和 Custody 签名。负面测试要求单 Custody、重复签名者、候选 WAL SHA错误、成员身份不一致、缺旧主隔离都不能获得恢复许可。

## 只读证据卷核对

通过隔离Docker容器的只读挂载检查了以前 T77 的 `otc-t75-fresh_wal-a` 和 `otc-t75-fresh_wal-b`：

- A 卷存在旧 Epoch5 的 CommitIndex 和 Epoch3/5/7 的本地 Custody。
- B 卷存在旧 Epoch7 的 CommitIndex 和 Epoch3/5/7 的本地 Custody。
- 这证明既有系统的 CommitIndex 文件并非每个Epoch都在A/B双方完整备份。严格主切后必须能从真实 WAL + 已持久化的签名证书恢复权威提交边界，不能要求已死旧主的本地 CommitIndex 文件仍可读取。

**注意：上述证据是只读文件目录检查，不等于成功验签旧卷中的字节内容或证明两份独立 Custody 安装回执已在幸存节点持久化。**

## 尚未达到生产GO

1. 目前 `CertifiedSignedWalEvidenceVerifier.Source` 要求注入可信成员配置、真正的本地 fsync WAL、持久原始 CommitIndex/签名证书和两份 *persisted independent* Custody 安装回执；**隔离V19业务服务尚未接入此统一Source**。RSA JUnit 测试用的签名确实有效，但签名输入来自测试生成的临时密钥与受控证据，而非现有Demo卷的真实密钥/回执。
2. 既有副本可能只保存 quorum 签名的 Commit 证书和自己的 Custody 文件，尚未证明两个独立 Custody *安装回执* 都保存在能够独立接管的幸存节点。下一步应在现有 Cert Custody 安装 RPC 中将已签名原主 Custody 收据绑定给备机一次fsync写入（不增加ZooKeeper热路径；尽量与既有RPC聚合），然后重新验证两份回执可以从磁盘恢复。
3. ZK多数派中断后自动执行安全新Epoch CAS、旧主隔离、发布READY仍未通过；上轮自动CAS入口代码操作被安全检查拦截，没有被偷偷恢复、清除撤权标记或模拟通过。
4. 尚未实际跑新的 256 分区 Netty WAL、Order/Trade 联合故障注入、账务/Projection 权威一致性，也**没有T81新的TPS**。之前真实单P000严格组提交约105.7 WAL/s、异步单条约97.2 WAL/s，距既定目标很远。

## 交付与环境

- 官方Common Commit：`ead6602`
- 11个完整源码/测试文件：`tests/patches/common-signed-wal-custody-recovery-t81-20261024.tar.gz` 及对应SHA256详单。
- 正式24个 `dc-saas-*` 容器不变；没有变更任何旧测试WAL卷数据，仅以只读方式检查T77证据卷；未重新启动隔离的3ZK+2Netty集群，因此不声称本轮真实HA通过。

**状态：通用 RSA 验签/CommitIndex/Custody 已从试点迁回 Common + 64项专项回归PASS；持久双 Custody 回执恢复和自动安全新Epoch仍是NO-GO。**
