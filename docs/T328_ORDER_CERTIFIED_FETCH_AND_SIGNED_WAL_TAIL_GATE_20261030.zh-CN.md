# T328｜交易优先：正式 Order B 签名冷恢复、Projection 重复路由批次消除、Order A 三尾部保护（2026-10-30）

## 现场与约束

- 用户优先级：**先让 Order/Trade/Projection/Robot/Tape 真实交易跑通**，严格 HA A↔B 注入后置。当前所有服务必须沿用原 ZooKeeper `/MDTService` 注册，Gateway 不改；Common 负责全部分区/复制/授权/提交/恢复，业务只负责序列化字节。
- 正式服务延续 T325/T327 原签名 E2 ZK `/otc/demo-t181-fresh-20261027`、原 RSA Genesis、正式 MySQL、原 Gateway；绝不擦除当前 Common WAL。
- T327 的直接资金修复尝试被执行平台安全检查阻止；本轮**未尝试绕过**，未再写 MySQL 资金，也未重启 Trade B、未开启 Robot、未人为推进/生成签名提交水位。

## Order A/B 256 WAL 的真实只读检查

新增 `tests/verify-t328-signed-order-ab-wal-readonly.py`：只读读取实际 A/B Epoch2 WAL，全分区按原 `CBW1` 头部、连续序号、CRC32（epoch/sequence/payload）核验。256 物理分区：

- **253/256 字节完全一致**；
- P110：A 20068 帧、B 20067 帧，B 为 A 的完整前缀；
- P180：A 20307、B 20306，B 为 A 完整前缀；
- P182：A 29589、B 29588，B 为 A 完整前缀。

A 多出的各一条尾部均 CRC 正确，但对应 A 的最高 CommitIndex 仅到 B 的最后已提交序号，**绝不可将额外记录称为已提交，也不可直接删除或回放**。上述三分区的签名 CommitIndex 文件名检查为 20067 / 20306 / 29588；最终签名证明仍以 Common 自身 RSA+双 Custody 校验为准，脚本只读文件，不伪造任何签名证书。

脚本实测返回 `T328_ORDER_A_RESTART_BLOCKED unsignedTailPartitions=3`，正常非零退出状态为 2；包裹断言验证拒绝门禁 PASS。因此 **本轮没有重启/替换 Order A**，将来须先完成原公共 WAL 严格水位鉴别与安全恢复，不能隐式截断这 3 个物理证据尾部。

## T328 Projection 读取改动

真实 T327 Order B 日志发现 `FetchCommittedOrderProjectionEventsHandler` 在进入 Common 已签读路径之前，先调用 `OrderPartitionRuntime.isPrimary(part)`，而业务层重复读取瞬态 Common routing census 时可能出现 `ORDER_COMMON_CERTIFIED_CENSUS_UNAVAILABLE: Common node routing census replaced while reading`。这不应导致额外一套业务副本判定。

只在 Common 已有 `CertifiedBusinessCommandRegistry` 增加 **只读 advisory** 的 `hasInstalledPrimary(partition)`，只判定本节点是否在已经通过严格启动认证的物理 writer 注册表中存在该分区；**不是当前业务授权**。Order/Trade 的原 Fetch 处理器不再在这个请求路径重复业务层实时分区快照；物理 Common 的 `readCertifiedCommittedWindow` 仍对每个请求独立校验最新 ZK Grant/当前 Epoch/签名 CommitIndex、双独立 Custody、连续原 WAL。缺少本地物理 Primary -> `NOT_PRIMARY`，不回退旧业务日志。

T328 Common 真实双 Netty/RSA/Custody 测试 **6/6 PASS**，Order 全量 **126/126 PASS**，Trade 全量 **203/203 PASS**。新 Common JAR SHA256 `2a8b6c8f5322b3351aed1db65d23e3fc89b447a08205dbcf784bfc1b2f6b5d44`，本地镜像 `local/otc-t328-ordersvr:certified-fetch` / `local/otc-t328-tradesvr:certified-fetch` 同 SHA。

## 正式部署验证

以 `compose.yaml` + `compose.t325-business-restore.yaml` + `compose.t328-cert-read-no-census.yaml` **仅重建 Order B**，没有同时重建其他业务服务。真实非空 E2 签名 WAL 的 Order B 启动日志：`Started OrderSvr in 56.35 seconds`，`COMMON_GATEWAY_DISCOVERY_CERTIFIED service=OrderSvr node=OrderSvrB endpoint=127.0.0.1:33041 exactOwnerSession=true`，零重启，256 分区目录及其中 6 个非空 WAL 均保留，正式 ZK `/MDTService/OrderSvr` A/B 两条注册存在。没有进行 SIGKILL、未开启新 Robot 写入。

最后实际状态：
- Order A = T319 旧镜像，**运行**、0 次重启；A 的三条未认证尾部待安全恢复，**禁止强行重启**。
- Order B = T328 新镜像，**运行**、0 次重启，签名冷恢复/注册 PASS；新的 Fetch 尚无完整 Projection MySQL 应用结果，不能宣布已全部通过。
- Trade A = T319，运行；Trade B = T327，由于测试租户 `T325_E2E` MySQL 丢失原签名 WAL 中 8 条历史测试入金 Posting、冷恢复正确拒绝，安全停止；Trade B 必须资金一致性恢复后再上。
- Robot 因 RF2 strict 缺 Trade B，保持停止；Projection 仍 T252 旧镜像，只看到历史 `...COMMIT_INDEX_NOT_CONNECTED`，完整订单/成交/资金投影未通过。
- Gateway 不变。真实成交、Tape 24h/Kline、资金持仓投影、自动双向主切一概**NO-GO**。

下一门禁明确：在不重置历史原 RSA、未提交 WAL 和金融账本的前提下，恢复 Trade B 丢失的测试 Posting（或合法全新 E2 Demo 重装）；随后验证 Order/Trade 两份签名状态可恢复，Projection 真正获取 Common 双签提交事件，再开启 Robot 和 Tape 验真实成交。不能用源端自称写入或临时命令来代替真实业务 E2E。
