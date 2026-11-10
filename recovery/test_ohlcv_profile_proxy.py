import hashlib
import unittest

from recovery.export_ohlcv_profile_proxy_candidate import VARIANTS, frozen_source


class OhlcvProfileProxyExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Portable export-contract fixture; the separate engineering CLI tests the actual source.
        cls.native = '''package com.app.dc.service.strategy.research;
public class OhlcvProfileProxyStrategy extends LegacyLiveSignalAdapter {
    private static final String STRATEGY_NAME = "research_ohlcv_profile_proxy";
    private static final String SYMBOL = "BTCUSDT";
    private static final int ENTRY_SIDE = 1;
    private static final int ENTRY_MODE = 0;
}
'''

    def test_all_scopes_are_distinct_but_have_one_declared_mechanism(self):
        names, groups = set(), set()
        for symbol in ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'XRPUSDT', 'DOGEUSDT', 'ADAUSDT', 'BNBUSDT', 'TRXUSDT', 'UNIUSDT'):
            for scene in ('trend', 'range', 'channel', 'breakout', 'reversal'):
                for mode, side in VARIANTS:
                    source, item, row = frozen_source(self.native, symbol, scene, side, mode)
                    names.add(item['strategyName']); groups.add(row['mechanism_group'])
                    self.assertIn('public class GeneratedStrategy extends', source)
                    self.assertIn('ENTRY_MODE = ' + str(mode) + ';', source)
                    self.assertIn('ENTRY_SIDE = ' + str(side) + ';', source)
                    self.assertEqual({}, item['request']['parameterSchema'])
                    self.assertEqual({}, item['request']['defaultParameters'])
                    self.assertEqual(.20, item['request']['optimizationProfile']['minForwardContribution'])
        self.assertEqual(200, len(names))
        self.assertEqual({'ohlcv_distribution_auction'}, groups)

    def test_invalid_scope_bool_and_modes_are_not_silent_defaults(self):
        for symbol, scene, side, mode in (('bad-symbol', 'trend', 1, 0), ('BTCUSDT', 'wrong', 1, 0),
                                         ('BTCUSDT', 'trend', True, 0), ('BTCUSDT', 'trend', 1, True),
                                         ('BTCUSDT', 'trend', 0, 0), ('BTCUSDT', 'trend', 1, 2)):
            with self.assertRaises(ValueError):
                frozen_source(self.native, symbol, scene, side, mode)

    def test_export_is_reproducible_and_unknown_template_is_rejected(self):
        first = frozen_source(self.native, 'BTCUSDT', 'range', 1, 0)
        self.assertEqual(first, frozen_source(self.native, 'BTCUSDT', 'range', 1, 0))
        self.assertNotEqual(hashlib.sha256(first[0].encode()).hexdigest(),
                            hashlib.sha256(frozen_source(self.native, 'BTCUSDT', 'range', -1, 0)[0].encode()).hexdigest())
        with self.assertRaises(ValueError):
            frozen_source(self.native.replace('ENTRY_MODE = 0;', 'ENTRY_MODE = 7;'), 'BTCUSDT', 'range', 1, 0)


if __name__ == '__main__':
    unittest.main()
