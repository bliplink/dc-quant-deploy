# SaaS 公共镜像自动部署

## 目标

部署机定时检查 `.env.prod` 中配置的 SaaS 应用镜像标签。默认标签是独立的 `saas-crypto`；如果后续统一改成 `latest`，脚本无需修改，只需调整对应 `*_TAG`。

自动任务不更新 MySQL、ClickHouse、ZooKeeper 等基础设施固定版本，也不会接触独立量化系统或 `/opt/sumscope`。

## 与量化自动更新的区别

量化系统可以逐服务比较运行容器和最新镜像后重启。SaaS 的 OrderSvr、TradeSvr、AdminSvr 等会共享公共协议并依赖数据库迁移，因此这里按一个完整发布批次处理：

1. 通过 GHCR Registry API 读取十个应用标签的 manifest digest，不下载镜像层。
2. digest 集合保持稳定达到安静窗口后，才认为同批 GitHub Actions 已构建完成。
3. 先快进部署仓库，确保数据库迁移和镜像版本同步。
4. 仅对变化或运行版本漂移的服务执行串行 `docker pull`。
5. 所有镜像拉取成功后，统一执行迁移、容器重建和完整健康检查。
6. 验证失败时，把镜像标签恢复为更新前运行容器的 image ID，再执行一次部署恢复。
7. 网络或部署失败使用指数退避，避免每个 cron 周期持续冲击 GHCR 和旧内核 `vfs` 存储。

## 安装

在 `/root/dc-saas-deploy` 执行：

```bash
sudo ./install-auto-update-cron.sh
```

默认每 5 分钟检查一次。自定义周期：

```bash
sudo ./install-auto-update-cron.sh --interval-minutes 10
```

首次安装后建议人工执行一次，建立已验证的 digest 基线：

```bash
sudo ./auto-update-saas.sh --force
```

## 状态和日志

- 日志：`/opt/dc-saas-runtime/log/auto-update-saas.log`
- 状态：`/opt/dc-saas-runtime/auto-update/`
- 最近成功发布：`last-successful.meta`
- 最近成功 digest 集合：`last-successful.digestset`
- 等待安静窗口的候选版本：`pending.digestset`
- 失败退避：`failure.state`

日志达到 10 MB 后由 `/etc/logrotate.d/dc-saas-auto-update` 轮转并压缩。

## 常用命令

```bash
# 只检查，不拉取、不改状态
sudo ./auto-update-saas.sh --dry-run

# 跳过安静窗口和失败退避，立即核对并部署
sudo ./auto-update-saas.sh --force

# 临时不更新部署 Git 仓库
sudo ./auto-update-saas.sh --force --skip-git-update

# 卸载自动任务；不影响容器和业务数据
sudo ./install-auto-update-cron.sh --remove
```

## 配置

可在 `.env.prod` 中覆盖：

```dotenv
SAAS_AUTO_UPDATE_INTERVAL_MINUTES=5
SAAS_AUTO_UPDATE_QUIET_SECONDS=300
SAAS_AUTO_UPDATE_PULL_TIMEOUT_SECONDS=600
SAAS_AUTO_UPDATE_MANIFEST_TIMEOUT_SECONDS=30
SAAS_AUTO_UPDATE_GIT_TIMEOUT_SECONDS=180
SAAS_AUTO_UPDATE_FAILURE_BACKOFF_SECONDS=600
SAAS_AUTO_UPDATE_FAILURE_MAX_BACKOFF_SECONDS=21600
SAAS_AUTO_UPDATE_DEPLOY_REPO=true
SAAS_AUTO_UPDATE_DEPLOY_BRANCH=saas-crypto
```

生产环境应保留部署仓库自动快进。若 Git 更新失败，脚本会在拉取和重启任何业务镜像前停止，避免新镜像与旧迁移脚本混用。
