# dc-quant-deploy

DC Quant 是一套单机 Docker Compose 部署的量化策略系统，覆盖策略采集、策略生成、回测优化、自动上线、实盘运行、日末复盘、系统日报和运行报告。

English documentation: [README.en.md](README.en.md)

## 这是什么系统

系统由多个服务协作完成完整策略生命周期：

```text
策略采集/生成 -> 回测优化 -> 自动上线 -> 实盘运行 -> 日末复盘 -> 系统报告
```

## 5 分钟架构图

```mermaid
flowchart LR
  User[用户 / 第三方系统] -->|HTTP / MCP / API key| GW[GW<br/>统一入口]
  Web[Web 页面] --> GW

  GW -->|策略生成请求| IND[INDSvr<br/>策略采集 / 生成 / 编译]
  IND --> Candidate[(strategy_candidate)]
  IND --> BacktestTask[(strategy_backtest_task)]

  BacktestTask --> SIM[SIMSvr<br/>Walk-forward 回测 / 参数优化]
  SIM --> Result[(backtest_result)]
  SIM -->|通过自动发布门槛| Live[(strategy_live_registry)]

  Live --> Quant[QuantSvr<br/>EMS + Risk + Telegram]
  GW -->|pubSignal / sendMsg| Quant
  Quant --> Signal[(signal)]
  Quant --> Order[(quant_order / quant_trade / position)]
  Quant --> TG[Telegram<br/>策略 UI / 群消息]

  Batch[BatchSvr<br/>日报 / 运行报告] --> Reports[(system reports)]
  Quant --> Review[(daily review)]

  MD[MDSvr<br/>行情支撑] --> Quant
  APS[APSSvr<br/>账户交易支撑] --> Quant

  Candidate --> CH[(ClickHouse)]
  BacktestTask --> CH
  Result --> CH
  Live --> CH
  Signal --> CH
  Order --> CH
  Reports --> CH
  Review --> CH
```

核心服务：

- `GW`：统一 HTTP/MCP/API key 入口。
- `INDSvr`：策略采集、策略生成、候选策略和编译。
- `SIMSvr`：walk-forward 回测、参数优化和自动发布。
- `QuantSvr`：类似 `EMS + Risk + Telegram` 的组合，负责实盘执行、风控参数、下单、通知和日末复盘。
- `BatchSvr`：系统日报、运行报告和批处理。
- `MDSvr/APSSvr`：行情与交易账户相关运行支撑。
- `Web`：页面入口。
- `ClickHouse`：策略、信号、订单、成交、回测和报告数据存储。

更完整的说明见：[系统总览](docs/02-architecture/system-overview.zh-CN.md)。

## 快速部署

机器默认要求：

- 内存 >= 8192 MB
- `${DEPLOY_ROOT}` 可用磁盘 >= 20 GB

从空服务器部署，使用内置 ClickHouse：

```bash
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
sudo ./prepare-host.sh
./deploy-standalone.sh
```

使用已有 ClickHouse：

```bash
git clone https://github.com/bliplink/dc-quant-deploy.git
cd dc-quant-deploy
sudo ./prepare-host.sh
cp .env.external-clickhouse.example .env.prod
vi .env.prod
./deploy-with-external-clickhouse.sh
```

`prepare-host.sh` 会幂等安装并验证 Docker Engine、Buildx、Docker Compose v2
和 Docker 开机自启，支持 Amazon Linux 2/2023、CentOS/RHEL/Rocky/AlmaLinux
与 Ubuntu/Debian。
对于已停止官方维护的 EL7/CentOS 7，脚本固定安装该仓库最后发布的
Docker CE 26.1.4 和 Compose 2.27.1，并自动使用 CentOS 7.9.2009
归档源与 EL7 Docker CE 镜像源解决官方镜像下线或网络不可达问题，不会
错误尝试新版本。内置 ClickHouse 默认通过可配置的
`CLICKHOUSE_IMAGE_REPOSITORY` 镜像代理拉取；如环境可直连 Docker Hub，
可将其改为 `clickhouse/clickhouse-server`。
仅检查现有环境可运行 `sudo ./prepare-host.sh --check`；如需让普通用户执行
Docker，可显式传入 `--docker-user USER`，该权限等同于宿主机 root 权限。

