# T156 — REAL T153 ARM64 Order/Trade domain code executed INSIDE deployed containers

2026-10-26. Isolated T149/T153 candidate stack only. Actual goal: safely reach Common-authenticated business startup and then replace stopped formal Demo Order/Trade so Robot can actually quote/trade.

## Material execution (not another host-only JUnit run)

- Wrote `bootstrap/T156OrderRealDomainSnapshotProbe.java` and `bootstrap/T156TradeRealDomainSnapshotProbe.java`: **compile against exact production Order/Trade T152 class files** and their dependency trees, Java bytecode 52 (Java 8).
- `verify-t156-container-business-state.sh` pinned the two local service source commits; copied compiled package classes **only to /tmp** in original T153 five isolated service containers, then invoked original production business state-management classes from the actual ARM64 image classpath in a new auxiliary Java process.
- RSA input was the original read-only A/B/C Demo public keys already mounted at `/read-only-original-rsa/public`. The auxiliary checks the same original RF2 Membership and physical voter identity as T150 and reopens the **dual-signed E1 Genesis** and local original-node fsynced image. It then creates actual OrderManager / OrderRecoveryStateMachine or Trade business manager/TradeRecoveryStateMachine instances and captures a fresh E1 seq0 image using the real business snapshot APIs.
- Order P090 A/B and P091 B/C: signed byte-for-byte equality PASS, staged `OrderRecoveryStateMachine.restore()` plus `finishReplay()` on a fresh manager PASS, no unexpected open orders. After restoring, create a real OrderBook at updateId=42 and require its new snapshot to **differ** from original empty signed Genesis. 4/4 normal and 4/4 negative PASS.
- Trade P090 A/B: actual `TradeBusinessSnapshotCapture` on account, position, data, order, execution dedupe managers, signed byte equality PASS, `TradeRecoveryStateMachine.restore()` staging PASS. Then put a real balance of 200 into AccountBalanceFacade; it must differ from original empty Genesis **and TradeRecoveryStateMachine.snapshot() must refuse the larger image under original authorized image size**. 2/2 normal and 2/2 negative PASS. The Trade applier `finishReplay()` is **not** invoked, as authentic Common original partition assignment and live business lock are required to safely mutate authoritative loaded state.

**Final reproducible result in the existing T153 containers:**
```text
T156_ORDER_NONEMPTY_BUSINESS_DENIED_ORIGINAL_EMPTY_RSA_PASS ...    (4 cases)
T156_IN_CONTAINER_ORDER_BUSINESS_CAPTURE_AND_RESTORE_ORIGINAL_RSA_PASS ... (4)
T156_TRADE_NONEMPTY_BUSINESS_DENIED_ORIGINAL_EMPTY_RSA_PASS ...    (2)
T156_IN_CONTAINER_TRADE_BUSINESS_CAPTURE_AND_STAGED_RESTORE_ORIGINAL_RSA_PASS ... (2)
T156_REAL_PRODUCTION_DOMAIN_AUXILIARY_IN_CONTAINER_6_OF_6_PASS
```

Run from `dc-quant-deploy` T156 source:
```bash
bash tools/t149-recovering-only/verify-t156-container-business-state.sh \
  /Users/kong/.webcodex-worktrees/ordersvr-7caf41e5-4661a89e \
  /Users/kong/.webcodex-worktrees/tradesvr-e0df3a38-9e0f452a
```
Read-only original Genesis; only writes auxiliary Java class files under container `/tmp`. No ZK mutations, Docker recreates, writer listener, Order/Trade orders, customer sessions, money operations, robot restarts or host ports.

## Precisely why formal Demo/Robot still cannot run T153

**The T153 main business JVM is the CommonRecoveryOnlyProcess**. It does not construct the domain managers above or load Spring/Gateway. An auxiliary JVM's successful capture/restore **cannot be used as proof of the main JVM's state or ledger**. Do not copy the auxiliary state or declare its external REST/Netty port ready.

Missing runtime links, in strict order:

1. A Common original-E1 zero-WAL **birth-time physical witness** with original voter auditable historical ACK/CommitIndex/Custody state, not a retrospective snapshot of an empty disk or mock `OriginalVoterZeroWal`.
2. A **fenced business-loaded recovery runtime** in each actual Order/Trade service JVM that owns their real managers/partition exclusive mutation barrier/journal baseline and authentic same-ZK-session Common voter lease. It must invoke `CommonCertifiedFreshGenesisInstall`, persist and reopen durable business journal and `REPLAY_COMPLETE`. Order and Trade continue only to implement opaque business snapshot/restore; all cluster control remains in Common.
3. Independent Common control certifies installed business state, retires old recovery-only listener and CAS-publishes READY. Then start a real business listener using CommonCertifiedNodeBootstrap; never toggle the phase string manually.
4. Only then point the existing Demo Robot at the newly running official Order/Trade, verify authenticated limit quote/cancel, cross fills, margin, balances, positions, admin/Projection watermark and no duplicates. Automatic A→B→A failure injection next.

The T155 live scan still finds 5 official Demo Order/Trade containers **stopped**, causing Gateway errors, while Robot, Gateway, MD, Admin and Projection container processes are up. This remains a user-facing issue; it is not resolved by T156. We did **not** replace formal containers because that would merely substitute non-serving RECOVERING processes for stopped services.

**Status:** T156 real image/domain compatibility and E1 snapshot/negative tests PASS; in-main-process recovery/actual online Robot trading/automatic HA NO-GO.