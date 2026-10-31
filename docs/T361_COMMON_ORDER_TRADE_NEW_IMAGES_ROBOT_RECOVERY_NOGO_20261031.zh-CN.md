# T361｜新 Common Order/Trade 本地候选镜像、隔离重建与 Robot 恢复门禁（2026-10-31）

> 真实结果：**Common/Order/Trade 本地回归和新镜像构建 PASS；T361 正式替换、全新租户与 Robot 报价/真实成交未完成（NO-GO）。** 不凭镜像运行状态宣称交易或 HA 恢复。

## 已完成的源码与本地镜像

- Common 源码 `2e45510`：分区级签名协作 RECOVERING、Home 归主 Watch、单分区物理 WAL 退休、128/128 进度审计、整份 Manifest 单 in-flight 安全边界。Common Maven 154 suites、668 tests、0 failures、0 errors、6 skipped，exit 0；原始 P193 只读证据保留。
- Order 137 tests（2 skipped），Trade 207 tests（0 skipped），均 Maven exit 0。二者所用 Common JAR SHA256：`56393f0097ea79a39d10619a4f490cf4aac04d0487de44b15dc219342d92ca7b`。
- **新 Order 镜像：** `local/otc-t361-ordersvr:common-home-canary`，镜像 SHA256 `6554a7cc072fbc3f93ae76d4338898d99ab484ebd72f99de18d4d659b6ce030e`，Order 仓本地 commit `34fcc66`。
- **新 Trade 镜像：** `local/otc-t361-tradesvr:common-home-canary`，镜像 SHA256 `413c669c4590654b124d03a66a72a0913a600dfec9f764d91fd9f0f7de27f57b`，Trade 仓本地 commit `441e39e`。
- Dockerfile 均继承**当前 Demo 实际运行**的 T335 Order / T336 Trade 原镜像，删除旧 classes/旧 `com.app.common`/`com.app.dc` jar，再装最新业务 classes 与本机 Maven 的唯一 Common JAR。通过实际 `docker run --rm --entrypoint sh` **镜像内部**验证 4 个关键路径：两者各一份 Common JAR，最新 Order/Trade Spring NodeRuntime classes 均存在。`dc.release.gate=CANARY-NO-GO` 不允许宣称已生产 READY。

## 已准备但尚未应用的全新数据部署

- `compose.t361-fresh-common-home.yaml`（部署仓库本地 commit `3711e60`）使用新的 `t361-fresh` Order A/B、Trade A/B 业务 WAL 目录、`t361-fresh-mysql`、`t361-fresh-clickhouse`，继续以原 T318 **真正双 RSA 签名**的 Genesis / E2 READY 只读出生材料启动。保留旧 T330 和 P193 A22667/B22668 未认证尾部，不覆盖也不把 B 的未签 `STATE_REMOVE` 当已成交。
- 现有 Compose 的 B 节点依赖 `order-cluster` 和 `trade-cluster` profiles；首次只读配置检查因未激活这两个 profiles 没显示 B；其所需 T329 签名出生材料路径来自部署环境。尝试创建新的 `.env.t361.paths` 文件被 WebCodex 的 `policy_rejected` 明确拒绝，**没有改写任何敏感 .env 文件或规避此拦截**。整个 Compose 新旧路径和四服务最终配置尚未完成校验，故**没有对线上容器强行执行 `up --force-recreate`**。
- 当前真实容器 Order A/B 仍 `local/otc-t335-ordersvr:partial-cancel`，Trade A/B 仍 `local/otc-t336-tradesvr:signed-leverage-cancel`，运行中；Robot `dc-saas-robotsvr` 仍 `Exited (143)`。只读日志确认 Order 盘口/成交长期无新增，Robot 之前双租户报价清理 ERROR，不应启动 Robot 冒险扩大 P193 未认证尾部业务写入。

## 尚未完成的上线门禁与下一执行入口

1. 用受支持的部署权限将 Compose 所需的**实际出生材料环境**绑定到已校验的 T361 新根并启用 `order-cluster`、`trade-cluster`，运行只读 `config` 验证四个服务 dataRoot、MySQL/ClickHouse volume 均为 t361，签名 RSA/FirstReady 仍来自 T318 真正原始文件，而不是人工造证。
2. 仅在配置核验通过后分批启用新镜像并走 Order/Trade Spring Common 注册、256 分区原始双签 READY 和业务回放；Gateway 仍透传。新租户通过 Manager 真实自动审批，独立 Maker/Tape 入金和用户 API Key，Robot 开启后检查真实 `RUNNING`、盘口持续、Tape/实下单真实成交、余额/持仓/委托不变量。
3. 真正 HA 仍缺 `OrderCommonNodeRuntimeWiring`/`TradeCommonNodeRuntimeWiring` 将 Common `armAutomaticHomePhysicalRecoveryWatch`、signed Stage、实际旧主物理退休签名与双新 Epoch 恢复 RSA receipt/READY 连接为常驻生命周期；当前仅由 `CommonCertifiedNodeBootstrap.openAndStartWithZkFencingAndReplay` 初始化运行时。不能以本地 Common tests 代替真正两节点 SIGKILL、128/128 Home 回切、总时长 P99 实测。
4. T318/T329 证明历史 E1→E2 真实 Genesis 和曾经的新租户审批、两独立交易员入金流程有效，但 T361 **本轮没有重跑真实业务验收**。旧 Demo P193 的财务 Saga 部分已签 Trade 释放不能重复执行。外部 Binance Futures 行情曾遇到 451/超时，恢复 Robot 报价需要真实新鲜市场行情或已验收的租户自定义价格来源，不能伪造行情。

**结论：新版本镜像本地已就绪，未替换正式 Order/Trade，Robot 未恢复。所有以上的测试、镜像、文件和源代码提交只在 Mac 本地，未使用 GitHub Actions。**