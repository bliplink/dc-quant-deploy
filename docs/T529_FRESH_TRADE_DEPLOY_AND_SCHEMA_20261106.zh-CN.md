# T529｜全新隔离部署、Trade Projection Schema 补齐与业务启动根因（2026-11-06）

## 结果与交付状态

**已实测 PASS：** 全新 MySQL、全部迁移和新增 Schema、独立 ZooKeeper、独立 Gateway、LoginSvr/ManagerSvr/AdminSvr 服务注册。**NO-GO：** 新环境 OrderSvr/TradeSvr 不允许脱离认证 Common Runtime 启动；没有新租户审批、真实 cashIn、Robot、成交、SQL 投影一致性或生产自动 HA。旧 T523 四个业务容器不变，仍运行，不能把其启动等同于成交。

本次只修部署/Schema：没有删任何业务 Common 门禁；没有添加 Order/Trade 私有集群逻辑、假 WAL、RSA、ACK 或 READY。没有使用 GitHub Actions。

## 发现并修复的全新安装 Schema 缺失

- 新 MySQL 初始化使用当前 `mysql/init/*.sql`，产生 43 张表，执行 `deploy-saas.sh` 同顺序的现有 **34 项迁移**后是 51 张表，但缺少 `dc_trade_projection_event`、`dc_trade_projection_mutation`、`dc_trade_projection_watermark`、`dc_trade_financial_readmodel_cursor`。历史进程启动时会创建这些表，故旧库有而正式 install/migrations 没有，解释了多次全新安装后 Trade/Projection 缺 Schema。
- 新增对应完全一致的 4 表建表文件：`mysql/init/12-trade-projection.sql`（全新安装）与 `mysql/migrations/20261106_trade_projection_financial_readmodel.sql`（迭代发布）。`CREATE TABLE IF NOT EXISTS` 幂等，真实新库重复运行 **2/2 PASS**；不拷贝老业务行、不截断/删除历史水位。
- 新隔离 MySQL **55 张正式表、827 字段、251 索引**，与旧库剔除五张 T529 暂存表后逐项完全一致。新租户 0、余额 0、Order/Trade 投影事件 0、消费水位 0；全局 BTCUSDT 存在。源码测试 `tests/test_trade_projection_fresh_schema.py` **4/4 PASS**；T528 数据连续性测试 **11/11 PASS**。

## 真实隔离环境，不复用旧业务状态

使用本机原镜像但全部独立控制和端口，没有覆盖旧服务：

| 组件 | 容器 | 端口 | 现场状态 |
| --- | --- | --- | --- |
| MySQL 8.0.36 | `otc-t529-fresh-mysql` | `127.0.0.1:34306` | 运行、隔离命名卷 `otc-t529-fresh-mysql-data`，55 表正确 |
| ZooKeeper 3.8.4 | `otc-t529-fresh-zk` | `127.0.0.1:42181` | 单节点运行，SASL 配置、单节点 ZOO_SERVERS 与 42181 绑定 PASS |
| GW | `otc-t529-fresh-gateway` | TCP `43000` / WS `43001` / HTTP `43002` | 真实启动监听且注册到新 ZK |
| LoginSvr | `otc-t529-fresh-loginsvr` | GW `43034`，HTTP `43990` | 运行、新 ZK 服务发现 PASS |
| ManagerSvr | `otc-t529-fresh-managersvr` | `43039` | 运行、新 GW 转发的非法参数请求返回正常业务校验 `9004` |
| AdminSvr | `otc-t529-fresh-adminsvr` | `43040` | 运行、新 ZK 发现 PASS |

