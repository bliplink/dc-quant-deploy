# Trade Web 用户指南

> 面向普通 Trader / Broker 客户。  
> 独立仓库：`bliplink/dc-trade-web@saas-crypto`  
> 镜像：`ghcr.io/bliplink/dc-saas-trade-web:saas-crypto`

## 1. 产品定位

Trade Web 是专业交易终端，只关注交易、行情、账户和持仓。

UI 目标参考成熟衍生品交易平台体验。

## 2. 行情

用户可以查看：

- 实时价格；
- Order Book；
- Kline；
- 成交；
- TradingView 图表；
- 不同周期。

实时行情通过统一 GW 订阅。

## 3. 下单

支持：

- Limit；
- Market；
- IOC；
- FOK；
- PostOnly；
- ReduceOnly；
- OPEN / CLOSE；
- Conditional / Trigger；
- TP / SL。

下单时需要正确处理：

- 价格精度；
- 数量精度；
- 最小数量；
- 最小金额；
- leverage；
- position mode；
- timeout。

## 4. Open Orders

用户可以：

- 查询当前挂单；
- 单笔撤单；
- Cancel All；
- 查看订单状态变化。

大订单量时内部数据和 DOM 渲染要分离，避免页面性能问题。

## 5. Positions

显示：

- symbol；
- side；
- quantity；
- entry price；
- mark / reference；
- unrealized PnL；
- leverage；
- liquidation price；
- margin。

Position Market Close 必须使用标准 CLOSE 语义。

## 6. Account Info

显示：

- balance；
- available；
- margin；
- realized / unrealized PnL；
- 账户配置。

Positions 与 Account Info 顶部布局需要保持一致。

## 7. 订单保护

支持：

- TP；
- SL；
- ReduceOnly；
- Position Close；
- Trigger order。

这些功能不能只靠前端模拟，最终必须由订单 / 风控核心验证。

## 8. Desktop / Mobile

Desktop：

- header / toolbar 紧凑；
- 下单首屏可见；
- 深色专业交易布局。

Mobile：

- 不是简单缩放 Desktop；
- 需要按专业交易 App 重新组织导航和交易栏。

## 9. 与 Tenant Web 的关系

Trade Web 一级导航可以有“租户”入口，但点击后应进入 Tenant Web 主页面。

不要在 Trade Web 中复制完整租户后台。

## 10. 用户文档原则

本指南面向最终用户，不描述 OrderSvr / TradeSvr 等内部服务。

用户只需要知道：

- 我能交易什么；
- 如何下单；
- 如何撤单；
- 如何看持仓；
- 如何理解资金和风险；
- 如何使用 API。
