import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('reset_data', Path(__file__).with_name('reset-saas-test-data.py'))
reset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reset)


class ResetSafetyTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='dc-reset-safety-')
        self.root = Path(self.temporary.name).resolve()
        (self.root / 'data').mkdir()
        self.allowed = patch.object(reset, 'ROOTS', {str(self.root)})
        self.allowed.start()

    def tearDown(self):
        self.allowed.stop()
        self.temporary.cleanup()

    def test_exact_component_inventory_preserves_other_directories(self):
        (self.root / 'data/TradeSvrA').mkdir()
        (self.root / 'control').mkdir()
        (self.root / 'evidence').mkdir()
        self.assertEqual([self.root / 'data/TradeSvrA'], reset.exact_targets(self.root))

    def test_broad_root_is_refused(self):
        with self.assertRaises(ValueError):
            reset.exact_targets(Path('/'))

    def test_zookeeper_snapshot_and_transaction_logs_are_both_selected(self):
        (self.root / 'data/zookeeper').mkdir()
        (self.root / 'log/zookeeper').mkdir(parents=True)
        (self.root / 'log/zookeeper/orphan-txn').write_text('fixture')
        self.assertEqual([self.root / 'data/zookeeper', self.root / 'log/zookeeper'], reset.exact_targets(self.root))

    def test_unknown_data_component_is_refused(self):
        (self.root / 'data/another-system').mkdir()
        with self.assertRaises(ValueError):
            reset.exact_targets(self.root)

    def test_dangling_symlink_is_refused(self):
        (self.root / 'data/mysql').symlink_to(self.root / 'missing')
        with self.assertRaises(ValueError):
            reset.exact_targets(self.root)

    def test_linked_component_is_refused(self):
        (self.root / 'outside').mkdir()
        (self.root / 'data/TradeSvrA').symlink_to(self.root / 'outside')
        with self.assertRaises(ValueError):
            reset.exact_targets(self.root)

    def test_open_file_is_refused(self):
        target = self.root / 'data/mysql'
        target.mkdir()
        with (target / 'active-journal').open('w') as stream:
            stream.write('fixture')
            with self.assertRaises(ValueError):
                reset.require_closed([target])

    def test_saas_container_even_stopped_is_refused(self):
        with patch.object(reset.subprocess, 'check_output', side_effect=['abc\n',
                '[{"Name":"/dc-saas-tradesvr","Mounts":[]}]']):
            with self.assertRaises(ValueError):
                reset.require_uninstalled(self.root)

    def test_unrelated_container_is_not_selected(self):
        with patch.object(reset.subprocess, 'check_output', side_effect=['abc\n',
                '[{"Name":"/opentradingcore-web","Mounts":[]}]']):
            reset.require_uninstalled(self.root)


if __name__ == '__main__':
    unittest.main()
