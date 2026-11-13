#!/usr/bin/env python3
"""Seal a completed, successful Common drill against its original candidate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys


DIRECTIONS = re.compile(
    r"^T554_INDEPENDENT_AB_SIGKILL_BOTH_DIRECTIONS_256_HOME_STRICT_PASS "
    r"aFailoverMs=([1-9]\d*) aHomeMs=([1-9]\d*) bFailoverMs=([1-9]\d*) bHomeMs=([1-9]\d*) "
    r"equalWal=256 equalSnapshot=256$", re.M)
THIRD = "T554_RETURNED_HOME_VOTER_THIRD_SIGKILL_256_LOCAL_PASS"
REPEATED = "T554_RETURNED_HOME_VOTER_THIRD_SIGKILL_REPEATED_HOME_256_PHYSICAL_MATCH_PASS"
INTERRUPTED = "T554_INTERRUPTED_LOCAL_TO_STRICT_SIGNED_STAGE_RESUMED_PASS"
BLOCKED_NOTICE_ACK = re.compile(
    r"^[.]*T554_BLOCKED_POISON_NOTICE_OTHER_PARTITION_PHYSICAL_HOME_ACK_PASS "
    r"blocked=(P[0-9]{3}) recovered=(P[0-9]{3})$", re.M)
COLD_TAIL_ACK = re.compile(
    r"^[.]*T554_BOTH_COLD_STRICT_TAILS_SIGNED_PREFIX_HOME_AND_BUSINESS_ACK_PASS$", re.M)
NORMAL_ASYNC_ACK = re.compile(
    r"^[.]*T554_NORMAL_DUAL_ASYNC_BACKUP_OUTAGE_PRESERVES_LOCAL_ACK_PASS "
    r"sameEpoch=2 bothCommittedHeads=2 appliedOnce=true originalRisk=true$", re.M)
NORMAL_ASYNC_KILL = re.compile(
    r"^[.]*T554_NORMAL_DUAL_ASYNC_PRIMARY_SIGKILL_AFTER_LOCAL_ACK_REAL_WITNESS_HOME_PASS "
    r"backupCommittedHead=1 abandonedLocalHead=2 originalPrimaryWalUnchanged=true "
    r"backupCommittedPrefixUnchanged=true inflightTailExcluded=true home128Each=true$", re.M)
NORMAL_ASYNC_BACKUP_EXPIRY = re.compile(
    r"^[.]*T554_NORMAL_DUAL_ASYNC_BACKUP_EXPIRY_PRESERVES_ACK_AND_CONTINUES_PASS$", re.M)
NORMAL_ASYNC_MIXED_STRICT_TAIL = re.compile(
    r"^[.]*T554_NORMAL_DUAL_ASYNC_BACKUP_EXPIRY_PRESERVES_ACK_AND_EXCLUDES_STRICT_TAIL_PASS$", re.M)


def sha(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def evidence_hashes(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Common physical evidence directory is missing or unsafe")
    paths = sorted(directory.rglob("*"))
    if any(path.is_symlink() or path.suffix in {".pk8", ".hmac"} for path in paths):
        raise ValueError("Common physical evidence contains an unsafe path or private identity")
    return {str(path.relative_to(directory)): sha(path) for path in paths if path.is_file()}


def verify_normal_async_primary_prefixes(directory):
    original = (directory / "a-original-local-acked.wal").read_bytes()
    prefix = (directory / "b-original-committed-prefix.wal").read_bytes()
    primary = (directory / "data-a/DemoSvr/DemoSvrA/P000/epoch-2/business.wal").read_bytes()
    backup = (directory / "data-b/DemoSvr/DemoSvrB/P000/epoch-2/business.wal").read_bytes()
    if (not prefix or len(original) <= len(prefix) or not original.startswith(prefix)
            or primary != original or backup not in (prefix, original)
            or not (directory / "a-home-business-proof").is_file()):
        raise ValueError("Common async original committed prefix or excluded in-flight tail proof is invalid")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("sha256")
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    candidate, result, digest = args.candidate, args.result, args.sha256
    if not candidate.is_absolute() or not result.is_absolute() or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Expected absolute evidence directories and exact Common SHA256")
    revision = (candidate / "commit.sha").read_text().strip()
    identity_lines = (result / "candidate.env").read_text().splitlines()
    if (not re.fullmatch(r"[a-f0-9]{40}", revision) or len(identity_lines) != 3
            or identity_lines[:2] != [f"common_revision={revision}", f"common_sha256={digest}"]
            or not re.fullmatch(r"fixture_revision=[a-f0-9]{40}", identity_lines[2])
            or sha(candidate / "common-tested-class-bytes.jar") != digest or sha(result / "common.jar") != digest):
        raise ValueError("Physical run does not use the original Common candidate")
    main_source = [line for line in (candidate / "source.sha256").read_text().splitlines()
                   if re.fullmatch(r"[a-f0-9]{64}  (?:pom\.xml|src/main/.+)", line)]
    if (len(main_source) < 2 or main_source != (result / "main-source.sha256").read_text().splitlines()
            or "[INFO] BUILD SUCCESS" not in (result / "fixture-build.log").read_text().splitlines()):
        raise ValueError("Physical fixture source or compilation is not verified")
    transcript = result / "failover.log"
    log_bytes = transcript.read_bytes()
    log = log_bytes.decode("utf-8")
    both = list(DIRECTIONS.finditer(log))
    lines = log.splitlines()
    if (len(both) != 1 or lines.count(THIRD) != 1 or lines.count(REPEATED) != 1
            or lines.count("OK (1 test)") != 1 or "FAILURES!!!" in log or not re.search(r"^Time: [\d,.]+$", log, re.M)
            or not log.find(THIRD) < log.find(REPEATED) < log.find("OK (1 test)")
            or both[0].start() >= log.find(THIRD)):
        raise ValueError("Common physical test is incomplete or unsuccessful")
    poison_source = result / "source/src/test/java/com/app/common/replication/CommonCertifiedLivePoisonRecoveryTest.java"
    poison_evidence = {}
    if poison_source.is_file():
        mixed_strict_tail = "a-async-strict-tail-home-proof" in poison_source.read_text()
        poison_tests = len(re.findall(r"^\s*@Test\s*$", poison_source.read_text(), re.M))
        poison_success = f"OK ({poison_tests} tests)"
        if poison_tests < 5 or lines.count(poison_success) != 1 or log.find(poison_success) >= both[0].start():
            raise ValueError("Common live poison and interrupted physical voter recovery tests are incomplete")
        evidence_root = result / "process-evidence-live-poison"
        scenarios = ["single", "repeated", "successor-restart-e3", "successor-restart-e5", "owner-restart-e3"]
        if "simultaneousPoisonedPartitions" in poison_source.read_text():
            scenarios.append("multiple")
        if "expiredWholeNodeExits" in poison_source.read_text():
            scenarios.append("node-lease-expiry")
        if "closedPhysicalVoterCannotPublishRecovery" in poison_source.read_text():
            scenarios.append("graceful-shutdown")
        if "foreignPoisonNoticeCannotStarveAnotherPhysicalPartitionRecovery" in poison_source.read_text():
            scenarios.append("blocked-poison-notice")
            recovered = BLOCKED_NOTICE_ACK.findall(log)
            if len(recovered) != 1 or set(recovered[0]) != {"P000", "P001"}:
                raise ValueError("Common blocked poison notice did not preserve independent physical recovery")
        if "bothColdVotersRecoverUnsignedStrictTailsWithoutReplayingThem" in poison_source.read_text():
            scenarios.append("cold-strict-tails")
            if len(COLD_TAIL_ACK.findall(log)) != 1:
                raise ValueError("Common cold strict tail recovery lacks genuine Home business ACK evidence")
        if "normalDualAsyncBackupOutageRetainsLocallyAcknowledgedWrites" in poison_source.read_text():
            scenarios.append("normal-dual-async")
            if len(NORMAL_ASYNC_ACK.findall(log)) != 1:
                raise ValueError("Common normal async physical ACK and prefix recovery evidence is incomplete")
        if "normalDualAsyncPrimaryKilledAfterLocalAckReturnsThroughRealWitnessedRecovery" in poison_source.read_text():
            scenarios.append("normal-dual-async-primary-kill")
            if len(NORMAL_ASYNC_KILL.findall(log)) != 1:
                raise ValueError("Common normal async primary SIGKILL and witnessed Home proof is incomplete")
        if "normalDualAsyncBackupNodeExpiryPreservesLocalAckAndContinuesWriting" in poison_source.read_text():
            scenarios.append("normal-dual-async-backup-expiry")
            required_proof = NORMAL_ASYNC_MIXED_STRICT_TAIL if mixed_strict_tail else NORMAL_ASYNC_BACKUP_EXPIRY
            if len(required_proof.findall(log)) != 1:
                raise ValueError("Common normal async surviving owner did not retain its local committed suffix")
        for scenario in scenarios:
            directory = evidence_root / scenario
            for required in ("DemoSvrA.log", "DemoSvrB.log", "final-manifest.txt"):
                if not (directory / required).is_file():
                    raise ValueError("Common live poison physical process evidence is missing")
            if scenario == "node-lease-expiry":
                events = (directory / "supervisor-events.txt").read_text().splitlines()
                original = (directory / "DemoSvrB.attempt-0.log").read_text()
                if (not events or events[0] != "attempt=0 exit=78"
                        or "FATAL_COMMON_NODE_EPOCH_FENCED exiting JVM (78)" not in original):
                    raise ValueError("Common expired node did not exit through the physical process lifecycle")
            if scenario == "graceful-shutdown":
                events = (directory / "supervisor-events.txt").read_text().splitlines()
                if not events or events[0] != "attempt=0 exit=143":
                    raise ValueError("Common graceful shutdown did not retain its original physical exit")
                if "LOCAL_DURABLE_ASYNC" not in (directory / "r-first-ack.txt").read_text():
                    raise ValueError("Common survivor did not continue durably before graceful voter return")
            if scenario.startswith("normal-dual-async"):
                receipt = (directory / "a-local-acked-before-peer").read_text().strip()
                if receipt != "LOCAL_DURABLE_ASYNC P000 2 2 rpoRisk=true":
                    raise ValueError("Common normal async original LOCAL receipt is missing")
                if (scenario.endswith("primary-kill")
                        and not (directory / "DemoSvrA.attempt-0.log").is_file()):
                    raise ValueError("Common normal async killed primary log is missing")
                if scenario.endswith("primary-kill"):
                    verify_normal_async_primary_prefixes(directory)
                if (directory / "client-ack-policy.txt").read_text().strip() != "LOCAL_DURABLE_ASYNC version=0":
                    raise ValueError("Common normal async immutable client ACK pin is missing")
            if scenario == "normal-dual-async-backup-expiry":
                markers = ["a-async-survivor-preserved", "a-async-survivor-home-proof"]
                if mixed_strict_tail:
                    markers.extend(["a-async-strict-tail-failed", "a-async-strict-tail-home-proof"])
                for marker in markers:
                    if not (directory / marker).is_file():
                        raise ValueError("Common normal async surviving owner and rejoin proofs are missing")
                events = (directory / "supervisor-events.txt").read_text().splitlines()
                if not events or events[0] != "attempt=0 exit=78":
                    raise ValueError("Common normal async backup did not expire through its real node fence")
            poison_evidence[scenario] = evidence_hashes(directory)
    recovery_evidence = {}
    full_source = result / "source/src/test/java/com/app/common/replication/CommonCertifiedFirstReadyE2AutomaticRecoveryTest.java"
    if '"voter-states-before-cleanup.txt"' in full_source.read_text():
        directory = result / "process-evidence"
        for name in ("home", "keys", "birth", "data-a", "data-b", "c"):
            if not (directory / name).is_dir():
                raise ValueError("Common full recovery physical files are missing")
        if not (directory / "final-manifest.txt").is_file():
            raise ValueError("Common full recovery final manifest is missing")
        states = (directory / "voter-states-before-cleanup.txt").read_text().splitlines()
        expected = {"second-return-a": "alive", "return-b": "alive", "return-a": "exit=137",
                    "original-b": "exit=137", "original-a": "exit=137", "witness": "alive"}
        if len(states) != len(expected) or dict(line.split(" ", 1) for line in states) != expected:
            raise ValueError("Common full recovery voters did not retain the expected physical lifecycles")
        recovery_evidence = evidence_hashes(directory)
    interrupted = lines.count(INTERRUPTED) == 1 and log.find(INTERRUPTED) < both[0].start()
    if os.environ.get("MAC_DEMO_REQUIRE_INTERRUPTED_RETURN") == "true" and not interrupted:
        raise ValueError("Common physical test is missing the interrupted signed Stage recovery")
    seal = {"common_revision": revision, "common_sha256": digest,
            "fixture_revision": identity_lines[2].split("=", 1)[1],
            "transcript_sha256": hashlib.sha256(log_bytes).hexdigest(),
            "equal_wal_pairs_per_verification": 256, "equal_snapshot_pairs_per_verification": 256,
            "both_directions_and_repeated_home": True, "interrupted_local_rearm": interrupted,
            "normal_dual_async": {"normal-dual-async", "normal-dual-async-primary-kill",
                                  "normal-dual-async-backup-expiry"}.issubset(poison_evidence),
            "normal_dual_async_max_pending_per_partition": 1,
            "normal_dual_async_recovery_head": "backup_certified_committed",
            "live_poison_recovery_evidence": poison_evidence,
            "full_recovery_physical_evidence": recovery_evidence}
    if (result / "status").read_text().strip() not in {"NO_GO", "PASS"}:
        raise ValueError("Unexpected initial Common verification status")
    temporary = result / "seal.tmp"
    temporary.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n")
    temporary.replace(result / "verification.seal.json")
    temporary = result / "status.tmp"
    temporary.write_text("PASS\n")
    temporary.replace(result / "status")
    print(f"Common physical result verified: {result}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))
