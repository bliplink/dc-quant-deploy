# Broker 代客交易 API 只读验收

**状态**：2026-10-13 已提交服务端修复和测试；Mac demo 仍无 Broker Key。旧的管理 QA 凭据在数据库中已不存在。真实 Broker 会话、跨租户和受托客户查询 **尚未通过端到端验收**。

## 运行原则

由租户管理员在 Tenant Web 使用独立 QA 租户创建 Broker Key，只选择 MARKET_READ、ACCOUNT_READ、ORDER_READ。不使用生产交易员或生产密钥，不向聊天、Issue、Git 仓库或 CI 日志发送 Secret。

先在 Mac mini 本地 Shell 环境配置下列四个环境变量，不要将敏感值写入仓库：

    OTC_BROKER_QA_KEY
    OTC_BROKER_QA_SECRET
    OTC_BROKER_QA_LOCATION
    OTC_BROKER_QA_CUSTOMER_ID

可选 OTC_BROKER_QA_FOREIGN_LOCATION 用于跨租户拒绝验收。执行：

    OTC_BROKER_QA_GATEWAY=http://127.0.0.1:18088 python3 tests/broker-api-readonly-acceptance.py

脚本不会输出密钥、Session 或账户数据。远程 Gateway 只允许 HTTPS，远程运行前需修复 Cloudflare Python 客户端拦截。

检查范围：签名登录并确认 Broker 会话类型、仅交易权限；行情、已授权客户余额；AdminSvr 委托和成交历史；tenantTradeAdmin/BALANCES、tenantApiKeyAdmin/LIST 拒绝；可选跨租户余额查询拒绝。

**不测试**：资金划转、入金/出金、下单、撤单、创建/撤销 API Key、用户/Robot/租户配置。所有请求必须经过 ALLOWED_METHODS 固定白名单；管理接口 action 也只能为只读。脚本通过不代表代客成交全链路验收通过。

前置：AdminSvr 部署含 Broker 历史查询授权修复的 4d4092f 或更新镜像。单元测试：

    python3 -m unittest discover -s tests -p test_broker_api_readonly_contract.py -v
