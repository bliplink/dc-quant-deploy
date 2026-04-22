# 系统总览

DC Quant 是一套围绕量化策略全生命周期设计的运行系统。它不是单一交易机器人，而是把策略采集、策略生成、回测优化、上线、实盘运行、复盘和系统报告串成一条完整链路。

## 系统能做什么

- 采集外部策略素材或信号来源。
- 生成候选策略，并编译成可运行版本。
- 对候选策略执行 walk-forward 回测和参数优化。
- 根据回测结果自动判断是否上线。
- 在实盘运行中消费信号、下单、记录成交和持仓。
- 每日对信号、订单、成交、持仓做复盘。
- 生成系统日报和运行报告，帮助运维快速了解当前状态。

## 服务职责

| 服务 | 职责 |
| --- | --- |
| `GW` | 统一 HTTP/MCP 入口，负责 API key 鉴权、工具转发和外部调用接入。 |
| `INDSvr` | 策略采集、策略生成、候选策略、编译和生成状态管理。 |
| `SIMSvr` | 策略回测、walk-forward、参数优化、回测报告和自动发布。 |
| `QuantSvr` | 实盘策略运行、信号消费、订单执行、Telegram 通知、日末复盘。 |
| `BatchSvr` | 系统日报、5 分钟运行报告、批处理任务。 |
| `MDSvr` | 行情相关支撑服务。 |
| `APSSvr` | 账户、交易、外部交易所相关支撑服务。 |
| `Web` | 页面入口。 |
| `Zookeeper` | 服务注册和发现。 |
| `ClickHouse` | 策略、信号、订单、成交、回测和报告数据存储。 |

## 部署形态

本仓库提供单机 Docker Compose 部署方式。运行时主要目录为：

```text
${DEPLOY_ROOT}/control
${DEPLOY_ROOT}/data
${DEPLOY_ROOT}/log
```

默认支持两种 ClickHouse 模式：

- `embedded`：由本仓库一起启动 ClickHouse。
- `external`：使用已有 ClickHouse，只做连通性和 schema 检查。

## 核心链路

```text
策略采集/生成:
GW/API -> INDSvr -> strategy_generation_task -> strategy_candidate -> strategy_backtest_task

回测上线:
SIMSvr -> backtest_result -> backtest_optimization_trial -> strategy_live_registry

实盘运行:
strategy_live_registry -> QuantSvr -> signal -> quant_order -> quant_trade

报告复盘:
QuantSvr/BatchSvr -> ClickHouse -> JSON/HTML 报告
```

部署完成后，建议先阅读：

- [部署后快速开始](quick-start-after-deploy.zh-CN.md)
- [用户使用手册](user-guide.zh-CN.md)
- [核心流程](flows.zh-CN.md)
