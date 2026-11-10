"""No financial replay or production connection in these source/protocol tests."""
import json
from pathlib import Path
import tempfile
import unittest

from recovery.export_directional_clock_candidate import frozen_source, export_candidate, source_file


class DirectionalClockSourceTest(unittest.TestCase):
    def template(self):
        return '\n'.join([
            'package com.app.dc.service.strategy.research;',
            'public class DirectionalClockStrategy extends LegacyLiveSignalAdapter {',
            'private static final String STRATEGY_NAME = "research_directional_clock";',
            'private static final String SYMBOL = "BTCUSDT";',
            'private static final int ENTRY_SIDE = 1;', '}'])

    def test_fifty_cells_two_directions_are_unique_but_one_group(self):
        names, groups = set(), set()
        for symbol in ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'XRPUSDT', 'DOGEUSDT', 'ADAUSDT', 'BNBUSDT', 'TRXUSDT', 'UNIUSDT'):
            for scene in ('trend', 'range', 'channel', 'breakout', 'reversal'):
                for side in (1, -1):
                    source, item, record = frozen_source(self.template(), symbol, scene, side)
                    names.add(item['strategyName']); groups.add(record['mechanism_group'])
                    self.assertIn('private static final int ENTRY_SIDE = ' + str(side), source)
                    self.assertEqual({}, item['request']['defaultParameters'])
                    self.assertEqual(.20, item['request']['optimizationProfile']['minForwardContribution'])
        self.assertEqual(100, len(names)); self.assertEqual({'directional_change_overshoot_clock'}, groups)

    def test_bad_scope_and_boolean_side_rejected(self):
        for symbol, scene, side in [('BTC-USDT', 'trend', 1), ('BTCUSDT', 'anything', 1), ('BTCUSDT', 'trend', True), ('BTCUSDT', 'trend', 0)]:
            with self.assertRaises(ValueError): frozen_source(self.template(), symbol, scene, side)

    def test_template_ambiguity_is_not_silently_rewritten(self):
        with self.assertRaises(ValueError): frozen_source(self.template() + self.template(), 'BTCUSDT', 'trend', 1)

    def test_existing_frozen_source_and_seed_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); native = source_file(root); native.parent.mkdir(parents=True)
            native.write_text(self.template(), encoding='utf-8')
            folder, item, _ = export_candidate(root, root / 'frozen', 'BTCUSDT', 'trend', 1)
            export_candidate(root, root / 'frozen', 'BTCUSDT', 'trend', 1)
            (folder / 'seed.json').write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError): export_candidate(root, root / 'frozen', 'BTCUSDT', 'trend', 1)

    def test_protocol_retains_dates_cost_gates_and_no_parameters(self):
        protocol = json.loads(Path(__file__).with_name('strategy_research_directional_clock_protocol_20261111.json').read_text())
        self.assertEqual('2025-10-12', protocol['primary_end_inclusive'])
        self.assertEqual('2025-10-13', protocol['holdout_begin'])
        self.assertEqual('0.20', protocol['minimum_forward_contribution'])
        self.assertEqual({}, protocol['holdout_locked_parameters'])
        self.assertEqual(0, protocol['holdout_fit_invocations'])
        self.assertFalse(protocol['server_codegen_allowed']); self.assertFalse(protocol['production_write'])


if __name__ == '__main__': unittest.main()
