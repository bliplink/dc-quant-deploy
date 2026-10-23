"""Resume-safe, local-only historical scene labeling with the existing INDSvr tool.

This runner never invokes the tool without --export-rows-only and --kline-dir.
It pins UTC, a loopback-only dummy ClickHouse endpoint, input hashes, and one
bounded date chunk per Codex batch. No production database writes are possible
through this invocation.
"""

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from recovery.convert_research_bars_for_scene_snapshot import convert
from recovery.export_strategy_research_data import SYMBOLS


MAIN_CLASS = 'com.app.dc.service.signal.codex.selection.ai.HistoricalSceneLocalCodexTool'
CLASS_FILE = Path('target/test-classes/com/app/dc/service/signal/codex/selection/ai/HistoricalSceneLocalCodexTool.class')
CLASSPATH = 'target/test-classes;target/classes;target/dependency/*;target/javalib/*'
PROMPT_VERSION = 'market_scene_v3_historical_kline_v1'


class UsageLimitError(RuntimeError):
    """The local Codex account reported a temporary usage limit."""


class ModelCapacityError(RuntimeError):
    """The pinned Codex model is temporarily at capacity."""


def child_log_contains(attempt_dir, phrase):
    for path in attempt_dir.glob('run_*/batch_*_codex_*.log'):
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - 8192))
            tail = stream.read().decode('utf-8', 'replace').lower()
        if phrase in tail:
            return True
    return False


def hit_usage_limit(attempt_dir):
    return child_log_contains(attempt_dir, 'hit your usage limit')


def hit_model_capacity(attempt_dir):
    return child_log_contains(attempt_dir, 'selected model is at capacity')


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def date_chunks(begin, end, days):
    current = begin
    while current <= end:
        last = min(end, current + timedelta(days=days - 1))
        yield current, last
        current = last + timedelta(days=1)


def expected_times(begin, end):
    result = set()
    current = begin
    while current <= end:
        result.add(current.strftime('%Y-%m-%d') + ' 00:00:00')
        result.add(current.strftime('%Y-%m-%d') + ' 12:00:00')
        current += timedelta(days=1)
    return result


