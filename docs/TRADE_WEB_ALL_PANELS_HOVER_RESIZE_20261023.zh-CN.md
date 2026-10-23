# 交易 Web 五组件统一悬停缩放验收｜2026-10-23

## 用户需求

1. 鼠标进入组件才显示拖动大小的手柄，移开隐藏。
2. 所有桌面组件（`chart`、`orderbook`、`place-order`、`orders`、`assets`）可从左侧、右侧、底边、左下和右下角调整尺寸。
3. 左侧组件的右边缘、右侧组件的左边缘都可以向两边拉长或拉短；保留移动桌面组件及已有布局存储。

## 源码

- `bliplink/dc-trade-web` 的 `saas-crypto@93fc562`。
- `src/pages/trade/resizableTradePanelsLayout.js`：默认和旧的 v9 `localStorage` 布局统一加 `['w','e','s','sw','se']`；在安全的断点下适当降低五组件的 `minW/minH`，保留原 `x/y/w/h` 和其他字段，避免布局重置。
- `src/pages/trade/style.less`：五组件一致的边缘手柄样式，平时 `opacity:0`、`pointer-events:none`；悬停、焦点或者正在缩放时显现；增加明显的横向边缘抓手。
- `src/pages/trade/index.jsx`：默认、持久化和恢复布局使用统一升级函数；手机端仍隐藏桌面网格。
- `test/resizable-trade-panels-layout.test.js`：3 项通过。`test:market-health` 2 项通过。webpack 生产构建通过。

## 真实 Demo 浏览器验证

- Chrome 1440×900 公开页面检查：五个组件 `w/e/s/sw/se` 手柄全部存在，鼠标移开时 opacity 0、pointer-events none，悬停后 opacity 1、pointer-events auto。
- 右侧盘口从左边缘放大 **244→318px**，再缩小 **318→259px**。
- 左侧 K 线从右边缘放大 **897→971px**，再缩小 **971→912px**。
- 资产面板底边高度放大 **226→304px**，再缩小 **304→278px**。调整后刷新，仍为 **278px**，证明非默认尺寸持久化。
- 390px 手机视口仍为 `compactWorkspace`，桌面网格隐藏，移动端交易入口存在。
- 真实布局拖拽会导致面板重新排布，浏览器验证时使用 `scrollIntoView` 保证下方资产面板可视。这不是组件功能缺陷。

## Demo 镜像和回退

- 已构建 `local/dc-saas-trade-web:unified-resize-hover-20261023`，在上一版 `order-resizable-20261023` 基础上覆盖新的 Web `dist`，中文使用手册仍在。
- 新增 Compose override：`config/trade-web-all-panels-resize-20261023.yaml`，叠加在原 `compose.yaml`、`trade-web-guide`、`trade-web-tabs`、`trade-web-order-entry`、`trade-web-tenant-labels` 和 `trade-web-order-resize` 配置之后。
- 只执行 `docker compose up -d --no-deps web`，没有重启交易后端；容器 healthy；公开 JS `main_2026_10_23_18_21_50.js`。
- 回退：移除此新 override，仅重启 Web 服务回到 `local/dc-saas-trade-web:order-resizable-20261023`。
