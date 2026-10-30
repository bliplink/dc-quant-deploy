# T329｜正式 Demo 全新重部署：自动审批、Maker/Tape 真实入金已通过；Robot 行情阻塞（2026-10-30）

## 用户授权与边界

用户明确要求**不要继续修旧服务、旧租户、旧资金、旧 WAL**；直接全新部署，注册租户、自动审批、Robot 报价、真实成交，再做严格 HA。所有操作均针对 Mac 开发 Demo，不使用 GitHub Actions，不添加 Order/Trade 自研集群。Gateway 保留原透传实现，ZooKeeper 只做注册/路由及 Common 控制面，业务持久化与签名由 Common 实施。

## 重部署实际变更及证据

1. 将正式后端容器停止后，使用全新的 `/srv/dc/data/t329-fresh-mysql`、`/srv/dc/data/t329-fresh-clickhouse` 数据卷重建 MySQL/ClickHouse；旧 T325 MySQL、Trade/Order WAL、T293/T318 RSA 和签名证据**未删除/覆盖**。
2. 不伪造新创世：复用之前真实三 ZooKeeper + 双独立 RSA 已验证的 **T318 原始 E1→E2 STRICT_QUORUM READY** 256 分区 Order/Trade Manifest 和 read-only signed birth root，新建 **T329 空业务 WAL 根**，未复制 T325 旧业务 WAL。
3. 已用本地 T328 构建镜像 `local/otc-t328-ordersvr:certified-fetch` / `local/otc-t328-tradesvr:certified-fetch` 完整重建 Order A/B、Trade A/B；四个 Spring JVM 均真正启动并打印 `COMMON_GATEWAY_DISCOVERY_CERTIFIED`，原 ZooKeeper `/MDTService/OrderSvr`、`/MDTService/TradeSvr` 可见 A/B。四节点本轮稳定运行、容器重启数 0。
4. 对旧业务服务仅作部署兼容：`ATSConfig.ini` 的唯一注册 ZooKeeper 地址改为 T318 真实集群的一个可达入口 `192.168.128.7:2181`；**旧客户端不支持逗号分隔多个地址**，Common 物理运行时本身仍是三 ZK。备份 `ATSConfig.ini.pre-t329-20261030` 留在 Mac 控制目录；未改 Gateway 透传实现。旧业务客户端原来对该无 SASL 的 Demo ZK 会报 `AuthFailed`，故通过 `JAVA_TOOL_OPTIONS=-Dzookeeper.sasl.client=false` 重建原 T252/T263 Gateway、Login、Manager、Admin、APS、Projection、Liq、MD、Robot 的**相同原镜像**。
5. Gateway 实际建立连接到 Order A/B、Trade A/B、Login、Manager、Admin；Common `CommonCertifiedGatewayRoutingProjection` 在旧 Gateway 路径发布**256/256** READY 路由，只作为已签名 Common Manifest 的只读兼容映射，并非第二个授权/复制算法。
6. 新库原始 init 缺失既有迁移，实际补入 `dc_symbol.location`、`dc_tenant_data_source`、`dc_tenant_liquidity_bootstrap`、`dc_tenant.next_user_no/tenant_id`、`dc_tenant_symbol.matching_mode`、`dc_tenant.liquidity_source/price_source`，以及 Trade 风险 ADL 旧表。复用已有 SQL，无业务特性扩展。把缺失的已有 reapply-safe SQL 归回 `mysql/migrations/`，保障未来新装。
7. 新库 PLATFORM 运行账号为空。用 `tests/provision-t329-fresh-platform-robot-identity.py` 从实际部署环境读取现有平台管理员与 Robot Runtime Key，仅在**T329 新 MySQL 根**中补原有运行身份。原 Robot Gateway 管理用户名与平台管理员相同，之前密码配置不一致，T329 Compose 显式同步既有平台管理员密码。重启 Login、Gateway 后 Robot Runtime Key 由 `ApiKeyService` 真实加载、Runtime API 验证成功；`LIST_RUNNABLE` 初次因缺 `liquidity_source` 失败，补入原已有 Broker source 迁移后不再出现此 SQL 错误。

