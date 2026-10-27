# T173｜2026-10-27 主 Demo Common 恢复实况（NO-GO）

## 本轮实机已完成

- `dc-saas-zookeeper` 中 `/otc/demo-real-common/order/manifest`、`/otc/demo-real-common/trade/manifest` 已安装且逐项校验：各 256 分区，generation 1、Epoch 1、STRICT_QUORUM、全部 RECOVERING（**没有 READY**）。来源：`tests/fixtures/common-fresh-e1/CommonDemoFreshE1RecoveringManifest.java`，提交 `5bdbebc`。
- 主 Demo 的 OrderSvrA/B、TradeSvrA/B 均以 Common `RECOVERING` 而非业务 `READY` 运行。其四个 ZooKeeper lease 分别持有不同的非零 ephemeralOwner；这只证明不同 ZK session，**不是四个独立物理主机**。业务端仍拒写。
- P090 OrderSvrA 由原本独立装载的 RSA 私钥生成本地 fsync Genesis、签名 receipt 和原始零 ACK birth 记录：`data/common-demo-original-e1/OrderSvr/OrderSvrA/`。B、Trade 两成员及其余 255 个分区的证书未齐备；不能声称双节点 Genesis PASS。B/Trade 后续批量签名与合证操作曾被执行安全检查阻断；没有伪造收据、迁移私钥或跳过校验。
- 本地独立验证 JVM（T149/T164）的 12 个容器已**停止而非删除**，包含旧隔离 ZooKeeper；保留证据卷。主 Demo 的四个 Common 恢复节点和主 ZooKeeper 未停止。
- 新租户 `DNN8Q9` 的 bootstrap 仍为 `NEEDS_RECONCILIATION / FUND`、`DEMO_CASH_OUTCOME_UNKNOWN`，`funding_confirmed=0`、Robot 数量=0。不能从 MySQL cash_log=0 推断 Trade 原始 WAL 未处理入金。
- 为避免新的未知结果造成重复 cashIn，已将 `compose.trial-liquidity-local.yaml` 中 `TRIAL_LIQUIDITY_DEMO_RETRY_ENABLED` 改为 `false`，使用现有镜像单独 recreate AdminSvr 并在运行容器核验生效；bootstrap 自动批准/初始化开关仍为 true。提交 `7567493`。

## 主线尚未完成的机制

1. **完整原始 E1 证明**：256 分区两节点各自真实持久 Genesis、RSA 证书、独立零 ACK WAL 证明，并通过 Common 的双 voter 回放/恢复事务。不得仅凭空目录建立新写入许可。
2. **Common 256 分区首次激活**：当前 `CommonOriginalE1FirstActivationStage` 只接受 `prior.assignments.size()==1`，而主 Demo manifest=256。必须设计验证全部原始成员/分区签名及旧节点撤权的舰队级 Epoch/READY 事务，不能简单去掉 `size==1` 然后宣布 READY。
3. **真实业务 READY**：每个分区完成完整 Snapshot/WAL 和签名提交水位、双节点物理 custody、加载业务状态比对后再授权 Common 写入、向 Gateway 路由。
4. **资金对账和 Robot**：在 Trade 恢复后先对 `DNN8Q9` 的原始 WAL、账本及资金流水按固定 funding request ID 对账，不可重试未知入金。完成后验收 20 bid+20 ask、主动 Tape 成交、余额/持仓/委托/成交/Projection 一致性。
5. **HA 实测**：Order/Trade A/B 真实自动连续互切、恢复追平、无重复成交/双主，MD Image/Diff 与旧发布者隔离。现在不得执行会误导业务可用性的主切宣称。

统一 `saas-crypto`，只做 Mac 本地编译部署；GitHub Actions 不使用。所有运行/测试证据须区分 `RECOVERING` 与真正可交易 `READY`。

## T174 续验：256 分区真正的阻塞与代码修复（2026-10-27）

- Common 原单分区首次阶段仅允许 1 分区清单；主 Demo 的 E1 manifest 各 256 分区，且 CommonRecoveringNodeRuntime 锁定整份 manifest version。逐分区循环 CAS 会撤销其它旧 E1 recovery listener，不能只去掉单分区判断。
- 新增 CommonOriginalE1FleetFirstActivationStage：全部 256 分区真正双 RSA Genesis、零 ACK WAL、双方 REPLAY_COMPLETE 后，整份 Manifest 一次性 E1/RECOVERING -> E2/RECOVERING；CAS 前签名/fsync 旧新 Manifest、512 原始成员证明摘要并二次重查。绝不产生 READY、ACK 或可交易端口。
- CommonOriginalE1SignedMembersSource 的新工厂坚持实际同一 ZK session 和原始成员 RSA；CommonRecoveryOnlyProcess 新开关 stageOriginalFleet 需要此前完成实际业务加载、原始 Genesis 安装和认证 stager 回调。OrderSvr/TradeSvr 仅注入恢复状态及凭据，由 Common 统一控制 CAS。
- 本地候选 Common commit 9d446b6、Order 9f7594e、Trade 196ab78，当前在各自 codex/t157 工作分支；Java 8 编译成功，Common 13 项相关 JUnit PASS；尚未移入服务主 saas-crypto，也未上线到主 Demo。
- 只读检查命令：python3 tests/check-demo-common-readiness.py；结果：docs/evidence/T174_demo_common_original_e1_census_20261027.json。Order 512 原始 voter RSA 票据只有 1 份，Trade 0；全部两个 256 分区都是不可路由 E1，无业务 READY。文件计数仅存在性，非验签或数据恢复证明。
- 此外，Order/Trade 当前 CommonPhysicalProofWiring 仅初始化 EMPTY CommonCertifiedPhysicalEvidenceRegistry，尚未打开真实 WAL/CommitIndex/双 Custody 证明；CommonRecoveredDomainWiring 仍只能校验 zero-ACK E1 Genesis，E2 CAS 后还必须实现可信历史 E1/E2 新服务加载和历史写主撤权交接。没有这两个缺口的修复，不能把 RECOVERING 升为业务 READY。
- 当前实际 Order/Trade A/B 四节点仅为受限恢复进程；DNN8Q9 仍资金结果未知、禁止自动重试；真正交易和 Robot 盘口仍 NO-GO。

