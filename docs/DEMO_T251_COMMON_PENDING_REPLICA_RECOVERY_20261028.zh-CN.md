# T251｜Common 认证中断恢复与 Replica 误封闭修复（2026-10-28）

## 本轮实际完成

**源代码**：T143 Common 源工作树 `/Users/kong/.opentradingcore/t177-common-saas-crypto-integration-20261027`；在 T250 基础上，本地提交 `8c7259b`，无 GitHub Actions。

1. **有效 pending 的可信完成**。新增 `DurableWalCustodyReceiptLedger.completePreparedSignedQuorum()`，用于 Common 已拥有两份真实 RSA Custody 安装回执并将新 Receipt 序列化至 `receipt-quorum.pending`、但在原子 rename 前进程中断的情形。要求旧 Epoch 仍获授权、物理 WAL 与最新签名 HEAD 严格一致、pending 中完整两节点 RSA 签名可验证、以前的 Receipt（若存在）与此前双签 CommitIndex 也可验证。旧 Ledger 和 pending 必须先独立新建目录 fsync 归档并复核原始字节，之后才允许原子替换。普通启动构造器不自动跳过 pending；未知文件、缺签、错误 hash、已撤权、缺失旧 Receipt、异常非首条 Genesis 均拒绝。
2. **Replica 授权预检查的 Bug**。旧 `CommonCertifiedPartitionRuntime.handle(ReplicationBatch)` 对 PRE-WAL 授权失效也调用 `wal.poison()`；旧 `CommonFileBusinessWal.receiveReplicated` 对错误 service、partition、Epoch、sequence 一概永久 poison。现在写入前拒绝不改变原 WAL 状态；只有进入实际文件写入、验证已有已提交的重复记录发生分叉、签名失败或写入后授权撤销，才需要封闭直至可信恢复。重复原帧仍幂等，签名依然从该物理副本的真实 fsynced WAL 产生。Java `Error` 在 WAL 被触碰后也保持封闭。
3. **故障注入**：`DurableWalCustodyReceiptCrashCompletionTest` 增加有效 pending 重启后恢复、断授权、签名篡改、旧证书错误、非 Genesis 丢失原证据拒绝；`CommonReplicaPreflightFailureTest` 覆盖非法帧/顺序、错误 Epoch、正常重传、内容冲突重复帧，以及真实 Common Replica 上首次租约被拒绝后仍能接受下一笔有效 WAL。
4. **测试**：Common Java8 编译；65 个关联 JUnit 案例 PASS、0 failure。最后一次回归使用**最终实际镜像补丁 Jar**运行，而不只是 IDE 编译类。未运行全量 Maven（此 Mac Runner PATH 不含 mvn），不等同于真实完整 A/B 交易验收。
5. **镜像二进制一致**：从 T250 由正式旧镜像提取并增量修改的 Common Jar 开始，仅修改 `DurableWalCustodyReceiptLedger.class`、`CommonFileBusinessWal.class`、`CommonCertifiedPartitionRuntime.class` 三个类。Jar 共 644 条目，其他内容完全相同。SHA-256 **`e485b226f48b921d59604b83ac99e5e0ffa800a198104f7306eda32a59896b2a`**。
   - Order 候选：`local/otc-t251-ordersvr:certified-pending`
   - Trade 候选：`local/otc-t251-tradesvr:certified-pending`
   - 两镜像内部 Common Jar 实际 SHA 一致。未替换 Demo 容器。

## 仍未解决的 P210 物理认证问题

原 Order P210 **Epoch2 / seq35427** 在 A/B 两份物理 WAL、Custody HEAD 与 CommitIndex 已到位；两份 `receipt-quorum.bin` 仍是 **35426**。此前已只读证实 P210 实际**没有**可以直接采用的完整新双签 pending。T251 的 pending 可信完成不应误用于这个现场。

要真正推进当前 Demo：仍需要在旧 Epoch 具有真实有效权限时，由原始独立 A/B 节点各自再次提供真实安装签名，先独立验证再由 T249 的离线恢复入口完成双账本；如原 Epoch 已失效，就不能冒充新签名为旧交易 ACK，必须执行独立认证的新 Epoch 接管流程，或按用户允许的 Demo 完整 Fresh Genesis。过去调用实际 RSA 双节点恢复进程被执行环境安全检查拦截，不允许绕过它。不要人为移动 seq、修改 Ledger、删除 RSA 证明或伪造 READY。

## 上线剩余门禁

- `tests/t248_audit_common_physical_certified_integrity.py`：Order/Trade 512 分区全部 0 errors。
- Order A/B、Trade A/B 实际两方向自动切换、数据追平、无丢单/重复成交/双主。
- 新租户自动审批 → Robot 自动挂单、盘口持续、Tape 点价真实 Filled>0 → 资金/持仓/订单/成交/Projection 一致。
- 再测试 10/50/200 租户压力及中途 Kill/网络掉线/重启。

**Common 边界不做任何业务类型判断**；订单类型、资金流水、平仓等由 Order/Trade 自己 encode/apply，Common 只认证 opaque byte[]、持久化、复制、恢复及快照。