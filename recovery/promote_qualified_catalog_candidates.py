"""Submit frozen, locally qualified catalog sources through INDSvr's normal import flow.

The server recompiles and backtests the last complete 365-day window before its
publisher decides whether to activate. No live registry rows are written here.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import paramiko

from recovery.local_strategy_backtest import DEFAULT_HOST, DEFAULT_USER, DEFAULT_KEY
from recovery.prod_gateway_tunnel import ForwardServer, ForwardHandler
from recovery.strategy_recovery_common import (
    call_gateway, CANDIDATE_IMPORT_TOPIC, CANDIDATE_STATUS_TOPIC, LIVE_LIST_TOPIC,
)
from recovery.run_local_historical_scene_campaign import write_json


def promotion_request(record, formal_dir, end_date):
    envelope = json.loads(Path(record['result_path']).read_text(encoding='utf-8'))
    result = envelope['result']
    if (not record['qualified'] or not result['qualified']
            or result.get('executionModelVersion') != 'v4_non_overlapping_walk_forward'
            or (result.get('holdout') or {}).get('passed') is not True
            or envelope.get('productionWrite') is not False):
        raise ValueError('candidate has no complete local formal and holdout qualification')
    source = Path(envelope['sourceFile']).read_text(encoding='utf-8')
    source_hash = hashlib.sha256(source.encode('utf-8')).hexdigest()
    if source_hash != record['source_sha256']:
        raise ValueError('frozen candidate source changed')
    # INDSvr's established source validator requires these exact argument names.
    # This is an identifier-only transform; retain the original local source hash.
    source = re.sub(r'\bkline\b', 'newKline', source)
    source = re.sub(r'\bindicators\b', 'indicatorSymbol', source)
    seed = json.loads((formal_dir / 'frozen' / record['strategy'] / 'seed.json').read_text(encoding='utf-8'))
    item = seed['strategies'][0]
    if (item['symbol'] != record['symbol'] or item['scene'] != record['scene']
            or item['strategyName'] != record['strategy']):
        raise ValueError('frozen strategy scope changed')
    request = dict(item['request'])
    request.update(strategyName=record['strategy'], scene=record['scene'],
                   symbol=record['symbol'], symbols=record['symbol'], text='15m',
                   description='Frozen catalog signal ' + record['hypothesis'] + '; ' + record['family'],
                   developmentMode='IMPORT', sync=False, validationOnly=False,
                   sourceRef='local-catalog-qualified:20261110:' + source_hash,
                   javaSourceBase64=base64.b64encode(source.encode('utf-8')).decode('ascii'))
    profile = dict(request['optimizationProfile'])
    profile['backtestEndDate'] = end_date.isoformat()
    profile['backtestBeginDate'] = (end_date - timedelta(days=364)).isoformat()
    request['optimizationProfile'] = profile
    return request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--formal-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--backtest-end-date', type=date.fromisoformat, required=True)
    parser.add_argument('--limit', type=int, default=1)
    parser.add_argument('--wait-seconds', type=int, default=1800)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--retry-source-format', action='store_true',
                        help='Retry only a failed exact-signature/IndicatorSymbol source validation')
    args = parser.parse_args()
    records = json.loads((args.formal_dir / 'results.json').read_text(encoding='utf-8'))
    qualified = sorted((record for record in records if record['qualified']), key=lambda item: item['strategy'])
    if args.limit > 0:
        qualified = qualified[:args.limit]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    requests = []
    for record in qualified:
        request = promotion_request(record, args.formal_dir, args.backtest_end_date)
        destination = args.output_dir / record['strategy']
        destination.mkdir(parents=True, exist_ok=True)
        request_path = destination / 'request.json'
        if request_path.exists() and json.loads(request_path.read_text(encoding='utf-8')) != request:
            raise ValueError('server request changed after freeze')
        write_json(request_path, request)
        requests.append((record, request, destination))
    print('prepared locally qualified server candidates', len(requests), flush=True)
    if args.prepare_only or not requests:
        return
    client = paramiko.SSHClient()
    client.load_host_keys(str(Path.home() / '.ssh' / 'known_hosts'))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(DEFAULT_HOST, username=DEFAULT_USER, key_filename=DEFAULT_KEY,
                   passphrase=os.environ.pop('STC_PROD_KEY_PASSPHRASE'),
                   look_for_keys=False, allow_agent=False, timeout=20)
    server = None
    try:
        ForwardHandler.transport = client.get_transport()
        ForwardHandler.remote_port = 31002
        server = ForwardServer(('127.0.0.1', 0), ForwardHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = 'http://127.0.0.1:%d/gw' % server.server_address[1]
        api_key = os.environ.get('DC_GW_APIKEY', '1')
        # Harmless read proves this is the quant GW, rather than the retained legacy port 3002.
        call_gateway(url, api_key, LIVE_LIST_TOPIC, {'status': 'ACTIVE', 'pageSize': 1}, attempts=1)
        for record, request, destination in requests:
            name = record['strategy']
            response_path = destination / 'submission.json'
            if response_path.exists():
                response = json.loads(response_path.read_text(encoding='utf-8'))
            else:
                existing = call_gateway(url, api_key, CANDIDATE_STATUS_TOPIC,
                                        {'strategyName': name}, attempts=1)
                write_json(destination / 'before-status.json', existing)
                summary = existing.get('summary') or {}
                compile_log = str((existing.get('generationTask') or {}).get('compile_log') or '')
                format_failure = (args.retry_source_format
                                  and summary.get('generationStatus') == 'FAILED'
                                  and summary.get('generationFailureCode') == 'COMPILE_FAILED'
                                  and ('Method signature must be exactly:' in compile_log
                                       or 'must use indicatorSymbol.getIndicator(symbol)' in compile_log))
                if not format_failure and any(str(summary.get(key) or '-').upper() not in ('', '-')
                       for key in ('candidateStatus', 'generationStatus', 'backtestTaskStatus')):
                    existing_version = str((existing.get('candidate') or {}).get('strategy_version')
                                           or (existing.get('generationTask') or {}).get('strategy_version') or 'v1')
                    response = {'strategyName': name, 'strategyVersion': existing_version, 'existing': True}
                else:
                    write_json(destination / 'submission-attempt.json', {'strategy': name,
                               'request_sha256': hashlib.sha256((destination / 'request.json').read_bytes()).hexdigest()})
                    response = call_gateway(url, api_key, CANDIDATE_IMPORT_TOPIC, request,
                                            timeout=180, attempts=1)
                write_json(response_path, response)
            version = str(response.get('strategyVersion') or 'v1')
            print('server candidate', name, version, 'submitted', flush=True)
            deadline = time.monotonic() + args.wait_seconds
            previous = None
            while time.monotonic() < deadline:
                status = call_gateway(url, api_key, CANDIDATE_STATUS_TOPIC,
                                      {'strategyName': name, 'strategyVersion': version}, attempts=1)
                write_json(destination / 'status.json', status)
                summary = status.get('summary') or {}
                phases = (str(summary.get('generationStatus') or '-').upper(),
                          str(summary.get('backtestTaskStatus') or '-').upper())
                if phases != previous:
                    print(name, 'generation', phases[0], 'backtest', phases[1], flush=True)
                    previous = phases
                if phases[0] in ('FAILED', 'CANCELLED', 'SKIPPED') or phases[1] in (
                        'SUCCESS', 'FAILED', 'CANCELLED', 'SKIPPED', 'SUSPENDED'):
                    live = call_gateway(url, api_key, LIVE_LIST_TOPIC,
                                        {'strategyName': name, 'status': 'ACTIVE', 'pageSize': 20}, attempts=1)
                    write_json(destination / 'live.json', live)
                    active = [row for row in live.get('items', []) if row.get('strategyName') == name
                              and str(row.get('status')).upper() == 'ACTIVE']
                    write_json(destination / 'outcome.json', {'strategy': name, 'version': version,
                               'generation_status': phases[0], 'backtest_status': phases[1],
                               'published': bool(active), 'registry_versions': active})
                    print(name, 'server terminal', phases, 'published', bool(active), flush=True)
                    break
                time.sleep(5)
            else:
                print(name, 'server still running; resume using saved submission', flush=True)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        client.close()


if __name__ == '__main__':
    main()