## T175 交易 E2E 前置真实检查（2026-10-27 13:xx CST）

- 真正 Order/Trade 业务 Gateway TCP 端口 `33036`/`33037` 当前均 `NO_LISTENER`；Common RECOVERING-only TCP `44122`/`44222` 可连通。容器 `Up` ≠ 交易服务已恢复。
- 主 Demo manifests（Order 和 Trade 各 256 分区）`READY=0`，业务请求不可路由。通过公共 Gateway 无 session 调用旧 `__e2e_readiness__` 只能得到 `AUTHENTICATED_SESSION_REQUIRED`；**不能把该结果当成 Order/Trade 已注册**。
- `validate-saas.sh` 原逻辑仅先检查 Docker running，旧 OrderC 容器故障会报大量历史日志而掩盖当前 Common RECOVERING 的主因；现新增前置门禁，实际运行输出 `dc-saas-ordersvr is Common RECOVERING only; cannot serve customer orders, trades or Robot (not business READY).` 并立即非零退出，不会误宣验收成功。
- 本地 JUnit：Order 匹配安全/幂等/启动门禁 9/9 PASS；Trade 成交去重/资金/启动门禁 13/13 PASS；Common 真实双节点原始 E1/出生证明/恢复门禁与 256 舰队计划 21/21 PASS。此为**离线单元测试**，不能代替真实 Gateway、资金/订单/成交/机器人 E2E。
- 阻塞仍是原始独立 RSA 证据未齐全、Common E1->E2 恢复后业务物理 WAL/Custody 状态与 serving Spring JVM 的可信接线未接通，四个 Demo 仍 RECOVERING。代码候选尚未切换主镜像，禁止用 `READY=true` 配置假装验收成功。

## T176 真实交易前置验证和兼容修复（2026-10-27）

- 在主 Demo 4 个真实 RECOVERING Docker JVM 上进行了只读 256 分区 Order/Trade 初始业务快照序列化探测：Order A/B 各 256 份、每份 213 字节，累计 SHA-256 一致：4353d3cb40f2a019071562435ea8879210504d8c300bfcc56e33d56d1e9c89c1；Trade A/B 各 256 份、每份 303 字节，累计 SHA-256 一致：86a183ffff67c36a4c8edfd1ac5033274c70e0d2d556358c41cff9261f34ec46。只验证 DTO 生成/编码，不能代表已加载真实 WAL 账户状态。
- 新增只读测试程序：tests/fixtures/common-fresh-e1/CommonDemoE1ImageCensus.java（Java 8 编译，通过四 JVM），不写快照文件、不触碰密钥、不会发布 READY。
- 发现 Order/Trade 的 FencedRecoveringBusinessState.inspect 原代码都写死从 /srv/dc/data/t150-original-genesis 读取 Pnnn/sealed/genesis-e1.snapshot（过时隔离测试目录）；主 Demo 实际是独立的新 E1 namespace，改开关会报 ORIGINAL_BUSINESS_IMAGE_MISSING。已在 Common Config 加入必填、绝对路径、非 symlink 的 originalSealedImageDir，并把它与原签名源 originalSignedQuorum 的路径强制对齐。Order/Trade 从该 Common 配置目录加载真实业务空镜像而不是 T150 固定旧地址，且对应 Demo 原始合证工具的 sealed 路径统一到 <data>/common-demo-original-e1/<service>/sealed/Pnnn。该修复仍没有跳过真实 RSA 或独立业务恢复检查。
- 开发分支本地新提交：Common ea91ec5、Order f30df63、Trade 05e8c53。Common 22 项 replay、birth、census、restore 相关 JUnit PASS；Order/Trade 原始业务 Snapshot 单元测试 4/4 和 3/3 PASS。未部署此开发版到主 Demo，不能宣称真实成交。
- 业务交易端口 33036/33037 仍未监听；Common RECOVERING 控制端口 44122/44222 在监听。主 Demo 不具备入金、机器人下单、撮合及成交查询的业务入口，不能运行会修改资金的 E2E。完全真实交易回归需原始 E1 双节点持久签名、256 分区真实恢复、E2 认证 READY 新 JVM 与 Gateway 路由检查通过后才允许执行。

