# T246｜Order/Trade 512 分区 ZK 协议审计与 Common 恢复阻塞

**时间**：2026-10-28 17:21–17:25 CST；仓库 `saas-crypto`。**Demo NO-GO**。本文件记录实时只读证据，不代表已修复数据或完成真实交易。

## 实际现场

- Order A `local/otc-t225-ordersvr:certified-common-window` 进程仍运行，但持续 `Common physically certified partition writer unavailable: Pxxx`，不能作为成功的认证写入者。
- Order B 原 T225 镜像容器已退出（Exit 1），其最近启动栈显示 `ORDER_COMMON_CERTIFIED_CENSUS_UNAVAILABLE`。
- Trade A 原 T230 镜像运行；Trade B 原 T230 镜像反复重启，`CommonFileBusinessWal.requireHistoricalSignedPrefix` 路径报 `historical read-only WAL does not match RSA-certified HEAD`。
- APSSvr T242 和 Robot T243 保持运行；T243 的真实 aggTrade/Tape 指令已到达，但 **Filled/Trade 结算仍无通过证据**。
- 物理认证未禁用，RSA 未改动；未清理历史 WAL、Custody 或 ZooKeeper。

## 认证 ZooKeeper 实时枚举

通过现有 `dc-saas-zookeeper` 的 SASL 认证只读 `get`，读取每个服务 `P000…P255`，得到：

| 指标 | Order | Trade |
| --- | ---: | ---: |
| 返回分区/唯一分区 | 256/256 | 256/256 |
| state=READY | 256 | 256 |
| epoch=2 | 256 | 256 |
| primary=A / primary=B | 128/128 | 128/128 |
| protocolVersion=1 | 256 | 256 |

**结论边界**：所有分区标记 READY 并不能证明节点具有可验证的 RSA/Custody/WAL 历史。故不能用 `get` 返回 READY 推导物理成功。Common 的业务认证初始化仍失败。

## 现有迁移器只读预演

`tests/trade_cluster_transition_host.py` 的 `validate_current` 要求 `protocolVersion >= 3`；`tests/trade_cluster_assignments.py` 的初始结构也是 v3，和当前 ZK v1 有差异。尚未证明此差异就是当前 Common T143 的拒绝原因，特别是 Trade B 已出现独立的历史 WAL/HEAD 不匹配。

运行现有迁移程序（**无 --apply**）：

```text
python3 tests/migrate_trade_cluster_assignments_host.py \
  --plan artifacts/t246-trade-v3-dryrun-plan.json \
  --zk-client-jvmflags='-Djava.security.auth.login.config=/conf/jaas.ini' \
  --partitions 256

plan=artifacts/t246-trade-v3-dryrun-plan.json partitions=256 changes=256 primaryA=128 primaryB=128 replicaA=128 replicaB=128
dry_run=true; topology and epoch are unchanged by the planned migration
```

对计划的 256 条变更做字段统计：每条变更 `protocolVersion`（1→3）并补齐 `learners`、`placementGroup`、`nodePool`，**没有更改** partitionId、epoch、primary、state 或 assignmentVersion。计划文件位于本地未跟踪 `artifacts/`；不包含私钥，但请勿在不审阅的情况下执行 CAS。

试图执行相关 Python 单元测试时，开发执行器返回安全检查拦截；**未通过测试，不以静态检查替代实测**。

## 恢复工作顺序

1. **Common 认证历史第一优先**：先审计 Order/Trade B 的原始 WAL 区间、已认证 HEAD、双 Custody 与可用恢复源的证明；证书/记录不一致时继续拒绝 READY。若发现已认证副本可恢复，应沿 Common 的受信恢复事务完成，不得就地改 WAL 或签名文件。
2. 分开确认当前 Common T143 对 `protocolVersion=1` 的处理语义，再决定是否使用现有 v3 元数据迁移器；**禁止以 ZK 全 READY 或迁移计划本身宣布成功**。
3. 如果无法完成可信恢复，用户允许在 Demo 完整重建。必须停稳所有 SaaS 服务、封存可用证据、检查 Compose/RSA/密钥挂载和 ZK + WAL + Custody + MySQL + Projection 的统一 Fresh Genesis；不能只删一个 B 的 WAL 或只重建数据库。目前 `tests/reset-saas-test-data.py` 限定 Linux runtime root；不直接用于当前 Mac 目录。
4. 恢复真实 Common 物理 READY 和可重启 A/B 后，再逐节点放入已构建的 T244 Order/Trade 镜像，开启配套签名业务开关，验证 Robot 持续报价→Tape IOC Maker 部分成交→双服务认证 WAL/回执→投影财务数据，必须有真实 Filled>0。
5. 交易成立后才执行 Order/Trade A/B 双向自动 SIGKILL 与 256 分区、余额、持仓、委托、成交流水一致性检查。当前全部 **NO-GO**。

架构保持：Common 只管 opaque byte[] 的 WAL/复制/授权/快照/恢复，不加入订单类型或资金规则。
## T246 增补：当前 Common T143 JAR 字节码确认（只读）

直接从已部署依赖 `com.app.common-3.0.22-t143-durable-signed-crossjvm-handoff-20261026-SNAPSHOT.jar` 用 `javap -c -p` 检查，而非假设新旧协议校验器就是启动失败原因：

- `CommonCertifiedPartitionAssignments.all()` 实际调用 `NodeClusterControlManager.requireCertifiedPartitionCensus()`，后者转交 `NodePartitionGrantTable.requireCertifiedCensus()`；只要当前批次尚未建立或被撤权，就抛 `Common authenticated node routing census not READY`，还要校验批次未过期及 hotpath fence。**这些代码路径没有直接校验 `protocolVersion >= 3`**。因此 ZK v1 与旧迁移校验器不兼容虽属待核对事项，**尚不能认定是当前 Census 异常的根因**。
- `NodeClusterControlManager.start()` 以初始延迟 0 的 `scheduleWithFixedDelay` 异步执行首次 `refresh`，并不等待批次安装完成才返回；`refresh()` 捕获续租或安装异常后默认只增加失败计数，只有 JVM 设置 `-Dcommon.node.control.debug=true` 才输出堆栈。当前业务 Bean 初始化可能在首次授权刷新前抢先读取 Census，但持续失败还需要诊断其真实续租异常。
- `CommonFileBusinessWal.requireHistoricalSignedPrefix(epoch,seq,hash)` 对 read-only 历史 WAL 要求节点未关闭/未 poisoned、Epoch 完全一致、被认证 seq>0 且与本地 `forcedSequence` 相等、签名 HEAD 哈希与本地 `forcedHash` 相等。任一失败都会统一报 `historical read-only WAL does not match RSA-certified HEAD`。**仅有当前异常文案不能推断到底是 Epoch、序号还是哈希不一致**，必须取得具体可审计比较结果，不能直接截断/删除日志。

尝试添加仅作用于 Trade B 的 Common 续租 debug Compose overlay 时，执行器安全检查拦截了该写入，**没有部署或修改 B JVM 参数**。不要将此项记为完成。
