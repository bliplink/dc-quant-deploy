import ast
from contextlib import contextmanager
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
    def test_pause_and_release_require_all_configured_workers(self):
        for count in (2, 8):
            self.assertEqual(count, RPO.delivery_fault_group(
                f'PAUSED delivery={count} configured={count} scheduler=1 holdMillis=30000', 'PAUSED'))
            self.assertEqual(count, RPO.delivery_fault_group(
                f'RESUMED delivery={count} configured={count} scheduler=1 reason=requested', 'RESUMED'))
        for bad in ('PAUSED delivery=2 configured=8 scheduler=1 holdMillis=30000',
                    'PAUSED delivery=2 scheduler=1 holdMillis=30000',
                    'PAUSED delivery=8 configured=8 scheduler=0 holdMillis=30000',
                    'PAUSED delivery=3 configured=3 scheduler=1 holdMillis=30000'):
            with self.subTest(proof=bad), self.assertRaises(RuntimeError):
                RPO.delivery_fault_group(bad, 'PAUSED')

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

    def frame(self, sequence, payload=b'fixture', epoch=2):
        checksum = zlib.crc32(struct.pack('>qq', epoch, sequence) + payload)
        return struct.pack('>IqqII', 0x43425731, epoch, sequence, len(payload), checksum) + payload

    def test_later_epoch_observation_requires_the_exact_requested_epoch(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'original.wal'
            raw = self.frame(1, epoch=7) + self.frame(2, epoch=7)
            target.write_bytes(raw)
            with patch.object(RPO, 'run') as run:
                self.assertEqual((raw, 2), RPO.copy_wal('fixture-node', 'B', 'P200', target, epoch=7))
                self.assertIn('/epoch-7/business.wal', run.call_args.args[2])
                with self.assertRaisesRegex(RuntimeError, 'CRC or coordinate'):
                    RPO.copy_wal('fixture-node', 'B', 'P200', target, epoch=6)

    def test_later_epoch_head_observer_does_not_silently_check_epoch_two(self):
        with patch.object(RPO, 'run', return_value='READY') as run:
            RPO.observe_physical_head('fixture-node', '1', '/tmp/tools', 'P200', 17, 'a' * 64, epoch=7)
            arguments = run.call_args_list[0].args[-1]
            self.assertIn(',P200,7,17,', arguments)

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


class ControlledFaultPlacementTest(unittest.TestCase):
    def fake(self, locations, events):
        iterator = iter(locations)
        @contextmanager
        def products(run, report, password):
            location = next(iterator)
            events.append(('enter', location))
            report['selected_setup'] = location
            try:
                yield location, (('TRADE', 'BTC004USDT'),)
            finally:
                events.append(('close', location))
        return products

    def test_collision_closes_normally_before_selecting_and_holding_safe_products(self):
        robot = 'AAA001'
        collision = next('C%05d' % i for i in range(10000)
                         if zlib.crc32(('C%05d' % i).encode()) % 256 == zlib.crc32(robot.encode()) % 256)
        safe = next('S%05d' % i for i in range(10000)
                    if zlib.crc32(('S%05d' % i).encode()) % 256 != zlib.crc32(robot.encode()) % 256)
        events, report = [], {}
        with patch.dict(RPO.CANCEL, controlled_products=self.fake([collision, safe], events)):
            with RPO.controlled_products_away_from_robots('run', report, 'fixture', [robot]) as (location, products):
                self.assertEqual(safe, location)
                self.assertEqual([('enter', collision), ('close', collision), ('enter', safe)], events)
                self.assertEqual(safe, report['selected_setup'])
        self.assertEqual(('close', safe), events[-1])
        self.assertEqual([True, False], [x['excluded_for_robot_partition_collision']
                                       for x in report['controlled_setup_attempts']])

    def test_exhaustion_is_bounded_and_never_enters_the_fault_body(self):
        events, report = [], {}
        with patch.dict(RPO.CANCEL, controlled_products=self.fake(['AAA001'] * 8, events)):
            with self.assertRaisesRegex(RuntimeError, 'Bounded controlled setup'):
                with RPO.controlled_products_away_from_robots('run', report, 'fixture', ['AAA001']):
                    self.fail('A colliding tenant reached the fault body')
        self.assertEqual(8, len(report['controlled_setup_attempts']))
        self.assertEqual(8, sum(event == 'close' for event, _ in events))

    def test_fault_body_failure_is_not_retried_as_another_tenant(self):
        events = []
        with patch.dict(RPO.CANCEL, controlled_products=self.fake(['BBB002'], events)):
            with self.assertRaisesRegex(RuntimeError, 'body outcome unknown'):
                with RPO.controlled_products_away_from_robots('run', {}, 'fixture', []):
                    raise RuntimeError('body outcome unknown')
        self.assertEqual([('enter', 'BBB002'), ('close', 'BBB002')], events)


if __name__ == '__main__':
    unittest.main()