def validate_rows(path, symbol, begin, end, model):
    if not path.is_file():
        raise ValueError('scene rows missing: %s' % path)
    expected = expected_times(begin, end)
    actual = set()
    scenes = {}
    with path.open('r', encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            if row.get('symbol') != symbol or row.get('status') != 'SUCCESS':
                raise ValueError('invalid symbol/status in %s' % path)
            if row.get('analysis_type') != 'historical_kline_scene' or row.get('prompt_version') != PROMPT_VERSION:
                raise ValueError('wrong historical scene contract in %s' % path)
            validator = json.loads(row.get('validator_result_json') or '{}')
            if (validator.get('provider') != 'local_codex'
                    or validator.get('status') != 'SUCCESS'
                    or validator.get('model') != model):
                raise ValueError('not a validated direct local Codex label in %s' % path)
            stamp = row.get('run_time')
            if stamp in actual:
                raise ValueError('duplicate scene time %s in %s' % (stamp, path))
            actual.add(stamp)
            scenes[row.get('scene', 'unknown')] = scenes.get(row.get('scene', 'unknown'), 0) + 1
    if actual != expected:
        raise ValueError('scene times differ from requested chunk: missing=%d unexpected=%d' %
                         (len(expected - actual), len(actual - expected)))
    return {'rows': len(actual), 'scene_counts': scenes, 'sha256': sha256(path)}


def prepare_inputs(args, symbols, campaign):
    bars_dir = args.output_dir / 'bars'
    hashes = {}
    for symbol in symbols:
        source = args.input_dir / (symbol + '-15m.tsv')
        source_hash = sha256(source)
        hashes[symbol] = source_hash
        target = bars_dir / (symbol + '_15M.jsonl')
        if campaign is not None and campaign['input_sha256'][symbol] != source_hash:
            raise ValueError('source input changed for ' + symbol)
        # Rebuild the mechanical JSONL conversion on every resume. An existing
        # file is not evidence that a previously interrupted conversion finished.
        print('convert', symbol, convert(source, target), 'bars', flush=True)
    return bars_dir, hashes


def newest_valid_rows(chunk_dir, symbol, begin, end, model):
    for path in sorted(chunk_dir.glob('attempt_*/run_*/scene-rows.jsonl'), reverse=True):
        try:
            return path, validate_rows(path, symbol, begin, end, model)
        except (ValueError, json.JSONDecodeError):
            continue
    return None, None


def build_command(args, bars_dir, symbol, begin, end, attempt_dir):
    return [args.java, '-Xms16m', '-Xmx512m', '-XX:+UseSerialGC',
            '-Duser.timezone=UTC', '-cp', CLASSPATH, MAIN_CLASS,
            '--symbol', symbol, '--begin', begin.isoformat(), '--end', end.isoformat(),
            '--batch-size', str(2 * args.chunk_days),
            '--max-points', str(len(expected_times(begin, end))),
            '--timeout-minutes', str(args.timeout_minutes),
            '--export-rows-only', '--kline-dir', str(bars_dir),
            '--output-dir', str(attempt_dir)]


def run_chunk(args, bars_dir, symbol, begin, end, chunk_dir):
    checkpoint = chunk_dir / 'checkpoint.json'
    existing_path, existing_stats = newest_valid_rows(chunk_dir, symbol, begin, end, args.model)
    if checkpoint.is_file():
        saved = json.loads(checkpoint.read_text(encoding='utf-8'))
        if existing_path is None or saved.get('rows_sha256') != existing_stats['sha256']:
            raise ValueError('checkpoint lost its verified label file: %s' % chunk_dir)
        return existing_stats, True
    if existing_path is not None:
        stats = existing_stats
        rows_path = existing_path
    else:
        attempts = sorted(chunk_dir.glob('attempt_*'))
        if attempts and not args.retry_failed:
            raise RuntimeError('incomplete chunk; inspect logs then use --retry-failed: %s' % chunk_dir)
        attempt_dir = chunk_dir / ('attempt_%03d' % (len(attempts) + 1))
        attempt_dir.mkdir(parents=True)
        env = os.environ.copy()
        env['DC_CLICKHOUSE_URL'] = 'http://127.0.0.1:9'
        env['DC_CLICKHOUSE_PASSWORD'] = 'offline-snapshot-only'
        env['DC_CODEX_MODEL'] = args.model
        command = build_command(args, bars_dir, symbol, begin, end, attempt_dir)
        with (attempt_dir / 'runner.log').open('w', encoding='utf-8') as output:
            completed = subprocess.run(command, cwd=args.indsvr_repo, env=env,
                                       stdout=output, stderr=subprocess.STDOUT,
                                       timeout=(2 * args.timeout_minutes + 5) * 60)
        if completed.returncode:
            if hit_usage_limit(attempt_dir):
                raise UsageLimitError('local Codex usage limit: %s' % attempt_dir)
            if hit_model_capacity(attempt_dir):
                raise ModelCapacityError('pinned Codex model at capacity: %s' % attempt_dir)
            raise RuntimeError('historical scene tool failed (%d): %s' %
                               (completed.returncode, attempt_dir / 'runner.log'))
        rows_path, stats = newest_valid_rows(chunk_dir, symbol, begin, end, args.model)
        if rows_path is None:
            raise RuntimeError('no complete validated scene rows: %s' % chunk_dir)
    write_json(checkpoint, {'symbol': symbol, 'begin': begin.isoformat(),
                            'end': end.isoformat(), 'rows_file': str(rows_path),
                            'rows_sha256': stats['sha256'], 'rows': stats['rows'],
                            'scene_counts': stats['scene_counts'],
                            'completed_utc': datetime.now(timezone.utc).isoformat(timespec='seconds')})
    return stats, False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--indsvr-repo', type=Path, required=True)
    parser.add_argument('--begin', type=date.fromisoformat, default=date(2024, 12, 1))
    parser.add_argument('--end', type=date.fromisoformat, default=date(2025, 8, 11))
    parser.add_argument('--symbols', default=','.join(SYMBOLS))
    parser.add_argument('--java', default='java')
    parser.add_argument('--model', default='gpt-5.6-sol')
    parser.add_argument('--chunk-days', type=int, default=10)
    parser.add_argument('--timeout-minutes', type=int, default=15)
    parser.add_argument('--max-chunks', type=int, default=0,
                        help='Limit newly executed chunks; zero means all')
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--wait-on-usage-limit', action='store_true',
                        help='Wait and retry only after an explicit Codex usage-limit error')
    parser.add_argument('--quota-retry-minutes', type=int, default=60)
    parser.add_argument('--wait-on-model-capacity', action='store_true',
                        help='Wait and retry only after explicit pinned-model capacity error')
    parser.add_argument('--capacity-retry-minutes', type=int, default=15)
    args = parser.parse_args()
    if (args.begin > args.end or not 1 <= args.chunk_days <= 10
            or args.timeout_minutes < 1 or args.quota_retry_minutes < 1
            or args.capacity_retry_minutes < 1):
        parser.error('invalid date range, chunk-days or timeout')
    if args.wait_on_usage_limit and not args.retry_failed:
        parser.error('--wait-on-usage-limit requires --retry-failed')
    if args.wait_on_model_capacity and not args.retry_failed:
        parser.error('--wait-on-model-capacity requires --retry-failed')
    symbols = [item.strip().upper() for item in args.symbols.split(',') if item.strip()]
    if not symbols or len(symbols) != len(set(symbols)) or any(item not in SYMBOLS for item in symbols):
        parser.error('symbols must be unique members of the approved ten-symbol set')
    args.input_dir = args.input_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    args.indsvr_repo = args.indsvr_repo.resolve()
    class_path = args.indsvr_repo / CLASS_FILE
    if not class_path.is_file():
        raise FileNotFoundError('compiled historical scene tool missing: %s' % class_path)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    campaign_path = args.output_dir / 'campaign.json'
    old = json.loads(campaign_path.read_text(encoding='utf-8')) if campaign_path.is_file() else None
    bars_dir, hashes = prepare_inputs(args, symbols, old)
    campaign = {'begin': args.begin.isoformat(), 'end': args.end.isoformat(),
                'symbols': symbols, 'chunk_days': args.chunk_days, 'model': args.model,
                'input_sha256': hashes, 'tool_class_sha256': sha256(class_path),
                'clock': 'UTC', 'output_mode': 'export_rows_only_no_production_write'}
    if old is not None and old != campaign:
        raise ValueError('campaign configuration or tool class changed; use a new output directory')
    if old is None:
        write_json(campaign_path, campaign)
    tasks = [(symbol, begin, end)
             for begin, end in date_chunks(args.begin, args.end, args.chunk_days)
             for symbol in symbols]
    completed = 0
    executed = 0
    for symbol, begin, end in tasks:
        chunk_dir = args.output_dir / 'chunks' / symbol / (begin.isoformat() + '_' + end.isoformat())
        chunk_dir.mkdir(parents=True, exist_ok=True)
        if args.max_chunks and executed >= args.max_chunks and not (chunk_dir / 'checkpoint.json').is_file():
            break
        print('chunk', symbol, begin, end, flush=True)
        while True:
            try:
                stats, skipped = run_chunk(args, bars_dir, symbol, begin, end, chunk_dir)
                break
            except UsageLimitError as error:
                if not args.wait_on_usage_limit:
                    write_json(args.output_dir / 'status.json',
                               {'completed_chunks': completed, 'total_chunks': len(tasks),
                                'failed_chunk': str(chunk_dir), 'error': str(error)})
                    raise
                write_json(args.output_dir / 'status.json',
                           {'completed_chunks': completed, 'total_chunks': len(tasks),
                            'waiting_chunk': str(chunk_dir), 'reason': str(error),
                            'retry_after_minutes': args.quota_retry_minutes,
                            'updated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds')})
                print('Codex quota reached; wait', args.quota_retry_minutes,
                      'minutes before retrying', chunk_dir, flush=True)
                time.sleep(args.quota_retry_minutes * 60)
            except ModelCapacityError as error:
                if not args.wait_on_model_capacity:
                    write_json(args.output_dir / 'status.json',
                               {'completed_chunks': completed, 'total_chunks': len(tasks),
                                'failed_chunk': str(chunk_dir), 'error': str(error)})
                    raise
                write_json(args.output_dir / 'status.json',
                           {'completed_chunks': completed, 'total_chunks': len(tasks),
                            'waiting_chunk': str(chunk_dir), 'reason': str(error),
                            'retry_after_minutes': args.capacity_retry_minutes,
                            'updated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds')})
                print('Pinned Codex model at capacity; wait', args.capacity_retry_minutes,
                      'minutes before retrying', chunk_dir, flush=True)
                time.sleep(args.capacity_retry_minutes * 60)
            except Exception as error:
                write_json(args.output_dir / 'status.json',
                           {'completed_chunks': completed, 'total_chunks': len(tasks),
                            'failed_chunk': str(chunk_dir), 'error': str(error)})
                raise
        completed += 1
        if not skipped:
            executed += 1
        write_json(args.output_dir / 'status.json',
                   {'completed_chunks': completed, 'total_chunks': len(tasks),
                    'newly_executed': executed, 'last_symbol': symbol,
                    'last_end': end.isoformat(), 'last_rows': stats['rows'],
                    'last_scene_counts': stats['scene_counts'],
                    'updated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds')})
        print('verified', stats['rows'], 'labels', stats['scene_counts'],
              'resumed' if skipped else 'new', flush=True)
    print('campaign progress', completed, '/', len(tasks),
          'newly executed', executed, flush=True)


if __name__ == '__main__':
    main()
