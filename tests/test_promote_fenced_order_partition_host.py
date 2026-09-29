import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('promote', Path(__file__).with_name('promote-fenced-order-partition-host.py'))
promote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(promote)


class FencedOrderPromotionTest(unittest.TestCase):
    def test_exact_replica_gets_advanced_epoch(self):
        before = {'partitionId': 'P019', 'epoch': 1, 'primary': 'OrderSvrB',
                  'replica': 'OrderSvrA', 'state': 'READY'}
        after = promote.promotion(before, 'OrderSvrA', 'P019', 1)
        self.assertEqual((2, 'OrderSvrA', 'OrderSvrB', 'READY'),
                         (after['epoch'], after['primary'], after['replica'], after['state']))
        self.assertEqual(1, before['epoch'])

    def test_stale_or_wrong_target_rejected(self):
        before = {'partitionId': 'P019', 'epoch': 2, 'primary': 'OrderSvrB',
                  'replica': 'OrderSvrA', 'state': 'READY'}
        for target, partition, epoch in [('OrderSvrA', 'P019', 1),
                                         ('OrderSvrB', 'P019', 2),
                                         ('OrderSvrA', 'P020', 2)]:
            with self.assertRaises(ValueError):
                promote.promotion(before, target, partition, epoch)


if __name__ == '__main__':
    unittest.main()
