"""Measure one funded matching book on the clean hosted installation, with ten background Robots."""
from collections import Counter
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
SECONDS = 60


def publish(title, summary):
    text = json.dumps(summary, ensure_ascii=True, indent=2)
    with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a') as stream:
        stream.write(f'## {title}\n\n```json\n{text}\n```\n')
    print(title, text, flush=True)


def book_prices(cancel, location, symbol):
    if not re.fullmatch('[A-Z0-9]{6}', location) or symbol != 'BTCUSDT':
        raise ValueError('Expected an installed public BTCUSDT maker')
    query = ("SELECT MAX(CASE WHEN o.side='Buy' THEN o.price END), "
             "MIN(CASE WHEN o.side='Sell' THEN o.price END) FROM dc_orders o "
             "JOIN dc_tenant_liquidity_bootstrap j ON o.location=j.location AND o.user_id=j.maker_user_id "
             "JOIN dc_tenant_robot r ON r.location=j.location AND r.api_user_id=j.maker_user_id "
             f"WHERE o.location='{location}' AND o.security_id='BTCUSDT' AND o.market_indicator='4' "
             "AND j.status='COMPLETE' AND j.funding_confirmed=1 AND r.enabled=1 AND r.runtime_status='RUNNING' "
             "AND r.last_heartbeat_time>=NOW()-INTERVAL 30 SECOND "
             "AND o.ord_status IN ('New','Partially_Filled') AND o.leaves_qty>0 AND o.price>0")
    until = time.monotonic() + 30
    while True:
        rows = cancel['PRODUCT']['readonly_sql'](query)
        if len(rows) == 1 and len(rows[0]) == 2 and 'NULL' not in rows[0]:
            bid, ask = map(Decimal, rows[0])
            if 0 < bid < ask:
                break
        if time.monotonic() >= until:
            raise RuntimeError('No fresh two-sided funded maker quotes in the installed order projection')
        time.sleep(0.5)
    # Keep GTC cancel orders off the touch. Provide a funded sell limit behind
    # the public maker to cover the complete IOC window even if its quote moves.
    return (str((bid * Decimal('0.95')).to_integral_value(rounding=ROUND_DOWN)),
            str((ask * Decimal('1.005')).to_integral_value(rounding=ROUND_UP)))


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_OS') != 'Linux':
        raise RuntimeError('This measurement requires a disposable hosted Linux installation')
    policy = os.environ.get('T554_HOSTED_ACK_POLICY', 'STRICT_QUORUM')
    os.umask(0o077)
    base = Path(os.environ['RUNNER_TEMP']) / 't554-install'
    receipt = json.loads((base / 'installation.json').read_text())
    generation = os.environ['SIMULATION_GENERATION']
    if receipt['generation'] != generation or not re.fullmatch('sim-demo-[0-9]{8}-[0-9]{6}', generation):
        raise RuntimeError('The installed generation differs from the measurement')
    install = runpy.run_path(str(ROOT / 'scripts/install-public-simulation.py'))
    inventory = install['inventory'](generation)
    if receipt['runningImages'] != inventory:
        raise RuntimeError('Installed runtime differs from the verified receipt')
    directory = base / generation
    ports = install['simulation'].common.env_pairs(directory / 'demo.env')
    os.environ['OTC_CAPACITY_GATEWAY_HTTP_PORT'] = ports['GW_HTTP_PORT']
    harness = runpy.run_path(str(ROOT / 'scripts/verify-mac-demo-distributed-execution-capacity.py'))
    cancel, native, execution = harness['CANCEL'], harness['NATIVE'], harness['EXEC']
    symbol = 'BTCUSDT'
    baseline = cancel['CAPACITY']['demo_tenants']()
    if set(baseline) != set(receipt['tenants']) or len(baseline) != 10 or set(baseline.values()) != {'RUNNING'}:
        raise RuntimeError('Expected the ten funded background Robots')
    port = int(ports['GW_TCP_PORT'])
    work = native['prepare'](directory)
    cancel_work = native['prepare'](directory, ROOT / 'tests/MacDemoNativeTcpOrderCancel.java', 'MacDemoNativeTcpOrderCancel')
    run = secrets.token_hex(4)
    location = receipt['tenants'][0]
    maker = cancel['new_trader'](location, symbol, 'TRADE', run, 0, funding_amount=100000)
    trader = cancel['new_trader'](location, symbol, 'TRADE', run, 1, funding_amount=100000)
    cancel_price, _ = book_prices(cancel, location, symbol)
    config = dict(location=location, user_id=trader[1], symbol=symbol, port=port, seconds=SECONDS)
    with cancel['native_trader_session'](trader, run, 'cancel') as (_, _, token):
        measured = native['run'](cancel_work, dict(config, token=token, price=cancel_price,
                prefix='T554CC-'+run, max_requests_per_second=40, start_at_epoch_ms=int(time.time()*1000)+5000))
    rows = measured['orders']
    completed = bool(rows) and all(row.get('passed') is True for row in rows)
    commands = sum(int(row.get(k) is True) for row in rows for k in ('new_inside_window','cancel_inside_window'))
    publish(f'{policy} TCP place and cancel, one funded session', {
        'seconds': SECONDS, 'attempted_cycles': len(rows), 'commands_per_second': commands / SECONDS,
        'failures': dict(Counter(row.get('failure_reason', row.get('outcome', 'MISSING')) for row in rows if not row.get('passed'))),
        'successful_cycles': sum(row.get('passed') is True for row in rows),
        'new_ms': execution['summary_ms'](rows, 'place_new_ms'), 'cancel_ms': execution['summary_ms'](rows, 'cancel_terminal_ms'),
        'stream_errors': measured['stream_errors']})
    if not completed or measured['stream_errors'] or not measured['measurement_complete']:
        raise RuntimeError('Native place and cancel did not reconcile')
    for rate in (4, 16):
        window = secrets.token_hex(4)
        _, cover_price = book_prices(cancel, location, symbol)
        client_id = 'T554EXEC-' + window + '-MAKER'
        cancel['api']('OrderSvr','placeOrder',dict(Location=location, SecurityID=symbol, MarketIndicator='4',
                UserID=maker[1], Side='Sell', Price=cover_price, OrderQty=str(execution['QUANTITY'] * (rate*SECONDS+1)),
                OCType='OPEN', OrdType='Limit', TimeInForce='GTC', ClOrdID=client_id, Terminal='API',
                AlgoName='cross', Demo='0', ReduceOnly='false'), maker[2])
        order_id = cancel['await_order'](maker, symbol, client_id, True)
        try:
            with cancel['native_trader_session'](trader, window, 'fill') as (_, _, token):
                measured = native['run'](work, dict(config, token=token, rate=rate, run=window,
                        quantity=str(execution['QUANTITY']), price=cover_price, start_at_epoch_ms=int(time.time()*1000)+5000))
            row = dict(measurement=measured, location=location, symbol=symbol, run=window)
            aggregate = harness['_summarize_receipts']([row], SECONDS, policy)
            harness['verify_stream_projections']([row])
            consistent = row.get('projection', {}).get('consistent') is True
            publish(f'{policy} TCP final execution receipts at {rate}/s', {
                    'aggregate': aggregate, 'projection_consistent': consistent, 'offered_seconds': SECONDS})
            if not consistent or not aggregate['all_accepted_final_receipts_pass']:
                raise RuntimeError('Native final receipts or projected fills did not reconcile')
        finally:
            if cancel['own_order'](cancel['open_orders'](maker, symbol), client_id):
                cancel['cancel'](maker, symbol, dict(order_id=order_id, client_order_id=client_id))
            cancel['await_order'](maker, symbol, client_id, False)
    if baseline != cancel['CAPACITY']['demo_tenants']() or install['inventory'](generation) != inventory:
        raise RuntimeError('A background Robot or runtime changed during measurement')


if __name__ == '__main__':
    main()
