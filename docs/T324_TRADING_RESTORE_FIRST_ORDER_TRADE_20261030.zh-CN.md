# T324｜优先恢复 Demo Order/Trade 交易，严格 HA 暂后（2026-10-30）

**用户 2026-10-30 最新执行顺序：先替换 Order/Trade、恢复真实交易与 Robot 报价，然后继续严格 A/B 自动 HA。** 该顺序临时覆盖此前 P0 严格 HA 完成后才启动业务的工程排期，但没有降低 Common 真实 WAL、签名/READY、已确认提交、旧主隔离、单例状态机和交易结果正确性门禁。当前正式 Demo 业务恢复 **尚未完成**。

## 本轮已经执行的只读部署核对

- 新增并实际运行 `python3 tests/t324_restore_preflight.py`（仅本地解析现有配置，不接 Docker、不改正式 MySQL、WAL、RSA 或 ZooKeeper）。该脚本正确输出 `T324_NO_GO` 和候选镜像/正式接线不兼容的具体原因。
- 正式 `.env.prod` 当前指向原有 `local/otc-t113-ordersvr:survivor-custody-2f4b98e`、`local/otc-t113-tradesvr:survivor-custody-2f87223`，Order A/B/C 和 Trade A/B 的 Compose profile 已开启，尚未切至新 T319 镜像。
- T321 实际启动成功的四个业务容器仍是 `local/otc-t319-ordersvr:virgin-e2-replica` / `local/otc-t319-tradesvr:virgin-e2-replica`。对应 `application.v4.properties` **`gatewayDiscovery.enabled=false`**，Common 控制连接 T84 三 ZooKeeper，旧 T318 E2 签名 manifest 与 T319 独立 v4 WAL 根；独立测试 MySQL 与正式 MySQL 也不同。正式 Compose 是 host 网络，而 T321 只在独立桥接网络验收。**直接改镜像标签或改容器名字不构成交易恢复。**
- 正式旧 Order A 上轮观察持续因 `receipt ledger head != physical custody` 重启；不能在不知道证明来源与新旧数据库水位关系的情况下覆盖原认证 WAL、重用旧 READY 或忽略完整性门禁。
- 本次通过的只是候选启动/连通证据，不代表已对正式 Gateway 真实注册、租户自动审批、Robot/Tape 报价、入金、下单、撮合及结算。
- 本轮 Mac 执行通道对 Docker 读/写指令均返回平台安全检查拦截；因此 **未实际停止、替换或启动正式 Order/Trade**，无真实交易 PASS 可宣称。不是 Docker 自身错误，不应包装成已执行。

## 继续执行的优先步骤（不再加做严格 HA 新方案）

1. 在不改变任何业务专用集群实现的前提下，将候选 Order/Trade 用一致的 Common JAR 和原始 RSA 身份构建为可用的**正式 Gateway 注册**版本，校验网络、DB、Common ZooKeeper 命名空间、物理 data root 和 256 分区分配。不能把 T319 signed E2 票据直接放进不同 ZK 路径。
2. 针对可丢弃 Demo 数据走**新的已签 Common Genesis/E2 READY**并整套换镜像，保留旧正式签名数据及 T293/T308/T318/T321 原始证据，不破坏 MySQL/ZK 的非目标业务；启动 Gateway→Order/Trade A/B、必要的 MD/APS/Robot 依赖。
3. 以真实 HTTP/Gateway/SDK 用例验证新租户申请→自动审批→Robot 自动挂价/Tape 点价→实际订单成交→资金、持仓、委托、成交和 MySQL 投影；错误即继续修复/重部署新 Demo 数据，真实证据通过后才宣布交易恢复。
4. 交易恢复后再回到 Common 严格 `QUORUM_DURABLE` A→B→A 无人值守真实 SIGKILL 与一致性测试。当前 **严格 HA 仍 NO-GO**，不阻止业务恢复阶段动手。

**本轮结论：已查明 T321→正式 Demo 的具体部署差异，预检查代码可运行；Docker 执行受阻，正式替换与交易验证尚未执行。**
