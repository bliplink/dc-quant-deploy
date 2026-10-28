# T245｜T244 Order/Trade 滚动发布与 Common 认证历史恢复阻塞

日期：2026-10-28 CST；分支 `saas-crypto`。**Demo：NO-GO；没有真实 Filled、Trade 资金认证结算或自动 A/B 互切的通过证据。**

## 证实的进展

1. 从目前运行的四个 Docker 容器反查 Compose 完整历史配置和 RSA 只读目录，恢复原有 `T212_RSA_A_DIR`、`T212_RSA_B_DIR`、`T212_RSA_PUBLIC_DIR` 变量，**不修改或重新生成密钥**。
2. 为四个服务逐一使用各自完整 Compose 配置追加 T244 overlay 做预检：**4/4 config 成功；环境变量、bind mounts、Host 网络、重启策略与运行容器完全相同，仅 image 更新**。T244 所述 RSA 环境缺失障碍已经排除。
3. T243 Robot 的 live `lastSequence` 从 2657 持续增长至 2931，和 `sourceQuoteSequence` 匹配，持续生成 Binance 来源的 Tape IOC（示例 BTC 0.0003）。Order A 旧镜像仍出现 `ORDER_COMMON_MATCH_PLAN_NOT_YET_CERTIFIED`，所以这些是指令而不是成交。

## 真实部署动作与失败

1. 原 A 不动，先 `docker compose ... up -d --no-deps --force-recreate ordersvr-b`：T244 Order B 镜像成功启动、连 ZooKeeper、恢复若干订单簿及业务统计，**尚无 READY/可提交认证业务 WAL 的证据**。
2. `tradesvr-b` 切换 T244，Common 在启动恢复 `CommonFileBusinessWal.requireHistoricalSignedPrefix`/Custody 时抛出 **`historical read-only WAL does not match RSA-certified HEAD`**，拒绝初始化是正确行为。
3. 先回滚 Trade B 至原 `local/otc-t230-tradesvr:scoped-product-recheck`：旧镜像也无法可靠 READY，见 `TRADE_COMMON_CERTIFIED_CENSUS_UNAVAILABLE` 与上述 WAL/HEAD 不匹配，说明问题不能单靠回退业务类解决。
4. Order A 多分区开始报 `Common physically certified partition writer unavailable: Pxxx`；为避免扩大影响，回滚 Order B 至原 `local/otc-t225-ordersvr:certified-common-window`。其重启后同样出现 `ORDER_COMMON_CERTIFIED_CENSUS_UNAVAILABLE`。**Order A、Trade A 从未升级，B 两节点已经回退镜像但不能声称恢复就绪。**
5. 原始日志分别保留在本机未提交的 `artifacts/t244-trade-b-recovery-error-20261028.log` 和 `artifacts/t244-order-b-live-during-replace-20261028.log`。**禁止直接提交未经脱敏的日志。** T244 新镜像保留供重新部署。

## 下一步必须完成（不是新增业务功能）

1. 对原始 Order/Trade 256 分区进行只读审计：ZooKeeper Epoch/owner/READY census，物理证书 HEAD 和原始 WAL 对应序号、双 Custody 水位、恢复来源与实际数据文件；定位具体不一致分区/证据，封存而非就地篡改。
2. 用户允许 Demo 全量重建。如果现有数据无法安全从认证副本追平，则使用有前置检查的**整套 Fresh Genesis/恢复**：ZooKeeper assignments、Common 原始 WAL/证书、Order/Trade、Projection、MySQL 一致初始化。不能只删除 MySQL、单个 WAL 或私钥；仓库 `tests/reset-saas-test-data.py` 只允许 `/data/dc-saas-runtime` 和 `/opt/dc-saas-runtime`，与本次 Mac 路径不匹配，不可绕过脚本保护盲删。
3. 恢复 B 的 READY/追平后，才能重新逐节点替换 T244，在 Order/Trade 两侧成对开启业务认证撮合与结算，跑新租户审批→Robot 稳定报价→Tape IOC 部分成交→两侧真实 Common 物理 WAL/回执→Projection 账目一致，要求实际 Filled>0。
4. 之后连续 A/B 双向 SIGKILL 自动切换、旧主隔离、256 分区和财务数据一致性；任何阶段未通过均为 **NO-GO**。

架构底线：Common 仅存 opaque WAL、认证复制、快照、恢复、HA，不包含 IOC/FOK/资金业务白名单；不得关闭 RSA/Custody 或伪造 Filled/READY。
