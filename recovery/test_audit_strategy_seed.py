import base64
import hashlib
import unittest

import audit_strategy_seed as audit


def seed_item(source, version='v1', defaults=None):
    raw = source.encode('utf-8')
    return {'strategyName': 'test_strategy', 'sourceStrategyVersion': version,
            'symbol': 'BTCUSDT', 'scene': 'trend',
            'sourceSha256': hashlib.sha256(raw).hexdigest(),
            'request': {'javaSourceBase64': base64.b64encode(raw).decode('ascii'),
                        'defaultParameters': defaults or {}}}


class AuditStrategySeedTest(unittest.TestCase):
    def test_current_source_with_defaults_has_no_flags(self):
        source = ('paramDouble("stopMultiplier",1); signal.side=Side.BUY; '
                  'signal.stopPrice=x; signal.takerPrice=y;')
        item = seed_item(source, defaults={'stopMultiplier': 1})
        active = [{'strategy_name': 'test_strategy', 'strategy_version': 'v1',
                   'reason': 'oos_not_passed'}]
        result = audit.audit({'strategies': [item]}, active)[0]
        self.assertEqual([], result['flags'])
        self.assertEqual('oos_not_passed', result['qualification'])

    def test_stale_seed_is_not_mistaken_for_current_source(self):
        item = seed_item('signal.side=x; signal.stopPrice=x; signal.takerPrice=y;')
        active = [{'strategy_name': 'test_strategy', 'strategy_version': 'v2',
                   'reason': 'qualified'}]
        result = audit.audit({'strategies': [item]}, active)[0]
        self.assertIn('archived_version_stale', result['flags'])
        self.assertEqual('v2', result['active_version'])

    def test_integrity_and_parameter_findings(self):
        item = seed_item('paramInt("period",14); signal.side=x;')
        item['sourceSha256'] = 'incorrect'
        active = [{'strategy_name': 'test_strategy', 'strategy_version': 'v1',
                   'reason': 'too_few_trades'}]
        result = audit.audit({'strategies': [item]}, active)[0]
        self.assertEqual(['period'], result['missing_defaults'])
        self.assertIn('source_sha256_mismatch', result['flags'])
        self.assertIn('stop_price_missing', result['flags'])
        self.assertIn('take_price_missing', result['flags'])


if __name__ == '__main__':
    unittest.main()
