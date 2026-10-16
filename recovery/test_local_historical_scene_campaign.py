"""Contract tests for the offline, checkpointed historical-scene campaign."""

import json
import tempfile
import unittest
from argparse import Namespace
from datetime import date
from pathlib import Path

from recovery.run_local_historical_scene_campaign import (
    build_command,
    date_chunks,
    expected_times,
    hit_usage_limit,
    run_chunk,
    validate_rows,
)


class HistoricalSceneCampaignTest(unittest.TestCase):
    def test_usage_limit_is_detected_only_from_codex_child_log(self):
        with tempfile.TemporaryDirectory() as directory:
            attempt = Path(directory)
            child = attempt / 'run_001' / 'batch_001_codex_1.log'
            child.parent.mkdir()
            child.write_text('ERROR: You have hit your usage limit. Try again later.\n',
                             encoding='utf-8')
            self.assertTrue(hit_usage_limit(attempt))
            child.write_text('ERROR: invalid scene response\n', encoding='utf-8')
            self.assertFalse(hit_usage_limit(attempt))

    def test_chunks_are_disjoint_and_complete(self):
        chunks = list(date_chunks(date(2024, 12, 1), date(2024, 12, 23), 10))
        self.assertEqual(chunks, [
            (date(2024, 12, 1), date(2024, 12, 10)),
            (date(2024, 12, 11), date(2024, 12, 20)),
            (date(2024, 12, 21), date(2024, 12, 23)),
        ])
        self.assertEqual(sum(len(expected_times(a, b)) for a, b in chunks), 46)

    def test_java_command_is_local_export_only(self):
        args = Namespace(java='java', chunk_days=10, timeout_minutes=15)
        command = build_command(args, Path('bars'), 'BTCUSDT',
                                date(2024, 12, 1), date(2024, 12, 10), Path('out'))
        self.assertIn('--export-rows-only', command)
        self.assertIn('--kline-dir', command)
        self.assertIn('-Duser.timezone=UTC', command)
        self.assertEqual(command[command.index('--max-points') + 1], '20')
        self.assertNotIn('--apply', command)

    def test_only_complete_direct_codex_rows_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'scene-rows.jsonl'
            rows = []
            for stamp, scene in [('2024-12-01 00:00:00', 'range'),
                                 ('2024-12-01 12:00:00', 'trend')]:
                rows.append({'symbol': 'BTCUSDT', 'run_time': stamp, 'scene': scene,
                             'status': 'SUCCESS', 'analysis_type': 'historical_kline_scene',
                             'prompt_version': 'market_scene_v3_historical_kline_v1',
                             'validator_result_json': json.dumps(
                                 {'provider': 'local_codex', 'status': 'SUCCESS',
                                  'model': 'gpt-5.6-sol'})})
            path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
            result = validate_rows(path, 'BTCUSDT', date(2024, 12, 1),
                                   date(2024, 12, 1), 'gpt-5.6-sol')
            self.assertEqual(result['rows'], 2)
            rows[1]['validator_result_json'] = json.dumps(
                {'provider': 'local_codex_derived', 'status': 'SUCCESS'})
            path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'direct local Codex'):
                validate_rows(path, 'BTCUSDT', date(2024, 12, 1),
                              date(2024, 12, 1), 'gpt-5.6-sol')

    def test_completed_chunk_resumes_without_model_call(self):
        with tempfile.TemporaryDirectory() as directory:
            chunk = Path(directory)
            rows = chunk / 'attempt_001' / 'run_001' / 'scene-rows.jsonl'
            rows.parent.mkdir(parents=True)
            body = []
            for stamp in ('2024-12-01 00:00:00', '2024-12-01 12:00:00'):
                body.append({'symbol': 'BTCUSDT', 'run_time': stamp, 'scene': 'range',
                             'status': 'SUCCESS', 'analysis_type': 'historical_kline_scene',
                             'prompt_version': 'market_scene_v3_historical_kline_v1',
                             'validator_result_json': json.dumps(
                                 {'provider': 'local_codex', 'status': 'SUCCESS',
                                  'model': 'gpt-5.6-sol'})})
            rows.write_text(''.join(json.dumps(row) + '\n' for row in body), encoding='utf-8')
            stats = validate_rows(rows, 'BTCUSDT', date(2024, 12, 1),
                                  date(2024, 12, 1), 'gpt-5.6-sol')
            (chunk / 'checkpoint.json').write_text(
                json.dumps({'rows_sha256': stats['sha256']}), encoding='utf-8')
            resumed, skipped = run_chunk(Namespace(model='gpt-5.6-sol'), Path(directory),
                                         'BTCUSDT', date(2024, 12, 1),
                                         date(2024, 12, 1), chunk)
            self.assertTrue(skipped)
            self.assertEqual(resumed['rows'], 2)


if __name__ == '__main__':
    unittest.main()
