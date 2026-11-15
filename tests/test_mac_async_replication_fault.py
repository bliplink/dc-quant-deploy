import runpy
from pathlib import Path
import unittest
from unittest.mock import MagicMock, Mock, patch


RPO = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                         'scripts/verify-mac-demo-async-rpo.py'))


class ReplicationDeliveryFaultTest(unittest.TestCase):
    def test_arm_accepts_normalized_status_and_rejects_expired_hold(self):
        arm = RPO['arm_replication_delivery']
        tools = MagicMock()
        (tools / 'replication-pause-agent.jar').read_bytes.return_value = b'test-only'
        for status, accepted in (
                ('PAUSED replication=8 holdMillis=10000', True),
                ('RESUMED replication=8 reason=deadline', False),
                ('PAUSED replication=7 holdMillis=10000', False)):
            with self.subTest(status=status), patch.dict(
                    arm.__globals__, require_replication_fault_tools=Mock(),
                    run=Mock(side_effect=['', '', status])):
                if accepted:
                    self.assertEqual(status, arm('node', '1', '/tools', '/control', tools)['status'])
                else:
                    with self.assertRaisesRegex(RuntimeError, 'Eight idle'):
                        arm('node', '1', '/tools', '/control', tools)


if __name__ == '__main__':
    unittest.main()
