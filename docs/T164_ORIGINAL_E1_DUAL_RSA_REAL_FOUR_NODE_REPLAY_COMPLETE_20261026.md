# T164 fresh E1 Common Order/Trade actual installation | 2026-10-26

## What actually ran

A brand-new isolated ZooKeeper namespace was created at `/otc/t164/order` and `/otc/t164/trade`, one original `P090` E1 STRICT_QUORUM A/B assignment each, all `RECOVERING`, no READY, no Gateway. The original T149 namespace and official Demo/T84 containers were unchanged.

Two original RSA A/B signers for EACH service created **virgin, previously nonexistent** Common business WAL roots on four separate Docker-backed volumes, verified the original immutable dual-RSA Genesis, issued SHA256withRSA signed fsynced `original-e1-zero-ack.birth` receipts and then re-opened the on-disk proofs. No old WAL root was retroactively signed.

Four real main-JVM Common recovery nodes were started with the new ZK manifests and original RSA. `OrderSvrA/B` and `TradeSvrA/B` performed real Common sealed Genesis Snapshot, durable JournalBaseline, actual business restore/apply, and wrote `P090.recovery` with `phase=REPLAY_COMPLETE`, `epoch=1`, `snapshotSeq=0`, `replaySeq=0`.

### Real integration failure and repair

The initial Trade A reached `phase=BASELINE_DURABLE` but exited: `TradeRecoveryApplier.verifyAssignment()` consulted the old `TradePartitionRuntime.assignment()` writer interface. Its result was `null` under legitimate `RECOVERING`. This is a specific Demo/Common versus Trade difference.

Trade service-only repair makes the recovery-only applier use Common's immutable, actual-ZK-censused E1 partition/epoch map, rejecting E2, other partitions, nonzero committed head and deltas. The normal `READY` writer-side assignment path remains unchanged. **No new Trade election, WAL replication or READY logic** was introduced.

Trade local git `2b1d0f8d5e11d4a1d2a8b7374bceb3bbdf4448b9`, GitHub `bliplink/com.app.dc.tradesvr` branch `codex/t158-trade-fenced-main-jvm-20261026` remote `4cad9b08a3f14d9349f3efe8cc30715728e1e927`; 219 tests total, 217 passed, 2 skipped, no failures or errors. Built `local/otc-t164-tradesvr:fenced-trade-replay-fix` ID `sha256:57a553416a0f4b4602877b9a16e6e21c388ed388729a921408a1305c5b10e3b6` with original Common JAR SHA256 `1f155c487ad1730744824cac80c77ecdfa8efcba78de6fb3dff0c8f79ac44208`. Trade A was recreated from `BASELINE_DURABLE` and advanced to `REPLAY_COMPLETE`; Trade B separately advanced to `REPLAY_COMPLETE` after installing the same image.

### Independent physical audit

`tools/t149-recovering-only/bootstrap/T164IndependentDualVoterProof.java` is a Java 8 read-only process. For each service, it verifies independent A/B original RSA `birth` signatures, separate physical original WAL roots, original dual-signed Genesis, two separate durable `REPLAY_COMPLETE` records (E1/sequence 0), an unmodified same-generation `RECOVERING` ZK manifest, and distinct current original voter ZK ephemeral sessions. Observed:

- `T164_INDEPENDENT_REAL_RF2_GENESIS_BIRTH_REPLAY_ZK_PASS service=OrderSvr` genesis SHA `ebd8b95c5ac453ef7b0a411f854082e4a6cf96b1e67f061e08444683f322c62d`
- `T164_INDEPENDENT_REAL_RF2_GENESIS_BIRTH_REPLAY_ZK_PASS service=TradeSvr` genesis SHA `4846b45d8ba0233486d67dac16395c3c62ba3c13e90593e6517556ca415203b4`

Order A was actually stopped, restarted with a new ZK session and re-attested `REPLAY_COMPLETE` in the new JVM. The ledger metadata file hash changes because the Common install transaction refreshes its recorded metadata; do not claim immutable-byte equivalence. A first Trade A restart test did not satisfy every auxiliary script assertion, but independent verification subsequently passed and the Trade A JVM remained running with the correct durable phase. Only count validated pass criteria.

### Readiness and online Robot

**NOT READY and no live Robot quotes yet.** The original official Demo `OrderSvr` and `TradeSvr` are offline. Gateway responds 1003/1015, Robot reports `ERROR`, `open_order_count=0`. The new T164 nodes intentionally expose no public business ports.

Common's `CertifiedNodeRecoveryGate` forbids E1 `RECOVERING` to E1 `READY`: it requires a **higher Epoch** with a physically verified old-owner fence, strict WAL/CommitIndex and signed custody evidence (or an explicitly certified fresh-Genesis-to-next-Epoch transition for this zero-ACK case). The normal Spring business replay gate is volatile and must be re-attested from genuine signed on-disk proof on each new JVM; it must not receive a fake green boolean.

The next task is the Common-only signed original E1 zero-ACK -> higher-Epoch READY publishing transaction, same-session ZK CAS and durable business re-open on READY JVM, with new writer/Netty network, then live Robot bid+ask and Gateway/MD proof. No automatic state flip or legacy service cluster fallback is acceptable.

## Reproduction

Java 8 bootstrap: `T164OriginalFreshNamespace.java`, `T164OriginalBirthVoter.java`, `T164IndependentDualVoterProof.java`.

Isolated four-JVM compose was produced with `tools/t149-recovering-only/t164-stage-new-original-e1.py`. The repair image was built using `tools/t149-recovering-only/build-t164-trade-fenced-replay-arm64.sh`.

Verification: `bash tools/t149-recovering-only/verify-t164-independent-four-ledgers.sh /Users/kong/.opentradingcore/t149-order-trade-deploy-20261026 /Users/kong/.opentradingcore/t164-fresh-e1-runtime-20261026`.

All performed by local build and Docker, without GitHub Actions, preserving independent original T84 Demo.