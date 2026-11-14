import runpy
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