## 新租户 E2E：逐项真实结果

- `python3 tests/verify-tenant-auto-approval.py` 在新 MySQL / 正式 GW / Manager 路径多轮成功：真实提交、`APPROVED`、租户管理员登录、重复请求幂等 PASS；五产品申请正确保持人工 `PENDING`。没有手工将租户审批状态改为成功。
- 测试租户 **BSIY2Q**，新数字 Maker 用户 `000600000001`、独立 Tape 用户 `000600000002`。Admin 自动 Worker 完成 Maker/Tape API Key 申请，通过新 TradeSvr 公共认证状态机分别实际 `cashIn` **10,000 USDT**；MySQL `dc_users_balance` 两户均 10,000，`dc_users_posting` 分别保存 `TENANT_TRIAL_LIQUIDITY_92ee...` 和 `TENANT_TRIAL_TAPE_LIQUIDITY_92ee...` 两条资金流水；`funding_confirmed=1`、`tape_funding_confirmed=1`。
- Trade Common 真实物理双节点 WAL：业务提交落在 **P068、P146**，两个分区 A/B 都有非空 `business.wal`，每个分区 A/B **3,282 字节且字节完全一致**。Order 新业务空 WAL 经原 CRC+连续帧验证，**A/B 256/256 字节一致**。这证明本轮两笔 Demo 入金真实落库且 A/B WAL 相同，**不等于 HA 双向 SIGKILL、Projection 最终一致性已通过**。
- 新建 `trial-liquidity-BTCUSDT` Robot，`BSIY2Q`、`HU6EGE` 两租户均已存在；Robot Runtime API 授权及 `LIST_RUNNABLE` 缺字段错误修复后，Robot 仍显示 **STALE、0 挂单**；Worker `RETRY / VERIFY`，不是成功完成状态。真实下单撮合、盘口深度与 Tape 成交均 **未通过**。

## 唯一明确剩余行情障碍

- `dc-saas-apssvr` 原 Binance Futures 行情客户端报 `UnknownHostException: fstream.binance.com`；原 Docker host-network 容器 `/etc/resolv.conf` 缺 `nameserver`。
- T329 仅对 APS 配置 DNS `1.1.1.1,8.8.8.8` 并重建，DNS 解析开始可用，但后续 `fstream.binance.com` WebSocket **连接超时**；Mac 直连 Binance Futures API 超时，经已有本机 HTTP proxy 请求 Futures 返回 451，不能视作可用实时行情。
- Robot 收到的 `dc.bookticker.BNFutures.BTCUSDT` 只有 `bid:null ask:null last:null bidLevels:0 askLevels:0`，随后反复因缺新鲜 book/depth 重新建链；这是 Robot `STALE` 的真实原因。**不应**为了冒充成功手工插单、向数据库补 24h 成交量、忽略 stale 门禁或虚称来自 Binance 的行情。
- 源码已有 `ROBOT_ALLOW_FRESH_MARK_REFERENCE` 可选真实 APS mark/index 参考价格入口（不伪造 Binance BBO）；现有 BrokerPrice preview 入站接口是**独立未验收**管线，标记 `BROKER_PRICE_PIPELINE_NOT_READY` 且带租户作用域，不能直接冒用成正式 Binance 价。后续只有获得真实有效外部行情或独立标注并证实安全的 Demo 自定义市场数据源，才可完成 Robot 报价和真实 Tape 撮合验证。

## 当下判定

**新装、四进程认证启动、租户自动审批、Maker/Tape 独立开户/入金及 A/B 物理 WAL 一致：PASS。Robot 持续报价、真实成交、24h 数据、Projection 权威一致、自动 A→B→A 严格 HA：NO-GO。**

未清理老证据，不使用 GitHub Actions、不推送存在大幅远端分叉的 `saas-crypto`。部署用 `compose.t329-fresh-demo.yaml`（新数据根/T318 旧合法签名），`compose.t329-legacy-zk-nosasl.yaml`（原业务客户端注册兼容/DNS），原有 `.env.prod` 不提交。本地验证和仓库更新可单独审计。
