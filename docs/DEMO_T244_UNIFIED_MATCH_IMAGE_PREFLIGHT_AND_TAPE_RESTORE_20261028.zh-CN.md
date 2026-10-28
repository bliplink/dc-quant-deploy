# T244｜Demo Tape 恢复证据与 Order/Trade 新镜像部署预检

**记录时间**：2026-10-28 16:14 CST；各服务 `saas-crypto` 分支。**最终验收 NO-GO：真实 Filled=0，Order/Trade A/B 交易与自动互切尚未通过。**

## 1. 实际成功的 Tape 事件输入（不等于成交）

- T242 APSSvr `local/otc-t242-apssvr:aggtrade-health` 已真实部署，仅替换 APSSvr；四个 Binance Futures aggTrade 连接（BTC、ETH、SOL、UNI）都 `opened`。
- 2026-10-28 16:02:08 CST，APSSvr 日志 **明确确认真实 Binance aggTrade 事件到达并已向 GW 发布**：`APS_AGGTRADE_SOURCE_FIRST_ACCEPTED` 以及 `APS_AGGTRADE_GATEWAY_FIRST_PUBLISHED`，BTCUSDT/ETHUSDT/SOLUSDT/UNIUSDT 全部成立。
- T243 Robot 从 `local/otc-t212-robotsvr:fresh-mark-ref` 基底构建只读水位诊断镜像 `local/otc-t243-robotsvr:tape-watermark-diag` 并替换唯一 `dc-saas-robotsvr`；Gateway depth 首条合法事件 `ROBOT_MD_FILTER_RECEIVED`，发布 `ROBOT_MD_QUOTE_READY`。
- 2026-10-28 16:10 CST，Robot 实际收到 **334、335、355、357 条**聚合成交事件，`lastSequence` 与 `sourceQuoteSequence`、`sourceBufferNewest` 同步连续前进；之前固定 `158976` 且 `events=0` 的旧游标/订阅状态通过定向恢复清除。多个租户真实发出 `RBtrialliquidi-TP...` IOC 请求，示例 `Buy 81167.1 0.0002 BTC`。
- 但 **Order A/B 旧镜像仍报 `ORDER_COMMON_MATCH_PLAN_NOT_YET_CERTIFIED`，且 MySQL `dc_orders_execorders.last_qty>0` 计数 0**；不能把 Robot instruction 当作真实成交。

## 2. T242 源码/单元测试可核验结果

- 共享业务协议 `.work/com.app.dc`：T241 `6461e9a`（RSA Auth Order→Trade 与 Trade→Order Signed Receipt）；Common 源码未改。
- `.work/ordersvr`：T242 `07ddfd9`；同一 opaque Common WAL 支持 Maker 部分成交 UPSERT、Taker 完整成交 REMOVE；可连续部分/最终两次成交。**118 Java8 主源码编译，30/30 单测 PASS**。
- `.work/tradesvr`：T242 `5a9f495`；原始认证 Order WAL 经济字段核对、双边资金/冻结保证金/手续费/去重、Maker 部分成交继续持有剩余订单。**167 Java8 主源码编译，36/36 单测 PASS**。
- `.work/apssvr`：T242 `01b4146`；aggTrade WS 连接订阅/心跳/重连及一组真实源/GW 低频首包日志。**99 Java8 主源码编译（项目需 GBK 源码编码），5/5 单测 PASS**。
- `.work/robotsvr`：T243 `27e837c`；只读源 Quote/Buffer/Tape 三序号诊断，并未改下单价格/频率/风控。**19/19 回归 PASS**。根部署 Compose commit T243 `0658723`。

## 3. T244 新 Order/Trade 镜像已在 Mac 构建并通过静态内容检查

| 服务 | 新镜像 | 继承原 Demo 镜像 | 结果 |
|---|---|---|---|
| Order A/B | `local/otc-t244-ordersvr:unified-match` | `local/otc-t225-ordersvr:certified-common-window` | Docker build PASS、完整业务类和共享 RSA 协议类存在 |
| Trade A/B | `local/otc-t244-tradesvr:unified-match` | `local/otc-t230-tradesvr:scoped-product-recheck` | Docker build PASS、完整业务类和共享 RSA 协议类存在 |

镜像实现：沿用当前在用的 Common 本地 Jar、Netty、ZooKeeper、物理 RSA、WAL 和集群控制，**仅将已编译业务主源码与共享协议 class 叠加进 `/srv/dc/dc/{OrderSvr,TradeSvr}/classes/`**。文件：
`.work/ordersvr/Dockerfile.t244-unified-match`、`.work/tradesvr/Dockerfile.t244-unified-match`；根 `compose.t244-unified-match.yaml`。无 GitHub Actions，本机不存在 `mvn`，Java8 用已有 target/dependency 校验。

### 为什么 T244 暂时未替换正在运行的 Order/Trade 容器

**严格部署预检失败，而不是镜像构建失败**：

- 当前 Order A/B 与 Trade A/B 均通过多层历史 Compose overlay 启动，继承了原 `/read-only-original-rsa/a|b`、`/read-only-original-rsa/public`、`/srv/dc/control`、`/srv/dc/data` 等只读/可写挂载。
- 使用其完整 `com.docker.compose.project.config_files` + `.env.prod` 在 T244 target 进行 `docker compose config` 时，解析缺 `T212_RSA_A_DIR`、`T212_RSA_B_DIR`、`T212_RSA_PUBLIC_DIR`。这些变量属于**以前启动时的外部环境**，不在当前普通 `.env.prod` 文件；直接简化 Compose up 可能导致旧证书路径和主备授权配置丢失。
- **本轮没有重新生成密钥、绕过安全检查或试图禁用物理认证；没有强行用新镜像重建 Order/Trade。** 需在相同原始 RSA/控制/日志/数据目录及真实 live env 下验证 Compare：只允许 image 改动，container mount/network/zk/rsa/volume/permission 不能改，再一台一台滚动替换，不可一把同时停 A/B。

## 4. 下一步真实可验收动作

1. 从现有 Demo 控制目录/部署脚本恢复原始 T212 RSA 变量**对应的已挂载路径**（不生成新密钥、不打印私钥），对各 A/B 当前运行容器完整 Compose 模板做 no-diff preflight，再逐节点替换 T244 Order/Trade 业务镜像。
2. 业务状态允许后启用成对的 feature flags：Order `order.trade.signedMatch.enabled=true` / `order.trade.signedMatch.delivery.enabled=true`，Trade `trade.orderMatch.signedRpc.enabled=true` / `trade.common.certifiedPairFill.enabled=true`；不允许只放开半链路。
3. 新租户自动审批→Robot 连续报价→真实 Maker/Taker 完整/部分 IOC/FOK 成交→Trade Common 物理 commit→Order 签名持久回执→Projection 真实订单/成交/账务/资金记录。补足无对手 IOC 取消、多 Maker 匹配、Market/Close 业务，以及 Trade→Projection 认证 CommitIndex 读取。
4. 完成 Order/Trade A/B 双向自动主切/旧主隔离/原始 WAL 追平、未丢单/无重复成交/资金持仓流水一致的实际 SIGKILL 验收。此前一律 NO-GO。

## 原则

Common 只管业务无关持久化、恢复、复制、归档、快照、Epoch/HA，不引入任何订单类型或财务字段判断。服务之间的 RSA 签名事件是**业务服务来源认证**，并不代替 Common 独立真实物理 2/2 Custody 证明。本轮保留原镜像用于回滚。
