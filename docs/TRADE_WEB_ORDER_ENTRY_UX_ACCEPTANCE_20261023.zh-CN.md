# Trade Web 下单表单匿名体验与按钮状态修复｜2026-10-23

## 范围与结果

- 代码仓库：`bliplink/dc-trade-web`，`saas-crypto@22a1758e79d3544010809d01d6a20b305354f42c`。
- 改动范围：`src/pages/trade/placeOrder/index.jsx`、`src/pages/trade/placeOrder/style.less`。
- 未登录状态：限价、市价、条件单均能切换和编辑；买入/卖出按钮跳转 `/login?location=<tenant>`；无需登录即可填写限价、数量、触发价格和条件单执行类型。
- 登录状态：三种订单类型买/卖按钮统一可点击，只有下单提交期间禁用。行情不健康时，仍在 `handlerPlaceOrder` 执行原有行情开仓校验，并弹错误提示，不绕过校验、预览或后端风险控制。
- 逻辑不支持的选项（例如市价单 PostOnly 和部分 TIF）依然禁用；没有改变订单/交易服务器。

## 构建、部署及验证

- 本地 `NODE_OPTIONS=--openssl-legacy-provider npm run build-prod` 成功。
- `test:market-health`、`test:position-risk`、`test:orderbook` 均通过。
- 镜像：`local/dc-saas-trade-web:order-entry-20261023`，在之前 `local/dc-saas-trade-web:tabs-unified-20261023` 基础上覆盖本次静态 bundle，保留交易 Web 中文使用手册。
- Compose：主 `compose.yaml` + `config/trade-web-guide-20261021.yaml` + `config/trade-web-tabs-20261023.yaml` + `config/trade-web-order-entry-20261023.yaml`。只执行 `up -d --no-deps web`，没有修改交易后端、数据库或恢复数据。
- `dc-saas-trade-web`: healthy；`https://trade.opentradingcore.com/` 返回新 JS `main_2026_10_23_17_36_03.js`。
- Chrome DevTools headless 实际公开 Demo 浏览器（桌面与 390×844 手机视口）验证：未登录状态限价、市价、条件单均可切换，输入可编辑，条件单执行类型可编辑，买入跳登录地址且保留租户参数；模拟认证状态后三种订单类型买/卖按钮均 `disabled=false`。
- 注意：认证态使用模拟浏览器状态验证按钮渲染，并非真实账号完整登录或真实下单测试。

## 当前运行版本与回退

- 运行标签：`local/dc-saas-trade-web:order-entry-20261023`。
- 回退：保留上一层本地镜像 `local/dc-saas-trade-web:tabs-unified-20261023`；移除此轮新增 Compose override，并只重新创建 `web` 容器。
