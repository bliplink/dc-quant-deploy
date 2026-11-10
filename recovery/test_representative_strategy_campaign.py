import unittest
import hashlib
import json
import tempfile
from datetime import date
from pathlib import Path

from recovery.export_representative_candidate import declaration, java_mask
from recovery.run_representative_strategy_campaign import select_shortlist
from recovery.run_representative_formal_batch import write_empty_formal_batch
from recovery.run_representative_formal_batch import research_parity_classpath
from recovery.promote_qualified_catalog_candidates import promotion_request, prior_submission, source_only_execution_audit


class RepresentativeCampaignTest(unittest.TestCase):
    def test_formal_parity_resolves_both_research_and_indsvr_contract_classes(self):
        from unittest.mock import patch
        import os
        with patch('recovery.run_representative_formal_batch.runner.java_classpath', return_value='formal-runtime'):
            cp = research_parity_classpath(Path('research'), Path('sim'))
        self.assertEqual([str(Path('research/target/test-classes')),
                          str(Path('research/target/classes')), 'formal-runtime'], cp.split(os.pathsep))

    def test_empty_shortlist_has_a_durable_zero_result_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_empty_formal_batch(root, 'frozen')
            self.assertEqual([], json.loads((root / 'results.json').read_text(encoding='utf-8')))
            status = json.loads((root / 'status.json').read_text(encoding='utf-8'))
            self.assertEqual((0, 0, 0, []), (status['completed'], status['total'], status['published'], status['errors']))
            complete = json.loads((root / 'FORMAL_COMPLETE.json').read_text(encoding='utf-8'))
            self.assertIs(complete['production_write'], False)
            self.assertEqual('frozen', complete['manifest_sha256'])

    def test_uploaded_source_never_uses_server_codegen_or_llm_repair(self):
        import base64
        payload = {'provider': 'external', 'sourceType': 'EXTERNAL_SOURCE',
                   'generationType': 'EXTERNAL_IMPORT', 'generationEngine': 'external_java',
                   'generationEngineRequested': 'external_java', 'generationEngineFallback': None}
        status = {'generationTask': {'payload': json.dumps(payload)}}
        request = {'javaSourceBase64': base64.b64encode(b'class Frozen {}').decode()}
        audit = source_only_execution_audit(status, request, 0)
        self.assertFalse(audit['server_codegen_used'])
        self.assertEqual(audit['uploaded_source_sha256'], hashlib.sha256(b'class Frozen {}').hexdigest())
        with self.assertRaisesRegex(ValueError, 'LLM calls'):
            source_only_execution_audit(status, request, 1)
        for key, value in [('provider', 'deepseek'), ('generationEngine', 'full_java'),
                           ('generationEngineRequested', 'full_java'), ('sourceType', 'MANUAL')]:
            with self.assertRaises(ValueError):
                source_only_execution_audit({'generationTask': {'payload': {**payload, key: value}}}, request, 0)
        with self.assertRaisesRegex(ValueError, 'fallback'):
            source_only_execution_audit({'generationTask': {'payload': {
                **payload, 'generationEngineFallback': 'full_java'}}}, request, 0)

    def test_prior_server_ledger_prevents_duplicate_submission_across_output_dirs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = {'strategyName': 'candidate', 'javaSourceBase64': 'frozen'}
            for suffix, version in [('first', 'v1'), ('formatfix', 'v2')]:
                folder = root / ('strategy-95-server-' + suffix) / 'candidate'
                folder.mkdir(parents=True)
                (folder / 'request.json').write_text(json.dumps(request), encoding='utf-8')
                (folder / 'submission.json').write_text(
                    json.dumps({'strategyVersion': version}), encoding='utf-8')
            selected = prior_submission(root / 'strategy-95-server-final', 'candidate', request)
            self.assertEqual(selected['strategyVersion'], 'v2')
            self.assertIsNone(prior_submission(root / 'strategy-95-server-final',
                                               'candidate', {**request, 'javaSourceBase64': 'different'}))

    def test_server_submission_requires_frozen_source_and_passing_holdout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'GeneratedStrategy.java'
            source.write_text('class Frozen {}', encoding='utf-8')
            envelope = {'sourceFile': str(source), 'productionWrite': False,
                        'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                        'result': {'qualified': True,
                                   'executionModelVersion': 'v4_non_overlapping_walk_forward',
                                   'admissionSchema': 'local_temporal_holdout_v2',
                                   'beginDate': '2024-12-15', 'endDate': '2025-10-12',
                                   'selectedParameters': {}, 'bestParamSetJson': '{}',
                                   'sliceResults': [],
                                   'holdout': {'passed': True, 'beginDate': '2025-10-13', 'endDate': '2025-12-13',
                                       'lockedParameters': {}, 'parameterPolicy': 'frozen_pre_holdout_representative',
                                       'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                                       'optimizerInvocations': 0, 'fitInvocations': 0}}}
            from datetime import timedelta
            for index in range(3):
                first = date(2024, 12, 15) + timedelta(days=44 * index)
                envelope['result']['sliceResults'].append({'sliceNo': index + 1,
                    **{phase + edge: str(first + timedelta(days=offset)) for phase, edge, offset in (
                        ('fit', 'Begin', 0), ('fit', 'End', 119), ('validate', 'Begin', 120),
                        ('validate', 'End', 149), ('forward', 'Begin', 150), ('forward', 'End', 163))}})
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
