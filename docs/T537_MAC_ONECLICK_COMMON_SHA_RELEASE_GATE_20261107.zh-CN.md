# T537｜Mac 一键部署 Common JAR 一致性门禁与当前业务阻塞（2026-11-07）

## 本轮判定

**Mac 部署入口的非破坏性测试 PASS；部署镜像身份检查缺陷已修复并回归 PASS。生产 Order/Trade 自动 HA 和真实业务闭环仍 NO-GO。**

此次只检查 Mac 上的现有 Docker、脚本及相关 Common 源码，未停止容器、未清理卷、未执行 SIGKILL、未部署新业务镜像、未调用 GitHub Actions。

## 已确认的 Mac 正式入口

- 主仓 `mac-colima-saas.sh` 包装 Colima 中的 `install-saas.sh` / `deploy-saas.sh`，提供 `status|forward|install|uninstall|reinstall|acceptance`。禁止其管理宿主 v2ray/xray。
- `./mac-colima-saas.sh status` 实测 Trade 18088、Platform 18090、Tenant 18092 的 `/healthz` 均为 READY。
- `bash -n install-saas.sh deploy-saas.sh mac-colima-saas.sh`、`docker compose --env-file .env.prod -f compose.yaml config -q` 均通过。
- 根目录当前**没有**受 Git 跟踪的 `deploy-saas-macos.sh`；此名称在旧 `.work/*` 导出副本里存在，不能直接误当成当前正式部署入口，不能因此重新造独立部署系统。

## 版本漂移的实际证据

2026-11-07 本机只读 Docker `sha256sum` 核验：
- `otc-t531-order-{a,b}-e2-abcontrol` 的 `com.app.common-t520-common-only.jar`：`b170df0dffd6d8cbeeb64ff3ac9865fe5a89aa803d49580bf0d78eae123801b2`。
- `otc-t532-trade-{a,b}-e2-ready` 的同一 Common JAR：同为 `b170df0dffd6d8cbeeb64ff3ac9865fe5a89aa803d49580bf0d78eae123801b2`。
- T526 已完成 Demo+Common 114/114 HA 回归的 JAR：`~/.opentradingcore/t526-build-20261106/t526-common-all-main.jar`，实际 SHA：`f08c59a291849b6c3bb635bc451a2706642af8e017d90381749af4d21dcb433a`。

四个业务节点**彼此一致，但不是 T526 新候选**。不应把旧版业务 JVM UP 当成最新 Common 生产自动 HA 已生效。

## 确定的部署脚本缺陷与修复

原 `deploy-saas.sh` 的 `verify_order_cluster_images`、`verify_md_cluster_images` 仅验证 Common SHA 标签形状与 revision 相同，**没有比较 SHA 内容**；而 Trade 集群缺少对应的镜像 Common 身份比对。

本轮修改：
1. Order 和 MD 对 Gateway 的 Common JAR SHA256 进行逐值相等检查，revision 仍必须相等。
2. 新增 `verify_trade_cluster_images`，在 `TRADE_CLUSTER_ENABLED=true` 时对 Gateway 与 Trade 执行完全相同的 Common revision+SHA 校验。
3. 在业务容器启动之前完成三类镜像身份检查；版本混用立即 fail-closed。
4. 新增 `tests/test-deploy-common-image-parity.sh`，采用只在测试进程中生效的 Docker 标签模拟，验证一致接受，Order/MD/Trade SHA 冲突、Trade revision 冲突、缺少 SHA 均拒绝，不接触真实 Docker。
5. 将回归测试接入 `tests/test-mac-colima-saas.sh`。

本轮实测：`bash tests/test-deploy-common-image-parity.sh` PASS，`bash tests/test-mac-colima-saas.sh` PASS，`bash tests/test-auto-update-saas.sh` PASS，`git diff --check` PASS。

**边界**：镜像 label 一致不自动证明文件内容一致，正式发版仍应读取容器中的 Common JAR SHA；更不代表 Spring Bean、256 分区自动恢复与真实业务都已通过。

## Common 生产自动恢复尚未打通的代码证据

T526 Common 工作树 `~/.opentradingcore/t525-common-latest-20261106` 的 `src/main/java/com/app/common/replication/CommonCertifiedProductionPhysicalRecovery.java` 中：

- `OriginalE1` 构造器仍硬性要求 `prior.epoch==1`。
- `originalE1FromPersistedHome` 固定建立 E1 的 128 分区证据。
- `verifiedPlans` 读取当前 256 分区 ZK census，但 `installedEpochs` 仍取旧 `OriginalE1` 的 epoch；对于当前 E2 Replica 会在创建 Watch 之前正确拒绝旧证明。
- `evidence` 仅接受 `a.getEpoch()==1`；恢复/READY 只放行 E1→E2。
- `requireRecovered` 仍明确拒绝尚无双 RSA 新 Epoch 物理收据的 STRICT READY。

T526 已泛化的是已认证原始 Genesis/WAL 的**业务恢复安装器**，不是生产 256 分区当前 Epoch 自动 PlanFactory 的全部装配。不能通过关闭门禁、复用旧 E1 证书或强制替换 JAR 来冒充 STRICT HA 通过。

## 下次一键部署及验收的硬门禁

- 继续在 **Common-only** 接通当前 Epoch 原始双物理 RSA/Snapshot/WAL/CommitIndex/Custody 的生产自动物理 Plan；先完成 Demo+Common 的严格及 LOCAL 模式明确区分的双向切换，拒绝假 READY。
- 按同一编译证据及 SHA 构建 Gateway/Order/Trade/MD 镜像，先过 `deploy-saas.sh` 全量镜像检查，再读容器内 Common JAR 校验，不能仅看标签。
- 复用 Mac 现有 `mac-colima-saas.sh` 和统一部署脚本，验证新租户自动审批、Robot 报价/Tape 成交、Order/Trade A/B 自动互切、资金持仓/委托成交/Projection 一致。
- 当前主仓工作区 `saas-crypto-latest` 与 `origin/saas-crypto-latest` 存在本地 7 个独有提交、远端 138 个独有提交，且有大量未提交文件；发布前必须使用独立干净 worktree/按目标 diff 审核，不允许强推、reset 或覆盖既有现场。

## 与 T528 的部署模式约束配合

正式一键部署必须先明确且记录唯一模式：`UPGRADE`（有旧数据的滚动升级）或 `FRESH`（新命名空间/空业务数据，旧消费者与 Projection 水位隔离）。按 AGENTS/T528 的约定执行 `tests/check_common_upgrade_continuity.py` 只读检查；该门禁与本次 Common 镜像 SHA 相等检查是**互补关系**，均不能被容器 UP 替代。未指定可信模式或检查返回 NO-GO 时，不进行后续旧节点替换。

远端 `origin/saas-crypto-latest` 现有 `tests/test-auto-update-saas.sh` 仍按旧文案断言 “restarting OrderSvr cluster and TradeSvr”，而实际 `tests/recover-order-cluster-partitions-host.sh` 已在确认 fence 后先重启 Order replicas，再重启 Trade A/B，并记录 “restarting OrderSvr replicas before TradeSvr”。因此干净远端基线的静态测试先失败；本轮仅同步该一条断言到实际顺序，没有改动重启逻辑或放宽 fence。

**当前结论：部署门禁修复 PASS，生产业务 HA NO-GO。**