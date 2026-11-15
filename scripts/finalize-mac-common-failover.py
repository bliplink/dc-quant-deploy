#!/usr/bin/env python3
"""Seal a completed, successful Common drill against its original candidate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import zlib


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
COLD_BATCH_TAIL_ACK = re.compile(
    r"^[.]*T554_BOTH_COLD_UNCERTIFIED_64_COMMAND_GROUP_RETAINED_HOME_ACK_PASS$", re.M)
NORMAL_ASYNC_ACK = re.compile(
    r"^[.]*T554_NORMAL_DUAL_ASYNC_BACKUP_OUTAGE_PRESERVES_LOCAL_ACK_PASS "
    r"sameEpoch=2 bothCommittedHeads=2 appliedOnce=true originalRisk=true$", re.M)
NORMAL_ASYNC_PIPELINE = re.compile(
    r"^[.]*T554_NORMAL_DUAL_ASYNC_64_LOCAL_ACKS_REAL_TCP_CUMULATIVE_CATCHUP_PASS "
    r"sameEpoch=2 bothCommittedHeads=65 appliedOnce=true originalRisk=true$", re.M)
NORMAL_ASYNC_KILL = re.compile(
    r"^[.]*T554_NORMAL_DUAL_ASYNC_PRIMARY_SIGKILL_AFTER_LOCAL_ACK_REAL_WITNESS_HOME_PASS "
    r"backupCommittedHead=1 abandonedLocalHead=2 originalPrimaryWalUnchanged=true "
    r"backupCommittedPrefixUnchanged=true inflightTailExcluded=true home128Each=true$", re.M)
NORMAL_ASYNC_KILL_CUMULATIVE = re.compile(
    r"^[.]*T554_NORMAL_DUAL_ASYNC_PRIMARY_SIGKILL_AFTER_LOCAL_ACK_REAL_WITNESS_HOME_PASS "
    r"backupCommittedHead=[12] originalLocalHead=2 originalPrimaryWalUnchanged=true "
    r"backupCommittedPrefixUnchanged=true uncommittedTailExcluded=true home128Each=true$", re.M)
NORMAL_ASYNC_PIPELINE_KILL = re.compile(
    r"^[.]*T554_NORMAL_DUAL_ASYNC_64_PRIMARY_SIGKILL_REAL_WITNESS_HOME_PASS "
    r"backupCommittedHead=([1-9][0-9]*) originalLocalHead=65 originalPrimaryWalUnchanged=true "
    r"backupCommittedPrefixUnchanged=true uncommittedTailExcluded=true home128Each=true$", re.M)
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
    frontier = directory / "authenticated-fixture-frontier-P000-2.txt"
    if frontier.exists():
        parsed = re.fullmatch(r"head=([12]) sha256=([a-f0-9]{64})\n", frontier.read_text())
        if not parsed:
            raise ValueError("Missing exact authenticated async recovery frontier")
        head = int(parsed[1])
        committed = prefix if head == 1 else original
        if (hashlib.sha256(committed).hexdigest() != parsed[2]
                or head == 2 and backup != original):
            raise ValueError("Async recovery frontier differs from its actual committed bytes")
        stream = directory / "data-b/DemoSvr/DemoSvrB/P000/epoch-2/commit-index/commits.wal"
        raw = stream.read_bytes()
        if len(raw) < 8 or struct.unpack_from(">II", raw) != (0x4f544353, 2):
            raise ValueError("Async recovery did not retain its cumulative commit stream")
        cursor, prior, highest = 8, 0, None
        while cursor < len(raw):
            if len(raw) - cursor < 8:
                raise ValueError("Async qualification requires a complete original commit stream")
            size, crc = struct.unpack_from(">II", raw, cursor)
            record = raw[cursor + 8:cursor + 8 + size]
            if not 10 <= size <= 32768 or len(record) != size or zlib.crc32(record) != crc:
                raise ValueError("Changed async cumulative commit record")
            if struct.unpack_from(">II", record) != (0x4f544357, 2):
                raise ValueError("Wrong async cumulative commit model")
            offset = 10 + struct.unpack_from(">H", record, 8)[0]
            if len(record) < offset + 26:
                raise ValueError("Truncated async cumulative commit metadata")
            epoch, sequence, previous = struct.unpack_from(">qqq", record, offset)
            sha_length = struct.unpack_from(">H", record, offset + 24)[0]
            prefix_sha = record[offset + 26:offset + 26 + sha_length]
            if epoch != 2 or sequence != prior + 1 or previous != prior or sequence > 2:
                raise ValueError("Async original cumulative commit chain changed")
            prior, highest = sequence, prefix_sha
            cursor += size + 8
        if prior != head or highest != parsed[2].encode("ascii"):
            raise ValueError("Reported async recovery frontier is not the original persisted head")


def verify_live_role_census(directory):
    sessions = []
    for node in ("DemoSvrA", "DemoSvrB"):
        proof = (directory / (node + ".actual-role-proof")).read_text()
        match = re.fullmatch(r"session=([1-9]\d*) roles=256 writers=128\n", proof)
        if not match:
            raise ValueError("Returned Common voter lacks all actual physical roles and writers")
        sessions.append(match[1])
    if (sessions[0] == sessions[1]
            or (directory / "voter-states-before-cleanup.txt").read_text()
               != "survivor=alive returned=alive stableMillis=2000\n"):
        raise ValueError("Returned Common voters did not retain independent stable live processes")


def cumulative_record_metadata(raw, epoch, partition, nodes):
    """Check the actual model and chain after Java's RSA verification.
    This metadata audit cannot authorize a commit, an ACK or READY."""
    if len(raw) < 8 or struct.unpack_from(">II", raw) != (0x4f544353, 2):
        raise ValueError("Actual runtime did not use the cumulative V2 stream")
    def utf(data, offset):
        if len(data) - offset < 2:
            raise ValueError("Truncated cumulative metadata string")
        size = struct.unpack_from(">H", data, offset)[0]
        if len(data) - offset - 2 < size:
            raise ValueError("Truncated cumulative metadata value")
        return data[offset + 2:offset + 2 + size].decode("ascii"), offset + 2 + size
    position, previous, previous_hash, records = 8, 0, "GENESIS", []
    while position < len(raw):
        if len(raw) - position < 8:
            raise ValueError("Incomplete actual runtime commit stream")
        size, crc = struct.unpack_from(">II", raw, position)
        body = raw[position + 8:position + 8 + size]
        if not 10 <= size <= 32768 or len(body) != size or zlib.crc32(body) != crc:
            raise ValueError("Changed actual cumulative frame")
        if struct.unpack_from(">II", body) != (0x4f544357, 2):
            raise ValueError("Legacy evidence found in cumulative runtime")
        member, offset = utf(body, 8)
        if not re.fullmatch(r"[a-f0-9]{64}", member) or len(body) - offset < 24:
            raise ValueError("Invalid cumulative runtime membership")
        e, seq, prior = struct.unpack_from(">qqq", body, offset)
        prefix, offset = utf(body, offset + 24)
        prior_hash, offset = utf(body, offset)
        if (e != epoch or not previous < seq <= previous + 64 or prior != previous
                or prior_hash != previous_hash or not re.fullmatch(r"[a-f0-9]{64}", prefix)
                or len(body) - offset < 4 or struct.unpack_from(">I", body, offset)[0] != 2):
            raise ValueError("Cumulative runtime chain or original frontier mismatch")
        offset += 4
        voters = set()
        for _ in range(2):
            if len(body) - offset < 4:
                raise ValueError("Missing actual cumulative voter")
            count = struct.unpack_from(">I", body, offset)[0]
            vote = body[offset + 4:offset + 4 + count]
            offset += 4 + count
            if not 4 <= count <= 4096 or len(vote) != count or struct.unpack_from(">I", vote)[0] != 2:
                raise ValueError("Actual cumulative WAL vote has another signing model")
            node, at = utf(vote, 4)
            part, at = utf(vote, at)
            if len(vote) - at < 16:
                raise ValueError("Truncated cumulative voter frontier")
            ve, vs = struct.unpack_from(">qq", vote, at)
            vh, at = utf(vote, at + 16)
            vm, at = utf(vote, at)
            if len(vote) - at < 4:
                raise ValueError("Missing original cumulative voter signature")
            signature = struct.unpack_from(">I", vote, at)[0]
            if (node not in nodes or node in voters or part != partition or (ve, vs) != (epoch, seq)
                    or vh != prefix or vm != member or not 0 < signature <= 1024
                    or len(vote) != at + 4 + signature):
                raise ValueError("Actual cumulative voter metadata does not bind its original commit")
            voters.add(node)
        if voters != nodes or offset != len(body):
            raise ValueError("Incomplete or trailing cumulative physical evidence")
        records.append((seq, prefix))
        previous, previous_hash = seq, hashlib.sha256(body).hexdigest()
        position += size + 8
    return records


def verify_cumulative_runtime_evidence(directory):
    indexes = {}
    for side in ("a", "b"):
        files = list(directory.glob("data-" + side + "/*/*/P[0-9][0-9][0-9]/epoch-2/commit-index/commits.wal"))
        if ({p.parents[2].name for p in files} != {"P%03d" % i for i in range(256)}
                or len(files) != 256 or len({p.parents[3].name for p in files}) != 1):
            raise ValueError("Full actual runtime lacks 256 original cumulative indexes per voter")
        indexes[side] = files
    nodes = {files[0].parents[3].name for files in indexes.values()}
    if len(nodes) != 2:
        raise ValueError("Cumulative runtime needs two actual physical voter identities")
    nonempty, record_count = 0, 0
    for files in indexes.values():
        for stream in files:
            epoch, part = stream.parents[1], stream.parents[2].name
            if (stream.is_symlink() or {p.name for p in stream.parent.iterdir()} != {".commit-writer.lock", "commits.wal"}
                    or any((epoch / old).exists() for old in ("custody/head.bin", "custody-ledger/receipt-quorum.bin"))):
                raise ValueError("Cumulative runtime mixed legacy commit evidence")
            records = cumulative_record_metadata(stream.read_bytes(), 2, part, nodes)
            nonempty += bool(records)
            record_count += len(records)
            remaining = dict(records)
            digest, sequence = hashlib.sha256(), 0
            with (epoch / "business.wal").open("rb") as original:
                while True:
                    header = original.read(28)
                    if not header:
                        break
                    if len(header) != 28:
                        raise ValueError("Actual original runtime WAL has an incomplete frame")
                    magic, e, seq, size, crc = struct.unpack(">IqqII", header)
                    if magic != 0x43425731 or e != 2 or seq != sequence + 1 or not 0 < size <= 1024 * 1024:
                        raise ValueError("Actual original runtime WAL framing changed")
                    payload = original.read(size)
                    if len(payload) != size or zlib.crc32(struct.pack(">qq", e, seq) + payload) != crc:
                        raise ValueError("Actual original runtime WAL CRC changed")
                    digest.update(header); digest.update(payload); sequence = seq
                    if seq in remaining and remaining.pop(seq) != digest.hexdigest():
                        raise ValueError("Actual cumulative runtime index differs from original WAL")
            if remaining:
                raise ValueError("Actual cumulative runtime index exceeds its physical WAL")
    if nonempty < 2:
        raise ValueError("Actual cumulative runtime has not physically committed business on both copies")
    return {"model": "CUMULATIVE_V2", "original_epoch2_indexes": 512,
            "nonempty_indexes": nonempty, "verified_metadata_records": record_count,
            "nodes": sorted(nodes), "raw_wal_prefixes_matched": True,
            "scope": "Actual process artifacts; RSA/role/fencing proof remains the preceding real Java drill."}


def verify_cold_batch_prefixes(directory):
    """Consistency audit after the real Java RSA/fencing drill, not an
    independent signature verifier or a substitute for that successful drill."""
    originals = []
    for side, node in (("a", "DemoSvrA"), ("b", "DemoSvrB")):
        epoch = directory / ("data-" + side) / "DemoSvr" / node / "P000/epoch-4"
        raw = (epoch / "business.wal").read_bytes()
        position, first_end = 0, 0
        for sequence in range(1, 66):
            if len(raw) - position < 28:
                raise ValueError("Missing original cold batch WAL frame")
            magic, old_epoch, seq, size, crc = struct.unpack_from(">IqqII", raw, position)
            payload = raw[position + 28:position + 28 + size]
            if (magic != 0x43425731 or old_epoch != 4 or seq != sequence
                    or not 0 < size <= 1024 * 1024 or len(payload) != size
                    or zlib.crc32(struct.pack(">qq", old_epoch, seq) + payload) != crc
                    or payload != (bytes((5, 3, 5)) if sequence == 1 else bytes((99, 98, 97)))):
                raise ValueError("Changed or invalid original cold batch WAL bytes")
            position += 28 + size
            if sequence == 1:
                first_end = position
        if position != len(raw):
            raise ValueError("Cold batch tail exceeds its exact 64-command bound")
        prefix = hashlib.sha256(raw[:first_end]).hexdigest()
        commit = (epoch / "commit-index/commits.wal").read_bytes()
        if len(commit) < 16 or struct.unpack_from(">II", commit) != (0x4f544353, 2):
            raise ValueError("Missing cumulative commit stream for cold batch")
        size, crc = struct.unpack_from(">II", commit, 8)
        record = commit[16:]
        if not 0 < size <= 32768 or len(record) != size or zlib.crc32(record) != crc:
            raise ValueError("Invalid cold batch original cumulative commit record")
        if len(record) < 10 or struct.unpack_from(">II", record) != (0x4f544357, 2):
            raise ValueError("Wrong cold batch cumulative proof model")
        membership_length = struct.unpack_from(">H", record, 8)[0]
        offset = 10 + membership_length
        if len(record) < offset + 26 or struct.unpack_from(">qqq", record, offset) != (4, 1, 0):
            raise ValueError("Uncertified cold batch tail became a cumulative commit")
        sha_length = struct.unpack_from(">H", record, offset + 24)[0]
        if record[offset + 26:offset + 26 + sha_length] != prefix.encode("ascii"):
            raise ValueError("Cold batch committed prefix differs from original WAL")
        originals.append((raw, commit, prefix))
    if originals[0] != originals[1]:
        raise ValueError("Cold batch physical originals differ between voters")
    expected = "committed=1 originalA=65 originalB=65 sha256=" + originals[0][2] + "\n"
    if (directory / "authenticated-fixture-prefix-P000-4.txt").read_text() != expected:
        raise ValueError("Missing authenticated cold batch recovery frontier")
    for name in ("a-cold-home-business-proof", "b-cold-home-business-proof"):
        if not (directory / name).is_file():
            raise ValueError("Cold batch did not prove both actual recovered business roles")


def async_pipeline_frame_ends(raw, expected_frames=65):
    position, ends = 0, {}
    for sequence in range(1, expected_frames + 1):
        if len(raw) - position < 28:
            raise ValueError("Incomplete original async pipeline WAL")
        magic, e, seq, size, crc = struct.unpack_from(">IqqII", raw, position)
        payload = raw[position + 28:position + 28 + size]
        if (magic != 0x43425731 or e != 2 or seq != sequence or not 0 < size <= 1024 * 1024
                or len(payload) != size or zlib.crc32(struct.pack(">qq", e, seq) + payload) != crc
                or payload != (bytes((5, 3, 5)) if sequence == 1 else bytes((99, 98, 97)))):
            raise ValueError("Async pipeline original sequence or payload changed")
        position += 28 + size
        ends[sequence] = position
    if position != len(raw):
        raise ValueError("Async pipeline exceeded its original 64-command suffix")
    return ends

def verify_async_pipeline_prefixes(directory):
    """Post-drill byte/model audit only; original Java validates RSA and grants."""
    originals = []
    for side, node in (("a", "DemoSvrA"), ("b", "DemoSvrB")):
        epoch = directory / ("data-" + side) / "DemoSvr" / node / "P000/epoch-2"
        raw = (epoch / "business.wal").read_bytes()
        ends = async_pipeline_frame_ends(raw)
        commit = (epoch / "commit-index/commits.wal").read_bytes()
        heads = cumulative_record_metadata(commit, 2, "P000", {"DemoSvrA", "DemoSvrB"})
        if (not heads or heads[-1][0] != 65
                or any(seq not in ends or hashlib.sha256(raw[:ends[seq]]).hexdigest() != prefix
                       for seq, prefix in heads)):
            raise ValueError("Async pipeline cumulative proof does not cover original bytes")
        originals.append((raw, commit))
    if originals[0] != originals[1]:
        raise ValueError("Async pipeline actual physical copies differ")


def verify_async_pipeline_primary_prefixes(directory):
    """Supplement the real Java full-queue crash proof with original-byte checks."""
    original = (directory / 'a-original-local-acked.wal').read_bytes()
    ends = async_pipeline_frame_ends(original)
    prefix = (directory / 'b-original-committed-prefix.wal').read_bytes()
    if prefix != original[:ends[1]] or not (directory / 'a-home-business-proof').is_file():
        raise ValueError('Full queue lacks its original quorum prefix or recovered business proof')
    receipt = (directory / 'a-local-acked-before-peer').read_text().strip()
    if receipt != 'LOCAL_DURABLE_ASYNC P000 2 65 rpoRisk=true':
        raise ValueError('Full queue lacks all 64 original LOCAL acknowledgments')
    frontier = re.fullmatch(r'head=([1-9][0-9]*) sha256=([a-f0-9]{64})\n',
                            (directory / 'authenticated-fixture-frontier-P000-2.txt').read_text())
    if not frontier or int(frontier[1]) not in ends:
        raise ValueError('Full queue lacks an authenticated bounded backup frontier')
    for side, node in (('a', 'DemoSvrA'), ('b', 'DemoSvrB')):
        epoch = directory / ('data-' + side) / 'DemoSvr' / node / 'P000/epoch-2'
        raw = (epoch / 'business.wal').read_bytes()
        if side == 'a':
            if raw != original:
                raise ValueError('Full queue original primary WAL changed after its crash')
        elif (len(raw) not in ends.values() or raw != original[:len(raw)]
              or len(raw) < ends[int(frontier[1])]):
            raise ValueError('Full queue backup has a foreign, incomplete or missing original prefix')
        records = cumulative_record_metadata((epoch / 'commit-index/commits.wal').read_bytes(),
                                              2, 'P000', {'DemoSvrA', 'DemoSvrB'})
        if (not records or any(seq not in ends or ends[seq] > len(raw)
                              or hashlib.sha256(raw[:ends[seq]]).hexdigest() != digest
                              for seq, digest in records)):
            raise ValueError('Full queue actual commit index differs from its original WAL')
        if side == 'b' and records[-1] != (int(frontier[1]), frontier[2]):
            raise ValueError('Full queue recovery frontier differs from its original persisted head')


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
        if "bothColdVotersKeepAnUncertifiedSixtyFourCommandGroupOutsideReplay" in poison_source.read_text():
            scenarios.append("cold-strict-batch-tails")
            if len(COLD_BATCH_TAIL_ACK.findall(log)) != 1:
                raise ValueError("Common 64-command cold tail recovery lacks its complete physical proof")
        if "normalDualAsyncBackupOutageRetainsLocallyAcknowledgedWrites" in poison_source.read_text():
            scenarios.append("normal-dual-async")
            if len(NORMAL_ASYNC_ACK.findall(log)) != 1:
                raise ValueError("Common normal async physical ACK and prefix recovery evidence is incomplete")
        if "normalDualAsyncSixtyFourLocalAcksCatchUpOnTheOriginalPhysicalVoters" in poison_source.read_text():
            scenarios.append("normal-dual-async-pipeline-64")
            if len(NORMAL_ASYNC_PIPELINE.findall(log)) != 1:
                raise ValueError("Common bounded async pipeline lacks its real physical catchup proof")
        if "normalDualAsyncPrimaryKilledAfterLocalAckReturnsThroughRealWitnessedRecovery" in poison_source.read_text():
            scenarios.append("normal-dual-async-primary-kill")
            cumulative_marker = '" originalLocalHead=2 originalPrimaryWalUnchanged=true"' in poison_source.read_text()
            expected_kill_marker = NORMAL_ASYNC_KILL_CUMULATIVE if cumulative_marker else NORMAL_ASYNC_KILL
            if len(expected_kill_marker.findall(log)) != 1:
                raise ValueError("Common normal async primary SIGKILL and witnessed Home proof is incomplete")
        if "normalDualAsyncFullQueuePrimaryKilledReturnsOnlyTheAuthenticatedBackupPrefix" in poison_source.read_text():
            scenarios.append("normal-dual-async-pipeline-64-primary-kill")
            markers = NORMAL_ASYNC_PIPELINE_KILL.findall(log)
            if len(markers) != 1 or not 1 <= int(markers[0]) <= 65:
                raise ValueError("Common full async queue primary crash proof is incomplete")
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
            if ('require-final-actual-roles' in poison_source.read_text()
                    and scenario in {"node-lease-expiry", "graceful-shutdown"}):
                verify_live_role_census(directory)
            if scenario == "node-lease-expiry":
                events = (directory / "supervisor-events.txt").read_text().splitlines()
                original = (directory / "DemoSvrB.attempt-0.log").read_text()
                if (not events or events[0] != "attempt=0 exit=78"
                        or "FATAL_COMMON_NODE_EPOCH_FENCED exiting JVM (78)" not in original):
                    raise ValueError("Common expired node did not exit through the physical process lifecycle")
            if scenario == "cold-strict-batch-tails":
                verify_cold_batch_prefixes(directory)
            if scenario == "graceful-shutdown":
                events = (directory / "supervisor-events.txt").read_text().splitlines()
                if not events or events[0] != "attempt=0 exit=143":
                    raise ValueError("Common graceful shutdown did not retain its original physical exit")
                if "LOCAL_DURABLE_ASYNC" not in (directory / "r-first-ack.txt").read_text():
                    raise ValueError("Common survivor did not continue durably before graceful voter return")
            if scenario.startswith("normal-dual-async"):
                receipt = (directory / "a-local-acked-before-peer").read_text().strip()
                expected_head = 65 if scenario.startswith("normal-dual-async-pipeline-64") else 2
                if receipt != f"LOCAL_DURABLE_ASYNC P000 2 {expected_head} rpoRisk=true":
                    raise ValueError("Common normal async original LOCAL receipt is missing")
                if scenario == "normal-dual-async-pipeline-64":
                    verify_async_pipeline_prefixes(directory)
                if (scenario.endswith("primary-kill")
                        and not (directory / "DemoSvrA.attempt-0.log").is_file()):
                    raise ValueError("Common normal async killed primary log is missing")
                if scenario == "normal-dual-async-pipeline-64-primary-kill":
                    verify_async_pipeline_primary_prefixes(directory)
                elif scenario.endswith("primary-kill"):
                    if cumulative_marker and not (directory / "authenticated-fixture-frontier-P000-2.txt").is_file():
                        raise ValueError("Common cumulative async recovery lacks its actual authenticated frontier")
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
    cumulative_model = None
    if (result / "source/src/main/java/com/app/common/replication/DurableWalCumulativeCommitProtocol.java").is_file():
        cumulative_model = verify_cumulative_runtime_evidence(result / "process-evidence")
    seal = {"common_revision": revision, "common_sha256": digest,
            "fixture_revision": identity_lines[2].split("=", 1)[1],
            "transcript_sha256": hashlib.sha256(log_bytes).hexdigest(),
            "equal_wal_pairs_per_verification": 256, "equal_snapshot_pairs_per_verification": 256,
            "both_directions_and_repeated_home": True, "interrupted_local_rearm": interrupted,
            "normal_dual_async": {"normal-dual-async", "normal-dual-async-primary-kill",
                                  "normal-dual-async-backup-expiry"}.issubset(poison_evidence),
            "normal_dual_async_max_pending_per_partition": 64 if "normal-dual-async-pipeline-64" in poison_evidence else 1,
            "normal_dual_async_pipeline_physical_proof": "normal-dual-async-pipeline-64" in poison_evidence,
            "normal_dual_async_full_queue_primary_crash": "normal-dual-async-pipeline-64-primary-kill" in poison_evidence,
            "normal_dual_async_recovery_head": "backup_certified_committed",
            "live_poison_recovery_evidence": poison_evidence,
            "full_recovery_physical_evidence": recovery_evidence,
            "actual_cumulative_runtime_evidence": cumulative_model}
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
