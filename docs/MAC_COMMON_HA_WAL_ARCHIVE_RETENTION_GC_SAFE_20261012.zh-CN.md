# Mac Demo HA WAL封存、隔离和安全删除机制（2026-10-12）

## 范围和结论

已完成 **Common 可复用的 WAL 归档回收事务和物理文件实现**，
但**没有在在线 Order/Trade 启用定时 WAL 轮转和删除**。
现网严格保留归档：单个归档只有在服务提供足量已签名的
Snapshot、Replica 和 Projection 持久水位，并把对应
Chronicle 句柄全部关闭后，才能成为回收候选。
本轮 Mac 冷部署还不到 48 小时，且所有历史回收证明
都未齐全，直接删除会导致不可接受的主备追平或历史缺口。

既有基础：
- Common `JournalArchiveRotationPolicy` 提供基于真实
  assignment epoch、当前已提交 head、满段大小、
  durable snapshot、Replica ACK、writer barrier 的
  **预判和锁后复核**；
- `DurableJournalArchiveSealLedger` 保存
  `PREPARED → WRITER_SWITCHED → ARCHIVE_SEALED`
  fsync 标记；故障时不假装已经封存成功；
- `JournalArchiveSealCoordinator` 以单分区排它屏障
  完成提交前缀封存、archive重读和落盘验证；
- `SnapshotRetentionFence` 为删除加入至少保留时长、
  全量Snapshot序号、所有同步Replica可恢复快照、
  Projection及其他消费端已持久序号、
  文件句柄释放和回滚历史完整性硬性约束。

## 本次 Common 新增功能

仓库 `bliplink/com.app.common`，验证分支
`codex/common-wal-rotation-policy-20261012`，
提交 `c196fec589d8b76923b985d81c57d26a80937b85`。

1. `JournalArchiveRetirementCoordinator`：
   持久化 `PREPARED → QUARANTINED → REMOVED`。
   开始前先评估外部签名水位，获得 Order/Trade
   提供的分区排他 Lease 后重新读取所有证据。
   不允许旧归档身份变更、错误epoch/throughSeq；
   无证据则返回 HOLD，不写日志、不动 WAL。
   原子隔离后再次在**同一锁**内核验 Snapshot、
   Replica、所有消费端的水位，才允许真正 unlink。
   任意阶段崩溃时保留持久标记，禁止自动跳过
   未完成回收。多个 worker 等锁后需重新读入账本，
   禁止两个进程重复删除同一段。
   默认必须显式 `enabled=true`，否则不执行 I/O。
2. `LocalArchiveQuarantineFileOps`：
   仅操作单层**已封存归档目录**，精确archiveId，
   验证**来源于独立可信seal manifest**的 SHA-256；
   禁止符号链接、未知文件、嵌套目录、跨路径根，
   限制单归档最多4096个文件。
   `archiveRoot → sibling quarantineRoot`
   采用同文件系统原子 rename、fsync 双端父目录；
   检验隔离态 SHA，才逐文件真实删除，fsync
   quarantine 父目录并确认原/隔离目录均消失。
   不支持传入运行中的活跃 WAL 路径。
3. Java8 全量 `mvn -q -o clean test`：
   **248/248 PASS，0 failures、0 errors、0 skipped**。
   新增真实文件原子移动、真正 unlink、重复执行、
   文件篡改/符号链接、未达保留期、Replica/Consumer
   水位落后，writer头过期，以及
   PREPARED/QUARANTINED/删除后崩溃的
   故障注入回归。

**这些类不生成认证证据，也不自行取得 ZooKeeper/
MySQL/Chronicle 的权威角色。Service Adapter 必须实现
对应的责任。不能把它们自动接入在线清理任务。**

## Mac Demo 实机只读 WAL 审计

部署仓库新增：
`tests/audit_saas_wal_archives_readonly.py`，
`tests/test_audit_saas_wal_archives_readonly.py`。
真实检查：

```bash
python3 tests/audit_saas_wal_archives_readonly.py \
  --data-root "$HOME/.opentradingcore/dc-saas-runtime-clean20261012/data" \
  --retention-hours 48 \
  --output "$HOME/.opentradingcore/local-ha-clean-20261012-v1/wal-archive-inventory-20261012.json"
```

归档目录总计 **512**：Order A/B 各128，Order C 256，
Trade A/B **0**；归档目录真实分配空间总计 **64MiB**。
这批Order初始化归档多为 `epoch0-seq0`，
每个目录只含 `metadata.cq4t`。
本次统计老于48小时候选为 **0**，授权物理删除 **0**，
未知或不安全目录 **0**。

活跃 WAL 使用**实际磁盘分配**而不是 Chronicle
预分配的表观文件大小统计：
当时 Order A/B/C 各约747MiB，Trade A/B 各约
1189MiB，合计约4.51GiB；这些都不是允许回收
的历史归档，也不可以直接删除。
审计采用`st_blocks × 512`，解决 `du` 与
`stat size` 估算分歧。
3项Python单元测试通过，含符号链接、未知归档身份、
超出扫描上限、文件稀疏空间与一律不批准删除等场景。

**输出永远包括：**
`deletionAuthorized=0`、
`retireAllowed=false`、
`DISABLED_NO_SIGNED_SNAPSHOT_REPLICA_PROJECTION_ACK_PROOFS`。
保留天数只是筛选，不是放行删除证据。

## 下一步真正上线所需的服务接口和门禁

Order和Trade分别实现：
1. 在业务分区锁+generation RW lock 下，取得当前
   ZK物理Primary epoch、持久commit marker、
   准确的状态机 `byte[]` Snapshot和完整日记线性前缀；
2. 新 writer 的fsync/断电恢复、旧文件句柄释放、
   全旧段归档可重读并覆盖Projection历史查询，
   才由 SealCoordinator完成封存；不能把 epoch
   回退或未提交tail当作可删的业务前缀。
3. **需要所有 Replica 重启后可恢复的持久Snapshot，
   而不是只复制了最后一个 WAL commit marker**；
   需先修复Trade在线 Replica Snapshot温缓存。
4. Projection的订单、成交和资金/持仓等每个消费组，
   必须具有真实持久水位并能证实范围内消费成功；
   不能只看单个高水位或租户RUNNING。
5. RetentionCoordinator可定期尝试，但每段
   必须检查和锁后复核所有外部fence。
   不满足继续保留；满足才真实隔离和删除。
   每次删除都需要审计事件、恢复可追踪的ledger。

当前**没有实际在线WAL删除、不启用MD自动主切**；
Trade两节点全同步Replica不可盲重启。
Gateway仅透传，不修改。
