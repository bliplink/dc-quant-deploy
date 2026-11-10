"""Read-only existing OHLCV/historical-scene extension; no generators or database writes."""

import argparse
import csv
import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import paramiko

from recovery.export_strategy_research_data import SYMBOLS, export_query, assert_unique_bar_times
from recovery.local_strategy_backtest import DEFAULT_HOST, DEFAULT_USER, DEFAULT_KEY
from recovery.strategy_inventory_snapshot import query
from recovery.strategy_recovery_common import atomic_write_json


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_bars(path, begin, end):
    assert_unique_bar_times(path)
    expected, stop = datetime.combine(begin, datetime.min.time()), datetime.combine(end + timedelta(days=1), datetime.min.time())
    count = 0
    with path.open(encoding='utf-8', newline='') as stream:
        for row in csv.reader(stream, delimiter='\t'):
            if len(row) != 6 or datetime.fromisoformat(row[0]) != expected:
                raise ValueError('missing, extra or malformed OHLCV timestamp in ' + str(path))
            o, h, low, close, volume = map(Decimal, row[1:])
            if not all(value.is_finite() for value in (o, h, low, close, volume)):
                raise ValueError('nonfinite OHLCV')
            if min(o, low, close) <= 0 or h < max(o, low, close) or low > min(o, close) or volume < 0:
                raise ValueError('invalid OHLCV bounds')
            expected += timedelta(minutes=15)
            count += 1
    if expected != stop:
        raise ValueError('incomplete OHLCV export in ' + str(path))
    return count


def verify_scenes(path, begin, end):
    expected, stop = datetime.combine(begin, datetime.min.time()), datetime.combine(end + timedelta(days=1), datetime.min.time())
    count = 0
    with path.open(encoding='utf-8', newline='') as stream:
        for row in csv.reader(stream, delimiter='\t'):
            if (len(row) != 5 or datetime.fromisoformat(row[0]) != expected
                    or row[2:] != ['SUCCESS', 'historical_kline_scene', 'market_scene_v3_historical_kline_v1']):
                raise ValueError('historical scene timestamp/contract gap or ambiguity in ' + str(path))
            expected += timedelta(hours=12)
            count += 1
    if expected != stop:
        raise ValueError('incomplete historical scene export in ' + str(path))
    return count


