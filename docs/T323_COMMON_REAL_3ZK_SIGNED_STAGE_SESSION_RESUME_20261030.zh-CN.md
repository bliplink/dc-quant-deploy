# T323｜Common 真三 ZooKeeper 严格故障 Stage 与重连恢复测试（2026-10-30）

## 结果

**真实三 ZooKeeper 新隔离命名空间，自动签名 Stage、旧主 A 消失、独立 A 副本重连、B 控制会话重新加入及使用原签名记录恢复均 PASS；缺少两份物理退役/恢复证明时，系统保持 E5 RECOVERING、拒绝 STRICT READY。**

本轮不宣称完整严格 HA：初始 E4 READY 是**隔离控制夹具**，不是新真实业务的双签 Genesis/WAL READY；模拟 A 故障使用真正 ZooKeeper 会话关闭，不是新的业务 SIGKILL。T308 分阶段完成的真实 SIGKILL/严格 ACK 是另一批独立证据，不能混淆。

## 变更和凭据

- Common 源码：~/.opentradingcore/t177-common-saas-crypto-integration-20261027；本轮本地 commit **31c0b51**，只增加 src/test/java/com/app/common/replication/CommonT323RealZkStrictWatchFailClosedTest.java，生产逻辑未变。前置 Common 回调提交为 446d256。
- 测试在 Docker 网络 otc-t84-source-integrated-net 上的独立 Maven JVM 运行，连接 T84 三个真实 ZooKeeper。原 T293 A/B RSA 只读挂载，新测试由原 B RSA 密钥在**全新 exact ZK namespace/version**现场签署 E4→E5 stage；**没有复制旧签名 Stage、覆盖旧 WAL 或生成新身份**。
- B Watch 先确认 A 真正存在时不得提前夺权；A 关闭旧真实 ZK 会话后 B 自动签署并 CAS E5 RECOVERING。
- B 使用同一 ZooKeeper session 冒充 A 的 Replica，Common 正确拒绝；A 使用真正不同的 ZK session 加入时，Common 正确识别新 Replica，但没有新的 oldEpochRetirement + recovery receipt，仍不可 READY。
- B 关闭 ZK 会话并重新连接，使用原 B 公钥只读复核全新原始 signed-stage，Common Watch 能恢复签名的 E5 RECOVERING，**没有重新签 Stage、没有第二次 CAS、没有 READY**。
- 原始 T308 真实严格切换证据的 ZK 保持不动。Common、Order/Trade 正式容器未替换；没有 GitHub Actions。

## 真实结果和持久文件

新测试最终的三 ZK 路径：/dc/cluster/t323-1793329528973/manifest

真实只读核查：NPC1|5；P090|5|T292-B|T292-A|STRICT_QUORUM|RECOVERING（非 READY）。

新 B RSA 签名持久文件：~/.opentradingcore/t323-real-zk-evidence-20261030/t323-1793329528973/P090-epoch-5.signed-stage

SHA256：a16ab0b2e94205ad93c52f18666783b0afa6ddefad62a9eb1c72b1f9718bdf67

真正运行的 JVM 测试标记：
- T323_REAL_3ZK_STRICT_B_RSA_E4_E5_STAGE_A_REJOIN_FAIL_CLOSED_PASS
- T323_REAL_3ZK_B_NEW_SESSION_PUBLIC_ONLY_SIGNED_STAGE_RESUME_PASS

显式 opt-in 三 ZK Docker 测试：**1 test / 0 failure / 0 error / 0 skipped，Maven exit 0**。

原 T308 ZooKeeper 路径 /dc/cluster/t292-20261029181500/manifest 保持 NPC1|13、P090|6|T292-A|T292-B|STRICT_QUORUM|READY。

完整 Common Maven+已有真实 Demo RSA：**152 suites / 651 tests / 645 pass / 6 skipped / 0 failure / 0 error，exit 0**。6 skipped 里包含 T323 仅显式允许时运行的 1 项；它已在真实 ZK 的单独进程中 PASS。

## 剩余真实门禁（NO-GO）

1. STRICT 真实自动 READY 还缺：新 Epoch 的原始 A/B 真正物理关闭和签名退役、两个物理恢复安装 ledger、双方独立恢复 RSA、已签 Snapshot/Image、双真实新节点租约，全部绑定 Common 常驻 Watch 的同一回调；不能通过时间或假的回执跳过。
2. 严格 RF2 2/2 副本宕机时不可能继续出具新严格双物理 ACK。要继续服务，只能复用已有 Common LOCAL_DURABLE_ASYNC 降级和第三签 C 见证，公开 RPO 风险，或等节点恢复再用严格 2/2。
3. T321 的隔离 Order/Trade A/B 四 JVM Spring、256 分区 E2 WAL、TCP、ZK 注册中心已 PASS，但没有接正式 Gateway、Robot/MD，未验真实成交、持仓/资金、自动业务 SIGKILL。
4. 正式 Order A 仍存在原物理 custody 和 ledger 不一致的重启问题；Order B/C、Trade B、Robot 仍 NO-GO。不可跳过认证、清空正式原 WAL 或误称业务恢复。

**当前 T323：真实 ZooKeeper 严格控制面恢复/安全拒绝 PASS；Common 严格完整物理自动 READY 与正式 Order/Trade 交易 E2E 仍 NO-GO。**
