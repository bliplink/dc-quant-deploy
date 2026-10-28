# OpenTradingCore 统一协作与发布要求

## 页面与手册必须同版（强制）

以后修改主站、交易 Web、租户管理 Web、平台对客页面或 API Docs 的任何**用户可见功能、文案、交互、布局、权限、入口、移动端页面**，必须在同一批次：

1. 核对影响的用户手册章节，更新操作说明和实际功能名称；
2. 用 Playwright 在当前真实界面或隔离部署版本重拍受影响的 PC/手机、登录/匿名截图，严禁假截图、旧截图、密钥与密码；
3. 更新源文档和对应中文/英文 PDF（已发布双语的产品必须双语核对）；
4. 跑各 Web 仓库 `qa/check-user-manual-sync.py` 门禁及 PDF 视觉/页数检查；
5. 与 UI 源码一同提交并发布，检查公网 PDF MIME/链接/版本后才能报告页面交付完成。

**禁止先发布 UI、后补手册；缺少手册同步证据，发布与验收为未完成。**

完整规定：`docs/FRONTEND_USER_MANUAL_SYNC_POLICY.zh-CN.md`。交易、租户、主站和 API 文档仓库各自也有对应的 `AGENTS.md`。

Common/Order/Trade/MD 的 HA、资金、订单一致性必须独立验收，不能被手册/页面测试替代。

统一图文 PDF 一键生成：`./scripts/generate-user-manuals.sh`，详见 `docs/USER_MANUAL_ONE_CLICK_GENERATION.zh-CN.md`。

## Common / Order / Trade 简洁集群架构（强制）

Before changing Common, OrderSvr, TradeSvr, MDSvr, deployment or HA, read:
`docs/ARCHITECTURE_SIMPLE_COMMON_BOUNDARY_20261029.zh-CN.md`.

Non-negotiable rules:
- Common is a business-opaque `byte[]` WAL/replication/snapshot/recovery/failover library. It MUST NOT branch on order types (GTC, IOC, FOK, PO, DAY, GFD) or domain balances, positions, executions, settings.
- Order/Trade own their state machines, validation, serialization, apply/replay/snapshot and financial correctness. All business state writes use one generic Common persistence path, not type-specific WAL or parallel cluster implementations.
- Keep the cluster **simple**. Do not add recovery workflows, certificates, second ledgers, specialized outboxes, business-specific gates, helper services or configuration toggles without an explicit necessity approved by the project owner.
- Preserve essential safety: an uncommitted WAL tail must not be acknowledged or replayed as committed; a former Primary must not write; no fabricated ACK/READY. Recovery should use existing committed high-water mark, WAL, and peer replication, automatically.
- ZooKeeper is control plane only; TCP one-way replication, minimal hot-path I/O; a healthy Primary should continue with clearly signaled local durability if a standby is down.
- Work directly on the Mac Demo and `saas-crypto` branches; avoid GitHub Actions unless requested; do not discard uncommitted user changes.
- Real acceptance: auto-approved tenant, Robot live quotes, real Tape trades, auto A/B failover, and exact business consistency. Do not claim PASS from tests or container UP alone.