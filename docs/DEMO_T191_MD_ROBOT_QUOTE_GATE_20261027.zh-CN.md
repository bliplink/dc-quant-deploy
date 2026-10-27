# T191 | MD routing restored; Robot quote is still NO-GO

Demo Mac / saas-crypto / local compile, no GitHub Actions. Limited to actual 2026-10-27 containers.

## MD
- Before: /dc/cluster/mdsvr/partitions absent; MDSvrA read-route count 0; MDSvrB stopped.
- Started dc-saas-mdsvr-b with existing official MD image, verified real MDSvrB ZooKeeper session.
- Initialized exactly 256 virgin MD assignments from existing deploy-saas.sh bootstrap pattern, alternating A/B primary; guarded create only if root absent.
- Sequentially restarted B then A, confirmed MD_READ_ROUTES_READY output A=128, B=128.
- Market images remain separately fenced: canPublish() requires local marked market epoch from complete actual OrderSvr image. Routing READY alone does not prove actual market Image.

## Robot actual runtime
- Tenant R0F6CC: three independently signed Common WAL cash commits, identical A/B WAL, actual MySQL balances/postings.
- Robot e2e-depth10 remains enabled but ERROR; after MD restore, failure moved from queryPublicMarket: INTERNAL_ERROR to placeOrder: ORDER_COMMON_DURABLE_COMMAND_NOT_CONNECTED.
- Robot open_order_count=0. No actual quote, match, or HA PASS.
- Order StateJournal has certified commitPreparedState but StrategyFacade recordCommand and AsyncAddOrderTask legacy batch still reject. Commit must precede live state mutation and client ACK; do not bypass gate.
- Trade B remains Exited(1): authenticated nonzero WAL P246 versus E2 virgin-only replica bootstrap. Requires verified cold replay and business consistency before READY.
- Do not retry old CashIn, delete nonzero WAL, forge custody, or disable durable ACK.

## Acceptance remaining
1. Cold Trade E2 rejoin with original A/B CommitIndex, custody and WAL, replay full Trade domain, compare Projection and funds.
2. Order new, risk approved, resting maker, cancel, fill through Common WAL, not legacy mutate-first.
3. Full actual MD Order Image, two Robot trader keys, persistent two-sided 10-level depth.
4. Real maker/taker match and ledger consistency.
5. SIGKILL A/B auto failover, catchup, no double-master or lost/duplicate trades.
