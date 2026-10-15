"""Fail-closed tests for assembling local historical-scene research inputs."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from recovery.assemble_local_historical_scene_input import (
    read_existing_scenes, verified_generated_scenes,
)
from recovery.run_local_historical_scene_campaign import sha256


class AssembleLocalSceneInputTest(unittest.TestCase):
    def test_canonical_scenes_require_every_half_day(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'BTCUSDT-scenes.tsv'
            row = '2025-08-12 00:00:00\trange\tSUCCESS\thistorical_kline_scene\tmarket_scene_v3_historical_kline_v1\n'
            path.write_text(row, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                read_existing_scenes(path, date(2025, 8, 12), date(2025, 8, 12))
            path.write_text(row + row.replace('00:00:00', '12:00:00'), encoding='utf-8')
            self.assertEqual(len(read_existing_scenes(
                path, date(2025, 8, 12), date(2025, 8, 12))), 2)

    def test_generated_scenes_require_verified_checkpoint_and_exact_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chunk = root / 'chunks' / 'BTCUSDT' / '2024-12-01_2024-12-01'
            rows = chunk / 'attempt_001' / 'run_001' / 'scene-rows.jsonl'
            rows.parent.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'no checkpoint'):
                verified_generated_scenes(root, 'BTCUSDT', date(2024, 12, 1),
                                          date(2024, 12, 1), 1, 'gpt-5.6-sol')
            body = []
            for stamp in ('2024-12-01 00:00:00', '2024-12-01 12:00:00'):
                body.append({'symbol': 'BTCUSDT', 'run_time': stamp, 'scene': 'range',
                             'status': 'SUCCESS', 'analysis_type': 'historical_kline_scene',
                             'prompt_version': 'market_scene_v3_historical_kline_v1',
                             'validator_result_json': json.dumps({
                                 'provider': 'local_codex', 'status': 'SUCCESS',
                                 'model': 'gpt-5.6-sol'})})
            rows.write_text(''.join(json.dumps(row) + '\n' for row in body), encoding='utf-8')
            checkpoint = {'symbol': 'BTCUSDT', 'begin': '2024-12-01',
                          'end': '2024-12-01', 'rows_file': str(rows),
                          'rows_sha256': sha256(rows), 'rows': 2}
            (chunk / 'checkpoint.json').write_text(json.dumps(checkpoint), encoding='utf-8')
            result, sources = verified_generated_scenes(
                root, 'BTCUSDT', date(2024, 12, 1), date(2024, 12, 1), 1,
                'gpt-5.6-sol')
            self.assertEqual(len(result), 2)
            self.assertEqual(len(sources), 1)
            with self.assertRaisesRegex(ValueError, 'low-quality'):
                verified_generated_scenes(
                    root, 'BTCUSDT', date(2024, 12, 1), date(2024, 12, 1),
                    1, 'gpt-5.6-sol', date(2024, 12, 1))
            body[1]['validator_result_json'] = json.dumps({
                'provider': 'local_codex', 'status': 'SUCCESS', 'model': 'wrong-model'})
            rows.write_text(''.join(json.dumps(row) + '\n' for row in body), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'direct local Codex'):
                verified_generated_scenes(root, 'BTCUSDT', date(2024, 12, 1),
                                          date(2024, 12, 1), 1, 'gpt-5.6-sol')


if __name__ == '__main__':
    unittest.main()