- 本地私有配置目录：`~/.opentradingcore/t529-fresh-runtime`，私有 `t529.env` 模式 `0600`，独立 control/data/log；没有提交密码或密钥。
- 业务尝试容器 `otc-t529-fresh-ordersvr` / `otc-t529-fresh-tradesvr` 使用 T521 认证版 Order/Trade；配置关闭 Order/Trade 旧业务 HA 后，**均退出 1**：
  - `COMMON_ONLY_AUTHENTICATED_RUNTIME_MISSING: order.common.cluster.required`
  - `COMMON_ONLY_AUTHENTICATED_RUNTIME_MISSING: trade.common.cluster.required`
  - 切到旧 T335/T336 镜像进行 A/B 对比（容器 `otc-t529-baseline-order`/`otc-t529-baseline-trade`）也严格拒绝，**证明缺口不是 T521 镜像单独引入的问题**。
  - 源码 `OrderSvr.main`、`TradeSvr.main` 的 `CommonExclusiveBusinessClusterStartup.requireCommonOnly` 是有意的认证存储门禁，业务 Adapter 还检查 `CommonCertifiedNodeRuntime` / `CommonBusinessRecoveryReadiness` / 已安装物理 WAL writer；**不能将其去掉或改为直接旧 MySQL 写入，否则违反业务状态提交后应用的合同**。
- **不能把上面的单节点 MySQL/ZK/GW PASS 说成单机交易 PASS**。没有启动任何 T529 Order/Trade 业务入口，也没有真实新租户、Broker API、现金入账、Robot 点价或交易 E2E。
- 自动审批原有 T527 测试请求 `TB3EDF` 缺 `admin_password`，为 PENDING；本轮新租户凭据相关自动化文件创建受执行环境安全检查拦截，**没有执行新租户申请**。不进行安全检查规避。

## 旧数据库与错误投影试验的完整回退

历史 MySQL `otc-t398-mysql`（原端口 33306）没有清空。T529 为解决旧水位混用，曾在确认旧消费者和 Robot 停止后，以原子 `RENAME TABLE` 将五张投影表迁入 `*_t529_archive`，新建空表；重新启动旧 Projection 后，它从**旧 T523 Order WAL** 重放了约 **21,000** 条旧 Robot 事件，部分 Pxxx 仍然报未找到认证 writer / SERVER.OrderSvr 未上线，故停止消费者。

随后对五张表执行**一次原子回滚**，原业务表名已恢复、旧数据/水位完全保留：
- `dc_order_projection_event` **550,827** 条；
- `dc_trade_projection_event` **113,006** 条；
- `dc_order_projection_watermark` 与 `dc_trade_projection_watermark` 各 6 行；
- 失败重放数据独立归档在 `*_t529_replay` 的五张表，例如 `dc_order_projection_event_t529_replay` **21,000** 条，不删除以便溯源。
- 旧 `otc-t438-robotsvr-session-recovery` 和 `otc-t454-projection-common-rejoin` 继续**停止**，避免旧资金状态与 T523 新 WAL 继续混用。旧 T523 Order/Trade A/B 四容器仍在运行、原数据未清理。
- Mac 磁盘空间约 53 GiB，Colima 15.6 GiB RAM；避免盲目重装全栈或删除数据卷。

## 接下来必须实际完成的唯一业务阻塞

**先实现或激活正式 Common 认证启动，不能绕开安全检查。** 只有两种合规方式：

1. 推荐：在这套全新干净 SQL/ZK 下，使用当前 Common 正式双节点 RF2 流程为 Order/Trade A/B 建立新命名空间、真实双物理签名 E1 出生记录、WAL + Snapshot + READY、逐分区认证后才允许 Gateway 发布业务，重用现有成熟的 T523 工具及部署接口。旧业务数据不导入；自动 HA 可仍未启用，但需要准确标记 NO-GO。
2. 若产品必须支持真正单节点，则只在 **Common** 增加/使用明确的持久化级别 LOCAL 认证启动和物理存储合同，Order/Trade 仍仅复用 Common BusinessAdapter；必须记录 LOCAL RPO 风险、提供原始 WAL 证据。不要移除 `COMMON_ONLY_AUTHENTICATED_RUNTIME_MISSING`。

完成服务认证后，依次使用新 Manager 的正式新租户自动审批、新 Trade 认证入金、账户余额、Robot 挂价/Tape、真实 Order/Trade WAL、成交结算、新 Projection 与新数据源水位 E2E 验证。无客户成交证据前**坚决 NO-GO**。

**防止误报：** 本轮“基础设施 PASS”与“业务交易 PASS”是完全不同的状态。所有新增的代码是 SQL 初始化与幂等迁移，不含 Common/Order/Trade 集群改造。