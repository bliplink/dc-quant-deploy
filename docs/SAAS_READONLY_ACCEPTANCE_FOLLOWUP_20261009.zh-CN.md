# 2026-10-09 SaaS 多租户与移动端后续验收

## 约束与版本

- 本轮为现有 12 租户 Demo 环境的只读浏览器与集群检查，不增加租户、不下单、不重置数据库、不修改真实租户路由、不回滚路由、不发布 Placement。
- 正式 Web 镜像在本轮验收起点为 `dc-trade-web@6620402`、`dc-saas-tenant-web@a9a4fb1`、`dc-saas-platform-web@b472c7b`；主站和三端 Logo 统一验收见 `BRAND_UNIFICATION_ACCEPTANCE_20261009.zh-CN.md`。
- 手动真实 `APPROVE` 开通仍未通过，不借此绕过此前的工具安全检查。

## 公网与平台入口

- 首次 `https://platform.opentradingcore.com/` 抽查出现 `Connection reset by peer` (`HTTP 000`)；其他主站、交易、租户站点均返回 200（请求总耗时约 0.74–0.84s）。
- 随后单独复测平台站，强制 IPv4 **5/5**、IPv6 **5/5** 请求均 HTTP 200；`http://127.0.0.1:18090/` 也是 HTTP 200；Cloudflare Tunnel 进程存在且平台 Web `healthy`。
- **结论**：有一次瞬时连接重置，但未复现持续 5xx / 连接问题；不应以单次失败断定平台服务崩溃，也不应因此宣称公网 100% 可靠。建议后续做按分钟的外网连通性条件告警。

## 交易页行情、K 线和跨租户抽样

- Chromium 无登录公共交易页 E2E 使用 MDSvr WebSocket 订阅，无公有行情快照轮询，检查匿名访问权限、盘口、K 线历史与实时推送、注册租户上下文及页面错误。
- **QA 租户 DPGR6B**：买卖盘口各 10 档、成交价正常；K 线历史 19 条，图表 11 个 canvas、实时至少 2 次更新； `web-public-market-e2e.js` PASS。
- **公开租户 VPDHPM**：买卖各 10 档、K 线历史 22 条、实时更新≥2 次，PASS。
- **公开租户 UJ2WZD**：买卖各 10 档、K 线历史 24 条、实时更新≥2 次，PASS。
- 主站公开列表显示 12 个租户，并正常分页；本轮抽验其中 3 个租户。**不是 12/12 全时段盘口验收**，更不是 200 租户压测。

## 手机、平板、桌面盘口及最近成交

- 第一版自动化未切换工作区，错误地将 390px 默认 Chart 页面上未挂载的盘口认成缺失。复核 `dc-trade-web/src/pages/trade/index.jsx` 确认手机 Order/交易工作区才挂载 `<OrderBookComponent />`；因此**不是移动端功能丢失**。
- 修正 `tests/mobile-market-readonly-acceptance.js` 先检验手机 Chart 的默认 5M，再切换到 Order/交易；分别检查双边盘口与最近成交标签。
- `DPGR6B`：390px、768px、1366px 均 **PASS**，各有 10 档买/卖盘、200 行最近成交记录、盘口报价非空，页面无 JS pageerror、无全页水平溢出（390px 页面宽度仍为 390px）。
- 真实 390px 盘口、最近成交截图已人工查看。发现手机 `order-book-row` / `recentTradeRow` 字号 9px、表头 8px；768px/桌面主报价行约 12px。
- 修复仅限 479px 以下手机：报价与最近成交 9→10px、表头 8→9px、对应行高 15→16px。Playwright 注入 CSS 预览的 390px 盘口和成交均未发生 DOM 单元格裁切（20 个盘口行、200 个最近成交条目），页面仍为 390px。正式源码 `dc-trade-web@18357e5` 已提交，待 GitHub Actions 与最终镜像验收后才能称为正式上线。
- 该 200 行是**客户端已加载的最近成交窗口记录数**，不代表 200 笔/秒；主站每个租户的 24h Trades 指标与最近成交数据口径未核对，暂不认为二者可直接比较。

## 核心一致性与 Web 健康

- `check-projection-consistency-host.sh`：event/mutation 主键正确、orphan mutations=0、Trade watermark mismatch=0（12）、Order watermark mismatch=0（12）、cross-partition event_id=0。
- `verify-order-cluster-state-host.sh`：分区与快照分布相符，256 个分区快照集合一致、Order A/B/C 正常、无重启/OOM。
- 交易 Web、租户 Web、平台 Web、MySQL、ZooKeeper 运行健康且无重启。
- 本轮尝试继续读取成交/机器人相关表结构时遇执行工具安全检查，已暂停该操作，未采用其他方式绕过；因此没有新取得**权威交易 TPS、P95/P99、逐租户 Tape 实际执行笔数**。不应编造这些性能数据。

## 证据与复跑

在 Mac mini 上，用已有只读 QA 工具复跑：

```bash
# 现有 QA 租户、手机版正确切换工作区，覆盖 390/768/1366
docker cp tests/mobile-market-readonly-acceptance.js dc-saas-web-e2e-runner:/runner/mobile-market-readonly-acceptance.js
docker exec -e E2E_LOCATION=DPGR6B dc-saas-web-e2e-runner \
  bash -lc 'NODE_PATH=/runner/node_modules node /runner/mobile-market-readonly-acceptance.js'

# Projection/Order HA
ENV_FILE=/Users/kong/.opentradingcore/dc-saas-fresh2-20261005.env \
  bash tests/check-projection-consistency-host.sh
bash tests/verify-order-cluster-state-host.sh
```

真实浏览器证据：`/Users/kong/.opentradingcore/dc-saas-runtime-fresh2-20261005/e2e-artifacts/acceptance-followup-20261009/`，内含不同租户公共交易页 JSON、手机各页面截图与 `mobile-market-report.json`。

## 未验收项及下一阶段

1. 当前真实下单和系统业务订单 TPS、P95/P99（应在隔离环境和配额保护下压测）；Tape 成交是否全部投影到 MySQL、主站 24h Trades 口径及其增长规律。
2. 12 租户长时间持续交易/报价、Robot 心跳、实时盘口空洞、Projection 追平以及 CPU PSI、GC/调度停顿关联；容量进阶 20/50/100/200 前先取得权威数据。
3. 平台手动审批新租户的真正 `APPROVE` 写流程仍未通过；对现有租户路由及 Placement 的写入按用户要求继续跳过。
