# T153 — Actual ARM64 Common/Order/Trade RECOVERING candidate deployment (2026-10-26)

This is **executed deployment evidence**, not an untested plan.

## Code provenance and tested binaries

- Common T153 [PR #35](https://github.com/bliplink/com.app.common/pull/35), local commit `ecab5b9f7d91dc41c01dadd8dd2eaa0327f10c02`, parent T152 Common PR #34. Implements same-ZK-session original E1 two-node lease/CAS census, with **mandatory external independent physical zero-ACK WAL audit**. Until a real original-voter WAL/CommitIndex/Custody auditor is connected, **NO E1 business install/READY**.
- Common Maven 566 tests passed, 0 failed/errored/skipped. Source-built Common binary (same Maven GAV as T143, **different binary**), SHA-256:
  `58c71dd41b70cbb4ac97d6ab3887978c5204e2d4a464017257a23908b961f659`
- Order local T152 source `4b1c7d8fce274208f4d6f74d7b70998775ad0a35`, [Order PR #20](https://github.com/bliplink/com.app.dc.ordersvr/pull/20). Trade local T152 source `2811eb262317206ef840eec9312a597ce9916bc8`, [Trade PR #37](https://github.com/bliplink/com.app.dc.tradesvr/pull/37).
- Both locally compiled offline with Maven then staged with **exactly one** T153 Common jar (SHA above). Actual local `linux/arm64` Docker images built:
  - `local/otc-t153-ordersvr:common-e1-candidate`, ID `sha256:ab08c77492d937d5be4c674bf3aeefca52128e585a36758f47d3a7e91c178cdd`.
  - `local/otc-t153-tradesvr:common-e1-candidate`, ID `sha256:6cd575b5ae2a4cd267ee950ed07cec97dca3dbb051f19bd1b758ad3db8f313c9`.
- Reproducible `build-t153-arm64-candidates.sh` used successfully a second time and produced **the same image IDs**, without GitHub Actions or remote pushes to GHCR. Runtime read-only no-network check verified exact one Common binary and SHA in BOTH images.

## Actual deployed runtime

At `/Users/kong/.opentradingcore/t149-order-trade-deploy-20261026` (original T149 isolated stack), `deploy-t153-recovering-candidate.sh` applied `compose.t153-candidate.yaml` using the SAME project and SAME original volume mounts and recreated ONLY the 5 service candidates:

- `otc-t149-ha-intake-ordersvr-a-1`
- `otc-t149-ha-intake-ordersvr-b-1`
- `otc-t149-ha-intake-ordersvr-c-1`
- `otc-t149-ha-intake-tradesvr-a-1`
- `otc-t149-ha-intake-tradesvr-b-1`

All five ended `Up` with T153 image tags. The exact three existing T149 ZK container IDs were compared before/after and unchanged. No host port was published. T84 Demo A/B + 3ZK and five old formal Order/Trade containers were NOT modified.

### Actual fault: old ZooKeeper ephemeral lease on rapid replacement

First `docker compose up --force-recreate` made Docker report `Started`, but the new JVMs correctly exited with:
`java.io.IOException: recovering node lease owned by another ZK session`.
This was **not a successful startup**. Old JVMs had stopped, but the original ZK 8,000ms session/ephemeral leases had not yet expired. No Common safety override or ZK lease deletion was used.

A manual retry AFTER session expiry succeeded, and signed/TCP/ZK regression passed. Initial automated script incorrectly treated logs as an unknown startup cause because `grep -q` under Bash `pipefail` closed its reader early (SIGPIPE). This was found in a **real repeated deployment** and corrected to consume the full log stream.

The final script now:
1. Pins exact images, SHA256, ARM64, original runtime folder, Compose names, ZK IDs, no published ports.
2. Recreates only five business candidates with `--no-deps` (never restarts ZK).
3. Waits 10s and checks actual JVMs (not just Docker launch).
4. If and ONLY if a JVM stopped with the exact old-ZK-session-lease error, waits for natural expiry, then starts that candidate ONCE. Any other error fails; no ZK data deletion, no forced READY.
5. Requires an additional 12s of JVM stability (more than one 8s ZK session window), all five running pinned images, unchanged ZK IDs and no host bindings.

This final script was then **executed again while the former five service JVMs still held ZK leases**. Real trace:
`T153_CORRECT_OLD_ZK_SESSION_FENCE: waiting for old lease retirement` and
`T153_FIVE_CANDIDATES_UP_THREE_ORIGINAL_ZK_UNCHANGED_PASS`.

### Post-deployment actual acceptance — PASS

After the successful *second rapid replacement*, `verify-t153-post-deploy.sh` compiled and staged only 3 read-only test classes into `/tmp` of the new candidate containers and completed:

- Existing original Genesis signed quorum reopen on Order P090 A/B, P091 B/C, Trade P090 A/B: **6/6 PASS**.
- Genuine 3-ZK lease/session and live Netty business WAL and unsigned control rejection against all five new T153 Common RECOVERING processes: **5/5 PASS**, `ready=false`.
- Genuine 3-ZK read-only observer requiring both different RF2 ephemeral lease owners, same E1 RECOVERING manifest before/after, immutable original RSA Genesis/local fsynced voter image: **6/6 PASS**.
- Current data directory inventory on five candidates only contains original T150 Genesis files, no current WAL file; DOES NOT prove historical zero-ACK, nor independent physical hosts.
- Terminal marker: `T153_POST_RECREATE_6_SIGNED_GENESIS_5_NETTY_DENY_6_LIVE_ZK_ALL_PASS`.

## Exact executable commands

Run from `dc-quant-deploy` T153 branch/worktree on the Mac; require preexisting pinned locally built source trees and original isolated runtime:

```bash
bash tools/t149-recovering-only/build-t153-arm64-candidates.sh \
  /Users/kong/.webcodex-worktrees/ordersvr-7caf41e5-4661a89e \
  /Users/kong/.webcodex-worktrees/tradesvr-e0df3a38-9e0f452a \
  /Users/kong/.webcodex-worktrees/t116-common-shared-gate-20261025-0841f867/target/com.app.common-3.0.22-t143-durable-signed-crossjvm-handoff-20261026-SNAPSHOT.jar

bash tools/t149-recovering-only/deploy-t153-recovering-candidate.sh \
  /Users/kong/.opentradingcore/t149-order-trade-deploy-20261026

bash tools/t149-recovering-only/verify-t153-post-deploy.sh \
  /Users/kong/.opentradingcore/t149-order-trade-deploy-20261026 \
  /Users/kong/.webcodex-worktrees/ordersvr-7caf41e5/target/dependency
```

Build only touches local Docker images, deploy only the existing *test* T149 5 service containers, verify compiles auxiliary classes into isolated candidate `/tmp`. No GH Actions.

## Strict remaining NO-GO for trading READY and failover

- Mandatory **genuinely attested original-voter physical historical zero-ACK WAL/CommitIndex/Custody**. Current directory absence or signed fresh Genesis alone is insufficient; the T153 Common interface rejects missing auditors. Same-Mac containers are not two independent host failure domains.
- T149 Java process is deliberately Common recovery-only with NO loaded Order/Trade Spring state managers, journal baseline, user API or business transaction server. T152 `CommonCertifiedFreshGenesisInstall` is not yet invoked in these actual service JVMs, so NO real service `REPLAY_COMPLETE` ledger exists and no runtime READY can be granted.
- Next: connect actual business-loaded fenced recovery state and service journal baselines to Common, verify current signed Census/zero-WAL source, persist real E1 business install/replay, independently reopen from a new JVM, grant Common ZK READY only after retiring recovery-only listeners. Then basic authenticated trading and actual A→B→A fault injection, balance/position/Projection reconciliation.

**T153 original isolated Order/Trade redeployment and non-routable safety acceptance: PASS. Business transaction READY/HA acceptance: NO-GO.**