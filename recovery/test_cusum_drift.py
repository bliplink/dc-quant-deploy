import json
from pathlib import Path
import tempfile
import unittest

from recovery.export_cusum_drift_candidate import export_candidate, frozen_source


TEMPLATE = '''package com.app.dc.service.strategy.research;
public class CusumDriftStrategy extends LegacyLiveSignalAdapter {
private static final String STRATEGY_NAME = "research_cusum_drift";
private static final String SYMBOL = "BTCUSDT";
private static final int ENTRY_SIDE = 1;
}
'''


class CusumDriftExportTest(unittest.TestCase):
    def test_two_directions_are_one_conservative_mechanism_without_parameters(self):
        names = set()
        for side in (1, -1):
            source, item, descriptor = frozen_source(TEMPLATE, 'BTCUSDT', 'trend', side)
            names.add(item['strategyName'])
            self.assertEqual('standardized_return_cusum_drift', descriptor['mechanism_group'])
            self.assertIn('private static final int ENTRY_SIDE = ' + str(side) + ';', source)
            self.assertEqual({}, item['request']['parameterSchema'])
            self.assertEqual({}, item['request']['defaultParameters'])
            self.assertEqual(.20, item['request']['optimizationProfile']['minForwardContribution'])
        self.assertEqual(2, len(names))

    def test_exactly_one_hundred_unique_scopes_not_one_hundred_independent_groups(self):
        names, groups = set(), set()
        for symbol in ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'ADAUSDT', 'DOGEUSDT', 'LINKUSDT', 'XRPUSDT', 'BNBUSDT', 'TRXUSDT', 'UNIUSDT'):
            for scene in ('trend', 'range', 'channel', 'breakout', 'reversal'):
                for side in (1, -1):
                    _, item, descriptor = frozen_source(TEMPLATE, symbol, scene, side)
                    names.add(item['strategyName']); groups.add(descriptor['mechanism_group'])
        self.assertEqual(100, len(names)); self.assertEqual(1, len(groups))

    def test_original_scene_window_policies_are_preserved(self):
        for scene in ('trend', 'range', 'channel', 'breakout', 'reversal'):
            _, item, _ = frozen_source(TEMPLATE, 'BTCUSDT', scene, 1)
            profile = item['request']['optimizationProfile']
            self.assertEqual(90 if scene == 'range' else 120, profile['fitWindowDays'])
            self.assertEqual(20 if scene in ('breakout', 'reversal') else 30, profile['validateWindowDays'])
            self.assertEqual(10 if scene in ('breakout', 'reversal') else 14, profile['forwardWindowDays'])

    def test_ambiguous_template_and_invalid_scopes_are_rejected(self):
        for args in [('btcusdt', 'trend', 1), ('BTCUSDT', 'unknown', 1), ('BTCUSDT', 'trend', True), ('BTCUSDT', 'trend', 0)]:
            with self.assertRaises(ValueError): frozen_source(TEMPLATE, *args)
        with self.assertRaises(ValueError): frozen_source(TEMPLATE + TEMPLATE, 'BTCUSDT', 'trend', 1)

    def test_frozen_source_and_seed_are_idempotent_but_changed_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'repo/src/test/java/com/app/dc/service/strategy/research/CusumDriftStrategy.java'
            source.parent.mkdir(parents=True); source.write_text(TEMPLATE, encoding='utf-8')
            folder, item, _ = export_candidate(root / 'repo', root / 'frozen', 'BTCUSDT', 'trend', 1)
            self.assertEqual(folder, export_candidate(root / 'repo', root / 'frozen', 'BTCUSDT', 'trend', 1)[0])
            self.assertEqual({'strategies': [item]}, json.loads((folder / 'seed.json').read_text()))
            (folder / 'GeneratedStrategy.java').write_text('changed', encoding='utf-8')
            with self.assertRaises(ValueError): export_candidate(root / 'repo', root / 'frozen', 'BTCUSDT', 'trend', 1)

    def test_protocol_is_fixed_training_causal_and_retains_formal_windows(self):
        protocol = json.loads(Path(__file__).with_name('strategy_research_cusum_drift_protocol_20261111.json').read_text())
        self.assertEqual('fixed_source_no_parameter_grid', protocol['selection_mode'])
        self.assertEqual('2024-12-15', protocol['primary_begin']); self.assertEqual('2025-10-12', protocol['primary_end_inclusive'])
        self.assertEqual('2025-10-13', protocol['holdout_begin']); self.assertEqual('2025-12-13', protocol['holdout_end_inclusive'])
        self.assertEqual('0.20', protocol['minimum_forward_contribution'])
        self.assertEqual({}, protocol['holdout_locked_parameters']); self.assertFalse(protocol['server_codegen_allowed'])
        self.assertFalse(protocol['production_write']); self.assertTrue(protocol['directions_are_not_independent_mechanisms'])


if __name__ == '__main__': unittest.main()
