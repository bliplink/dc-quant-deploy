# T330｜全新 Demo 双租户自动审批、Robot 报价与 Common WAL 一致性（2026-10-30）

## 用户要求与本轮实际操作

用户要求停止围绕 T325/T329 旧 WAL、租户和资金账本兜圈，**全新重部署**后走真实注册→自动审批→Maker/Tape 自动开户/入金→Robot 报价→真实成交，再进行严格 HA。保留 RSA、签名与原始故障证据，不使用 GitHub Actions、不改变 Gateway 透传或 Common/业务集群边界。

### 数据隔离与磁盘

- 已证实 T329 Order P176 因 B Common TCP 45323 重启期间被拒绝，A 的第 386 条 WAL 只有本地 fsync、没有 B 物理持久 ACK；拒绝把尾部当已提交，保留在 `data/t329-fresh/`。只读核查 **255/256** A/B 字节一致，P176 A386/B385，SHA256 原始值已记录于 `~/.opentradingcore/t330-demoreset-diagnostic-20261030/T329-P176-uncertified-wal-pre-reset.txt`。
- Mac 只剩 14 GiB，发现旧 Demo `log/ProjectionSvr.log.2026-10-29` 约 80 GiB，当前 `ProjectionSvr.log` 约 68 GiB。各存尾部 800 行与 SHA256 后，只删除 10/29 已旋转的单文件，清空仍在使用的旧日志，并把 `ProjectionSvr/config/log4j.ini` 改为 `RollingFileAppender, MaxFileSize=16MB, MaxBackupIndex=3`，不改签名/WAL。可用空间提升为 **161 GiB**，使用率降为 **63%**。
- 新增 `compose.t330-fresh-demo.yaml`，T330 MySQL/ClickHouse 数据分别在 `data/t330-fresh-mysql` 与 `data/t330-fresh-clickhouse`，Order/Trade A/B 在 `data/t330-fresh/{OrderSvr,TradeSvr}/{A,B节点}`。T318 原来真实双签 E1→E2 STRICT_QUORUM READY Manifest、只读 Genesis、双独立 RSA 未更改；T325/T329 原数据全部保留。
- 新 MySQL 初始化 43 张基础表，按已有根目录 SQL 补 `20261019_dc_symbol_tenant_identity.sql`, `20261019_tenant_product_data_source.sql`, `20260930_tenant_liquidity_bootstrap.sql`, `20261017_tenant_numeric_user_ids.sql`, `20261020_tenant_product_matching_mode.sql`, `20261018_01_broker_tenant_sources.sql`, `20260904_01_bankruptcy_insurance_adl.sql`，最后 48 表。另按仓库已有 `20260908_order_projection.sql` 创建原本遗漏的两个 Order 投影表。
- 原合法 E2 初始运行要求空物理 WAL 根目录**预先存在**，首次 T330 Trade 重启循环报 `Common warm E2 signed physical WAL root absent`，已按服务/节点显式建立四个独立空根并恢复。今后一键部署必须把 mkdir 作为检查前置，不能通过弱化 Common 签名检查解决。
- 使用 `tests/provision-t330-fresh-platform-robot-identity.py` 只写新 MySQL 的平台原有身份和现有 Robot Runtime Key（不打印凭据、不生成新 Key）；原旧客户端注册于同一 T318 三 ZK 目录，Legacy ZK SASL 关掉，仅此开发 Demo。Mac→Colima localhost SSH reverse tunnel 的真实 Binance Futures WSS 握手和 APS 实时报价仍有效。

## 启动/注册结果

必须先启动 **Trade A/B**，均真实 Spring 启动、Common 认证、256 个新 E2 WAL 分区、原 ZK 注册，容器 0 次重启；然后部署 **Order A/B**，均真实 Spring 启动、256 WAL 分区、Common 认证、原 ZK 注册，`TradeSvr partition primaries preconnected: 2/2` 两节点各通过，容器 0 次重启；再启动 Gateway、Login、Manager、Admin、APS、MD、Liq、Projection、Robot。Gateway 同时和两个 Order/Trade、三个控制服务真实建立 TCP 连接；MD A/B 各 128 只读分区。

## 正式 API 自动审批与真实资金、Robot 报价

