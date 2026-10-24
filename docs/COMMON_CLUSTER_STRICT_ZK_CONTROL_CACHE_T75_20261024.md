# T75｜Common RF2 严格 ACK：ZooKeeper 退出逐笔热路径（2026-10-24）

## 本轮结论

**隔离单分区 P000 试点中，严格模式主节点写入、备份节点收据签名和双方 Custody 的 READY 热路径不再同步请求 ZooKeeper；ZooKeeper 仍由控制线程定期访问，用于授权、Epoch、撤权与故障切换。** 首轮批量 TPS 改善，A/B 常规 SIGKILL 双向严格恢复通过；同时暴露了一个**ZK 多数派中断之后同一 Epoch 旧租约不可恢复、下一次主切也不能自动晋升**的独立可用性问题。性能验证 PASS 不等于 HA 全功能 GO。

### 实际代码变化

- 新增 `DemoV19Rf2StrictAssignmentCache`。仅隔离试点且 `DEMO_V19_STRICT_ZK_OFF_HOTPATH=1` 才启用；单节点 P000 后台控制线程每约 **35ms** 读取 ZK 严格 assignment，最大读取年龄 **150ms**，从读取开始计时，不允许以响应完成时间重新延长。监听 assignment 改动、删除和 ZK 会话事件，立即使快照失效；使用 invalidation generation 防止“后台读取在监听撤权后才完成”覆盖撤权结果。断开连接、过期、ZK 版本/raw 内容变化时禁止严格签名和 ACK。该 150ms 控制快照还受独立 `DemoHotpathLeaseCache` 2,200ms 租约和 2,500ms 旧主退休屏障约束。
- `DemoV19Rf2StrictAckRuntime` 从上述有界缓存读取版本化 Epoch/Primary/配置，并执行本地有效 grant 核查，不在每笔 WAL 的数据请求线程重复向 ZK readData。此前 T74 缓存的 RSA voter membership、真实两副本 WAL fsync、双签名、Common CommitIndex、双 Custody 持久化及最终 ACK Gate 保持启用。
- `DemoV19Rf2DynamicReceiptService` 用相同控制快照处理**独立备份 JVM 的 WAL Receipt 和 Custody**，每次仍校验本机所属物理成员和本地租约；不能仅凭调用方的标记、旧签名或已过期快照完成认证。`RECOVERING / Genesis PREPARE` 期间保留同步 ZK 授权检查，只有转为合法严格 READY 后才走缓存，以免内部恢复过程被旧缓存授权。
- `DemoV19ClusterHarness` 使严格写入运行时、原节点 Netty signer 和独立 Custody 共享同一后台快照；保留原路径作为默认回退。本轮不修改生产 Common Maven JAR 的公共 API，也没有部署正式 Order/Trade。
- 新增 Java8 `DemoV19Rf2StrictAssignmentCacheTest` 验证从 ZK RPC 开始计时的 TTL、时钟倒退、raw 与 ZK version 变更必须拒绝。加上现有恢复回归共 **27/27 JUnit PASS**。

### 同口径性能对照

单台 Mac 的 8 CPU Docker 虚拟机内，3 个真实 ZK JVM / 2 个独立 Netty + WAL JVM / 单分区 P000，同一 Netty 32条 WAL GROUP 请求和严格认证规则。

| 测试 | 客户端成功 | 严格 WAL吞吐 | 整批 P95 |
|---|---:|---:|---:|
| T74 原严格 ZK 热路径（12组×32条，并发4） | 384/384 | 71.998 条/秒 | 2288.8 ms |
| **T75 有界 ZK 控制缓存（12组×32条，并发4）** | **384/384** | **138.703 条/秒** | **1116.6 ms** |
| T75 逐条Netty ACK（30笔，并发4） | 30/30 | 3.631 条/秒 | 2257.0 ms/笔 |
| T75 已完成双向主切后（50组×32条，并发8） | 1600/1600 | 91.928 条/秒 | 5049.9 ms/组 |

