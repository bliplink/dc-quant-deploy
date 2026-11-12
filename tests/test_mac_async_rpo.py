import ast
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zlib


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/verify-mac-demo-async-rpo.py'
SPEC = importlib.util.spec_from_file_location('mac_async_rpo', SCRIPT)
RPO = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RPO)


class AsyncRpoEvidenceTest(unittest.TestCase):
    def test_pause_budget_reads_the_actual_dotted_java_property(self):
        with tempfile.TemporaryDirectory() as directory:
            properties = Path(directory) / 'application.properties'
            properties.write_text('other.setting=true\ntrade.common.control.leaseTtlMs=15000\n')
            self.assertEqual(15000, RPO.require_pause_lease_budget(properties))
            properties.write_text('trade.common.control.leaseTtlMs=3000\n')
            with self.assertRaisesRegex(RuntimeError, 'sufficient existing node lease'):
                RPO.require_pause_lease_budget(properties)
            properties.write_text('OTHER_SETTING=15000\n')
            with self.assertRaisesRegex(RuntimeError, 'one exact configured node lease'):
                RPO.require_pause_lease_budget(properties)

    def test_receipt_observation_has_its_own_post_orchestration_clock(self):
        expected = {'fixture-client': {'ExecID': 'fixture-execution'}}
        with patch.object(RPO.time, 'monotonic', side_effect=[1000, 1000, 1000.25]), \
                patch.object(RPO, 'final_reports', side_effect=[None, expected]) as read:
            self.assertEqual(expected, RPO.wait_final_reports('fixture-node', None, {'fixture-client'}))
        self.assertEqual(2, read.call_count)
        self.assertLess(RPO.RECEIPT_OBSERVATION_SECONDS, RPO.REPLICA_PAUSE_WATCHDOG_SECONDS)

    def frame(self, sequence, payload=b'fixture'):
        checksum = zlib.crc32(struct.pack('>qq', 2, sequence) + payload)
        return struct.pack('>IqqII', 0x43425731, 2, sequence, len(payload), checksum) + payload

    def test_actual_wal_observation_checks_crc_and_contiguous_coordinates(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'original.wal'
            raw = self.frame(1) + self.frame(2)
            target.write_bytes(raw)
            with patch.object(RPO, 'run'):
                self.assertEqual((raw, 2), RPO.copy_wal('fixture-node', 'A', 'P001', target))
                for invalid in (raw[:-1], self.frame(2), raw[:-1] + bytes([raw[-1] ^ 1])):
                    target.write_bytes(invalid)
                    with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                        RPO.copy_wal('fixture-node', 'A', 'P001', target)

    def test_strict_mode_stops_before_creating_any_fault_or_customer(self):
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary)
            root = local / 'mac-demo-20261112-000000'
            root.mkdir()
            customer = Mock(side_effect=AssertionError('Customer mutation was reached'))
            with patch.dict(RPO.FRESH, LOCAL=local), \
                    patch.dict(RPO.CAPACITY, require_strict_demo=Mock(),
                               common_release_identity=lambda root: {'client_ack_policy': 'STRICT_QUORUM'}), \
                    patch.dict(RPO.PRODUCT, ok=customer), \
                    patch.object(sys, 'argv', [str(SCRIPT), str(root)]):
                with self.assertRaisesRegex(RuntimeError, 'normal dual-node asynchronous'):
                    RPO.main()
            customer.assert_not_called()
            self.assertEqual([], list(root.iterdir()))

    def test_pause_watchdog_has_valid_code_and_an_independent_process_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)

            def launch(arguments, **options):
                ast.parse(arguments[arguments.index('-c') + 1])
                self.assertTrue(options['start_new_session'])
                (output / 'pause-watchdog.armed').write_text('armed\n')
                return Mock()

            with patch.object(RPO.subprocess, 'Popen', side_effect=launch):
                RPO.arm_pause_watchdog('a' * 64, output)


if __name__ == '__main__':
    unittest.main()
