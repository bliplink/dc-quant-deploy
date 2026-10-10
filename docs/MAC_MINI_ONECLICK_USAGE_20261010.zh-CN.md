# Mac mini / Colima 一键部署（2026-10-10）

现有脚本保留，无需另起安装工程：`deploy-saas-macos.sh` 是 **macOS 宿主机调用的正式入口**，自动兼容 Docker context 指向 Colima 或 Docker Desktop，内部使用 `deploy-saas.sh` 初始化和验收。

## 已完成的升级

- macOS 不必安装 GNU `flock`：使用原子 `mkdir` 的独立部署锁，覆盖**整个**环境文件修改、配置、镜像拉取及子部署流程；子脚本失败时清理自有锁。**遇到现有锁禁止自行删除，必须确认进程状态。** Mac 入口调用主部署时明确标记已经持锁，不再出现“声明持锁但实际未加锁”的竞态。
- 新增 `--check`：只读检测 Docker 引擎、Compose 解析及 Mac Docker context。`--check --full-cluster` 显式验证 Order A/B/C、MD A/B/C 和 Trade A/B 5 个 Profile，不运行任何配置覆写、容器创建、数据清理或镜像拉取；如果已存在 `dc-saas-*` 容器，提示必须先处理镜像/Compose 配置漂移。**只读检查通过并不代表允许滚动升级。**
- 发布锁中的 `ORDERSVR_TAG` 从 `sha-26b01eb` 升至 `sha-7842df4`（已成功完成 OrderSvr GitHub Actions 构建，包含 P246 修复和写入排空基础组件）。其余服务继续使用各自固定 GHCR SHA；不可假设全部已经是最新源码镜像。
- `tests/test_deploy_saas_macos.py` 用伪造 macOS 命令及 Docker 验证 8 项入口行为：只读检查不更改 `.env`、完整 Cluster Profile、禁止未知参数、锁内拒绝并发、正常 child/失败 child 释放锁、Docker 不可用时拒绝、Compose 不完整时拒绝。

## 安全的检查命令（在 Mac 宿主机运行）

```bash
cd /Users/kong/dc-quant-deploy
ENV_FILE="$PWD/.env.prod" ./deploy-saas-macos.sh --check --full-cluster
```

此命令**不会**安装、重启或删除任何容器。确定新部署环境时，使用独立且权限为 `0600` 的 `.env` 文件，并通过变量 `MACOS_DEPLOY_ROOT` / `MACOS_BUILD_ROOT` 指定 macOS 用户可写的隔离目录；不要将凭据文件或真实 URL 直接提交 GitHub。

一键正式安装入口仍为：

```bash
ENV_FILE="$PWD/.env.prod" ./deploy-saas-macos.sh --full-cluster
```

**注意：当前 Mac mini 已经运行 OrderSvr A/B/C，与发布锁指定镜像不同。** 由于同步副本 ACK 和 P246 GAP 问题，`deploy-saas.sh` 内现有的镜像/Compose 漂移防护会阻止普通热更新。不得绕过这些保护。

## 现有 `mac-colima-saas.sh` 的用途

该早期辅助脚本通过 Colima SSH + Linux VM 内 `sudo` 来运行 `install-saas.sh` / `uninstall-saas.sh`，并管理三个 Web SSH 端口转发。它是**旧环境的管理/转发工具**，不能与新的 Mac 宿主机部署入口交替执行 `reinstall`：后者可能指向不同的部署根目录，导致状态不一致。当前宿主机已经直接连接 Colima Docker context，应该统一使用 `deploy-saas-macos.sh`。

## 目前尚未完成

- 尚未添加经验证的 macOS `reset` 自动化入口。Linux `uninstall-saas.sh --purge-data` 仅允许 `/data` 或 `/opt`，不能安全删除 macOS 用户目录，亦不可简单修改其白名单绕过安全边界。
- 当前已保存 P246 样本，计划之后执行干净环境替换，但需要先完成真正的停写/重建检查和全栈新镜像拉取，并验证磁盘和 Colima Docker VM 容量。**本轮没有删除 Demo 数据或替换运行中的 OrderSvr。**
- 必须完成 Order HA 故障恢复、三副本提交水位与 Projection 对账，才可以解除面向 200 个租户的自动扩容限制。

详见 [Mac clean redeploy plan](MAC_MINI_CLEAN_REDEPLOY_PLAN_20261010.zh-CN.md) 与 [P246 recovery issue](ORDER_HA_P246_RECOVERY_BLOCKER_20261010.md)。

## 2026-10-10：只读重置计划与受控旧数据隔离

已增加 `scripts/mac-saas-reset.py`，由 `deploy-saas-macos.sh reset` 统一调用：

