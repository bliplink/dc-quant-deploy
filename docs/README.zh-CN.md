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
- [场景、策略选择、信号与下单链路运维](05-operations/strategy-chain-health-and-gap-fill.zh-CN.md)
- [实盘策略 v4 资格门槛与持续复核](05-operations/live-strategy-v4-qualification.zh-CN.md)
- [100 条实盘策略补齐进度与研究交接](05-operations/strategy-inventory-100-progress-20261014.zh-CN.md)
- [当前补齐100条策略的持续目标与接续入口](05-operations/strategy-inventory-100-active-goal-20261110.zh-CN.md)：优先读这里确认真实合格库存、已结束批次和正在执行的工作；不调用服务端DeepSeek生成策略。
- [ADX服务器拒绝结果与本地发布前门槛复核](05-operations/true-adx-server-admission-and-strict-floor-20261110.zh-CN.md)：区分原始通过标记、本地严格资格、服务器执行成功和正式发布；保留失败与精确源码/JAR证据。
- [四档训练校验启动合并证明](05-operations/four-profile-launch-batching-20261110.zh-CN.md)：原校验器不改，8组32档训练对照一致；说明新作用域工具和在跑冻结队列的集成边界。
- [完整目录检查点安全交接及启动合并实装](05-operations/full-catalog-batched-checkpoint-handoff-20261110.zh-CN.md)：115条原结果不重放，原完整队列接入2个隔离worker；新的实时入口、OS锁与guardian恢复约束。
- [OHLCV价格分箱代理的新研究与排队入口](05-operations/ohlcv-profile-proxy-research-20261111.zh-CN.md)：一个机制组、四个工程方向，123项Java/178项Python及4份全年对照通过；200作用域先等待旧平衡批次结束，不冒充已金融通过。
- [LINK均线回调策略本地通过及服务器拒绝记录](05-operations/fit-risk-link-server-admission-20261110.zh-CN.md)：固定源码一次导入、完整365日失败、0发布，以及确定package空白差异的只读产物审计。
- [本地固定源码→回测→服务器验证工作流](05-operations/local-source-strategy-workflow-20261110.zh-CN.md)
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
- [场景、策略选择、信号与下单链路运维](05-operations/strategy-chain-health-and-gap-fill.zh-CN.md)
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

## 生产运维入口

- [生产对账、验收与会话交接](05-operations/production-reconciliation-and-handoff.zh-CN.md)：包含最近生产基线、executionID 对账补账、风控验收、日志磁盘治理和后续优先级。
