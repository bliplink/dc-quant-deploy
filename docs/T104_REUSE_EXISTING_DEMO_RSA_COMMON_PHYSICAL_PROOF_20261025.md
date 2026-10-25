# T104 — reuse existing Demo RSA identities, Common physical proof wiring

**Date:** 2026-10-25. Mac mini local Maven/Docker only. **No new RSA keys were generated.** No GitHub Actions. No live Order/Trade Demo container, ZK, MySQL, WAL, tenant or financial data was replaced/reset/deleted.

## Confirmed existing RSA identity material (unchanged)

The existing isolated Demo HA T84/T82 container mounts identify three preexisting RSA identities `CommonHaDemoA`, `CommonHaDemoB`, `CommonHaDemoC`. Each node already owns `node.pk8` (PKCS#8 DER; private key mode `0600`) and a trusted shared `CommonHaDemo{A,B,C}.pub.der` (X509 DER). These mounts are backed by the existing Demo secret directory on the Mac. Its **absolute host path is deliberately omitted from this public GitHub document**. No key contents were logged, copied into Git or baked into Docker layers. Reuse these read-only mounts for each Order/Trade node, with different local-node identity directories for A/B, and the preexisting public trust directory.

The shared `com.app.dc` utility `ExistingDemoRsaNodeIdentity` accepts only existing absolute paths and `CommonHaDemo[A-C]` nodes. It rejects missing/symlinked/invalid files, private keys with non-owner-only access, duplicate public keys and mismatched private/public identities. It reads existing keys into memory, performs RSA sign/verify proof of possession, never calls a key generator, never writes any file and grants no epoch, WAL ACK, Custody or READY.

**These RSA identities represent distinct JVM identities hosted on ONE Mac, not independent physical hardware fault domains.** A/B signatures alone do not establish physical redundancy.

## Pushed source branches

| Source | Git branch | Latest commit |
| --- | --- | --- |
| shared `com.app.dc` | `feat/t85-common-ha-integration-20261024` | `7cf3ac1` |
| Order | `feat/t93-order-common-only-delete-20261024` | `12fc87c` |
| Trade | `feat/t92-trade-common-only-delete-20261024` | `0b339f5` |

Order and Trade each have an opt-in `ExistingDemoRsaWiring` Spring bean consuming **the same** locally installed shared identity loader (`com.app.dc` JAR SHA-256 `10c31b97a4ce658702948958a0f4ad7504826fef7f99313afe07c422bf0e3fe1`). Defaults off; private/public directories, nodeId are explicit external values. Missing or swapped identity refuses startup. This does NOT substitute an identity for a physical proof.

`OrderCommonPhysicalProofWiring` / `TradeCommonPhysicalProofWiring` bind **existing Common classes only**: an actual `CertifiedPersistedCustodySource` bean is required to instantiate `CertifiedSignedWalEvidenceVerifier` as the Common `CertifiedNodeRecoveryGate.PhysicalVerifier`. `CertifiedPersistedCustodySource` itself requires real old-Epoch membership, verified physically persisted custody head, signed receipt ledger and independent old-owner-fencer. There is no fake default Source, no synthetic signer, no business-local WAL or election. Both beans default off and fail startup when enabled without real proof dependencies.

## Verification actually executed

- Shared existing A/B/C RSA sign/verify: **3 passed, zero failures/skips** using real previously generated Demo keys. Swapping B's private key into A is rejected. No keys generated.
- Order fresh Maven `clean test` with real existing A key: **162 tests, zero failures/errors, 2 skipped**.
- Trade fresh Maven `clean test` with real existing B key: **188 tests, zero failures/errors/skips**.
- Spring real-bean tests: both services reject missing configuration, deliberately swapped existing node identities, and enabled physical evidence verifier with no real Common persisted custody Source.
- ARM64 Docker rebuilt:
  - `local/otc-t104-ordersvr:existing-rsa-12fc87c`, `sha256:5650dfd6d1b3dc58056fc520bc5ff3f985f08f428bb01e6ae914e763d4aa4340`.
  - `local/otc-t104-tradesvr:existing-rsa-0b339f5`, `sha256:f355aab5131f92fd8dd71fec07959c0ed016628e3f55479a6179fb1877fc1a7c`.
- Each T104 container was started with `--network none --read-only`, **only the existing Demo A or B private node directory** and trusted public directory mounted with Docker `:ro`. It successfully loaded existing matching RSA keys, signed a bounded test challenge and verified with the exact pinned public key. Both output `DOCKER_EXISTING_DEMO_RSA_REUSE_PASS` without disclosing secrets.
- Container binary gate confirms the exact same Common JAR SHA-256 `cf309a09d10db3486b700517e0a5e62d3f5b86f03e41ca11cc0a9151b38c67e3`, exact shared `com.app.dc` identity JAR, no old Order/Trade `service.cluster` bytecode directory, and **no `*.pk8` private key baked in either image**.
- `python3 tests/verify-t104-existing-rsa-images.py` → binary preflight PASS but release **NO-GO**. `--strict-release` → exit **2** as required. Both images have `dc.release.authorized=false`.

## Config template: paths must be actual runtime read-only mounts

Service-specific JVM `-D` properties (shown for Order A; adapt node identity and prefix for each process):

```
-Dorder.common.existingRsa.enabled=true
-Dorder.common.existingRsa.nodeId=CommonHaDemoA
-Dorder.common.existingRsa.localPrivateDir=/srv/v19/local-identity
-Dorder.common.existingRsa.trustedPublicDir=/srv/v19/identities
```

Mount existing `node.pk8` directory as `/srv/v19/local-identity:ro`, existing trusted public-key directory as `/srv/v19/identities:ro`. For Trade B, use `trade.common.existingRsa.*`, `CommonHaDemoB` and B's separate original private directory. The external host directory is supplied securely by the deployment host; NEVER add absolute key host paths or private-key contents to a public Compose/YAML/README or environment diagnostics.

**Physical recovery still requires distinct explicit controls** (`*.common.physicalEvidence.enabled=true`, `*.common.control.enabled=true`) and a real Common `CertifiedPersistedCustodySource`/old-owner fencer with authenticated persisted WAL and 2/2 signed custody. RSA identity setup alone does not enable these controls and is insufficient for cluster readiness.

## Remaining release blockers (unchanged)

The service mutation hot paths still lack the fully installed Common physical WAL/CommitIndex/custody-validated business ACK and Common-exclusive snapshot install/READY verification. No true 2-JVM Order/Trade transactional trading, live recovery, A→B→A automatic takeover, replica catch-up, MySQL/Projection/balances/orders/executions reconciliation, or 10/50/200 tenant stress was done in T104. Single Mac shared failure domain cannot be certified as physically independent HA.

**T104 verdict:** reuse of existing Demo RSA identities and opt-in Common persisted-evidence verifier wiring PASS; live HA/deployment release remains NO-GO. Existing active Demo images remain unchanged.