对于全新 EL7/XFS 主机，如果旧内核迫使 Docker 使用 `vfs` 存储驱动，
主机准备脚本会在 `/opt/sumscope` 是独立挂载盘时自动使用
`/opt/sumscope/docker-data`。也可以通过
`DOCKER_DATA_ROOT=/更大的目录` 显式指定。脚本不会自动迁移已有 Docker
容器、镜像，也不会覆盖已有 `/etc/docker/daemon.json`。由于 `vfs` 会复制
镜像层而不是共享镜像层，完整部署要求 Docker 数据根至少有 120GB 可用空间。

如果要在独立机器只部署部分服务，先配置外部 ClickHouse、ZooKeeper 和
`control.prod/dc.dat`，然后运行：

```bash
./deploy.sh --services apssvr,quantsvr
```

定向部署会复用完整部署相同的配置生成、备份和运行校验，但使用
`--no-deps`，不会在该机器自动启动 ZooKeeper、ClickHouse 或其他业务服务。
对于不依赖 ClickHouse 且使用 `RegisterEnable=0` 固定地址模式的 APSSvr，
空机可直接执行：

```bash
./deploy.sh --services apssvr
```

部署仓库已包含可公开分发的试用 `control.prod/dc.dat`。脚本会自动安装
Docker、复制并校验试用许可证、补齐首次部署配置、创建挂载目录，并且只
启动 APSSvr。正式环境可在部署前替换 `control.prod/dc.dat`；缺少内置文件时
也可以使用 `--license-url HTTPS_URL` 下载许可证。空文件或占位许可证会在
启动容器前被明确拒绝，避免服务进入反复重启状态。定向部署默认按
`MIN_SELECTED_MEMORY_MB=1024`、`MIN_SELECTED_DISK_GB=5` 校验宿主机，
不会套用完整系统的 8GB/20GB 门槛；部署高内存服务时可在 `.env.prod`
覆盖这两个值。配置同步会保留宿主机 `control` 挂载根目录和已有运行时
`overrides`，定向部署只重建所选容器，避免在线绑定挂载失效。
如果是空机验证，希望只部署指定业务服务并自动带起必要的本机基础设施，
可直接运行：

```bash
./deploy.sh --services loginsvr --with-deps
```

该命令会在缺少 Docker 时自动执行主机准备，自动生成首次部署所需的
`.env.prod` 和 `control.prod` 默认文件，只启动 LoginSvr 和 ClickHouse，
不会启动其他业务服务。默认 LoginSvr 使用
`SERVER.LoginSvr.RegisterEnable=0` 固定地址模式，因此不会安装或启动
ZooKeeper；只有所选服务明确配置 `RegisterEnable=1` 时才会带起 ZooKeeper。

部署脚本会自动创建 `${DEPLOY_ROOT}/control`、`${DEPLOY_ROOT}/data`、
`${DEPLOY_ROOT}/log` 及各 Java 服务的偏好目录，不需要手工预建。
`control` 以只读方式挂载到容器，`data`、`log` 和 Java 偏好目录按
`RUNTIME_UID:RUNTIME_GID` 设置为可写；脚本不会递归修改已有业务数据的归属。

部署后验证：

```bash
./validate.sh
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml ps
curl -I http://127.0.0.1/web/
curl 'http://127.0.0.1:8123/?query=SELECT%201'
```

部署完成后的第一步见：[部署后快速开始](docs/01-getting-started/quick-start-after-deploy.zh-CN.md)。

## 部署后安全加固

安全加固是独立运维步骤，不会随一键部署自动执行。确认系统部署成功后，再执行：

```bash
sudo ./security/harden-host.sh
sudo ./security/validate-host-security.sh
```

如果需要回滚主机安全策略：

```bash
sudo ./security/rollback-host-security.sh
```

加固脚本会禁用宿主机 `nginx`，保留 `dc-web` 容器对外服务；默认只放行 SSH、Web、GW 和 ClickHouse 外部代理端口。生产如果 SSH 不是 `22`，先在 `.env.prod` 中设置 `PUBLIC_SSH_PORT`。

