import runpy
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent))
TRAFFIC = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/mac-demo-robot-traffic.py'))
WAIT = TRAFFIC['wait_traffic']
NOW = datetime(2026, 11, 14, 1, 48, tzinfo=timezone.utc)


class RobotTrafficSelectionTest(unittest.TestCase):
    def test_fault_traffic_accepts_current_and_historical_logger_layouts(self):
        for logger in ('UpdateOrderHandler', 'UpdateOrderHandler:123'):
            with self.subTest(logger=logger):
                messages = [
                    dict(ExecType='Newing', Location='ABC123', ClOrdID='quote-1',
                         Terminal='RobotSvr', Side='Buy'),
                    dict(ExecType='Newing', Location='ABC123', ClOrdID='tape-1',
                         Terminal='RobotSvr-Tape', TimeInForce='IOC')]
                lines = ['INFO sid:null,' + json.dumps(row, separators=(',', ':'))
                         + ' (' + logger + ')' for row in messages]
                snapshot = TRAFFIC['snapshot']
                with patch.dict(snapshot.__globals__, logs=Mock(return_value=lines)):
                    quotes, requests, _, _ = snapshot([], ['trade'], NOW, NOW)
                self.assertEqual({('ABC123', 'Buy', 'quote-1')}, quotes)
                self.assertEqual({('ABC123', 'tape-1')}, requests)

    def test_other_logger_cannot_supply_trade_ingress_evidence(self):
        row = dict(ExecType='Newing', Location='ABC123', ClOrdID='quote-1',
                   Terminal='RobotSvr', Side='Buy')
        line = 'INFO sid:null,' + json.dumps(row, separators=(',', ':')) + ' (OtherHandler:123)'
        snapshot = TRAFFIC['snapshot']
        with patch.dict(snapshot.__globals__, logs=Mock(return_value=[line])):
            quotes, requests, _, _ = snapshot([], ['trade'], NOW, NOW)
        self.assertFalse(quotes)
        self.assertFalse(requests)

    @staticmethod
    def traffic():
        return ({('STOPPED', 'Buy', 'old-quote'), ('LIVE', 'Buy', 'live-quote')},
                {('STOPPED', 'old-tape'), ('LIVE', 'live-tape')}, set(),
                [('STOPPED', 'old-fill'), ('LIVE', 'live-fill')])

    def test_stopped_robot_with_recent_logs_cannot_win_fault_target_preference(self):
        with patch.dict(WAIT.__globals__, snapshot=Mock(return_value=self.traffic()),
                        running_robot_locations=Mock(return_value={'LIVE'}),
                        utc_now=Mock(return_value=NOW)):
            observed = WAIT([], [], NOW, prefer_location=lambda tenant: tenant == 'STOPPED')
        self.assertEqual('LIVE', observed['location'])
        self.assertEqual(['live-fill'], observed['tape_execution_ids'])

    def test_runtime_membership_is_refreshed_while_waiting_for_a_live_candidate(self):
        running = Mock(side_effect=[set(), {'LIVE'}])
        with patch.dict(WAIT.__globals__, snapshot=Mock(return_value=self.traffic()),
                        running_robot_locations=running, utc_now=Mock(return_value=NOW)), \
                patch.object(TRAFFIC['time'], 'sleep') as sleep:
            observed = WAIT([], [], NOW)
        self.assertEqual('LIVE', observed['location'])
        self.assertEqual(2, running.call_count)
        sleep.assert_called_once_with(4)

    def test_explicit_stopped_robot_cannot_pass_using_its_historical_fills(self):
        with patch.dict(WAIT.__globals__, snapshot=Mock(return_value=self.traffic()),
                        running_robot_locations=Mock(return_value={'LIVE'}),
                        utc_now=Mock(return_value=NOW)), \
                patch.object(TRAFFIC['time'], 'monotonic', side_effect=[0, 0, 2]), \
                patch.object(TRAFFIC['time'], 'sleep'), \
                patch.object(TRAFFIC['subprocess'], 'run', return_value=Mock(stdout='STOPPED')):
            with self.assertRaisesRegex(RuntimeError, 'did not produce fresh'):
                WAIT([], [], NOW, location='STOPPED', seconds=1)


if __name__ == '__main__':
    unittest.main()
