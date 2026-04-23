# 安全说明

本仓库面向开源部署使用，只应包含可公开的部署脚本、示例配置和说明文档。

## 部署后主机加固

主机防火墙和公网端口收敛由独立脚本处理，不会随一键部署自动执行：

```bash
sudo ./security/harden-host.sh
sudo ./security/validate-host-security.sh
```

回滚主机安全策略：

```bash
sudo ./security/rollback-host-security.sh
```

默认策略：

- 禁用宿主机 `nginx`，Web 由 `dc-web` 容器提供。
- 只放行 SSH、`80`、`3000/3001/3002`、`28123`。
- 不直接开放 `8123/9000/2181/Java` 内部端口。
- 执行安全加固前会创建短时间自动回滚 timer，避免 SSH 误锁。

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
- 用户需要自行提供 `QUANTSVR_BOT_TOKEN`、`QUANTSVR_BOT_USERNAME`、`QUANTSVR_BOT_GROUP_ID`、`QUANTSVR_BOT_ADMIN_LIST`、`INDSVR_DEEPSEEK_API_KEY`。
- `QUANTSVR_ENABLE_BOT` 可留空；填写 `QUANTSVR_BOT_TOKEN` 后部署脚本会自动启用 Telegram bot。
- GW 内部密码无需用户配置。
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
