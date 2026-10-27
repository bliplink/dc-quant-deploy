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
