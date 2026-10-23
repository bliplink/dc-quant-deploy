# Trade Web 下单面板桌面拖动缩放验收｜2026-10-23

## 目标和原因

交易 Web 的限价、市价、条件单统一属于 `place-order` 网格面板。React Grid Layout 允许拖动，但默认缩放手柄仅右下角；下单面板初始位于网格最右侧，向右拖无法增加宽度，且原 `minW:16`、`minH:14` 限制了缩小。新的左侧、西南角、底边和原东南角手柄允许用户调整宽高。

## 实现

- `bliplink/dc-trade-web` 分支 `saas-crypto` 提交 `8bb20f4`。
- `src/pages/trade/resizableOrderEntryLayout.js` 对默认和旧有 `localStorage` v9 布局的下单面板补上 `resizeHandles: ['w','sw','s','se']`，调整按断点的最小宽高，不改变原先 `x,y,w,h`。`src/pages/trade/index.jsx` 在载入和持久化布局时调用该升级函数，不必清空用户布局。
- `src/pages/trade/style.less` 明确标识左边缘与下部缩放手柄，避免出现看不见/无法发现的抓手。
- 专项 Mocha 测试 `test/resizable-order-entry-layout.test.js` 共 3 个通过；`npm run test:market-health` 2 个通过；webpack 生产构建通过。

## Demo 镜像部署与回退

- 线上仅替换 `dc-saas-trade-web`：`local/dc-saas-trade-web:order-resizable-20261023`，在 `tenant-label-only-20261023` 镜像上覆盖新 `dist`，保留原用户指南、品牌、登录、账户 Tab 和下单改动。
- Compose 叠加配置：`compose.yaml`、`config/trade-web-guide-20261021.yaml`、`config/trade-web-tabs-20261023.yaml`、`config/trade-web-order-entry-20261023.yaml`、`config/trade-web-tenant-labels-20261023.yaml`、`config/trade-web-order-resize-20261023.yaml`。
- 只运行 `up -d --no-deps web`；其他业务服务未重启。容器 `healthy`；公开 `https://trade.opentradingcore.com/` 引用 `main_2026_10_23_18_01_05.js`。
- 回退：去掉最后一个 override，改用 `local/dc-saas-trade-web:tenant-label-only-20261023`，仅重新创建 `web`。

## 真实浏览器故障回归

使用 Chrome DevTools Protocol，1440×900 桌面实际访问公开 Demo：

- 初始下单面板约 `259×382px`，确认 `w/sw/s/se` 四个缩放手柄均可见。
- 拖左边缘向左放大至 `407px`，向右缩小至 `304px`。
- 拖底边向下放大至 `486px`，向上缩小至 `408px`。
- DOM 保留 `Limit`/`Market`/`Conditional` 标签、下单按钮底栏；刷新后保持 `304×408px`；`localStorage` 有相应布局及手柄配置。
- 模拟 390px 手机视口：进入 compactWorkspace，桌面网格隐藏、原移动端交易 workspace 正常展示。
- 测试没有使用真实交易员下单，因此没有额外创建订单。
