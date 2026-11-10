import unittest
import hashlib
import json
import tempfile
from datetime import date
from pathlib import Path

from recovery.export_representative_candidate import declaration, java_mask
from recovery.run_representative_strategy_campaign import select_shortlist
from recovery.promote_qualified_catalog_candidates import promotion_request


class RepresentativeCampaignTest(unittest.TestCase):
    def test_server_submission_requires_frozen_source_and_passing_holdout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'GeneratedStrategy.java'
            source.write_text('class Frozen {}', encoding='utf-8')
            envelope = {'sourceFile': str(source), 'productionWrite': False,
                        'result': {'qualified': True,
                                   'executionModelVersion': 'v4_non_overlapping_walk_forward',
                                   'holdout': {'passed': True}}}
            result = root / 'result.json'
            result.write_text(json.dumps(envelope), encoding='utf-8')
            seed_dir = root / 'frozen' / 'candidate'
            seed_dir.mkdir(parents=True)
            seed = {'strategies': [{'strategyName': 'candidate', 'symbol': 'BTCUSDT', 'scene': 'range',
                                   'request': {'optimizationProfile': {}}}]}
            (seed_dir / 'seed.json').write_text(json.dumps(seed), encoding='utf-8')
            record = {'result_path': str(result), 'qualified': True, 'strategy': 'candidate',
                      'symbol': 'BTCUSDT', 'scene': 'range', 'hypothesis': 'frozen', 'family': 'Range',
                      'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
            request = promotion_request(record, root, date(2026, 11, 9))
            self.assertEqual(request['optimizationProfile']['backtestBeginDate'], '2025-11-10')
            self.assertEqual(request['optimizationProfile']['backtestEndDate'], '2026-11-09')
            self.assertIs(request['validationOnly'], False)
            envelope['result']['holdout']['passed'] = False
            result.write_text(json.dumps(envelope), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'qualification'):
                promotion_request(record, root, date(2026, 11, 9))

    def test_family_deduplication_and_existing_qualified_slot_limit(self):
        catalog = [{'hypothesis': 'a_long', 'family': 'A'},
                   {'hypothesis': 'a_short', 'family': 'A'},
                   {'hypothesis': 'b', 'family': 'B'}]
        rows = [dict(hypothesis=name, symbol='BTCUSDT', scene='range',
                     accepted='YES', wf_validate_bps=str(score), wf_validate_pf='2',
                     wf_forward_bps='WITHHELD')
                for name, score in [('a_long', 30), ('a_short', 20), ('b', 10)]]
        selected = select_shortlist(rows, catalog, {'BTCUSDT/range': 2})
        self.assertEqual([row['hypothesis'] for row in selected], ['a_long', 'b'])
        self.assertTrue(all(row['qualified'] is False for row in selected))
        self.assertEqual(len(select_shortlist(rows, catalog, {'BTCUSDT/range': 1})), 1)

    def test_java_extraction_ignores_comment_and_string_braces(self):
        source = '''public class Outer {
    static final class Signal {
        String text = "} class Fake {";
        // }
        /* } */
        int run() { return 1; }
    }
    static final class Other { }
}'''
        extracted = declaration(source, 'Signal')
        self.assertIn('return 1;', extracted)
        self.assertNotIn('class Other', extracted)
        self.assertEqual(len(source), len(java_mask(source)))


if __name__ == '__main__':
    unittest.main()
