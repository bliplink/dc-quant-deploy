# OrderSvr same-key queue fix: Demo image rollout and acceptance

Date: 2026-10-20 (Demo Asia/Shanghai time). This delivery is the **isolated
business queue race fix** for tenant-created markets, not the separate
Common/Trade HA project.

## Source and deployment

- Common isolated branch: `fix/common-single-key-worker-20261020`.
- Common patch commit: **`b0be90c`** in `.work/app-common-queue-fix-20261020`.
- Previous Order image: `local/dc-saas-ordersvr:tenant-symbol-fullimage-20261019`.
- Replacement on **Order A, B and C**:
  `local/dc-saas-ordersvr:single-key-queue-b0be90c-20261020`.
- Compose override: `config/order-singlekey-rollout-20261020.yaml`
  (last `-f` for Order deployment). Apply `--profile order-cluster
  --profile order-cluster-c`, then `up -d --no-deps --force-recreate`
  on the three explicitly selected `ordersvr` services, one at a time.
- Rebuild locally: `bash tests/build-order-singlekey-image.sh` with the
  Common class files compiled from the isolated branch on Java 8. Requires
  the original local Order base image to remain available.
- The new image overlays only
  `com/app/common/thread/AsyncSingleSeqThreadGroup.class` and its `$1`
  anonymous-worker class under `OrderSvr/classes/`. Java's actual Order
  classpath starts `classes:config:lib/*`, so these classes take precedence
  over the unchanged original Common 3.0.22-SNAPSHOT JAR. Its SHA-256
  remains `8cbb195a131664c96692598bef51644ced9074f01ad80b3878b84cfce9444da4`
  on all three nodes; no Snapshot/WAL/cluster Java classes were modified.

## Actual rollout and runtime checks

1. Replaced C, then B, then A, without restarting Admin, APS, MD, Trade,
   Gateway, ZooKeeper, MySQL or resetting tenant data.
2. On **all three** running containers, the patched
   `AsyncSingleSeqThreadGroup.class` SHA-256 is
   `68bd50bd4dfbf6d3890cc75ee97056fd616954c061cdb1320291579f656e907a`
   and `javap -classpath classes:lib/*` confirms the patched read/write lock
   structure is loaded in the leading classpath.
3. All nodes were `running` and connected to ZooKeeper. Partition samples
   `P000`, `P001`, `P002` remained `READY`, at epoch 1 with A/B primary
   assignments. This is only a rolling-deploy readiness check, **not** a new
   HA fault-injection acceptance.
4. Public `AdminSvr.querySymbol` continued listing
   `N9NZV5/BTC003USDT`; `MDSvr.queryPublicMarket` returned `code=0` with
   TTL-expired index/mark null. Disabled `H2FIJU/BTC001USDT` and
   `BTC002USDT` remained filtered. Anonymous tenant-administration list
   continued returning `AUTHENTICATED_SESSION_REQUIRED`.

## Real post-upgrade custom-product trades — all PASSED

For every run: new Demo tenant auto-approved, tenant-created `BTC003USDT`,
CUSTOM source created and explicitly bound as sole current source; signed
Broker TenantAPI price publication `index=90000/mark=90001`, two independent
WEB traders funded 1000 simulated units each, Sell/Buy 0.001 @ 90000,
order/execution MySQL projection and both Trade private account/position
queries verified. Temporary Broker API Key deleted after each test.

| New tenant | Admission mode | Client launch gap | Persisted order created gap | Results |
| --- | --- | --- | --- | --- |
| ESPONL | Maker first confirmed resting, then Taker | N/A | ~5 s | Both Filled, 2 executions, balances/positions pass |
| KFAOUW | Near-simultaneous opposing writes | 0.351 ms | 290 ms | Both Filled, 2 executions, balances/positions pass |
| K4OB59 | Near-simultaneous opposing writes | 0.318 ms | 13 ms | Both Filled, 2 executions, balances/positions pass |

For all three tenants, independent read-only
`tests/check-custom-product-crossing-readonly.py` found **two Filled orders,
zero crossed New pairs, zero duplicate execution IDs**. Maker/Taker fees
and resulting long/short positions reconciled; the side submitted first may
be the Taker depending on the actual matching order.

The near-simultaneous test was added to
`tests/test-custom-product-live-e2e.py` as opt-in
`--execute --with-traders --near-simultaneous`. It synchronizes the first
requests with a barrier rather than requiring an already resting Maker. It
records **client request launch gap**; network/Order admission occurs later,
so the persisted-order creation timestamp is included above as a separate
metric. The test retried only explicitly rejected, not admitted `5004`
product-catalog-not-ready errors, not an ambiguous write.

## Previous vs patched Common single-key stress evidence

- Original **deployed** Common 3.0.22 JAR: 16 concurrent producers for
  the same new key yielded **peak parallel callbacks 16** (broken).
- Patched class first in classpath: **peak parallel callbacks 1** in eight
  repeated 16-thread runs, all messages delivered in each.
- Isolated Common Java 8 JUnit: **8/8 passed** (16/32/100 simultaneous
  first adds, 10k events no loss/duplicates, per-producer FIFO,
  distinct-key parallelism, dead-worker queued tail transfer, shutdown).

## Limitations / final merge plan

- Two near-simultaneous real matches and isolated queue stress are concrete
  acceptance, but do **not** establish 200-tenant sustained load or prove
  all potential matching bugs absent.
- This image is a **local Demo class overlay**, not a republished Common
  Maven 3.0.22 binary. Do not reference it as a universal released Common
  version. When the other Codex Common HA branch is ready, cherry-pick
  `b0be90c`, compile a single authoritative Common version with both the
  HA and queue changes, then rebuild all services that use the revised
  Common library, and redo matching/consistency and HA verification.
- No GitHub Actions, GHCR push, Common central release or Docs/文稿 folder
  access occurred. This rollout did not change Trade/Common HA mechanisms.
