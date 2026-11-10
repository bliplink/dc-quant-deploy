"""Audit ACTIVE rows against the running INDSvr gate; explicitly retire failures.

Default mode is read-only. Apply requires an exact frozen plan hash, the new
status-only offline contract, and fresh server-side qualification verification.
No direct database writes, close signals, order cancellation, or risk changes.
"""

import argparse
import hashlib
import json
import os
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import paramiko

from recovery.prod_gateway_tunnel import ForwardHandler, ForwardServer
from recovery.strategy_inventory_snapshot import ACTIVE_SQL, RESULT_SQL, key, query, reason
from recovery.strategy_recovery_common import atomic_write_json, call_gateway, LIVE_LIST_TOPIC


OFFLINE_TOPIC = 'dc.ind.workbench.live.strategy.offline'
AUDIT_TOPIC = 'dc.ind.strategy.library.audit'
METRICS = ['run_time', 'begin_date', 'end_date', 'trade_count', 'profit_factor',
           'max_drawdown_pct', 'fee_adjusted_validate_pnl', 'fee_adjusted_forward_pnl',
           'oos_pass', 'total_pnl', 'min_forward_contribution']
EXPECTED_CONFIG = {
    'strategy.selection.backtest-qualification.enabled': 'true',
    'strategy.selection.backtest-qualification.execution-model-version': 'v4_non_overlapping_walk_forward',
    'strategy.selection.backtest-qualification.max-age-days': '45',
    'strategy.selection.backtest-qualification.min-trades': '20',
    'strategy.selection.backtest-qualification.min-profit-factor': '1.20',
    'strategy.selection.backtest-qualification.max-drawdown-pct': '0.15',
}


def build_rows(active, results):
    lookup = {key(row): dict(zip(METRICS, row['latest_metrics'])) for row in results}
    return [{**row, 'metrics': lookup.get(key(row, True)),
             'reason': reason(lookup.get(key(row, True)))} for row in active]


def confirmed_failure(row):
    return row['reason'] not in ('qualified', 'realistic_backtest_missing')


def offline_request(row):
    for field in ('strategy_name', 'strategy_version', 'symbol_scope', 'text_scope'):
        value = row.get(field)
        if not isinstance(value, str) or not value.strip() or any(c in value for c in '*|,;'):
            raise ValueError('exact strategy/version/scope is required: ' + field)
    if not confirmed_failure(row):
        raise ValueError('only confirmed gate failures may be offlined')
    return {
        'strategyName': row['strategy_name'], 'strategyVersion': row['strategy_version'],
        'symbolScope': row['symbol_scope'], 'textScope': row['text_scope'],
        'closePositions': False, 'requireIneligible': True,
        'source': 'eligibility_status_reconcile_20261110',
        'reason': 'Registered ACTIVE but blocked by INDSvr qualification: ' + row['reason']
                  + '; status-only offline, existing position management unchanged',
    }


def remote_text(client, command):
    _, out, err = client.exec_command(command, timeout=60)
    data, error = out.read().decode('utf-8', 'replace'), err.read().decode('utf-8', 'replace')
    if out.channel.recv_exit_status():
        raise RuntimeError('remote read failed: ' + error[:1000])
    return data


def check_config(client):
    content = remote_text(client, "sudo docker exec dc-indsvr sh -c "
                          "'grep -E \"^strategy.selection.backtest-qualification\\.\" config/application.properties'")
    config = dict(line.strip().split('=', 1) for line in content.splitlines() if '=' in line)
    for name, expected in EXPECTED_CONFIG.items():
        if config.get(name) != expected:
            raise ValueError('running qualification configuration differs: ' + name)
    return config