def overlap_rows(path, first, last, bars):
    records = {}
    with path.open(encoding='utf-8', newline='') as stream:
        for row in csv.reader(stream, delimiter='\t'):
            if first <= row[0][:10] <= last:
                key = datetime.fromisoformat(row[0])
                if key in records:
                    raise ValueError('ambiguous source overlap timestamp')
                records[key] = tuple(map(Decimal, row[1:])) if bars else tuple(row[1:])
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-dir', 'output-dir', 'protocol'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    source, output, protocol_path = args.source_dir.resolve(), args.output_dir.resolve(), args.protocol.resolve()
    if output.exists():
        raise ValueError('preserve every export attempt; output directory must be new')
    protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    if protocol.get('protocol_version') != 'temporal_source_research_v2':
        raise ValueError('explicit frozen temporal-v2 protocol required')
    first = date.fromisoformat(protocol['holdout_begin']) - timedelta(days=2)
    last = date.fromisoformat(protocol['holdout_end_inclusive'])
    ready = json.loads((source / 'READY.json').read_text(encoding='utf-8'))
    if ready['end'] != protocol['primary_end_inclusive'] or ready['clock'] != 'UTC':
        raise ValueError('extension must follow the frozen primary input')
    output.mkdir(parents=True)
    atomic_write_json(output / 'manifest.json', {'schema': 'existing_ohlcv_holdout_extension_v1',
        'protocol_sha256': sha(protocol_path), 'source_ready_sha256': sha(source / 'READY.json'),
        'export_begin': str(first), 'export_end_inclusive': str(last), 'host': DEFAULT_HOST,
        'production_write': False, 'server_codegen_allowed': False})
    client = paramiko.SSHClient()
    client.load_host_keys(str(Path.home() / '.ssh/known_hosts'))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    records = []
    try:
        client.connect(DEFAULT_HOST, username=DEFAULT_USER, key_filename=DEFAULT_KEY,
            passphrase=os.environ.pop('STC_PROD_KEY_PASSPHRASE'), look_for_keys=False,
            allow_agent=False, timeout=20, banner_timeout=20, auth_timeout=20)
        client.get_transport().set_keepalive(20)
        _, stdout, stderr = client.exec_command('hostname', timeout=20)
        hostname, error = stdout.read().decode().strip(), stderr.read().decode()
        if stdout.channel.recv_exit_status() or hostname != 'prod-mooncake-standby':
            raise ValueError('unexpected read-only export host')
        if query(client, 'SELECT timezone() AS timezone FORMAT JSONEachRow') != [{'timezone': 'UTC'}]:
            raise ValueError('existing input export assumes verified ClickHouse UTC')
        for symbol in SYMBOLS:
            for suffix, bars in (('-15m.tsv', True), ('-scenes.tsv', False)):
                if sha(source / (symbol + suffix)) != ready['files'][symbol]['bars_sha256' if bars else 'scenes_sha256']:
                    raise ValueError('frozen primary input changed')
            bar_path, scene_path = output / (symbol + '-15m.tsv'), output / (symbol + '-scenes.tsv')
            export_query(client,
                "SELECT startTime,toFloat64(open),toFloat64(high),toFloat64(low),toFloat64(close),toFloat64(volume) "
                "FROM dc.kline_view WHERE lowerUTF8(text)='15m' AND securityID='%s' "
                "AND open IS NOT NULL AND high IS NOT NULL AND low IS NOT NULL AND close IS NOT NULL "
                "AND startTime>=toDateTime('%s 00:00:00','UTC') "
                "AND startTime<toDateTime('%s 00:00:00','UTC')+INTERVAL 1 DAY AND endTime<now64(6) "
                "ORDER BY startTime ASC,(length(fmtTime)>=10) DESC,endTime DESC,fmtTime ASC LIMIT 1 BY startTime"
                % (symbol, first, last), bar_path)
            export_query(client,
                "SELECT run_time,scene,status,analysis_type,prompt_version FROM dc.deepseek_market_scene_analysis "
                "WHERE symbol='%s' AND run_time>=toDateTime('%s 00:00:00','UTC') "
                "AND run_time<toDateTime('%s 00:00:00','UTC')+INTERVAL 1 DAY "
                "AND analysis_type='historical_kline_scene' AND prompt_version='market_scene_v3_historical_kline_v1' "
                "AND status='SUCCESS' ORDER BY run_time" % (symbol, first, last), scene_path)
            counts = {'bars': verify_bars(bar_path, first, last), 'scenes': verify_scenes(scene_path, first, last)}
            for suffix, bars in (('-15m.tsv', True), ('-scenes.tsv', False)):
                old = overlap_rows(source / (symbol + suffix), str(first), ready['end'], bars)
                new = overlap_rows(output / (symbol + suffix), str(first), ready['end'], bars)
                if not old or old != new:
                    raise ValueError('existing source overlap differs: ' + symbol + suffix)
            records.append({'symbol': symbol, **counts, 'bars_sha256': sha(bar_path),
                'scenes_sha256': sha(scene_path), 'overlap_days': 2, 'overlap_exact': True})
            atomic_write_json(output / 'status.json', {'completed': len(records), 'total': len(SYMBOLS),
                'records': records, 'production_write': False})
            print('VERIFIED_EXTENSION', symbol, counts, flush=True)
        atomic_write_json(output / 'EXTENSION_COMPLETE.json', {'records': records,
            'snapshot_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'manifest_sha256': sha(output / 'manifest.json'), 'production_write': False,
            'server_codegen_calls': 0, 'read_only_existing_data': True})
    except Exception as error:
        atomic_write_json(output / 'error.json', {'error': str(error), 'completed': len(records), 'production_write': False})
        raise
    finally:
        client.close()


if __name__ == '__main__':
    main()
