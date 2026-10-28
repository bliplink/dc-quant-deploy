# T247/T248｜Common 认证 WAL 尾部修复、Census 启动时序与 P210 双账本阻塞

**2026-10-28 17:33–17:52 CST**，Mac Docker Demo，`saas-crypto`。当前 **NO-GO**：Robot 和 Order/Trade A/B 已停止；不存在真实 Filled、双边 Trade 结算与 A/B 自动切换 PASS 证据。

## T247 真实物理数据核查

- 实际审计 Order/Trade A/B 512 个 WAL 分区：仅 **Order P106、P142 和 Trade P023** 三个存在 A/B 字节不同，且每个较短 WAL 是较长 WAL 的完整前缀。
- 实测原始帧序号、CRC 与 RSA Custody HEAD、双 Custody Receipt、Primary CommitIndex 逐项一致：
  - Order P106：HEAD 33892，A WAL 33893、B WAL 33892；A 最后多 1317 字节。
  - Order P142：HEAD 23646，A WAL 23647、B WAL 23646；A 最后多 1317 字节。
  - Trade P023：HEAD 3364，B WAL 3365、A WAL 3364；B 最后多 4492 字节。
- 三个较短 WAL 的 SHA-256 等于 RSA HEAD 与 receipt ledger 已记录的 signed prefix hash。三个 owner 的 CommitIndex 分别完整为 1..33892、1..23646、1..3364，副本没有权威 CommitIndex。
- 编写 `tests/t247_restore_certified_order_trade_wal.py`：默认只读，`--apply` 必须 Order/Trade 四进程全部离线、ZK 两组 leases 空、256 分区其余 WAL 无差异、签名头及真实提交索引严格符合预期。先 fsync 封存完整原 WAL，再原子替换三个尾部为相同的认证前缀。
- 本轮真实执行 `--apply` 返回 **T247_OFFLINE_RESTORE_PASS cases=3**；全部源 WAL/HEAD/Receipt 证据保存在本地 **`/Users/kong/.opentradingcore/t247-certified-tail-forensics/T247-20261028T094016Z`**，不是自动 HA 验收成功。

## 四节点重启与 T244 部署

- Order/Trade 原 T225/T230 A/B 重新启动，ZooKeeper 两组 leases 均能列出 A+B；初期超过一分钟无 WAL/HEAD/Census 报错，Order A/B 都能恢复订单簿。
- 继而逐节点换 T244 Order B、Trade B，开始出现 `ORDER_COMMON_CERTIFIED_CENSUS_UNAVAILABLE` / `TRADE_COMMON_CERTIFIED_CENSUS_UNAVAILABLE`。Common T143 `NodeClusterControlManager.start()` 初始 grant/lease refresh 异步调度，业务 Bean 在第一次 certified census 安装前读取会 fail-closed。**现象与时序竞争相符，但尚未证明不存在底层续租失败。**
- Order A 在继续启动历史恢复过程中触发另一独立失败：`receipt ledger head != physical custody`。**P210 的数据修改时间约 16:20 CST，早于本轮维护，不是此轮滚动升级新写入的故障。**

## T248 新发现：Order P210 双账本落后

实际两个节点 Order P210 物理文件完全一致：

| 证据 | A | B |
| --- | ---: | ---: |
| 原始 WAL 和 RSA Custody HEAD | Epoch 2, Seq 35427 | Epoch 2, Seq 35427 |
| Receipt Ledger | Epoch 2, Seq **35426** | Epoch 2, Seq **35426** |
| Primary CommitIndex | 1..35427 | 无（Replica 正常） |
| WAL 哈希对 HEAD | MATCH | MATCH |

这是已经发生的 **Custody/CommitIndex 与 Receipt Ledger 落后一笔**。不能像普通未认证 WAL 尾部一样截断掉 35427，也不能凭空伪造历史双节点回执。需要独立有效的真实 custody ack/恢复事务；现有 Common T143 在启动 `DurableWalCustodyReceiptLedger.load()` 时直接拒绝 HEAD 不一致。

在修改或重建之前，P210 的 A/B 原始 WAL、HEAD、Ledger 及最近两个 CommitIndex 已 fsync 封存于本机：
`/Users/kong/.opentradingcore/t248-p210-forensics/P210-20261028T095116Z`（8 对象、93,078,570 字节）。

## T248 代码准备（尚未上线）

- Order/Trade `{Order,Trade}CommonNodeRuntimeWiring` 在**Spring 启动阶段**加入最多 20 秒的真实 Common census 授权等待；每 100ms 重试认证查询。拿到非空认证分区与真实 `localPartitionCount` 才继续，超时抛异常并拒绝启动。不会绕过 RSA/授权，也不在交易 WAL 热路径加入 ZK。
- 两边 Java8 编译 PASS，新镜像构建 PASS：
  - `local/otc-t248-ordersvr:census-await`
  - `local/otc-t248-tradesvr:census-await`
- 代码尚无在正确 P210 基础下的真实启动/交易 PASS；不能把编译成功当成部署验收。
- 新增 `tests/t248_audit_common_physical_certified_integrity.py`：只读审计 512 分区的 WAL、CRC、SHA、Custody/Receipt。这次实际输出 **2 个错误，均属于 P210 的 A/B 双账本 HEAD/Receipt 不一致**。退出码 1 正确阻止 READY。
- 为防止外部资金命令在没有可信集群时继续写入，已经停止 Robot 和所有 Order/Trade A/B；保留 MySQL/ZK 等基础环境和历史证据。

## 下一步阻塞与验收边界

**P210 是下一关唯一已明确的当前持久化完整性阻塞。** 必须在 Common 内完成可信 recovery：若两物理节点仍能对已保存的相同 WAL/签名 CommitIndex 独立提供签名 custody 证明，则恢复 Receipt Ledger；否则封存历史并按照用户允许的开发 Demo **完整 Fresh Genesis** 一次性重建（包含 Common/ZK/Order/Trade/Projection/DB），不可只删 P210 单个账本或自行伪造证书。

确认 512 分区全量读审计 0 错误、Order/Trade A/B 真实恢复/授权后，部署 T248，成对启用真实签名撮合/财务事务，验证新租户自动审批→Robot 报价→Tape IOC Maker 部分成交→Trade 正确保证金/资金/持仓→订单及 Projection 落库，最后双向 SIGKILL 自动互切与一致性。当前 **NO-GO**。