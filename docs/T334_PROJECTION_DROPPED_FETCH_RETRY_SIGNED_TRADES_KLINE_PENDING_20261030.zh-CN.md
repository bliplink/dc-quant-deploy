# T334｜Projection Fetch 丢失回调自动恢复和双租户签名撮合验收（2026-10-30）

## 源码、测试与部署（已完成）

- T333 Order A/B 双节点滚动部署后，两个真实撮合分区 P094/P193 的物理 Common WAL 继续增长，但 MySQL Projection 水位停在 17:32。旧 Projection 异步 Fetch 丢失回调时 fetchInFlight 一直为 true，定时 safetyPoll 永远跳过，直至手工重启。
- T334 基于原运行镜像匹配源码修复读取端：Fetch 发起时保存 startedAtMs 和 generation；超过 max(10s,2×fetchTimeoutMs) 超时则清理 in-flight 并重新请求；过期回调不允许改变新游标。Common WAL、Trade/Order 状态机、Gateway 和原 RSA 未更改。
- Projection 全量 Maven 27/27 PASS；同运行镜像 lib/classes 精确 Java 8 ABI 编译、6/6 JUnit PASS。源码本地提交 b369ce3，镜像 local/otc-t334-projectionsvr:fetch-timeout，SHA 48e6226b22b2ca3d494f1a2c072ae15ea59fabedf3a63dcd35df9268a04d58ee。
- 通过 compose.t334-projection-fetch-timeout.yaml 只重建 Projection，Order A/B、Trade A/B 的 StartedAt 未变。17:55 Spring 与二进制消费端真实启动，重启数 0。

## 已认证 WAL 与数据库持续追平（真实运行）

- 原 T333 文档称版本更新后没有新增成交，需要纠正：只读解析原始 WAL、校验 CRC/连续序号后，17:34 起 P094 至少新增 162 份原子撮合和 162 个签名回执，P193 至少 100/100。MySQL 当时仍是 2862/2862 因 Projection 卡住，不是交易已经停摆。
- 重新连接后 MySQL P094 水位 9229→9729→10948→11857，P193 12278→12778→15778→20627；已认证撮合/回执 2862/2862→2944/2944→3175/3175→3302/3302，17:58 进一步达 3327/3327。
- Order A/B 原始物理 WAL 256/256 分区严格逐字节一致。Trade A/B此前也通过全部分区逐字节一致检查；本轮未进行 HA SIGKILL，不能以 WAL 一致替代自动 HA 成功。

## 未通过

- SWUUDO/WGOAVT Gateway 的 MDSvr.queryPublicMarket recentTrades 仍无记录，AdminSvr.queryKLine 仍 code=0、data=[]。虽有真实金融结算和双签原子成交，成交未成功展示为 MD 行情/K 线。
- 当前已核对 MD ExecOrderInput 订阅旧业务主题 dc.order.trade.*.1.**，而 T333 下游有已提交金融签名之后的 Maker=1、Taker=0 通知。需要检查服务重启的旧订阅/MD market Image 路由与最终 ClickHouse 写入；不可伪造 Kline。
- 普通用户 Demo=0 交易查询/资金持仓及自动 A→B→A SIGKILL HA 仍 NO-GO。T329 P176 未认证尾部及旧 RSA 证据保留。

不使用 GitHub Actions、不远端 push、不覆盖签名 WAL、不修改 Gateway 透传行为。