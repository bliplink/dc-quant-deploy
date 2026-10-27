# T162 Common-only Order/Trade main JVM isolated deployment — 2026-10-26

## Real environment and artifacts

- Development machine: Mac ARM64, local Maven and Docker; no GitHub Actions.
- Order source `0fe187f0171e8db8c4cf5e9bcd407de85029f51b`. Trade source `c47e0bab48f474f65c7b7bae847863c9f598b003`.
- Both ARM64 images contain exact same Common Jar `SHA256 6324dbdf2f855f9cb54bac22ddd6ba6d5235b1ba5a28b4a9c865e952911c899b`, from Common T162 583 tests, 0 fail, 0 errors, 0 skip.
- Order image `local/otc-t162-ordersvr:common-fenced-intake` ID `sha256:450267ff1d27327934d002c5f393c65036da77a86ced77a4e6a9a7ecd33df01e`.
- Trade image `local/otc-t162-tradesvr:common-fenced-intake` ID `sha256:ced7e0d1de461bfbbfcdeed4d24d4c678541b0555fa0c96a2d22073e8c0c3dc0`.
- Local reproducible builder `tools/t149-recovering-only/build-t162-common-fenced-arm64.sh`; isolated compose deployer `tools/t149-recovering-only/deploy-t162-common-fenced-intake.sh`.

## Observed PASS

On the real host, rebuilt and replaced the exact five **T149 isolated** Order/Trade containers:

`ordersvr-a`, `ordersvr-b`, `ordersvr-c`, `tradesvr-a`, `tradesvr-b`.

They all remained running after initial ZK lease expiration and passed authentic Common same-JVM E1/RECOVERING census, existing RSA and registered business-state inspection. The three original isolated ZK container IDs and independent T84 Demo A/B container IDs were unchanged. None exposed an external business port. This is not online READY and not live Robot quoting.

Earlier real **test-JVM**, **not production service**, evidence: Order/Trade shared Common Netty/RSA WAL, signed CommitIndex/custody; real OrderManager contained uncrossed bid and ask after eight certified WAL commits; crossing orders rejected without atomic matching; Trade real balance, margin and position tests passed. Full Order 182 tests (177 pass, 5 skipped); Trade 216 (214 pass, 2 skipped).

## Official Demo Robot status: FAIL

`dc-saas-ordersvr`, `dc-saas-ordersvr-b`, `dc-saas-ordersvr-c`, `dc-saas-tradesvr` and `dc-saas-tradesvr-b` remain stopped. The running Robot/Gateway logs at 2026-10-26 21:12 +08 show:
- `SERVER.TradeSvr is not Online`
- `SERVER.OrderSvr is not Online`
- Gateway queryTradePosition/queryOpenOrder response 1003/1015
- Robot status `ERROR`, quote cleanup pending, `open_order_count=0`.

Don't optimize Robot itself first. Restore Common-certified **real business** Order/Trade network endpoints, then verify Robot buy and sell LIMIT admissions to the real orderbook and from API/MD.

## Remaining real gates

1. Brand-new non-serving original ZK namespace, both original RSA-pinned independently born physical E1 WAL roots and fsynced zero-ACK birth signatures. Original T149/T150 sealed Genesis is **not** evidence that historical ACKs never existed. Do not retroactively re-sign its preexisting WAL dirs.
2. T163 adds the Common-issued same-session real E1 Genesis installer with verified source configuration. Supply real roots/quorum, run durable REPLAY_COMPLETE in the original JVM; prove cross-JVM state re-open and old writer exclusion.
3. Authenticate Common READY and bind **real Spring/Gateway** writers with correct durable WAL, risk approval and noncrossed maker quote commit-before-apply path. Do not bypass either proof.
4. Replace official Demo Order/Trade only after actual live service path is ready; verify Robot new/cancel and two-sided bid/ask. Then strict A↔B automatic failover, authoritative Projection/Trade account/order/position reconciliation.

**GO/NO-GO: NO-GO** to publish READY or announce Robot quoting. This document records actual integration test progress only.