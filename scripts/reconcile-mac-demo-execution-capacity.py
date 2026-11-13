#!/usr/bin/env python3
"""Read-only, exact execution/position/public-trade check after owned load cleanup."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import time


HERE = Path(__file__).resolve().parent
CANCEL = runpy.run_path(str(HERE / 'verify-mac-demo-order-cancel-capacity.py'))
SYMBOL = 'BTC004USDT'
QUANTITY = Decimal('0.001')


def verify_rows(location, run, orders, executions, positions, public, observed):
    prefix = 'T554EXEC-' + run + '-'
    maker = [row for row in orders if row[0] == prefix + 'MAKER']
    assert len(maker) == 1 and maker[0][3] in ('Cancelled', 'Canceled')
    filled = {row[0]: row for row in orders if row[0] != prefix + 'MAKER' and row[3] == 'Filled'}
    assert filled and all(row[0].startswith(prefix) for row in orders)
    assert all(row[3] in ('Filled', 'Cancelled', 'Canceled', 'Rejected', 'Expired') for row in orders)
    taker_users = {row[2] for row in filled.values()}
    assert len(taker_users) == 1 and maker[0][2] not in taker_users
    expected_maker, expected_taker = set(), {}
    for client, row in filled.items():
        match = '\x1f'.join([location, SYMBOL, maker[0][1], row[1], '0'])
        expected_maker.add('E' + hashlib.sha256((match + '\x1fmaker').encode()).hexdigest()[:30])
        expected_taker[client] = 'E' + hashlib.sha256((match + '\x1ftaker').encode()).hexdigest()[:30]
    assert all(client in expected_taker and execution == expected_taker[client]
               for client, execution in observed.items())
    maker_rows = [row for row in executions if row[0] == prefix + 'MAKER']
    taker_rows = [row for row in executions if row[0] != prefix + 'MAKER']
    assert len(maker_rows) == len(taker_rows) == len(filled)
    assert {row[1] for row in maker_rows} == expected_maker
    assert {row[0] for row in taker_rows} == set(filled)
    assert all(row[1] == expected_taker[row[0]] for row in taker_rows)
    assert all(Decimal(str(row[2])) == QUANTITY for row in executions)
    quantity = QUANTITY * len(filled)
    expected_positions = {maker[0][2]: (Decimal(0), quantity),
                          next(iter(taker_users)): (quantity, Decimal(0))}
    assert len(positions) == 2
    assert {row[0]: (Decimal(str(row[1])), Decimal(str(row[2]))) for row in positions} == expected_positions
    public_ids = {row['execID'] for row in public}
    assert len(public) == len(public_ids) == len(filled)
    assert public_ids <= expected_maker | set(expected_taker.values())
    assert all(int(row['count()']) == 1 and Decimal(str(row['sum(quantity)'])) == QUANTITY for row in public)
    for client, row in filled.items():
        match = '\x1f'.join([location, SYMBOL, maker[0][1], row[1], '0'])
        maker_id = 'E' + hashlib.sha256((match + '\x1fmaker').encode()).hexdigest()[:30]
        assert len({maker_id, expected_taker[client]} & public_ids) == 1
    return {'filled_takers': len(filled), 'maker_executions': len(maker_rows),
            'taker_executions': len(taker_rows), 'physical_public_trades': len(public),
            'position_quantity_per_side': str(quantity)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('generation', type=Path)
    parser.add_argument('run')
    args = parser.parse_args()
    root = args.generation.resolve(strict=True)
    if not re.fullmatch(r'mac-demo-[0-9]{8}-[0-9]{6}', root.name) or not re.fullmatch(r'[a-f0-9]{8}', args.run):
        parser.error('Expected an exact Mac generation and owned run ID')
    active = subprocess.check_output(['docker', 'inspect', '-f',
                                     '{{index .Config.Labels "com.docker.compose.project"}}',
                                     'dc-saas-mysql'], text=True).strip()
    if active != root.name:
        raise RuntimeError('Execution reconciliation requires the same active SQL generation')
    original = json.loads((root / ('execution-capacity-' + args.run + '.json')).read_text())
    location = original['location']
    assert re.fullmatch(r'[A-Z0-9]{6}', location)
    output = root / ('execution-' + args.run + '-md-reconciliation-'
                     + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f') + '.json')
    report = {'status': 'NO_GO', 'at': datetime.now(timezone.utc).isoformat(),
              'original_measurement_passed': original['passed'], 'generation': root.name,
              'run': args.run, 'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    sql = CANCEL['PRODUCT']['readonly_sql']
    try:
        query = ("SELECT execID,count(),sum(quantity) FROM dc.market_trade WHERE location='" + location
                 + "' AND securityID='" + SYMBOL + "' GROUP BY execID FORMAT JSONEachRow")
        deadline = time.monotonic() + 30
        while True:
            orders = sql("SELECT clord_id,order_id,user_id,ord_status FROM dc_orders WHERE location='" + location
                         + "' AND clord_id LIKE 'T554EXEC-" + args.run + "-%'")
            executions = sql("SELECT o.clord_id,e.exec_id,e.last_qty FROM dc_orders o JOIN dc_orders_execorders e "
                             "ON e.location=o.location AND e.order_id=o.order_id WHERE o.location='" + location
                             + "' AND o.clord_id LIKE 'T554EXEC-" + args.run + "-%'")
            positions = sql("SELECT user_id,long_position,short_position FROM dc_orders_position WHERE location='"
                            + location + "' AND security_id='" + SYMBOL + "'")
            raw = subprocess.check_output(['docker', 'exec', 'dc-saas-clickhouse', 'clickhouse-client',
                                           '--config-file', '/etc/clickhouse-client/config.xml',
                                           '--query', query], text=True, timeout=20)
            public = [json.loads(line) for line in raw.splitlines()]
            try:
                observed = {row['client_order_id']: row['execution_id'] for row in original['orders']
                            if 'execution_id' in row}
                report.update(verify_rows(location, args.run, orders, executions, positions, public, observed))
                break
            except AssertionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.5)
        report['status'] = 'EXECUTION_IDENTITIES_POSITIONS_AND_RAW_PUBLIC_TRADES_PASS'
    except Exception as error:
        report['failure_type'] = type(error).__name__
        raise
    finally:
        with output.open('x') as evidence:
            json.dump(report, evidence, indent=2)
            evidence.write('\n')
    print(report['status'], output, flush=True)


if __name__ == '__main__':
    main()
