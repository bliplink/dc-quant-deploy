# T325｜优先正式替换 Order/Trade，恢复原有 ZooKeeper 注册与真实交易链路（2026-10-30）

## 实际已部署（正式 Demo Mac，不是隔离启动）

按用户最新指令“先替换 Order/Trade，先恢复交易，严格 HA 后测”，已在正式 `dc-saas` 容器用已本地构建的 `local/otc-t319-ordersvr:virgin-e2-replica` 和 `local/otc-t319-tradesvr:virgin-e2-replica` **实际替换**四个服务：

| 正式容器 | Spring | 原有 ZooKeeper Gateway 注册 | Common Epoch2 WAL |
|---|---|---|---|
| dc-saas-ordersvr | PASS | OrderSvrA 127.0.0.1:33036 | 256 |
| dc-saas-ordersvr-b | PASS | OrderSvrB 127.0.0.1:33041 | 256 |
| dc-saas-tradesvr | PASS | TradeSvrA 127.0.0.1:33037 | 256 |
| dc-saas-tradesvr-b | PASS | TradeSvrB 127.0.0.1:33046 | 256 |

原正式 ZooKeeper 服务 `127.0.0.1:32181` 中：`/MDTService/OrderSvr` 注册 A、B；`/MDTService/TradeSvr` 注册 A、B；四个各自旧协议节点的 ephemeral 注册均实测存在。注册调用原有 Common 的 `CommonCertifiedGatewayDiscovery`，`GW` 未修改。四个业务 TCP 端口真实 CONNECTED。持续运行至少 15 分钟时四个进程重启数均 0。

使用原正式 T181 已完整认证的双物理 RSA Genesis 和 E2 STRICT READY 清单：`/otc/demo-t181-fresh-20261027/order/manifest` / `trade/manifest`，实际两个都 `NPC1|2`，分区 P000/P255 E2 STRICT READY。旧 T181/T182、T318、T319 认证证据原地保留；**没有将旧 T182 非零 WAL 移入新数据根**。新干净数据目录 `$DEPLOY_ROOT/data/t325-trading-e2` 四节点分别有 256 份真实 `business.wal`。最初缺目录出现 `Common warm E2 signed physical WAL root absent`，只创建了四个空物理根，再重启；Spring、RSA 和新 WAL 全部认证并启动。

原四个正式业务容器的 Docker inspect 元数据保留在本机私有目录 `~/.opentradingcore/t325-trading-restore-20261030/rollback/`（0600）；T321 独立测试写进程被停止，测试旧 WAL 保留。原 `.env.prod` 仍是旧版本镜像的历史参数，**今后更新必须使用本轮新 Compose override，否则可能回退旧容器**。

## 真实业务 E2E 结果与未通过事项

- 正式 `dc-saas-robotsvr` 已实际重启，真实收到 Binance book ticker。
- 新隔离租户 `R32530`：通过真实 Gateway 登录及 TradeSvr 的 **Common 认证 cashIn**，Robot 成功得到 `RUNNING` 和 **10 bids + 10 asks/20 open quotes**，参考报价偏差在 30 bps 以内。该报价验收 PASS。
- Robot Tape 被开启，日志有真实 `tape instruction` 和 `events` 计数，但 `AdminSvr queryKLine` 返回 `data:[]`，60 秒验收失败：**Tape 真实成交/租户 K 线 NO-GO**。已针对仅测试租户 `R32530` 将 `strategy_config.tape_enabled=false`，保留 20 档报价，避免未验证的连续 Tape 测试流量。
- 另一独立测试租户 `T325_E2E`：用正式 Gateway 登录四个测试用户，发送带真实 `Info1` request ID 的 Common 认证 cashIn，**MySQL 确认 4 条入金 posting**。创建有效 BTCUSDT tenant product 后测试进入 FOK/IOC 阶段；但下单虽收到成功响应，待投影的 `dc_orders`、`dc_orders_execorders` 在 MySQL 都仍为 0，测试等待 `New` 超时。**完整撮合/资金持仓一致性尚未验收。**
- 核心阻塞已经定位到**明确源码占位实现，而不是 Gateway 或 ZK 网络问题**：原 `.work/ordersvr/src/main/java/com/app/dc/handler/FetchCommittedOrderProjectionEventsHandler.java` 的 `fetch()` 固定返回 `ORDER_COMMON_PROJECTION_COMMIT_INDEX_NOT_CONNECTED`，Trade 同名处理器固定返回 `TRADE_COMMON_PROJECTION_COMMIT_INDEX_NOT_CONNECTED`；现运行的 `dc-saas-projectionsvr` 持续收到这两种 ERROR。它们尚未把 Common 的物理双 RSA Custody/CommitIndex 已确认日志转为 Projection 二进制 Fetch。**不能将旧 Order/Trade 私有 Chronicle Journal 恢复为权威源，也不能把未提交 WAL 直接落库**。真正的 P1 下一步是 Common 域不透明的已认证读取接口 + 业务 envelope 转 Projection Wire，补好以后本地构建镜像、更新本轮 Compose override、重跑真实入金/下单/成交/投影/Tape 验收。
- 正式 `dc-saas-ordersvr-c` 仍为旧镜像 Exited(1)，本轮用户要求先恢复 A/B 交易，不冒充 C 已恢复。旧版本 Robot 其他租户可能仍有业务报错，不以本次 20 档 PASS 推断全租户健康。
- 本轮**没有严格自动 A→B→A SIGKILL 验收**；Common 严格生产全自动仍 HA NO-GO。先修真实交易投影。

## 可复现部署和验收源码

- `tests/prepare-t325-formal-trading-config.py`：根据现有 T319 配置生成四份权限 0600 正式业务 properties，指向原正式 T181 签名 E2 Genesis 和真实 ZK、全新业务 WAL，恢复原旧协议 ZK Gateway 注册。仅生成本地受控配置，不包含密码或私钥。
- `compose.t325-business-restore.yaml`：在**原有** Compose 之上仅覆盖 Order/Trade A/B 镜像、业务 properties 和原 RSA 只读挂载。保留 Gateway/MD/MySQL/Robot 原定义。
- `tests/verify-t325-formal-business-boot.sh`：只读检查四个镜像、Spring、原有 `/MDTService` ZooKeeper 注册、1024 文件的 Common E2 WAL，不发交易、不启用 HA，输出 `T325_BOOT_ONLY_PASS trades=NOT_VERIFIED tapeKline=NO_GO projectionCommonCertifiedReader=NOT_CONNECTED strictHA=NOT_TESTED`。该脚本在正式容器上已通过。
- 运行时私有本机目录 `~/.opentradingcore/t325-trading-restore-20261030/config/` 存放生成的 0600 配置；Compose 用环境变量 `T325_CONFIG_ROOT` 指向它，`T325_RSA_ROOT` 使用原 RSA 本地私有目录，绝不可提交私钥。原始 `dc-saas` Compose 文件没有重写。

**本轮结论：真实正式 Order/Trade 4/4 启动/注册和 Common 数据落盘 PASS；认证入金 + 20 档 Robot 盘口 PASS；订单/成交 MySQL Projection Fetch、Tape 正成交 K 线、完整业务 E2E 与严格自动 HA 仍 NO-GO。**
