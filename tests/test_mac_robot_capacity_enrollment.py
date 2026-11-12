import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/verify-mac-demo-robot-capacity.py'
SPEC = importlib.util.spec_from_file_location('mac_robot_capacity', SCRIPT)
CAPACITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAPACITY)


class RobotCapacityEnrollmentTest(unittest.TestCase):
    def test_approved_robot_may_appear_after_the_approval_response(self):
        original = {'OLD123': 'ERROR'}
        complete = dict(original, NEW123='WAITING_MARKET_DATA')
        approve = Mock(return_value={'status': 'APPROVED', 'approved_location': 'NEW123'})
        with patch.object(CAPACITY, 'demo_tenants', side_effect=[original, original, complete]), \
                patch.object(CAPACITY.time, 'sleep'), \
                patch.dict(CAPACITY.PRODUCT, {'ok': approve}):
            self.assertEqual({'OLD123', 'NEW123'}, CAPACITY.enroll(2))
        approve.assert_called_once()

    def test_an_unexpected_robot_does_not_count_as_the_approved_tenant(self):
        approve = Mock(return_value={'status': 'APPROVED', 'approved_location': 'NEW123'})
        with patch.object(CAPACITY, 'demo_tenants', side_effect=[
                {'OLD123': 'RUNNING'}, {'OLD123': 'RUNNING', 'OTHER1': 'RUNNING'}]), \
                patch.dict(CAPACITY.PRODUCT, {'ok': approve}):
            with self.assertRaises(RuntimeError):
                CAPACITY.enroll(2)
        approve.assert_called_once()

    def test_missing_approved_robot_times_out_without_submitting_another_application(self):
        now = [0.0]

        def advance(seconds):
            now[0] += seconds

        approve = Mock(return_value={'status': 'APPROVED', 'approved_location': 'NEW123'})
        with patch.object(CAPACITY, 'demo_tenants', return_value={'OLD123': 'RUNNING'}), \
                patch.object(CAPACITY.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(CAPACITY.time, 'sleep', side_effect=advance), \
                patch.dict(CAPACITY.PRODUCT, {'ok': approve}):
            with self.assertRaisesRegex(RuntimeError, 'did not appear'):
                CAPACITY.enroll(2)
        approve.assert_called_once()


if __name__ == '__main__':
    unittest.main()