def snapshot(client, url, api_key, directory):
    directory.mkdir(parents=True, exist_ok=True)
    rows = build_rows(query(client, ACTIVE_SQL), query(client, RESULT_SQL))
    audit = call_gateway(url, api_key, AUDIT_TOPIC, {}, timeout=90, attempts=1)
    qualified = sum(row['reason'] == 'qualified' for row in rows)
    if audit['activeCount'] != len(rows) or audit['activeQualifiedCount'] != qualified:
        raise ValueError('database and runtime gate audit disagree; repeat a read-only snapshot')
    atomic_write_json(directory / 'active-rows.json', rows)
    atomic_write_json(directory / 'runtime-audit.json', audit)
    atomic_write_json(directory / 'registry-backup.json', query(client,
        'SELECT * FROM dc.strategy_live_registry FORMAT JSONEachRow'))
    return rows, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-plan-sha256')
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    plan_path = directory / 'plan.json'
    if not args.apply and plan_path.exists():
        raise ValueError('existing frozen plan; use a new output directory without overwriting evidence')
    if args.apply:
        if not args.expected_plan_sha256 or not plan_path.exists():
            parser.error('--apply requires an existing plan and --expected-plan-sha256')
        if hashlib.sha256(plan_path.read_bytes()).hexdigest() != args.expected_plan_sha256:
            raise ValueError('frozen plan hash changed')
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        if plan['close_positions'] is not False or plan['direct_database_writes'] is not False:
            raise ValueError('unsafe plan policy')
    client = paramiko.SSHClient()
    client.load_host_keys(str(Path.home() / '.ssh/known_hosts'))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect('18.140.45.126', username='ec2-user',
                   key_filename=str(Path.home() / 'Desktop/id_rsa_2048'),
                   passphrase=os.environ.pop('STC_PROD_KEY_PASSPHRASE'),
                   look_for_keys=False, allow_agent=False, timeout=20)
    client.get_transport().set_keepalive(20)
    server = None
    try:
        if remote_text(client, 'hostname').strip() != 'prod-mooncake-standby':
            raise ValueError('unexpected production host')
        config = check_config(client)
        ForwardHandler.transport = client.get_transport()
        ForwardHandler.remote_port = 31002
        server = ForwardServer(('127.0.0.1', 0), ForwardHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = 'http://127.0.0.1:%d/gw' % server.server_address[1]
        api_key = os.environ.get('DC_GW_APIKEY', '1')
        if not args.apply:
            rows, audit = snapshot(client, url, api_key, directory / 'before')
            targets = [row for row in rows if confirmed_failure(row)]
            for row in targets:
                offline_request(row)
            plan = {'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    'host': '18.140.45.126', 'runtime_config': config,
                    'active_before': len(rows), 'qualified_before': audit['activeQualifiedCount'],
                    'target_count': len(targets), 'targets': targets,
                    'retained': [row for row in rows if not confirmed_failure(row)],
                    'close_positions': False, 'direct_database_writes': False,
                    'target_reasons': dict(Counter(row['reason'] for row in targets))}
            atomic_write_json(plan_path, plan)
            print(json.dumps({name: plan[name] for name in
                  ('active_before', 'qualified_before', 'target_count', 'target_reasons')}), flush=True)
            print('PLAN_SHA256=' + hashlib.sha256(plan_path.read_bytes()).hexdigest(), flush=True)
            return
        if config != plan['runtime_config'] or plan['host'] != '18.140.45.126':
            raise ValueError('plan production policy mismatch')
        # Old service versions ignore unknown fields and would emit close signals.
        # A nonexistent exact name proves the new response contract before any mutation.
        probe = call_gateway(url, api_key, OFFLINE_TOPIC, {
            'strategyName': '__eligibility_status_only_capability_probe__',
            'strategyVersion': 'v0', 'symbolScope': 'BTCUSDT', 'textScope': '15m',
            'closePositions': False, 'requireIneligible': True}, attempts=1)
        if (probe.get('changed') is not False or probe.get('closePositions') is not False
                or probe.get('closeSignalCount') != 0 or probe.get('offlineExecutionStatus') != 'status_only'):
            raise ValueError('server does not support safe status-only offline; no target was changed')
        atomic_write_json(directory / 'capability-probe.json', probe)
        outcomes = []
        for index, row in enumerate(plan['targets'], 1):
            checkpoint = directory / 'outcomes' / (hashlib.sha256('|'.join(key(row, True)).encode()).hexdigest() + '.json')
            if checkpoint.exists():
                saved = json.loads(checkpoint.read_text(encoding='utf-8'))
                if saved['state'] == 'needs_inspection':
                    raise ValueError('previous mutation needs inspection: ' + str(checkpoint))
                outcomes.append(saved)
                continue
            request = offline_request(row)
            # Single mutation attempt: never blindly replay a timeout or partial success.
            outcome = {'request': request}
            if checkpoint.with_suffix('.attempt.json').exists():
                raise ValueError('previous attempt has no response; inspect server state before continuing')
            atomic_write_json(checkpoint.with_suffix('.attempt.json'), outcome)
            try:
                response = call_gateway(url, api_key, OFFLINE_TOPIC, request, timeout=120, attempts=1)
                if response.get('changed'):
                    if (response.get('closePositions') is not False or response.get('closeSignalCount') != 0
                            or response.get('offlineExecutionStatus') != 'status_only'):
                        raise ValueError('unexpected offline execution contract')
                    state = 'offlined'
                else:
                    state = 'already_inactive_or_replaced'
                outcome.update(state=state, response=response)
            except Exception as error:
                outcome.update(state='needs_inspection', error=str(error))
                atomic_write_json(checkpoint, outcome)
                raise
            atomic_write_json(checkpoint, outcome)
            outcomes.append(outcome)
            print(index, '/', plan['target_count'], row['strategy_name'], row['strategy_version'], state, flush=True)
        # ClickHouse ALTER UPDATE is asynchronous; verify completion, not API acceptance.
        targets = {key(row, True) for row in plan['targets']}
        remaining = []
        for _ in range(30):
            remaining = [row for row in query(client, ACTIVE_SQL) if key(row, True) in targets]
            if not remaining:
                break
            time.sleep(2)
        if remaining:
            raise ValueError('target ACTIVE mutations have not completed')
        rows, audit = snapshot(client, url, api_key, directory / 'after')
        live = call_gateway(url, api_key, LIVE_LIST_TOPIC, {'status': 'ACTIVE', 'pageSize': 200},
                            timeout=120, attempts=1)
        atomic_write_json(directory / 'after' / 'ui-active-list.json', live)
        if live['total'] != len(rows):
            raise ValueError('UI ACTIVE count differs from database truth')
        summary = {'finished_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                   'target_count': plan['target_count'], 'outcomes': dict(Counter(o['state'] for o in outcomes)),
                   'active_after': len(rows), 'qualified_after': audit['activeQualifiedCount'],
                   'unqualified_active_after': audit['activeUnqualifiedCount'],
                   'ui_active_count': live['total'], 'close_signals_emitted': 0,
                   'direct_database_writes': False}
        atomic_write_json(directory / 'summary.json', summary)
        print(json.dumps(summary), flush=True)
    finally:
        if server:
            server.shutdown()
            server.server_close()
        client.close()


if __name__ == '__main__':
    main()
