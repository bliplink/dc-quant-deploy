# T166: real Common SAME-ZK-SESSION dual-voter E1 replay attestation (2026-10-27)

Goal: advance OpenTradingCore towards live Robot quotes without enabling Order/Trade's retired local cluster.

## Actual executed result

- Common original RSA and both E1 birth-time zero-WAL certificates survive, plus both sealed Genesis, both independent `REPLAY_COMPLETE` Ledgers and JournalBaseline on the actual physical volume mounts.
- New Common `CommonOriginalE1TwoVoterReplayPreflight` runs *inside the authenticated original local recovery JVM on the SAME ZooKeeper session*. It requires both original signed Genesis images, both original physically born zero-WAL roots, two independent on-disk durable restore/replay transactions, exact snapshot hash/Epoch/zero committed HEAD, exact JournalBaseline metadata, and revalidates E1 leases and manifest after IO. No fake callback can publish READY.
- Tested with original Demo RSA: tamper B journal -> DENIED; delete B ledger -> DENIED. Common full suite before the actual-volume-path fix: **585/585 PASS**. The exact partition-root `P090/P090` bug was uncovered by an actual physical-JVM deployment, corrected in Common, and re-tested successfully with original RSA.
- Latest Common JAR (post-path fix) SHA256 `991579637320bfdb37458e638d701ab9a2861b70f1782b3fe402652a70b5653c`.
- Local ARM64 Order `local/otc-t166-ordersvr:both-original-replay` image SHA `76d6498cc37db7f92d2ee7c36ed9d1122b37a42fb6aaa07e42126788a7ac4d72`.
- Local ARM64 Trade `local/otc-t166-tradesvr:both-original-replay` image SHA `e5ed16f23008d6d333975069ce4850bfa1b2baa3bdbc4abb1fea8d283029011b`.

### Four real container PASS

Under the physically original T164 namespace `/otc/t164/{order,trade}`, actual Docker process logs each produced:

```text
T166_COMMON_ORIGINAL_E1_SAME_ZK_BOTH_REPLAY_COMPLETE_PASS service=OrderSvr node=OrderSvrA partition=P090 ready=false
T166_COMMON_ORIGINAL_E1_SAME_ZK_BOTH_REPLAY_COMPLETE_PASS service=OrderSvr node=OrderSvrB partition=P090 ready=false
T166_COMMON_ORIGINAL_E1_SAME_ZK_BOTH_REPLAY_COMPLETE_PASS service=TradeSvr node=TradeSvrA partition=P090 ready=false
T166_COMMON_ORIGINAL_E1_SAME_ZK_BOTH_REPLAY_COMPLETE_PASS service=TradeSvr node=TradeSvrB partition=P090 ready=false
```

All four containers are **RUNNING**, exact E1 physical `REPLAY_COMPLETE` persisted, same Common JAR, original three isolated ZK containers remained unchanged. No customer ports are published. Real Order/Trade Spring/Gateway is **NOT** started, ZK is `RECOVERING` (no READY), no Robot real quote is possible here.

### Robot/official Demo

The official `dc-saas-ordersvr` A/B/C and `dc-saas-tradesvr` A/B are still EXITED on old T113, with retired service-owned cluster configurations (legacy lifecycle/replication/failover enabled). No unsafe T113 restart attempted. Re-ran real Gateway heartbeat `--pilot H00001`: Robot status ERROR, 0 active orders, Gateway still says OrderSvr/TradeSvr not Online. So **DO NOT report Robot quotes or business GO**.

## Source and reproduction

- Common classes `CommonOriginalE1TwoVoterReplayPreflight`, `CommonOriginalE1LiveInstaller`, `CommonOriginalE1VerifiedSourceConfig`.
- `tools/t149-recovering-only/build-t166-dual-replay-arm64.sh`: locally pins original Order/Trade commits, exact Common JAR SHA and ARM64, builds without GitHub Actions.
- `tools/t149-recovering-only/t166-stage-real-four-voter-ledgers.py`: mounts independent peer read-only E1 data/ledger, enforces virgin original preconditions, no READY.
- `tools/t149-recovering-only/deploy-t166-dual-original-rf2-preflight.sh`: verifies no business host ports, staged signed roots and four same-session PASS markers. Initial run uncovered exact `P090/P090` bug, corrected in Common and redeployed. A shell-name diagnostic bug was also corrected; final run PASS 4/4.
- `tools/t149-recovering-only/verify-t165-live-demo-robot-quote.py --pilot H00001` proves official Robot failure until real serving.

## Next engineering gate

One Common-owned, certified **initial** E1-RECOVERING → later-Epoch staged recovery/READY authority, not an unsafe raw ZK flag. It must continue original RSA/zero ACK checks, fence E1 recovery business before new writer creation, re-open the true restored business in serving Spring JVM (not a separate recovery process), bind Common physical RF2 Netty WAL/custody/CommitIndex, and publish actual Gateway endpoints only after authority. T164/T166 contains only P090; no claim of 256 partitions/25 tenants. Then connect a real tenant whose product hashes to an activated partition, verify Robot quote+cancel, real bid/ask through MD, Trade risk and Projection.

**Current outcome: Common RF2 durable recovery attestation 4/4 PASS; live Robot quote NO-GO.**