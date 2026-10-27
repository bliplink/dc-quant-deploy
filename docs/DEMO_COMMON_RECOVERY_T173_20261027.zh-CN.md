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
