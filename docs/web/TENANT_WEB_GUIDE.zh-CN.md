# Tenant Web 使用指南

> 面向租户 / Broker 管理员。  
> 独立仓库：`bliplink/dc-saas-tenant-web`

## 1. 产品定位

Tenant Web 是某一个租户 / Broker 自己的业务管理后台。

它既不是平台管理员后台，也不是普通 Trader 的交易终端。

## 2. 租户入口

Tenant Web 主页面至少提供：

- 租户申请；
- 租户登录。

审核通过后，租户获得唯一 `location`。

## 3. 客户与交易账户

租户可以管理自己名下客户：

- 创建客户；
- 创建交易账户；
- 查询客户；
- 查询账户状态；
- 管理交易用户；
- 查看账户资金和交易状态。

所有数据必须受当前 `location` 约束。

## 4. API Key 管理

Tenant Web 需要提供 API Key 管理入口，用于：

- Broker 后端接入；
- 普通 Trader API；
- Tenant 自建系统。

至少展示：

- API Key 类型；
- 权限；
- rate limit profile；
- 创建时间；
- 状态；
- 禁用 / 删除；
- Secret 只在安全流程中展示。

## 5. 资金管理

根据权限，租户可以对自己名下客户执行：

- 充值；
- 提现；
- 查询余额；
- 查询资金流水。

不得跨 location 操作其它 Broker 客户。

## 6. Broker API 入口

Tenant Web 应提供明显的 Developer / API Docs 入口，链接到：

- Broker API Guide；
- Trader API Guide；
- Tenant API Guide；
- OpenAPI 文档站。

Broker 可以完全自建自己的前端 / App / CRM，只使用本平台交易核心。

## 7. 与 Trade Web 的关系

Tenant Web 主页面应提供进入 Trade Web 的入口。

推荐：

```text
Tenant Web
  ├─ 客户管理
  ├─ API Key
  ├─ 资金
  ├─ Broker API
  └─ Trade Web
```

不要在 Trade Web 内复制完整租户管理二级菜单。

## 8. 验收要求

至少验证：

- 申请；
- 审批后登录；
- customer / trading account 创建；
- API Key；
- 充值 / 提现；
- 跳转 Trade Web；
- location 隔离；
- Broker API 文档入口；
- Desktop / Mobile 基本可用。
