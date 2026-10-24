# T70 — 单参数 ACK 策略与严格/异步同口径压测（2026-10-24）

## 范围和状态
本次在 Mac M4（主机10个CPU核心、Docker Linux VM 8 vCPU）以独立 Compose 新卷分别启动3个ZooKeeper、两个Common A/B JVM、分离 WAL 的 P000 单分区；正式 dc-saas-* 的24个容器保持运行，没有部署 Order/Trade、没有使用 GitHub Actions。选用真实 Netty V19_APPEND **每笔只含一个 delta=1 WAL 命令**。只在同一台 Mac，非独立故障域。

## 新的唯一配置参数
```bash
# 新集群部署前，在 Docker Compose 环境选择其中一个：
DEMO_V19_ACK_POLICY=STRICT_QUORUM
# 或
DEMO_V19_ACK_POLICY=LOCAL_DURABLE_ASYNC
```
Compose 文件：`compose.t70-ack-policy.yaml` 搭配 `compose.v19-rf2-strict-cutover.yaml`；变量在 `otc-ha-bootstrap`、`otc-ha-demo-a`、`otc-ha-demo-b` 一致注入，仍需 ZK grant、WAL 和写入 fencing。

- **严格 STRICT_QUORUM**：在已认证 Epoch3 的每笔写入均需真实主备 WAL fsync、两张RSA收据、Common CommitIndex 与双方Custody；客户端字段 `durabilityMode=QUORUM_DURABLE`、`quorumDurable=true`、`possibleDataLossIfPrimaryPermanentlyLost=false`。测试代码在本次结尾加了fail-closed：如果在严格策略下进入solo grant也不得偷偷返回降级成功 ACK。
- **本地异步 LOCAL_DURABLE_ASYNC**：仅主节点本地强制 WAL 落盘才成功 ACK，后台单向复制；`durabilityMode=LOCAL_DURABLE_ASYNC`、`quorumDurable=false`、`possibleDataLossIfPrimaryPermanentlyLost=true`。选择该策略意味着接受主节点永久故障导致部分已确认记录丢失的RPO风险。
- 读取当前部署的策略固定值于 ZooKeeper `/dc/cluster/commonhademo/v19-fence-test/harness/ack-policy`，未指定参数时保留此前 Legacy 试点兼容；传入其它值拒绝。对于**已经初始化的 ZK 数据卷**，直接更改参数后运行 bootstrap 或节点会抛 `ACK_POLICY_CHANGE_REQUIRES_AUTHORIZED_EPOCH_CUTOVER`；从严格改为本地、从本地改为严格这两个方向都已实测拒绝。**这只实现了新集群部署/进程启动选择，并未实现同一套正在交易的老集群无中断切换**；已有数据上变更需未来经认证的旧主撤权、Epoch CAS、真实 WAL 水位验证和审计。
- 旧环境变量 `DEMO_ASYNC_REPLICATION=1` 仍只是后台复制传输选项，不是客户端ACK选择器；这一轮不再需要人为组合多项试点开关去定义策略。

## 相同粒度的严格与异步 ACK 对照
使用同一 Java 8 `DemoV19Rf2StressDriver`、同一 Netty TCP APPEND 方法、P000、delta=1、`requestId` 幂等、12秒超时、Docker VM 8核、相同物理Mac。严格测试在真实 A主故障→B自动接管→A恢复→Epoch3 双Custody严格READY 后开始；异步测试从独立新卷Epoch1开始。不同独立卷是为了不绕过旧 Epoch 下的模式封存；并不能消除JIT预热和IO竞争差异。

| 客户端写入数 | 并发 | ACK策略 | 及时ACK | WAL写入TPS | 单笔P50 | 单笔P95 | 单笔P99 |
|---:|---:|---|---:|---:|---:|---:|---:|
| 100 | 4 | STRICT_QUORUM | 100/100 | 3.782 | 1007.164 ms | 1401.749 ms | 1666.434 ms |
| 100 | 4 | LOCAL_DURABLE_ASYNC | 100/100 | 84.292 | 42.423 ms | 70.089 ms | 84.002 ms |
| 200 | 8 | STRICT_QUORUM | 200/200 | 4.853 | 1401.394 ms | 2822.519 ms | 3055.508 ms |
| 200 | 8 | LOCAL_DURABLE_ASYNC | 200/200 | 100.879 | 75.396 ms | 121.455 ms | 143.062 ms |

同口径下本地异步100笔场景吞吐约22.3倍严格模式，200笔场景约20.8倍；它们牺牲了远端复制完成之前的RPO保证，**不能以此声明更优的数据安全性**。相比T68按32条批量认证的86.94 WAL条/秒，本次逐单严格3.78–4.85 TPS单位虽均按WAL条计，但确认频次与请求粒度不同，不能混淆。

## 独立数据一致性与安全拒绝
- 严格两组测试完成后，两个独立JVM均到Epoch3 seq303、303个不同请求，WAL SHA=`b5feb705e74e56678abc95bd2baa903847d4aac9abd6201b361eee339af282ab`、State SHA=`e6201b08af4a7888c9cc099159bfdc8d0d1662f23e97969ee220b5a44ed65272`，完全一致。随后新代码重启B后仍能返回真实Epoch3 QUORUM_DURABLE、seq304。
- 异步两组完成后A/B均到Epoch1 seq301、301个不同请求，WAL SHA=`3c54e3e2f9af8e6bcdf57a26d77b67c01ae57e0e750885f8efd3baa30218a193`、State SHA=`c38397c5a2815a8555d0ed1be217bc8a33a117a78de48706b774f764168b3b80`，一致。异步最终一致并不等于写入时2/2确认。
- 正反模式更改都在保留原 ZK 数据卷时拒绝并以非零退出。严格模式的A副本被SIGKILL后对B提交的写入失败，**没有返回伪造的本地成功 ACK**。这符合严格策略的数据保证，但仍意味着备用故障时交易无法继续确认；要可用必须通过授权模式迁移显式改为LOCAL_DURABLE_ASYNC，不能自动暗改。

## 未完成内容与下一关
此选择器是 `DemoV19AckPolicy` 的 Common 隔离试点适配，尚未进入生产 Common Maven 正式接口、Order/Trade或真实租户后台配置。线上已有数据的ACK策略在线迁移机制未完成，不能直接切换。后续为通用Common实现认证Epoch策略状态机（ZK CAS、旧主撤权、已确认水位和潜在RPO边界）、订单/交易业务ACK策略参数注入、带真实业务状态的双向迁移、200虚拟客户端严格单笔/批量压力及真实16vCPU服务器对照。`STRICT_QUORUM` 默认建议为安全优先路径；明确接受风险的Demo场景可以显式选择异步本地确认。

## 工件
- 完整源码和Compose：`tests/patches/common-rf2-ack-policy-t70-20261024.tar.gz`
- 每文件SHA256：`tests/patches/common-rf2-ack-policy-t70-20261024.sha256`
