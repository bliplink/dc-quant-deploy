# OpenTradingCore coding boundaries (mandatory)

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
