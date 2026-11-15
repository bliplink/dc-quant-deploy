import hashlib
from pathlib import Path
import runpy
import struct
import tempfile
import unittest
import zlib


SEAL = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/finalize-mac-common-failover.py'))


class PhysicalEvidenceSealTest(unittest.TestCase):
    def test_async_pipeline_checks_original_65_frames_and_both_cumulative_copies(self):
        # Synthetic format audit only. Dummy signatures do not authorize any
        # commit, customer ACK or real P0 result.
        def utf(value):
            raw = value.encode('ascii')
            return struct.pack('>H', len(raw)) + raw
        frames = []
        for seq in range(1, 66):
            payload = bytes((5, 3, 5)) if seq == 1 else bytes((99, 98, 97))
            frames.append(struct.pack('>IqqII', 0x43425731, 2, seq, len(payload),
                                      zlib.crc32(struct.pack('>qq', 2, seq) + payload)) + payload)
        wal = b''.join(frames)
        previous, prior_hash = 0, 'GENESIS'
        stream = struct.pack('>II', 0x4f544353, 2)
        for seq in (1, 65):
            prefix = hashlib.sha256(b''.join(frames[:seq])).hexdigest()
            votes = []
            for node in ('DemoSvrA', 'DemoSvrB'):
                votes.append(struct.pack('>I', 2) + utf(node) + utf('P000') + struct.pack('>qq', 2, seq)
                             + utf(prefix) + utf('a' * 64) + struct.pack('>I', 256) + bytes(256))
            body = (struct.pack('>II', 0x4f544357, 2) + utf('a' * 64) + struct.pack('>qqq', 2, seq, previous)
                    + utf(prefix) + utf(prior_hash) + struct.pack('>I', 2)
                    + b''.join(struct.pack('>I', len(vote)) + vote for vote in votes))
            stream += struct.pack('>II', len(body), zlib.crc32(body)) + body
            previous, prior_hash = seq, hashlib.sha256(body).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = []
            for side, node in (('a', 'DemoSvrA'), ('b', 'DemoSvrB')):
                epoch = root / ('data-' + side) / 'DemoSvr' / node / 'P000/epoch-2'
                (epoch / 'commit-index').mkdir(parents=True)
                (epoch / 'business.wal').write_bytes(wal)
                (epoch / 'commit-index/commits.wal').write_bytes(stream)
                paths.append(epoch)
            SEAL['verify_async_pipeline_prefixes'](root)
            for bad in (wal[:-1], wal + frames[-1], bytes((wal[0] ^ 1,)) + wal[1:]):
                (paths[1] / 'business.wal').write_bytes(bad)
                with self.subTest(bytes=len(bad)), self.assertRaises(ValueError):
                    SEAL['verify_async_pipeline_prefixes'](root)
            (paths[1] / 'business.wal').write_bytes(wal)
            (paths[1] / 'commit-index/commits.wal').write_bytes(struct.pack('>II', 0x4f544353, 2))
            with self.assertRaises(ValueError):
                SEAL['verify_async_pipeline_prefixes'](root)
            # Full-queue crash audit accepts the actual retained frontier,
            # including legal late delivery, and rejects a claimed longer head.
            first_end = 16 + struct.unpack_from('>I', stream, 8)[0]
            first_stream = stream[:first_end]
            (paths[0] / 'commit-index/commits.wal').write_bytes(first_stream)
            (root / 'a-original-local-acked.wal').write_bytes(wal)
            (root / 'b-original-committed-prefix.wal').write_bytes(frames[0])
            (root / 'a-home-business-proof').touch()
            (root / 'a-local-acked-before-peer').write_text('LOCAL_DURABLE_ASYNC P000 2 65 rpoRisk=true\n')
            for head, committed in ((1, first_stream), (65, stream)):
                raw = b''.join(frames[:head])
                (paths[1] / 'business.wal').write_bytes(raw)
                (paths[1] / 'commit-index/commits.wal').write_bytes(committed)
                frontier = root / 'authenticated-fixture-frontier-P000-2.txt'
                frontier.write_text('head=' + str(head) + ' sha256=' + hashlib.sha256(raw).hexdigest() + '\n')
                SEAL['verify_async_pipeline_primary_prefixes'](root)
                frontier.write_text('head=66 sha256=' + hashlib.sha256(raw).hexdigest() + '\n')
                with self.assertRaises(ValueError):
                    SEAL['verify_async_pipeline_primary_prefixes'](root)
                frontier.write_text('head=' + str(head) + ' sha256=' + hashlib.sha256(raw).hexdigest() + '\n')
                (paths[1] / 'business.wal').write_bytes(raw[:-1])
                with self.assertRaises(ValueError):
                    SEAL['verify_async_pipeline_primary_prefixes'](root)

    def test_actual_cumulative_model_rejects_legacy_or_mismatched_vote_metadata(self):
        # Format/chain checks only; dummy signatures never supply RSA authority.
        member, prefix, nodes = 'a' * 64, 'b' * 64, {'A', 'B'}
        def utf(value):
            raw = value.encode('ascii')
            return struct.pack('>H', len(raw)) + raw
        def vote(node, version=2, part='P000', digest=prefix):
            return (struct.pack('>I', version) + utf(node) + utf(part) + struct.pack('>qq', 2, 1)
                    + utf(digest) + utf(member) + struct.pack('>I', 256) + bytes(256))
        def stream(first, second, version=2):
            body = (struct.pack('>II', 0x4f544357, version) + utf(member) + struct.pack('>qqq', 2, 1, 0)
                    + utf(prefix) + utf('GENESIS') + struct.pack('>I', 2)
                    + struct.pack('>I', len(first)) + first + struct.pack('>I', len(second)) + second)
            return struct.pack('>II', 0x4f544353, 2) + struct.pack('>II', len(body), zlib.crc32(body)) + body
        good = stream(vote('A'), vote('B'))
        self.assertEqual([(1, prefix)], SEAL['cumulative_record_metadata'](good, 2, 'P000', nodes))
        bad_cases = [stream(vote('A'), vote('B'), version=1),
                     stream(vote('A', version=1), vote('B')), stream(vote('A'), vote('A')),
                     stream(vote('A'), vote('B', part='P001')),
                     stream(vote('A'), vote('B', digest='c' * 64)), good + b'partial']
        for raw in bad_cases:
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                SEAL['cumulative_record_metadata'](raw, 2, 'P000', nodes)

    def test_cold_batch_consistency_requires_exact_retained_tail_and_committed_frontier(self):
        # Synthetic local files exercise only the post-drill consistency
        # checker. They carry no RSA authority and cannot qualify a real P0.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frames = []
            for seq in range(1, 66):
                raw = bytes((5, 3, 5)) if seq == 1 else bytes((99, 98, 97))
                crc = zlib.crc32(struct.pack('>qq', 4, seq) + raw)
                frames.append(struct.pack('>IqqII', 0x43425731, 4, seq, len(raw), crc) + raw)
            wal = b''.join(frames)
            prefix = hashlib.sha256(frames[0]).hexdigest()
            def utf(value):
                raw = value.encode('ascii')
                return struct.pack('>H', len(raw)) + raw
            record = (struct.pack('>II', 0x4f544357, 2) + utf('a' * 64)
                      + struct.pack('>qqq', 4, 1, 0) + utf(prefix) + utf('GENESIS') + struct.pack('>I', 0))
            commit = (struct.pack('>II', 0x4f544353, 2)
                      + struct.pack('>II', len(record), zlib.crc32(record)) + record)
            originals = []
            for side, node in (('a', 'DemoSvrA'), ('b', 'DemoSvrB')):
                epoch = root / ('data-' + side) / 'DemoSvr' / node / 'P000/epoch-4'
                (epoch / 'commit-index').mkdir(parents=True)
                original = epoch / 'business.wal'
                original.write_bytes(wal)
                (epoch / 'commit-index/commits.wal').write_bytes(commit)
                originals.append(original)
            frontier = root / 'authenticated-fixture-prefix-P000-4.txt'
            frontier.write_text('committed=1 originalA=65 originalB=65 sha256=' + prefix + '\n')
            for name in ('a-cold-home-business-proof', 'b-cold-home-business-proof'):
                (root / name).touch()
            SEAL['verify_cold_batch_prefixes'](root)
            for bad in (wal[:-1], b''.join(frames[:64]), wal + frames[-1], bytes((wal[0] ^ 1,)) + wal[1:]):
                originals[1].write_bytes(bad)
                with self.subTest(tail_bytes=len(bad)), self.assertRaises(ValueError):
                    SEAL['verify_cold_batch_prefixes'](root)
            originals[1].write_bytes(wal)
            frontier.write_text('committed=65 originalA=65 originalB=65 sha256=' + prefix + '\n')
            with self.assertRaises(ValueError):
                SEAL['verify_cold_batch_prefixes'](root)

    def test_cold_batch_proof_marker_cannot_be_replaced_by_single_tail_case(self):
        marker = 'T554_BOTH_COLD_UNCERTIFIED_64_COMMAND_GROUP_RETAINED_HOME_ACK_PASS'
        self.assertIsNotNone(SEAL['COLD_BATCH_TAIL_ACK'].search('..' + marker + '\n'))
        self.assertIsNone(SEAL['COLD_BATCH_TAIL_ACK'].search(marker + ' incomplete\n'))
        self.assertIsNone(SEAL['COLD_TAIL_ACK'].search(marker + '\n'))

    def test_returned_voters_need_distinct_live_actual_roles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'DemoSvrA.actual-role-proof').write_text('session=1 roles=256 writers=128\n')
            (root / 'DemoSvrB.actual-role-proof').write_text('session=2 roles=256 writers=128\n')
            state = root / 'voter-states-before-cleanup.txt'
            state.write_text('survivor=alive returned=alive stableMillis=2000\n')
            SEAL['verify_live_role_census'](root)
            for bad in ('session=1 roles=256 writers=128\n', 'session=2 roles=255 writers=128\n',
                        'session=2 roles=256 writers=127\n'):
                (root / 'DemoSvrB.actual-role-proof').write_text(bad)
                with self.assertRaises(ValueError):
                    SEAL['verify_live_role_census'](root)
            (root / 'DemoSvrB.actual-role-proof').write_text('session=2 roles=256 writers=128\n')
            state.write_text('survivor=alive returned=dead stableMillis=2000\n')
            with self.assertRaises(ValueError):
                SEAL['verify_live_role_census'](root)

    def test_normal_async_backup_expiry_requires_exact_survivor_proof(self):
        marker = 'T554_NORMAL_DUAL_ASYNC_BACKUP_EXPIRY_PRESERVES_ACK_AND_CONTINUES_PASS'
        self.assertIsNotNone(SEAL['NORMAL_ASYNC_BACKUP_EXPIRY'].search('..' + marker + '\n'))
        self.assertIsNone(SEAL['NORMAL_ASYNC_BACKUP_EXPIRY'].search(marker + ' pending\n'))

    def test_mixed_strict_tail_proof_cannot_be_replaced_by_older_async_marker(self):
        marker = 'T554_NORMAL_DUAL_ASYNC_BACKUP_EXPIRY_PRESERVES_ACK_AND_EXCLUDES_STRICT_TAIL_PASS'
        older = 'T554_NORMAL_DUAL_ASYNC_BACKUP_EXPIRY_PRESERVES_ACK_AND_CONTINUES_PASS'
        self.assertIsNotNone(SEAL['NORMAL_ASYNC_MIXED_STRICT_TAIL'].search('..' + marker + '\n'))
        self.assertIsNone(SEAL['NORMAL_ASYNC_MIXED_STRICT_TAIL'].search(marker + ' incomplete\n'))
        self.assertIsNone(SEAL['NORMAL_ASYNC_MIXED_STRICT_TAIL'].search(older + '\n'))
        self.assertIsNone(SEAL['NORMAL_ASYNC_BACKUP_EXPIRY'].search(marker + '\n'))

    def test_normal_async_ack_and_kill_require_complete_proof_markers(self):
        markers = {
            'NORMAL_ASYNC_ACK': ('T554_NORMAL_DUAL_ASYNC_BACKUP_OUTAGE_PRESERVES_LOCAL_ACK_PASS '
                                 'sameEpoch=2 bothCommittedHeads=2 appliedOnce=true originalRisk=true'),
            'NORMAL_ASYNC_KILL': ('T554_NORMAL_DUAL_ASYNC_PRIMARY_SIGKILL_AFTER_LOCAL_ACK_REAL_WITNESS_HOME_PASS '
                                  'backupCommittedHead=1 abandonedLocalHead=2 originalPrimaryWalUnchanged=true '
                                  'backupCommittedPrefixUnchanged=true inflightTailExcluded=true home128Each=true'),
        }
        for name, marker in markers.items():
            with self.subTest(marker=name):
                self.assertIsNotNone(SEAL[name].search('...' + marker + '\n'))
                self.assertIsNone(SEAL[name].search(marker + ' incomplete\n'))

    def test_cumulative_async_loss_marker_preserves_the_actual_backup_frontier(self):
        for head in (1, 2):
            marker = ('T554_NORMAL_DUAL_ASYNC_PRIMARY_SIGKILL_AFTER_LOCAL_ACK_REAL_WITNESS_HOME_PASS '
                      'backupCommittedHead=' + str(head) + ' originalLocalHead=2 originalPrimaryWalUnchanged=true '
                      'backupCommittedPrefixUnchanged=true uncommittedTailExcluded=true home128Each=true')
            self.assertIsNotNone(SEAL['NORMAL_ASYNC_KILL_CUMULATIVE'].search('..' + marker + '\n'))
            self.assertIsNone(SEAL['NORMAL_ASYNC_KILL'].search(marker + '\n'))
            self.assertIsNone(SEAL['NORMAL_ASYNC_KILL_CUMULATIVE'].search(marker + ' incomplete\n'))
        self.assertIsNone(SEAL['NORMAL_ASYNC_KILL_CUMULATIVE'].search(marker.replace('backupCommittedHead=2', 'backupCommittedHead=3') + '\n'))

    def test_async_primary_loss_allows_only_the_exact_original_inflight_tail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = b'original-prefix-and-local-tail'
            prefix = b'original-prefix'
            (root / 'a-original-local-acked.wal').write_bytes(original)
            (root / 'b-original-committed-prefix.wal').write_bytes(prefix)
            primary = root / 'data-a/DemoSvr/DemoSvrA/P000/epoch-2/business.wal'
            backup = root / 'data-b/DemoSvr/DemoSvrB/P000/epoch-2/business.wal'
            primary.parent.mkdir(parents=True)
            backup.parent.mkdir(parents=True)
            primary.write_bytes(original)
            (root / 'a-home-business-proof').touch()
            for raw in (prefix, original):
                backup.write_bytes(raw)
                SEAL['verify_normal_async_primary_prefixes'](root)
            for raw in (b'', b'changed-prefix', prefix + b'-unknown-tail'):
                backup.write_bytes(raw)
                with self.subTest(backup=raw), self.assertRaises(ValueError):
                    SEAL['verify_normal_async_primary_prefixes'](root)
            backup.write_bytes(prefix)
            primary.write_bytes(prefix)
            with self.assertRaises(ValueError):
                SEAL['verify_normal_async_primary_prefixes'](root)

    def test_cold_tail_ack_accepts_only_complete_physical_proof_marker(self):
        marker = 'T554_BOTH_COLD_STRICT_TAILS_SIGNED_PREFIX_HOME_AND_BUSINESS_ACK_PASS'
        for prefix in ('', '....'):
            self.assertIsNotNone(SEAL['COLD_TAIL_ACK'].search(prefix + marker + '\n'))
        self.assertIsNone(SEAL['COLD_TAIL_ACK'].search(marker + ' incomplete\n'))

    def test_blocked_notice_ack_accepts_junit_progress_dots(self):
        marker = ('T554_BLOCKED_POISON_NOTICE_OTHER_PARTITION_PHYSICAL_HOME_ACK_PASS '
                  'blocked=P001 recovered=P000')
        for prefix in ('', '........'):
            with self.subTest(prefix=prefix):
                self.assertEqual([('P001', 'P000')],
                                 SEAL['BLOCKED_NOTICE_ACK'].findall(prefix + marker + '\n'))
        self.assertEqual([], SEAL['BLOCKED_NOTICE_ACK'].findall(marker + ' malformed\n'))

    def test_public_physical_bytes_are_hashed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'business.wal').write_bytes(b'physical-test-bytes')
            self.assertEqual({'business.wal': hashlib.sha256(b'physical-test-bytes').hexdigest()},
                             SEAL['evidence_hashes'](root))

    def test_private_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('node.pk8', 'source.hmac'):
                with self.subTest(name=name):
                    path = root / name
                    path.write_bytes(b'test-only')
                    with self.assertRaises(ValueError):
                        SEAL['evidence_hashes'](root)
                    path.unlink()

    def test_symbolic_directories_and_missing_evidence_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / 'physical'
            directory.mkdir()
            (directory / 'linked').symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                SEAL['evidence_hashes'](directory)
            with self.assertRaises(ValueError):
                SEAL['evidence_hashes'](root / 'missing')


if __name__ == '__main__':
    unittest.main()