T74/T75 的384 WAL口径相同，但两轮在共享Mac上先后执行，JIT、磁盘队列和容器负载不同；**观察到约 1.93 倍吞吐和 P95 约减半，不代表经独立重复随机实验确认的因果提升**。50组/并发8反而表现出更大的排队尾延迟。每批请求只收到一个 ACK，32条 WAL 的“批吞吐”不等于32次独立逐笔 RPC；目前未达到5–10ms ACK或单分区1–2k消息/秒目标。

### 真实故障验证和已知缺口

1. **ZK 多数派故障后拒绝旧授权：** 在保留 T73 原 Epoch7 卷上停止 zk2、zk3，等待8秒，Primary B 的 Netty APPEND 真实返回 **503** `missing, revoked or stale quorum grant`。实际测试运行成功（最初执行脚本由于 macOS 无 `timeout` 命令未执行写入，已纠正并重测）。ZK恢复后，旧租约一旦 `revokeAll`，同一 Epoch 不允许自动续权；控制器没有经证书授权自动创建新 Epoch；随后即使 SIGKILL Primary B，Replica A 也不能完成晋升，客户端继续拒绝。**该复合故障是 NO-GO，可用性恢复缺口必须修复，禁止绕过撤权机制强行解锁。**
2. **独立新卷常规 A/B 主切：** 使用 `otc-t75-fresh`、独立 ZK/WAL/网络数据，启用本轮严格快照。初始 Epoch1 A写入seq1；SIGKILL A，B自动Epoch2（客户本地 ACK 在 STRICT 策略下不成功），A恢复后真实两物理签名+双 Custody，自动发布 Epoch3 READY，新严格 ACK seq2，A/B SHA完全一致；接着 SIGKILL B，A自动Epoch4，B恢复后Epoch5新双签名/双Custody严格 READY，确认 seq3；不存在通过手写ZK操作或测试脚本直接发布READY。
3. **高负载后 JVM 重启：** Epoch5 A作为Primary，真实50组×32条/并发8后全部1600条严格 ACK，最终 seq1603；停止并重启两个数据 JVM、不清空 ZK/WAL 后，能重放原有效证书并新增一条严格ACK到seq1604，A/B均 `lastEpoch=5`、`distinctRequests=1604`；WAL SHA=`7e4cad420de4eaddd63273517878cd1c6088142fd7f2b5e04bc270828d5a2462`，State SHA=`f49e23f8c83b7785ce91d36a17eac0aacaa99d9ab529f62396d27d49837f8d17`，完全一致。
4. **正式服务保持不动**：停止 `otc-t71-strict` 和 `otc-t75-fresh` 两套隔离容器，保留合计16个 ZK / WAL证据卷。 `dc-saas-*` 24个容器依旧运行。未用 GitHub Actions、未推送、未将隔离 Pilot 当作已合并至 Common 中央仓库或 Order/Trade 上线。

### 下一阶段不可跳过的门槛

1. **修复复合故障后的恢复授权**：从 ZK 控制 quorum 丢失而旧 grant 永久撤权后，必须由可信物理 CommitIndex / 两份 Custody 提供已确认水位，并经新 Epoch CAS + 旧主隔离创建合法恢复事务；不能在原 Epoch 简单清除 revoked 标记。拿到严格 READY 后，再复测ZK多数派故障→恢复→SIGKILL任意数据主机→A/B重新2/2。
2. **降低证书与 Custody 固定成本**：维持完整 RSA 和双 fsync 条件下优化每批的 TCP 交互、序列/水位摘要和高并发排队，评估合法批量提交与累计证明缓存。当前50组32条/并发8 P95仍约5秒。
3. **扩展控制面**：本轮后台35ms *每分区*轮询只适合P000隔离试点，推广256分区必须改为节点级批处理/Watch聚合，避免ZK查询量随分区数量线性暴涨。必须跨独立机器验证撤权通知延时上界与物理网络分区的不可双主安全证明。
4. 完成真实 Common发行版本、Order/Trade生产状态机接入和10/50/200租户及资金/持仓/委托/成交/Projection权威对账之前，整个平台 HA 仍**NO-GO**。

完整源码归档：`tests/patches/common-rf2-strict-zk-control-cache-t75-20261024.tar.gz`；逐文件 SHA256：同目录 `.sha256`。采用独立环境 Compose `compose.t75-strict-local-control.yaml`、`compose.t75-fresh-cache.yaml`。
