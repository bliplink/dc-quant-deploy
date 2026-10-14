"""Read-only production snapshot of active strategy v4 qualifications.

Requires STC_PROD_KEY_PASSPHRASE in the process environment. No credentials are
stored in reports or source. The SSH host must already be in known_hosts.
"""

import argparse
import base64
import csv
import io
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import paramiko


ACTIVE_SQL = """SELECT strategy_name, strategy_version, symbol_scope, text_scope,
 scene, category, runtime_type, effective_time
 FROM dc.strategy_live_registry
 WHERE status='ACTIVE' AND (retire_time IS NULL OR retire_time > now())
 FORMAT JSONEachRow"""

REGISTRY_SQL = """SELECT strategy_name, strategy_version, symbol_scope,
 text_scope, scene, status, retire_time, effective_time, artifact_uri
 FROM dc.strategy_live_registry FORMAT JSONEachRow"""

CANDIDATE_SQL = """SELECT strategy_name, strategy_version, scene, status,
 compile_status, source_ref, artifact_uri, create_time
 FROM dc.strategy_candidate FORMAT JSONEachRow"""

RESULT_SQL = """SELECT strategy_name, strategy_version, upper(symbol) AS key_symbol,
 lower(text) AS key_text, argMax(tuple(toString(run_time),begin_date,end_date,
 trade_count,profit_factor,max_drawdown_pct,fee_adjusted_validate_pnl,
 fee_adjusted_forward_pnl,oos_pass,total_pnl,min_forward_contribution),run_time) AS latest_metrics
 FROM (
   SELECT r.* FROM dc.backtest_result AS r
   LEFT JOIN (
     SELECT id,
       argMax(JSONExtractString(JSONExtractRaw(payload,'backtestParam'),'beginDate'),update_time) AS requested_begin,
       argMax(JSONExtractString(JSONExtractRaw(payload,'backtestParam'),'endDate'),update_time) AS requested_end
     FROM dc.strategy_backtest_task
     WHERE status='PENDING'
       AND lowerUTF8(JSONExtractString(payload,'workflowMode'))='live_recheck'
     GROUP BY id
   ) AS recheck ON recheck.id=r.sid
   WHERE r.execution_model_version='v4_non_overlapping_walk_forward'
     AND r.run_time >= now()-INTERVAL 45 DAY
     AND (ifNull(recheck.id,'')='' OR ifNull(recheck.requested_begin,'')=''
       OR (recheck.requested_begin=r.begin_date
         AND (ifNull(recheck.requested_end,'')='' OR recheck.requested_end=r.end_date)))
 )
 GROUP BY strategy_name,strategy_version,key_symbol,key_text
 FORMAT JSONEachRow"""


def query(client, sql):
    encoded = base64.b64encode(sql.encode('utf-8')).decode('ascii')
    command = 'printf %s ' + encoded + ' | base64 -d | sudo docker exec -i dc-clickhouse clickhouse-client'
    _, stdout, stderr = client.exec_command(command, timeout=120)
    data = stdout.read().decode('utf-8', 'replace')
    error = stderr.read().decode('utf-8', 'replace')
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError('ClickHouse query failed: ' + error[:2000])
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def key(row, active=False):
    symbol = row['symbol_scope'] if active else row['key_symbol']
    text = row['text_scope'] if active else row['key_text']
    return tuple(str(value).strip().lower() for value in
                 (row['strategy_name'], row['strategy_version'], symbol, text))


def reason(row):
    if row is None:
        return 'realistic_backtest_missing'
    if row['oos_pass'] != 1:
        return 'oos_not_passed'
    if row['trade_count'] < 20:
        return 'too_few_trades'
    if row['profit_factor'] < 1.20:
        return 'profit_factor_too_low'
    if row['max_drawdown_pct'] > 0.15:
        return 'drawdown_too_high'
    if row['fee_adjusted_validate_pnl'] <= 0:
        return 'fee_adjusted_validate_not_positive'
    if row['fee_adjusted_forward_pnl'] <= 0:
        return 'fee_adjusted_forward_not_positive'
    return 'qualified'


def passes_forward_contribution(row):
    if reason(row) != 'qualified':
        return False
    ratio = forward_contribution_ratio(row)
    required = row.get('min_forward_contribution') or 0.20
    return ratio is not None and ratio >= required


