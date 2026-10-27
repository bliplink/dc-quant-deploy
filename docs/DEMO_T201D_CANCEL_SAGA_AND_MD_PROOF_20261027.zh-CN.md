# T200–T201d｜Order/Trade Common 认证撤单与 MD 恢复进度

日期：2026-10-27 23:26（Mac Mini Demo），统一分支 saas-crypto；未调用 GitHub Actions。**完整验收状态：NO-GO。**

## 真正已完成

### T200｜Order 已恢复存量 MD Image 发布
- 根因：Order 从签名 WAL 冷恢复了 Maker 后，未保证重新发布市场 Image；旧发布仅在订阅/新的订单变更时发生。旧 ORDER_MD_PERF_STATS 的 publishedOrderBook / stateBooks 均为 0。
- 修复：Order PublishMarketDept 单节点定时器，从真实 OrderManager 的恢复后内存簿生成快照，经 Common 真实 ZooKeeper PartitionRuntime 确认 Primary；异步发布线程在发出消息前再次核对 Primary。Replica 不发布；不复制新 WAL，不使用新 HTTP 服务。
- 本地新镜像 Order A/B 全量 Java8 编译、离线 Docker 构建，通过真实冷重启。
- 真实监测：OrderSvrB 为 P089 当前 Primary，publishedOrderBook=1、stateBooks=1，每次约 862 B。OrderSvrA 为 Replica，publishedOrderBook=0、stateBooks=0。Order A/B 都恢复 activeOrders=664。
- 注意：此证据只证明 Order 向 Gateway 发布完整簿；MD A/B 实际接收/安装、匿名 Web 盘口与 Snapshot/Diff 连续性还未取得可核验的最终数据，不能据此宣称 MD E2E PASS。

### T201 / T201b / T201c / T201d｜认证撤单第一版
- 新 TradeCertifiedCancelAdmission 只接受 OPEN、无成交、原价原量的严格 Trade_Cancel/Cancelled。按租户/交易员/产品/订单 ID 核验真实 Trade 冻结订单，不信任客户端的数量/价格，计算账户冻结保证金/手续费与仓位冻结的 after-state；在 Common 物理 RF2 双签 WAL、Custody、CommitIndex 完整提交后应用四域：ACCOUNT_BALANCE UPSERT、POSITION UPSERT、OPEN_ORDER REMOVE、DEDUPE_RESULT UPSERT。
- 新 OrderCertifiedCancelSaga 仅在 Gateway SessionOrderAuthority 已授权的租户 batch cancel 范围使用。金融 ACK 为明确成功、且 Common 真实主节点授权仍有效时才提交 Order 状态。
- T201 第一版真实限量 Robot 测试曾遭到 TRADE_CANCEL_ORIGINAL_RESERVATION_NOT_FOUND 拒绝：签名 WAL 和 Order Maker **没有被删除**，不能当作成功。
- 该失败根因定位到 Trade OrderManager.init() 在 Common E2 冷恢复后调用全局未授权 queryOpenOrder，触发 1003 且清空真实签名恢复的 Trade 内存 OPEN_ORDER。T201b 修复为 Common 模式严禁旧的跨租户 reload/clear，保留 Common 签名状态；Trade A/B 重部署、Gateway 注册 PASS，旧查询错误在新启动日志中未再出现。
- T201c 根据中间崩溃安全性将跨服务顺序改为 **Order 签名 Pending_Cancel 并撤出 Maker → Trade 签名释放冻结资金 → Order 签名终态 REMOVE**，拒绝 Trade 时保留不可撮合的 Pending_Cancel。每节点一个 30s 低频补偿器，扫描至多 16 个 Pending_Cancel，按原订单幂等完成；不制造客户端成功、不可自动恢复 Maker。
- T201d 增加固定 4096 条订单锁条纹，保证一个订单的上述 3 个阶段不会在多线程并发交错；未使用 Java intern，防止随订单 ID 数量无限增长。
- Trade 3 项资金 after-state 计划单测通过（正常、冻结数量不足、篡改价格）；Order 2 项阶段序单测通过（Trade 拒绝不得删掉已认证 Pending、Trade 成功才能签名终态）。
- 订单、交易全部生产 Java 8 编译通过。四个 T201d/T201b 真实容器已完成带非空 WAL 冷重启和 Common/Gateway 注册。
- 新版本真实业务复测遭执行环境安全检查拦截；**T201b/T201d 实际资金释放、真实签名 Pending/REMOVE 和 Robot 多轮刷新均没有新的成功结果**，不得因为五项单测或容器运行而标记通过。

## 真实数据仍保持
- Order P089: A/B 各 664 条活动订单，原始业务 WAL 676 条签名提交帧、两端字节和 SHA256 一致。
- Trade P246: A/B 原始业务 WAL 7 条签名提交帧、两端字节 SHA256 一致。
- 用 Common 原 RSA 钉扎公钥和真实只读物理 custody HEAD 验证，Order/Trade A/B 2/2 PASS；不是单纯比较文件大小。
- 原始 3 笔 CashIn 的不可变签名 WAL 前缀、MySQL 流水和余额已 read-only 核对 PASS；无重复入金。
- 两只开发探针 R0F6CC/e2e-depth10 和 R0F6CC/t199-signed-live 均 enabled=0，停止报价，旧错误码 CANCEL_FAILED 不表示本次修改后已通过。
- 没有清除签名 WAL 或提现/入金数据，没有申请生成新密钥。

## 本地代码提交及 Demo 镜像
- Order saas-crypto：43116e0（认证 Pending 三阶段 + MD Image），运行镜像 local/otc-t201d-ordersvr:certified-cancel-saga。
- Trade saas-crypto：3d84bdd（四域冻结释放 + 租户订单索引修复），运行镜像 local/otc-t201b-tradesvr:certified-cancel-index。
- Common saas-crypto：1f0574b（前阶段已通过真实运行中新订单的副本实时 Apply），现有四节点使用同一份 Common 物理引擎。
- 运行时 Compose 覆盖已写入 Mac 原隔离控制目录；四节点原始配置的 certifiedCancel enabled 开关均有独立 .t201-before-cancel 回滚备份。
- Docker/GHCR：只用 Mac 本地离线 Docker 构建，不需要 GitHub Actions 构建额度。

## 下一真实验收门禁（不可跳过）
1. T201d 用原独立测试租户一到两单真实 cancelBatchOrder，验证 Order Pending 签名帧先于 Trade RELEASE 帧，再验证 Order REMOVE。逐帧验证 Common CommitIndex/Custody，Order A/B 内存及 WAL 连续，Trade A/B balance/position/open order/dedupe 完全一致，并确保失败重试不重复释放资金。
2. MD 双节点实际收到 Order 的全量 Image，验证匿名 queryPublicMarket 和 Snapshot/Diff 连续更新。
3. Robot 从 1x1 增至原 10x10 多轮更新，检查连续盘口与 24h 统计，不能留下僵尸 Pending_Cancel。
4. CrossStrategy 相向订单真实撮合，成交回报、Balance/Position/Orders/Executions/Projection 签名 after-state 与数据核对一致。
5. 真实 SIGKILL 自动 A→B→A、反向 B→A→B，资金/仓位/订单/成交/MD 在互切后一致，只有全部 PASS 才关闭此任务。

本报告区分生产代码构建、容器启动、原始双签一致、Order 发布 MD Image 与真实业务端到端交易；绝不把前四者当作第五项通过。