`python3 tests/verify-tenant-auto-approval.py` 通过真实 Gateway→Manager→Login，新增租户 `WGOAVT`，申请状态直接 `APPROVED`，租户管理员真实登录成功，重复提交幂等；五产品请求按当前策略仍 `PENDING`。

本次还创建了更早的 T330 测试租户 `SWUUDO`，不是从旧库导入。

截至 16:05 本机实测：

| 租户 | 自动 Worker | Maker 真实资金 | Tape 真实资金 | Robot | 当前挂单 |
|---|---|---:|---:|---|---:|
| SWUUDO | COMPLETE / DONE | 10,000 USDT | 10,000 USDT | RUNNING | 40 |
| WGOAVT | COMPLETE / DONE | 10,000 USDT | 10,000 USDT | RUNNING | 40 |

Maker/Tape 入金通过 TradeSvr 真正调用；没有直接 SQL 增加账户余额。APS 通过 Binance Futures 实时 WebSocket，Robot 确实收到非空 BTCUSDT Bid/Ask，触发 Order A 真正撮合状态和新单/撤单；Order A 真实订单簿曾显示约 39–58 笔活动委托（单分区统计），Robot 自报 40/租户。两端物理 WAL：Order A/B **256/256 字节一致**，有非空签名业务 WAL；Trade A/B 在两个实际资金分区均有 WAL。

## 未完成，严格禁止冒称成功

- **Tape 已持续按 Binance 成交量生成 IOC 指令**，Order A 收到 Tape 新单，Trade 的 `Newing success=true code=0` 实际出现，但 Order 统计 `tradeExecs=0`。截至 16:05，**没有可靠证据证明任何 Tape 真实撮合成交**；不能用指令数量、订单 ACK 或 Robot 挂单量替代成交。
- `queryOpenOrder` 偶发 `ORDER_COMMON_CERTIFIED_CENSUS_UNAVAILABLE`，Tape 在此请求失败时明确跳过，仍需针对原业务路由校验修复，不要修改 Common 的实时授权热路径。
- 新 MySQL 初始缺 `dc_order_projection_watermark`/event，已补原 DDL、重启 Projection。新 Projection 之后报 `projection event exists ahead of watermark`：分析 Order Fetch 发现把**重复业务订单 ID**作为 `eventId`，而 MySQL `dc_order_projection_event.event_id` 唯一。修复 T331 将投影读端事件 ID 用唯一真实 Common 物理 `partition:epoch:sequence`，**不更改已签名 WAL**。源码位于 `.work/ordersvr/src/main/java/com/app/dc/handler/FetchCommittedOrderProjectionEventsHandler.java`，新增 2 个 JUnit，**全量 Order 128/128 通过**，本地 Order commit **`9761518`**。
- 上述 T331 改动**尚未替换正在运行的 T330 T328 镜像**。还发现当前 Projection 消费端只解析单个 `mutation.order`，但实际 Common 提交使用 `STATE_BATCH` 和原子匹配 batch，需要支持经认证的多状态帧/合法 ACK-only 帧后才能部署 T331 并完成投影。不能为了绕过错误伪造订单、重置 watermark 或跳过缺失的真实已签帧。
- 新库 `dc_order_projection_event`, `dc_order_projection_watermark`, `dc_orders_execorders` 实际数量仍为 **0**，未验收订单/成交/持仓投影，24h K 线和真正 Tape 成交 **NO-GO**。
- 未做 Order/Trade SIGKILL 自动 A→B→A 严格 HA；无完整交易 E2E GO。

## 接续优先级

1. 在原 Projection 业务消费者实现认证 `STATE_BATCH`、`STATE_MATCH_ATOMIC` 和签名 ACK-only 回放，正确使用 T331 物理事件键；先回归再受控部署，避免写入中的 Order A 热替换/再次产生未认证尾部。
2. 核对 Tape IOC 价格/数量与真实 Maker 订单（Maker `0.001 BTC`，Tape 通常 `0.0002–0.0003 BTC`），完成部分 Maker 成交与 Trade settlement Outbox、资金持仓/成交和 K 线真实结果验收。
3. 只在真交易 E2E 持续正确后，进入严格 RF2 故障注入；期间不能强行删除 WAL、假造物理 ACK 或为了显示绿色状态伪造 READY。
