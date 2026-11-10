import copy
import json
from pathlib import Path
import tempfile
import unittest

from recovery.run_cusum_drift_batch import frozen_queue
from recovery.test_cusum_drift import TEMPLATE
from recovery.verify_cusum_identity_matrix import (
    digest_json, group_scopes, parse_parity, require_matching_reference,
    require_matrix_coverage, training_symbols, verify_compiled_record,
)
from recovery.verify_fit_only_risk_contract import sha

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT', 'XRPUSDT', 'DOGEUSDT', 'ADAUSDT', 'BNBUSDT', 'TRXUSDT', 'UNIUSDT']


class CusumIdentityMatrixTest(unittest.TestCase):
    def test_actual_training_ready_membership_comes_only_from_original_files_map(self):
        ready = dict(purpose='training_only', train_end_exclusive='2024-12-15', files={s: {'bars_sha256': '0' * 64} for s in SYMBOLS})
        self.assertNotIn('symbols', ready); self.assertEqual(sorted(SYMBOLS), training_symbols(ready))
        with self.assertRaises(ValueError): training_symbols(dict(purpose='training_only', train_end_exclusive='2024-12-15', symbols=SYMBOLS))
        changed = copy.deepcopy(ready); changed['files'].pop('BTCUSDT')
        with self.assertRaises(ValueError): training_symbols(changed)

    def records(self):
        queue = frozen_queue(TEMPLATE, SYMBOLS); canonical, records = [], []
        for _, rows in group_scopes(queue):
            reference = dict(rows[0], training_bars=35040, training_signals=10, mismatches=0,
                actual_full_year_replay=True, full_year_log_sha256='reference-log')
            canonical.append(reference)
            for row in rows:
                records.append(dict(row, training_bars=35040, training_signals=10, mismatches=0,
                    context_sha256='context', canonical_strategy=reference['strategy'],
                    canonical_full_year_log_sha256='reference-log'))
        return queue, canonical, records

    def test_twenty_groups_have_all_five_scenes_with_trend_reference_first(self):
        queue, _, _ = self.records(); groups = group_scopes(queue)
        self.assertEqual(20, len(groups)); self.assertEqual(100, sum(len(rows) for _, rows in groups))
        self.assertEqual(groups, group_scopes(list(reversed(queue))))
        for key, rows in groups:
            self.assertEqual('trend', rows[0]['scene']); self.assertEqual(5, len({r['scene'] for r in rows}))
            self.assertTrue(all((r['symbol'], r['side']) == key for r in rows))

    def test_missing_duplicate_and_wrong_scene_queues_cannot_claim_matrix_completion(self):
        queue, _, _ = self.records()
        for changed in (queue[:-1], queue[:-1] + [queue[0]],
                        [dict(queue[0], scene='range')] + queue[1:]):
            with self.assertRaises(ValueError): group_scopes(changed)

    def test_only_fixed_original_cusum_policy_and_explicit_integer_direction_are_accepted(self):
        queue, _, _ = self.records()
        for fields in (dict(family='renamed'), dict(mechanism_group='other'), dict(side=True)):
            with self.assertRaises(ValueError): group_scopes([dict(queue[0], **fields)] + queue[1:])

    def test_actual_full_year_parser_requires_all_bars_and_exact_signal_risk_parity(self):
        self.assertEqual(535, parse_parity('bars=35040, researchSignals=535, exportedSignals=535, mismatches=0, economics={}'))
        self.assertEqual(0, parse_parity('bars=35040, researchSignals=0, exportedSignals=0, mismatches=0'))

    def test_partial_or_mismatched_parity_output_is_not_a_full_year_reference(self):
        for text in ('missing', 'bars=35039, researchSignals=535, exportedSignals=535, mismatches=0',
                     'bars=35040, researchSignals=535, exportedSignals=534, mismatches=0',
                     'bars=35040, researchSignals=535, exportedSignals=535, mismatches=1'):
            with self.assertRaises(ValueError): parse_parity(text)

    def test_never_share_a_reference_across_symbol_direction_or_policy(self):
        queue, canonical, _ = self.records(); reference = canonical[0]
        row = next(r for r in queue if r['symbol'] == reference['symbol'] and r['side'] == reference['side'])
        require_matching_reference(row, reference)
        for fields in (dict(symbol='OTHERUSDT'), dict(side=-reference['side']), dict(hypothesis='different'),
                       dict(actual_full_year_replay=False), dict(training_bars=35039)):
            with self.assertRaises(ValueError): require_matching_reference(row, dict(reference, **fields))

    def test_all_twenty_actual_reference_bindings_and_hundred_exact_records_are_required(self):
        queue, canonical, records = self.records()
        require_matrix_coverage(queue, canonical, records, 'context')
        with self.assertRaises(ValueError): require_matrix_coverage(queue, canonical[:-1], records, 'context')
        with self.assertRaises(ValueError): require_matrix_coverage(queue, canonical, records[:-1], 'context')

    def test_correct_counts_cannot_hide_changed_descriptor_reference_or_context(self):
        queue, canonical, records = self.records()
        for fields in (dict(side=-records[0]['side']), dict(context_sha256='different'),
                       dict(canonical_strategy='different'), dict(training_signals=11),
                       dict(canonical_full_year_log_sha256='different')):
            changed = [dict(records[0], **fields)] + records[1:]
            with self.assertRaises(ValueError): require_matrix_coverage(queue, canonical, changed, 'context')

    def test_source_jar_seed_validator_and_scene_profile_bytes_remain_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); record = dict(strategy='scope', symbol='BTCUSDT', scene='range')
            for key, digest_key in (('source_path', 'source_sha256'), ('artifact_path', 'artifact_sha256'),
                    ('validator_log_path', 'validator_log_sha256')):
                path = root / key; path.write_bytes(b'original'); record[key] = str(path); record[digest_key] = sha(path)
            profile = dict(fitWindowDays=90, minForwardContribution=.2)
            seed = {'strategies': [dict(strategyName='scope', symbol='BTCUSDT', scene='range',
                request=dict(optimizationProfile=profile, parameterSchema={}, defaultParameters={}))]}
            path = root / 'seed.json'; path.write_text(json.dumps(seed))
            record.update(seed_path=str(path), seed_sha256=sha(path), optimization_profile_sha256=digest_json(profile))
            verify_compiled_record(record)
            path.write_text(json.dumps({'strategies': [dict(seed['strategies'][0], scene='trend')]}))
            with self.assertRaises(ValueError): verify_compiled_record(record)
            changed = copy.deepcopy(seed); changed['strategies'][0]['request']['optimizationProfile']['fitWindowDays'] = 120
            path.write_text(json.dumps(changed)); record['seed_sha256'] = sha(path)
            with self.assertRaisesRegex(ValueError, 'scene-specific'): verify_compiled_record(record)


if __name__ == '__main__': unittest.main()
