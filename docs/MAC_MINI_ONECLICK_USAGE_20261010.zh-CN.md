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