def forward_contribution_ratio(row):
    if row is None or (row.get('total_pnl') or 0) <= 0:
        return None
    return row['fee_adjusted_forward_pnl'] / row['total_pnl']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='18.140.45.126')
    parser.add_argument('--user', default='ec2-user')
    parser.add_argument('--key', default=str(Path.home() / 'Desktop' / 'id_rsa_2048'))
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    passphrase = os.environ['STC_PROD_KEY_PASSPHRASE']
    client = paramiko.SSHClient()
    client.load_host_keys(str(Path.home() / '.ssh' / 'known_hosts'))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(args.host, username=args.user, key_filename=args.key,
                   passphrase=passphrase, look_for_keys=False, allow_agent=False,
                   timeout=20, banner_timeout=20, auth_timeout=20)
    try:
        active = query(client, ACTIVE_SQL)
        registry = query(client, REGISTRY_SQL)
        candidates = query(client, CANDIDATE_SQL)
        results = query(client, RESULT_SQL)
    finally:
        client.close()
    metric_fields = ['run_time', 'begin_date', 'end_date', 'trade_count',
                     'profit_factor', 'max_drawdown_pct',
                     'fee_adjusted_validate_pnl', 'fee_adjusted_forward_pnl', 'oos_pass',
                     'total_pnl', 'min_forward_contribution']
    by_key = {key(row): dict(zip(metric_fields, row['latest_metrics'])) for row in results}
    active_keys = {key(row, active=True) for row in active}
    candidate_by_version = {(row['strategy_name'].strip().lower(),
                             row['strategy_version'].strip().lower()): row for row in candidates}
    rows = []
    for item in active:
        result = by_key.get(key(item, active=True))
        rows.append({**item, **(result or {}), 'reason': reason(result),
                     'passes_forward_contribution': passes_forward_contribution(result)})
    rows.sort(key=lambda row: (row['reason'], row['symbol_scope'], row['scene'], row['strategy_name']))
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    fields = ['strategy_name', 'strategy_version', 'symbol_scope', 'text_scope',
              'scene', 'category', 'runtime_type', 'reason', 'run_time', 'begin_date',
              'end_date', 'trade_count', 'profit_factor', 'max_drawdown_pct',
              'fee_adjusted_validate_pnl', 'fee_adjusted_forward_pnl', 'oos_pass',
              'total_pnl', 'min_forward_contribution', 'passes_forward_contribution']
    with (output / 'active_strategy_qualification.tsv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter='\t', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    inactive_qualified = []
    for item in registry:
        result_key = key(item, active=True)
        if result_key in active_keys or reason(by_key.get(result_key)) != 'qualified':
            continue
        inactive_qualified.append({**item, **by_key[result_key]})
    inactive_fields = ['strategy_name', 'strategy_version', 'symbol_scope', 'text_scope',
                       'scene', 'status', 'retire_time', 'effective_time', 'artifact_uri',
                       'run_time', 'trade_count', 'profit_factor',
                       'fee_adjusted_validate_pnl', 'fee_adjusted_forward_pnl']
    with (output / 'inactive_qualified_registry.tsv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=inactive_fields, delimiter='\t', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(inactive_qualified)
    qualified_unregistered = []
    for result_key, metrics in by_key.items():
        if result_key in active_keys or reason(metrics) != 'qualified':
            continue
        candidate = candidate_by_version.get(result_key[:2], {})
        qualified_unregistered.append({
            'strategy_name': result_key[0], 'strategy_version': result_key[1],
            'symbol': result_key[2], 'text': result_key[3],
            **metrics,
            'forward_contribution_ratio': forward_contribution_ratio(metrics),
            'passes_forward_contribution': passes_forward_contribution(metrics),
            'candidate_scene': candidate.get('scene', ''),
            'candidate_status': candidate.get('status', ''),
            'compile_status': candidate.get('compile_status', ''),
            'source_ref': candidate.get('source_ref', ''),
            'artifact_uri': candidate.get('artifact_uri', ''),
        })
    candidate_fields = ['strategy_name', 'strategy_version', 'symbol', 'text',
                        'candidate_scene', 'candidate_status', 'compile_status',
                        'run_time', 'trade_count', 'profit_factor',
                        'fee_adjusted_validate_pnl', 'fee_adjusted_forward_pnl',
                        'total_pnl', 'min_forward_contribution',
                        'forward_contribution_ratio', 'passes_forward_contribution',
                        'source_ref', 'artifact_uri']
    with (output / 'qualified_unregistered_candidates.tsv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=candidate_fields, delimiter='\t', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(qualified_unregistered)
    summary = {
        'snapshot_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'active_count': len(rows),
        'qualified_count': sum(row['reason'] == 'qualified' for row in rows),
        'active_passing_forward_contribution_count': sum(
            row['passes_forward_contribution'] for row in rows),
        'inactive_qualified_registry_count': len(inactive_qualified),
        'qualified_unregistered_candidate_count': len(qualified_unregistered),
        'qualified_unregistered_passing_forward_contribution_count': sum(
            row['passes_forward_contribution'] for row in qualified_unregistered),
        'reason_counts': dict(Counter(row['reason'] for row in rows)),
        'unqualified_by_symbol_scene': dict(Counter(
            row['symbol_scope'] + '/' + row['scene'] for row in rows if row['reason'] != 'qualified')),
    }
    (output / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