```bash
./deploy-saas-macos.sh reset \
  --mode plan \
  --runtime-root "$HOME/.opentradingcore/dc-saas-runtime-fresh2-20261005" \
  --evidence "$HOME/.opentradingcore/evidence/p246-reproducer-20261010/P246-primary-archived-commit.tar.gz"
```

**`plan` 是默认且只读的模式**，验证 P246 文件 SHA-256、运行目录限定在 `~/.opentradingcore/dc-saas-runtime-*`、全部订单服务的 Compose 项目归属与根目录 bind mount，并检查是否有独立的容器借用了 SaaS 根目录。当前现网 `plan` 已检测到 **24 个 `dc-saas` Compose 成员**，以及唯一一台 Playwright 浏览器测试 Runner。只有镜像为 `mcr.microsoft.com/playwright:v1.55.0-noble`、名称严格等于 `dc-saas-web-e2e-runner`、且唯一运行目录挂载为 `e2e-artifacts:/artifacts` 时，才会将其作为可停止的测试进程。**独立 API Docs 不属于重置范围。**

真正的受控冷重置（会造成业务中断）要求显式选择 `--mode stage --confirm STAGE_DISPOSABLE_DC_SAAS`。该动作在 Mac 原子目录锁内重新核对 Docker 容器归属，只停止和移除确认归属的旧 `dc-saas` Compose 成员及上述验明身份的临时 Runner，然后将旧数据目录**原子迁移到 `~/.opentradingcore/.dc-saas-quarantine/`**；不运行递归删除、不清空镜像、不触碰独立文档、不开启新集群。如果期间校验不通过，则中止并保留故障现场。旧目录在新集群通过验收后，才考虑另行回收，不能把 `stage` 误认为已释放约 120 GB 空间。

**当前还没有执行 `stage`：**Mac 磁盘约 93% 使用率，旧运行目录约 120 GB。P246 归档及其快照已经独立保存在 `~/.opentradingcore/evidence/p246-reproducer-20261010/`，而正式安装应使用现有 `--full-cluster`。由于需要 22 服务冷启动、云端镜像拉取、密钥初始化和容量保护，必须在后续完成带自动业务验收的重建流程后再执行停机；不能用只读计划冒充成功重装。

相关自动化：`tests/test_mac_saas_reset.py` 与 `tests/test_deploy_saas_macos.py`，由 `.github/workflows/validate-macos-cold-reset.yml` 持续验证。

## 2026-10-10：新集群上线后的隔离数据空间回收

新集群已从空数据启动并经过部署程序验收：**24 个 Compose 容器运行、Order 256/256 READY、Trade 256/256 READY、4 个 Web 端口 HTTP 200**。新运行目录：`~/.opentradingcore/dc-saas-runtime-clean-20261010`；旧约 120 GB 运行目录已通过受控 `reset --mode stage` 迁至 `~/.opentradingcore/.dc-saas-quarantine/dc-saas-runtime-fresh2-20261005-20261010T064806Z`。

现在新增**独立且默认只读**的旧目录回收工具 `scripts/mac-saas-purge-quarantine.py`，也能通过 `deploy-saas-macos.sh purge` 调用。它只有在以下条件全部满足时，才允许显式选择 `--mode execute`：旧目录必须是严格命名的私有 quarantine 子目录；新根目录必须位于 `~/.opentradingcore` 且完全独立；P246 备份 SHA-256 无变化；新 24 个容器运行，Order、Trade 和 Robot 镜像与已验收版本逐一匹配；MySQL/ZK/Order 确实挂载新目录；**全部 Docker 容器（包括已停止的容器）均未引用旧目录**；四个本机 Web 入口均 HTTP 200。任何一项失败都禁止永久删除。

只读计划（不删除任何文件）：

```bash
./deploy-saas-macos.sh purge --mode plan \
  --quarantine "$HOME/.opentradingcore/.dc-saas-quarantine/dc-saas-runtime-fresh2-20261005-20261010T064806Z" \
  --new-runtime "$HOME/.opentradingcore/dc-saas-runtime-clean-20261010" \
  --evidence "$HOME/.opentradingcore/evidence/p246-reproducer-20261010/P246-primary-archived-commit.tar.gz"
```

**永久删除必须另外显式提供** `--mode execute --confirm PURGE_ONLY_QUARANTINED_OLD_DC_SAAS`。它会在复查所有条件并获得 Mac 安装互斥锁后才递归删除**这一份旧隔离目录**，不对 API Docs 备份、GitHub 代码、P246 证据或新的 MySQL/Order 数据做任何操作。隔离数据被永久清理后就无法使用它执行旧环境回滚，故只在用户确认 Demo 旧数据没有业务价值且基本健康验收通过后执行。**这项回收不代表自动 WAL 生命周期 GC 已完成**；后者仍需副本提交水位、Projection 持久化和异地可恢复备份证明。
