import hashlib
from pathlib import Path
import runpy
import tempfile
import unittest


SEAL = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/finalize-mac-common-failover.py'))


class PhysicalEvidenceSealTest(unittest.TestCase):
    def test_normal_async_backup_expiry_requires_exact_survivor_proof(self):
        marker = 'T554_NORMAL_DUAL_ASYNC_BACKUP_EXPIRY_PRESERVES_ACK_AND_CONTINUES_PASS'
        self.assertIsNotNone(SEAL['NORMAL_ASYNC_BACKUP_EXPIRY'].search('..' + marker + '\n'))
        self.assertIsNone(SEAL['NORMAL_ASYNC_BACKUP_EXPIRY'].search(marker + ' pending\n'))

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
