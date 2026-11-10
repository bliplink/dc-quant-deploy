import json
from pathlib import Path
import tempfile
import unittest

from recovery.export_runs_clustering_candidate import export_candidate, frozen_source, source_file

TEMPLATE = '''package com.app.dc.service.strategy.research;
public class RunsClusteringStrategy extends LegacyLiveSignalAdapter {
private static final String STRATEGY_NAME = "research_runs_clustering";
private static final String SYMBOL = "BTCUSDT";
private static final int ENTRY_SIDE = 1;
}
'''


class RunsClusteringExportTest(unittest.TestCase):
    def test_two_directions_are_one_mechanism_without_parameters(self):
        names = set()
        for side in (1, -1):
            source, item, descriptor = frozen_source(TEMPLATE, 'BTCUSDT', 'trend', side)
            names.add(item['strategyName'])
            self.assertIn('private static final int ENTRY_SIDE = ' + str(side) + ';', source)
            self.assertEqual('conditional_signed_runs_clustering', descriptor['mechanism_group'])
            self.assertEqual({}, item['request']['parameterSchema']); self.assertEqual({}, item['request']['defaultParameters'])
            self.assertEqual(.20, item['request']['optimizationProfile']['minForwardContribution'])
        self.assertEqual(2, len(names))

    def test_hundred_scopes_are_not_a_hundred_independent_mechanisms(self):
        names, groups = set(), set()
        for symbol in ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'ADAUSDT', 'DOGEUSDT', 'LINKUSDT', 'XRPUSDT', 'BNBUSDT', 'TRXUSDT', 'UNIUSDT'):
            for scene in ('trend', 'range', 'channel', 'breakout', 'reversal'):
                for side in (1, -1):
                    _, item, descriptor = frozen_source(TEMPLATE, symbol, scene, side)
                    names.add(item['strategyName']); groups.add(descriptor['mechanism_group'])
        self.assertEqual(100, len(names)); self.assertEqual(1, len(groups))

    def test_original_scene_window_and_cost_objective_policies_remain(self):
        for scene in ('trend', 'range', 'channel', 'breakout', 'reversal'):
            _, item, _ = frozen_source(TEMPLATE, 'BTCUSDT', scene, 1); p = item['request']['optimizationProfile']
            self.assertEqual(90 if scene == 'range' else 120, p['fitWindowDays'])
            self.assertEqual(20 if scene in ('breakout', 'reversal') else 30, p['validateWindowDays'])
            self.assertEqual(10 if scene in ('breakout', 'reversal') else 14, p['forwardWindowDays'])
            self.assertEqual('FEE_ADJUSTED_PROFIT_FIRST', p['objective'])

    def test_ambiguous_templates_and_implicit_directions_are_rejected(self):
        with self.assertRaises(ValueError): frozen_source(TEMPLATE + TEMPLATE, 'BTCUSDT', 'trend', 1)
        for args in [('btcusdt', 'trend', 1), ('BTCUSDT', 'unknown', 1), ('BTCUSDT', 'trend', True), ('BTCUSDT', 'trend', 0)]:
            with self.assertRaises(ValueError): frozen_source(TEMPLATE, *args)

    def test_idempotent_export_preserves_exact_source_and_seed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); native = source_file(root / 'native'); native.parent.mkdir(parents=True); native.write_text(TEMPLATE)
            folder, item, _ = export_candidate(root / 'native', root / 'frozen', 'BTCUSDT', 'trend', 1)
            self.assertEqual(folder, export_candidate(root / 'native', root / 'frozen', 'BTCUSDT', 'trend', 1)[0])
            self.assertEqual({'strategies': [item]}, json.loads((folder / 'seed.json').read_text()))
            (folder / 'GeneratedStrategy.java').write_text('changed')
            with self.assertRaises(ValueError): export_candidate(root / 'native', root / 'frozen', 'BTCUSDT', 'trend', 1)

    def test_protocol_fixes_runs_and_original_disjoint_financial_windows(self):
        p = json.loads(Path(__file__).with_name('strategy_research_runs_clustering_protocol_20261111.json').read_text())
        self.assertEqual('fixed_source_no_parameter_grid', p['selection_mode'])
        self.assertEqual('2024-12-15', p['primary_begin']); self.assertEqual('2025-10-12', p['primary_end_inclusive'])
        self.assertEqual('2025-10-13', p['holdout_begin']); self.assertEqual('2025-12-13', p['holdout_end_inclusive'])
        self.assertEqual('0.20', p['minimum_forward_contribution']); self.assertEqual({}, p['holdout_locked_parameters'])
        self.assertEqual(64, p['fixed_source_defaults']['returnSignWindow'])
        self.assertTrue(p['directions_are_not_independent_mechanisms'])
        self.assertFalse(p['server_codegen_allowed']); self.assertFalse(p['production_write'])


if __name__ == '__main__': unittest.main()
