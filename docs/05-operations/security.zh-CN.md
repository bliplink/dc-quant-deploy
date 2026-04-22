# 安全说明

本仓库面向开源部署使用，只应包含可公开的部署脚本、示例配置和说明文档。

## 不要提交的内容

- `.env.prod`
- 真实 API key
- Telegram bot token
- Telegram 群号等敏感运行配置
- ClickHouse 生产用户名、密码、地址
- 交易所 API key、secret
- 真实订单、成交、账户、持仓数据
- 生产日志、备份文件、运行报告中的敏感信息

## 示例配置规则

- 示例密钥统一使用 `replace-with-*`、`change-me`、`example-*`。
- `control.prod.example/` 只能放脱敏示例。
- 对外开放 MCP 前，必须启用 `GW` API key 检查。
- `apiKeyList.csv` 中的示例 key 仅用于说明格式，不能用于生产。


## 运行时敏感配置

- QuantSvr、INDSvr 的 bot/API key 只维护在 `.env.prod`。
- APSSvr 默认不需要外部 API key，交易所/BirdEye 开关默认关闭。
- 部署脚本会生成 `control/overrides/<Service>/config/application.properties`。
- 生成的 override 文件属于本地运行产物，不提交 Git。
- 修改 `.env.prod` 后，需要重启对应服务。

## MCP 暴露建议

- 只开放确实需要给第三方使用的工具。
- 给不同第三方分配不同 API key，便于后续吊销。
- 外部网络访问建议加防火墙、反向代理或 VPN。
- `pubSignal` 会影响实盘策略行为，接入前必须确认调用方可信。
- `sendMsg` 会直接发 Telegram 群消息，建议限制频率，避免刷屏。

## 数据库安全

- 不建议把 ClickHouse 直接暴露到公网。
- 对只读查询、写入任务、运维管理使用不同账号。
- 初始化脚本中的示例账号密码上线前必须替换。
- 备份文件不要提交到 Git。

## 报告与日志

系统报告、回测报告、交易日志可能包含策略名、交易品种、价格、订单信息和账户信息。开源仓库中只放模板或脱敏示例，不放真实报告。

## 发现安全问题

如果你发现安全问题，请优先使用 GitHub Security Advisory 或仓库维护者提供的私有联系方式反馈。不要在公开 issue 中粘贴真实密钥、生产地址或可利用细节。