## 必填运行参数

默认一键部署可以先拉起系统骨架。要启用 Telegram 和 DeepSeek 能力，用户需要在 `.env.prod` 中自行提供：

```bash
QUANTSVR_BOT_TOKEN=
QUANTSVR_BOT_USERNAME=
QUANTSVR_BOT_GROUP_ID=
QUANTSVR_BOT_ADMIN_LIST=
INDSVR_DEEPSEEK_API_KEY=
```

说明：

- `QUANTSVR_ENABLE_BOT` 可留空；填写 `QUANTSVR_BOT_TOKEN` 后部署脚本会自动启用 Telegram bot。
- 如果要强制关闭 Telegram bot，可在 `.env.prod` 中设置 `QUANTSVR_ENABLE_BOT=false`。
- `QUANTSVR_BOT_ADMIN_LIST` 使用 `|` 分隔多个管理员 ID，并给完整值加引号，例如 `QUANTSVR_BOT_ADMIN_LIST='123|456'`。
- GW 内部密码无需用户配置。
- 修改 `.env.prod` 后，需要重启对应服务。

## 部署后如何使用

主要入口：

- 使用 `GW` 的 MCP/API 入口提交外部信号或消息。
- 使用 `INDSvr` 创建或导入策略，生成 candidate。
- 使用 `SIMSvr` 自动执行回测、参数优化和上线判断。
- 使用 `QuantSvr` 运行已上线策略并生成日末复盘。
- 使用 `BatchSvr` 查看每日系统报告和 5 分钟运行报告。

完整使用说明见：[用户使用手册](docs/03-user-guide/user-guide.zh-CN.md)。

## 核心文档

- [文档中心](docs/README.zh-CN.md)
- [系统总览](docs/02-architecture/system-overview.zh-CN.md)
- [部署后快速开始](docs/01-getting-started/quick-start-after-deploy.zh-CN.md)
- [用户使用手册](docs/03-user-guide/user-guide.zh-CN.md)
- [核心流程](docs/02-architecture/flows.zh-CN.md)
- [MCP 接口](docs/04-reference/mcp-api.zh-CN.md)
- [QuantSvr 风控与 Telegram](docs/03-user-guide/quantsvr-risk-telegram.zh-CN.md)
- [核心数据表](docs/04-reference/data-model.zh-CN.md)
- [报告与排障](docs/05-operations/reports-and-troubleshooting.zh-CN.md)
- [安全说明](docs/05-operations/security.zh-CN.md)

## 常用运维

重启单个服务：

```bash
./restart-service.sh quantsvr
```

升级单个服务镜像：

```bash
vi .env.prod
docker compose --env-file .env.prod -f compose.yaml -f compose.override.generated.yaml pull quantsvr
./restart-service.sh quantsvr
```

查看日志：

```bash
docker logs dc-quantsvr --tail 200
tail -n 100 ${DEPLOY_ROOT}/log/QuantSvr.log
```

全量部署失败后回滚：

```bash
./rollback.sh
```

## 安全提醒

- 不要提交 `.env.prod`。
- 不要提交真实 API key、Telegram token、ClickHouse 生产密码。
- QuantSvr、INDSvr 的 bot/API key 只维护在 `.env.prod`，部署脚本会生成 `control/overrides/<Service>/config/application.properties` 并挂载到容器。
- 用户需要自行提供 `QUANTSVR_BOT_TOKEN`、`QUANTSVR_BOT_USERNAME`、`QUANTSVR_BOT_GROUP_ID`、`QUANTSVR_BOT_ADMIN_LIST`、`INDSVR_DEEPSEEK_API_KEY`。
- APSSvr 默认不需要外部 API key，相关交易所/BirdEye 开关默认关闭。
- 更新 `.env.prod` 后，重启对应服务让新配置生效。
- `control.prod.example/` 只放示例配置。
- 对外开放 MCP 前必须替换 `apiKeyList.csv` 中的示例 key。

许可证：Apache-2.0，详见 [LICENSE](LICENSE)。
