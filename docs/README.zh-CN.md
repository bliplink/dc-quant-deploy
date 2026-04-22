# DC Quant 文档中心

如果你是第一次从 GitHub 打开这个项目，建议按下面顺序阅读。根目录 `README.md` 只保留项目入口和部署命令，详细说明集中在本目录。

## 新人 10 分钟路径

1. [系统总览](02-architecture/system-overview.zh-CN.md)：先理解 DC Quant 是什么、每个服务负责什么。
2. [部署后快速开始](01-getting-started/quick-start-after-deploy.zh-CN.md)：部署完成后按步骤验证服务、数据库、MCP 和 Telegram。
3. [用户使用手册](03-user-guide/user-guide.zh-CN.md)：了解策略采集、生成、回测、上线、实盘、复盘和报告怎么串起来。
4. [核心流程](02-architecture/flows.zh-CN.md)：用链路图快速定位请求和数据流向。
5. [报告与排障](05-operations/reports-and-troubleshooting.zh-CN.md)：遇到失败、没上线、没下单、MCP 不通时从这里查。

## 按角色阅读

### 部署和运维

- [部署后快速开始](01-getting-started/quick-start-after-deploy.zh-CN.md)
- [报告与排障](05-operations/reports-and-troubleshooting.zh-CN.md)
- [安全说明](05-operations/security.zh-CN.md)

### 策略使用者

- [用户使用手册](03-user-guide/user-guide.zh-CN.md)
- [QuantSvr 风控规则与 Telegram 使用说明](03-user-guide/quantsvr-risk-telegram.zh-CN.md)
- [核心流程](02-architecture/flows.zh-CN.md)

### 外部系统接入方

- [MCP 接口说明](04-reference/mcp-api.zh-CN.md)
- [QuantSvr 风控规则与 Telegram 使用说明](03-user-guide/quantsvr-risk-telegram.zh-CN.md)
- [安全说明](05-operations/security.zh-CN.md)

### 排障和二次开发

- [核心数据表](04-reference/data-model.zh-CN.md)
- [核心流程](02-architecture/flows.zh-CN.md)
- [报告与排障](05-operations/reports-and-troubleshooting.zh-CN.md)

## 目录结构

```text
docs/
  01-getting-started/   部署后第一步
  02-architecture/      系统总览和核心链路
  03-user-guide/        使用手册、QuantSvr 风控、Telegram
  04-reference/         MCP 接口、核心表
  05-operations/        报告、排障、安全
```

## 核心定位

DC Quant 是一套单机 Docker Compose 部署的量化策略系统。它覆盖：

```text
策略采集 -> 策略生成 -> 回测优化 -> 自动上线 -> 实盘运行 -> 日末复盘 -> 系统报告
```

其中 `QuantSvr` 可以理解为 `EMS + Risk + Telegram` 的组合：

- `EMS`：把信号转成订单，处理订单、成交、持仓和执行回报。
- `Risk`：在开仓前和持仓中检查仓位、亏损、滑点、止损止盈、运行状态。
- `Telegram`：提供用户 UI，用来设置 API、启动/停止策略、调整风控参数、查看运行状态和接收群消息。