## T178｜主 Demo 四节点统一 Common 镜像已上线，但交易仍 NO-GO（2026-10-27）

- Common 源分支 saas-crypto：67bed56；真实 297 生产 Java 类、137 测试源码全编译；Common 首次 Genesis/恢复相关 22 项 JUnit 通过。
- Order saas-crypto：113af17；Trade saas-crypto：2fac239；删除各自原 cluster 目录 32/38 个 Java 文件，统一 Common 状态机与控制。候选完整 Java 8 clean compile 通过；Order 42 项业务+集群回归，Trade 33 项回归通过。保留 Order 原有成交回调诊断/缺委托时拒绝静默丢失。
- 离线 Docker 镜像：local/otc-t178-ordersvr:saas-common-merged 和 local/otc-t178-tradesvr:saas-common-merged，内含唯一且完全一致的 Common Jar SHA256：87bdcb4d59cd71a19c5682dcac43317d6eded231e0c0bdeb6010b6adb3f24ac3。服务旧 cluster class 目录不存在。
- A/B 四节点在主 Demo 已替换为 T178 并持续启动、重新取得分别独立的 Common ZK ephemeral leases。旧 ZooKeeper 会话退役前新 A 曾因 recovering node lease owned by another ZK session 被正确拒绝；未手动删除 lease，待其自然退役后启动成功。
- **不可误报 READY：**Order/Trade 的 256 分区均为 0 READY；业务端口 33036、33037 关闭；Common 恢复控制端口 44122、44222 在监听，Robot、真实下单、成交及 A/B 业务主切尚未验收成功。实时证据：docs/evidence/T178_real_demo_common_redeployment_20261027.json。
- 最后剩余是机制闭环：每个分区实际双原始 RSA Genesis+零 ACK WAL 证明及 A/B 业务 REPLAY_COMPLETE、批量 E1 交接与 E2 READY 签名物理证据注册、新 serving JVM 正确恢复并授权 Gateway。只有本机真实通过该完整环节，才能运行新租户开户、Robot 20+20 挂价、真实买卖成交、撤单及 Order/Trade 自动连续互切与资金/委托/成交/持仓/Projection 一致性验收。
- 未清理 Main Demo 数据/未知资金请求，也未使用 GitHub Actions。旧业务运行许可不得通过修改 READY 标志或删除 lease 获得。

## T179｜恢复阻塞的直接证据和同会话原始 Birth 修复（2026-10-27）

- 主 Demo T178 四个 Order/Trade A/B 节点仍正常运行，但共 512 个 Order、512 个 Trade 原始本地签名/零 WAL 出生证明文件尚不完整，双签 Genesis 0/256，且两份 Manifest 各 0/256 READY。
- 已检查真实四份 application.properties：每个节点完整的 E1 原始签名源配置均 0/256；inspectFencedBusiness、installFencedFreshGenesis、stageOriginalFleet 未启用。因此光更换镜像或直接开启 REST/Netty 业务监听不会出现可交易 READY。
- 部署仓库 tests/check-demo-common-readiness.py 修正了真正的封存 Genesis 目录 common-demo-original-e1/<Service>/sealed/Pnnn/，与 Common 源实现一致，并统计每份真实应用配置 256 分区签名来源/首次激活开关。对应离线单元测试 6/6 通过，证据 docs/evidence/T179_e1_original_provisioning_and_source_config_20261027.json。
- 发现此前 standalone CommonDemoOriginalE1Birth.java 虽读取活动租约，却自行创建了另一 ZK session，不足以证明签发者拥有原节点会话；修改为签名要求 exact session owner，不能借用其他 JVM 的 ZK Lease。源演示回执的文件存在性不表示同会话认证通过。
- Common 的 saas-crypto 源码新增 CommonOriginalE1LeaseBoundBirth：仅原始 ZK 租约真实 owner 能为全新 E1/256 manifest 中属于自己的分区，使用现有被 pin 的 RSA、不可重复的全新原始磁盘根签署并 fsync 业务 Genesis、零 ACK birth 和签名票据；整个过程不开放 Gateway、不发行 READY、拒绝旧目录/别人的会话及重复初始化。Common 本地 commit 8eda30f，Java 8 源码整体编译；3 项该生产入口正反向测试，相关原始恢复总计 25/25 PASS。
- **当前不能标注完成**：生产首次启动的业务 Snapshot 提供方和 256 分区签发调度尚未接入同一个持有 Lease 的 original Order/Trade JVM；跨节点真实签名证书和持久事务未生成，也没有 E2/E3 真正业务 READY 授权发布。T178 运行镜像仍是之前版本；严禁无认证开关或不可信签名冒充完成。
- 用户期望的新租户自动审批/Robot 挂价/真实成交/Order Trade A/B 自动切换/资金一致性均在上述 Common 真正授权完成前无法执行；DNN8Q9 CASH_OUTCOME_UNKNOWN 不能重复 cashIn。
