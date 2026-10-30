# T337｜T336 P193 Common 未认证尾部复核及跨代目录误读保护（2026-10-30）

## 现场状态（只读验收，仍 NO-GO）

- 当前 Demo Order A/B 运行镜像 `local/otc-t335-ordersvr:partial-cancel`，Trade A/B 运行 `local/otc-t336-tradesvr:signed-leverage-cancel`，Projection T334 运行。Order B 日志持续 `Common physically certified partition writer unavailable: P193`；Robot 没有恢复持续报价。
- 按当前 T330 原始数据目录明确执行：`T328_SIGNED_ORDER_WAL_ROOT=~/.opentradingcore/dc-saas-runtime-clean-20261016/data/t330-fresh/OrderSvr python3 tests/verify-t328-signed-order-ab-wal-readonly.py`。返回码 **2**，**255/256** 分区二进制一致；P193 B 为 22668 条、A 为 22667 条，B 多 1 条 CRC 合法但未认证尾部；无数据截断、业务应用或证书写入。
- 若省略 `T328_SIGNED_ORDER_WAL_ROOT`，脚本现在**明确拒绝并返回码 4**，不再悄悄默认读取 T325。此前误读 T325 会出现 P110/P180/P182 三处历史尾部，不能误算到 T336。本轮 `python3 -m py_compile` 为 0。
- 本地 Common 原有 `CommonHistoricalCertifiedPrefixWithTailTest` 2/2、`CertifiedDirtyTailBoundaryGuardTest` 8/8、`CommonCertifiedE2LargeColdHistoryTest` 3/3，共 **13/13 PASS**，只证明安全边界代码回归，不证明现场自动恢复。
- T330 Trade A/B P022 各有 **8853** 条 WAL，文件 SHA256 均为 `c726837bced82c36d9d9ab0760073e8df93ae7eabb9d202f4481f4e7bf75c3f1`；Trade A 存在 seq8838 CommitIndex 文件。此只读核验没有执行 RSA 证书验签，**不提升资金证明级别**；Trade 原先的已认证去重释放证据仍按 T336 报告保持。

## 本轮追加：真实原始 RSA + Custody 证明与 22,667 条回放

- 正式 Order/Trade A/B 容器均确认加载同一 Common JAR：SHA256 `2a8b6c8f5322b3351aed1db65d23e3fc89b447a08205dbcf784bfc1b2f6b5d44`。本轮未重新构建镜像。
- Common 新增 `CommonT337OriginalP193SignedPrefixTest`：只读取得 T330 原始 P193 A/B WAL、原始 A/B RSA **公钥**（不用私钥），把 WAL、Custody HEAD、双独立持久化回执复制至 JUnit 临时盘，再由现有 `CommonCertifiedE2ReplicaHistory` 和 `DurableWalCustodyReceiptLedger` 进行真正的 RSA、HEAD、签名回执及分窗回放。验证原始 22667 条全部符合认证提交，B 有第 22668 条未认证尾部；原始 A/B WAL 逐字节不变；不发布 ACK/READY。
- `CommonCertifiedE2LargeColdHistoryTest` 新增模拟 P193 规模的 22667 条双签历史与 1 条未认证 `STATE_REMOVE`，验证签名窗口恢复且禁止旧 WAL 被当作可写认证头。
- 四个 Common 测试类本地 Maven 合计 **15/15 PASS，0 failed / 0 error / 0 skipped**（原始 RSA 证据用例实际运行），Common 本地提交 `1af4847`，分支 `codex/t177-common-saas-crypto-integration-20261027`。
- 此证据比单纯 CRC 校验更强，但它仅证明**原始已提交物理记录可认证恢复**。尚未实现 Common 持续运行时的原 Primary 安全撤权、缺证尾部隔离后自动切换/自动重新加入及业务 READY；不得据此将实时服务 NO-GO 改成 GO。

## 唯一修复边界

1. Common 必须从原物理 RSA/CommitIndex/Custody 独立认证 P193 的最后提交边界 **22667**，确认 ZooKeeper Epoch/assignment/原 Primary 隔离、恢复写屏障及 HEAD SHA 一致。
2. 保留 B 的 22668 原始帧及证据；不允许把未认证 `STATE_REMOVE` 当作提交，不允许通过 CRC 或仅靠双方对账自动抹除安全门禁。
3. 必须由 Common 现有统一 WAL/恢复 API 在有合法冻结与授权前提下恢复到 22667，之后自动重新加入与复制追平。不能在 Order/Trade 添私有 HA 或再增加一个恢复子系统。
4. Order 从已认证 Pending_Cancel 状态恢复，Trade 对已认证资金释放仅重用**幂等结果**，只补最后一次经 Common 正式提交的 Order 终态。最后真实跑 Robot 盘口、Tape 成交、MD/Kline、A↔B SIGKILL 和资金/持仓/订单/Projection 一致性。

**未做：** 没有修改现有 WAL/CommitIndex/Custody、没有生成新客户端 ACK/READY、没有重新退款、没有实际 SIGKILL 或完成自动切换。最终验收仍为 **NO-GO**。
