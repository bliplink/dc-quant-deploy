#!/usr/bin/env python3
"""Verify cancellation or signed match readmission after an actual lost reservation."""
import argparse
import base64
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import runpy
import secrets
import signal
import struct
import time
import zlib

HERE = Path(__file__).resolve().parent
RPO = runpy.run_path(str(HERE / 'verify-mac-demo-async-rpo.py'))
CANCEL, CAPACITY, PRODUCT = RPO['CANCEL'], RPO['CAPACITY'], RPO['PRODUCT']
run, inspect, until, manifest = (RPO[key] for key in ('run', 'inspect', 'until', 'manifest'))
ROBOT = RPO['ROBOT']


def lost_reservation_identity(frame, partition, epoch, sequence, location, user, order_id):
    """Decode the existing TradeJournalRecord inside one CRC-verified Common frame."""
    if len(frame) < 28:
        raise RuntimeError('Lost reservation frame is incomplete')
    magic, observed_epoch, observed_seq, size, crc = struct.unpack_from('>IqqII', frame)
    payload = frame[28:]
    if (magic != 0x43425731 or observed_epoch != epoch or observed_seq != sequence
            or size != len(payload) or not 0 < size <= 1024 * 1024
            or zlib.crc32(struct.pack('>qq', epoch, sequence) + payload) != crc):
        raise RuntimeError('Lost reservation physical coordinate or CRC differs')
    try:
        fields = payload.decode('utf-8').split('\t')
        if len(fields) != 7:
            raise ValueError('Trade journal envelope must have seven fields')
        decode = lambda value: base64.b64decode(value, validate=True).decode('utf-8')
        observed_partition, event_type, event_id = (decode(fields[i]) for i in (0, 3, 4))
        batch = json.loads(decode(fields[6]))
        request = str(order_id) + ':Newing'
        open_key = location + '\x1f' + user + '\x1f' + str(order_id)
        if (observed_partition != partition or int(fields[1]) != epoch or int(fields[2]) != sequence
                or event_type != 'STATE_BATCH' or event_id != request
                or batch.get('location') != location or batch.get('requestId') != request
                or batch.get('sourceType') != 'NEWING_OPEN_PREPARED'
                or sum(m.get('entityType') == 'OPEN_ORDER' and m.get('operation') == 'UPSERT'
                       and m.get('entityKey') == open_key for m in batch['mutations']) != 1):
            raise ValueError('Observed reservation belongs to a different order or account')
    except (ValueError, TypeError, KeyError, UnicodeError) as error:
        raise RuntimeError('Lost physical reservation does not identify the observed Order') from error
    return {'partition': partition, 'epoch': epoch, 'sequence': sequence, 'event_id': event_id,
            'source_type': batch['sourceType'], 'frame_sha256': hashlib.sha256(frame).hexdigest()}


def account(trader):
    location, user, token = trader
    row = PRODUCT['ok'](RPO['URL'], 'TradeSvr', 'queryAccountBalance',
                        {'location': location, 'userid': user}, token, route_location=location)
    fields = ('Balance', 'UsedMargin', 'FreezedMargin', 'FreezedCommission')
    if not isinstance(row, dict) or any(row.get(key) is None for key in fields):
        raise RuntimeError('Live account reply is missing an exact financial field')
    values = {key: Decimal(str(row[key])) for key in fields}
    if not all(value.is_finite() for value in values.values()):
        raise RuntimeError('Live account reply has a non-finite financial value')
    return {key: str(value.normalize()) for key, value in values.items()}


def terminal_cancel_mutations(location, order_id):
    return PRODUCT['readonly_sql'](
        "SELECT partition_id,source_epoch,journal_seq,entity_type,operation,payload "
        "FROM dc_trade_projection_mutation "
        f"WHERE location='{location}' AND request_id='{order_id}:Trade_Cancel' "
        "AND source_type='CANCEL_OPEN_PREPARED' ORDER BY source_epoch,journal_seq,mutation_index")


def require_readmitted_reservation(rows, partition, epoch):
    if (len(rows) != 4 or len({tuple(row[:3]) for row in rows}) != 1
            or rows[0][0] != partition or int(rows[0][1]) != epoch
            or {(row[3], row[4]) for row in rows} != {
                ('ACCOUNT_BALANCE', 'UPSERT'), ('POSITION', 'UPSERT'),
                ('OPEN_ORDER', 'UPSERT'), ('DEDUPE_RESULT', 'UPSERT')}):
        raise RuntimeError('Readmission must use one real new-epoch four-domain reservation commit')
    receipt = json.loads(next(row[5] for row in rows if row[3] == 'DEDUPE_RESULT'))['result']
    if receipt.get('info3') != 'LOCAL_DURABLE_ASYNC' or receipt.get('info4') != '/'.join(rows[0][:3]):
        raise RuntimeError('Readmission receipt differs from its actual LOCAL reservation coordinate')
    return rows


def matched_accounts(traders, symbol, before):
    result = []
    for index, trader in enumerate(traders):
        location, user, token = trader
        balance = account(trader)
        position = PRODUCT['ok'](RPO['URL'], 'TradeSvr', 'queryTradePosition',
            {'securityid': symbol}, token, route_location=location)
        fees = PRODUCT['readonly_sql']("SELECT COALESCE(SUM(fee),0),COUNT(*),COUNT(fee) "
            f"FROM dc_orders_execorders WHERE location='{location}' AND user_id='{user}'")
        side, other = ('Long', 'Short') if index == 0 else ('Short', 'Long')
        fields = ('LongPosition', 'ShortPosition', 'LongUsedMargin', 'ShortUsedMargin')
        if not isinstance(position, dict) or any(position.get(key) is None for key in fields):
            raise RuntimeError('Matched reservation recovery is missing exact live position fields')
        if (len(fees) != 1 or fees[0][1:] != ['2', '2']
                or Decimal(balance['Balance']) != Decimal(before[index]['Balance']) + Decimal(fees[0][0])
                or Decimal(balance['FreezedMargin']) != 0 or Decimal(balance['FreezedCommission']) != 0
                or Decimal(str(position[side + 'Position'])) != RPO['QUANTITY']
                or Decimal(str(position[other + 'Position'])) != 0
                or Decimal(balance['UsedMargin']) <= 0
                or Decimal(balance['UsedMargin']) != Decimal(str(position['LongUsedMargin']))
                    + Decimal(str(position['ShortUsedMargin']))):
            return None
        # Mark price, floating P&L and observation time are not persisted
        # position state and can move between LOCAL and Home observations.
        stable_position = {key: str(Decimal(str(position[key])).normalize()) for key in fields}
        result.append({'user': user, 'balance': balance, 'position': stable_position, 'execution_fees': fees})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('generation', type=Path)
    parser.add_argument('--tools', type=Path,
                        default=Path.home() / '.opentradingcore/t554-rpo-replication-fault-tools-20261115')
    parser.add_argument('--after-loss', choices=('cancel', 'match'), default='cancel')
    args = parser.parse_args()
    root = args.generation.resolve(strict=True)
    os.umask(0o077)
    with (RPO['FRESH']['LOCAL'] / '.mac-demo-fresh.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        CAPACITY['require_strict_demo'](root)
        release = CAPACITY['common_release_identity'](root)
        RPO['require_replication_fault_tools'](args.tools)
        if release['client_ack_policy'] != 'LOCAL_DURABLE_ASYNC':
            raise RuntimeError('Reservation loss requires normal dual-node asynchronous confirmation')
        for name in ('head-observer-self-test.status', 'head-observer-linux-self-test.status'):
            if (args.tools / name).read_text().strip() != 'PASS':
                raise RuntimeError('The read-only physical head observer has not passed its release tests')
        initial = {kind: manifest(root, kind) for kind in ('order', 'trade')}
        baseline = CAPACITY['demo_tenants']()
        if not baseline or not all(value == 'RUNNING' for value in baseline.values()):
            raise RuntimeError('The original Robot cohort must be running before this case')
        robot_before = inspect('dc-saas-robotsvr')
        run_id = secrets.token_hex(4)
        output = root / (('async-reservation-loss-' if args.after_loss == 'cancel'
                          else 'async-reservation-readmission-') + run_id)
        output.mkdir(mode=0o700)
        record = {'status': 'NO_GO', 'generation': root.name, 'common_release': release,
                  'initial': initial, 'started_at': datetime.now(timezone.utc).isoformat(),
                  'after_loss': args.after_loss,
                  'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'rpo_helper_sha256': hashlib.sha256((HERE / 'verify-mac-demo-async-rpo.py').read_bytes()).hexdigest()}

        def save():
            pending = output / 'evidence.pending'
            pending.write_text(json.dumps(record, indent=2) + '\n')
            pending.replace(output / 'evidence.json')

        save()
        primary = backup = None
        policy_overridden = False
        killed = False
        local = None
        failure = None
        trader = None
        counterparty = None
        password = secrets.token_urlsafe(24)
        admin_password = secrets.token_urlsafe(24)
        since = None
        try:
            with RPO['controlled_products_away_from_robots'](run_id, record, admin_password, baseline) as (location, products):
                symbol = next(symbol for mode, symbol in products if mode == 'TRADE')
                partition = 'P%03d' % (zlib.crc32(location.encode()) % 256)
                if any(zlib.crc32(other.encode()) % 256 == int(partition[1:]) for other in baseline):
                    raise RuntimeError('Controlled reservation partition collides with the active Robot cohort')
                trader = CANCEL['new_trader'](location, symbol, 'TRADE', run_id, 0, password)
                if args.after_loss == 'match':
                    counterparty = CANCEL['new_trader'](location, symbol, 'TRADE', run_id, 1, password)
                    record['counterparty_account_before'] = account(counterparty)
                primary_slot = initial['trade'][partition]['primary'][-1]
                backup_slot = 'B' if primary_slot == 'A' else 'A'
                epoch = initial['trade'][partition]['epoch']
                primary = f'{root.name}-trade-{primary_slot.lower()}-hostready'
                backup = f'{root.name}-trade-{backup_slot.lower()}-hostready'
                order_partition = 'P%03d' % (zlib.crc32((location + '\x1f4\x1f' + symbol).encode()) % 256)
                order_slot = initial['order'][order_partition]['primary'][-1].lower()
                order_node = f'{root.name}-order-{order_slot}-hostready'
                order_before = inspect(order_node)
                backup_before = inspect(backup)
                original_policy = inspect(primary)['HostConfig']['RestartPolicy']
                if original_policy != {'Name': 'on-failure', 'MaximumRetryCount': 0}:
                    raise RuntimeError('Expected the existing unlimited on-failure restart policy')
                record.update(location=location, user=trader[1], symbol=symbol, partition=partition,
                              epoch=epoch, primary=primary, backup=backup, original_restart_policy=original_policy,
                              account_before=account(trader))
                tools_path = '/tmp/t554-reservation-loss-tools-' + run_id
                target_pids = {}
                for node in (primary, backup):
                    run('docker', 'exec', node, 'mkdir', '-m', '700', tools_path)
                    for name in ('head-observer.jar', 'T554RpoAttach.class'):
                        run('docker', 'cp', str(args.tools / name), node + ':' + tools_path + '/' + name)
                    jvms = run('docker', 'exec', node, '/opt/java/openjdk/bin/jps', '-l').splitlines()
                    pids = [line.split()[0] for line in jvms if 'sun.tools.jps.Jps' not in line]
                    if len(pids) != 1:
                        raise RuntimeError('Expected one unique physical Trade JVM')
                    target_pids[node] = pids[0]

                def certified_before():
                    try:
                        a, head = RPO['copy_wal'](primary, primary_slot, partition, output / 'primary-before.wal', epoch)
                        b, other = RPO['copy_wal'](backup, backup_slot, partition, output / 'backup-before.wal', epoch)
                    except RPO['IncompleteWalObservation']:
                        return None
                    if not head or a != b or head != other:
                        return None
                    prefix = hashlib.sha256(a).hexdigest()
                    expected = f'READY epoch={epoch} sequence={head} sha256={prefix} pending=false'
                    observations = {node: RPO['observe_physical_head'](
                        node, target_pids[node], tools_path, partition, head, prefix, epoch)
                        for node in (primary, backup)}
                    record['authenticated_pre_fault_heads'] = observations
                    save()
                    return (a, head) if all(value == expected for value in observations.values()) else None

                before_raw, before_head = until(certified_before, 30, 'Funding did not reach both authenticated physical heads')
                robot_location = next(other for other in sorted(baseline)
                    if initial['trade']['P%03d' % (zlib.crc32(other.encode()) % 256)]['primary'] == 'TradeSvr' + primary_slot)
                order_nodes = [f'{root.name}-order-{slot}-hostready' for slot in 'ab']
                trade_nodes = [f'{root.name}-trade-{slot}-hostready' for slot in 'ab']
                record['robot_before_fault'] = ROBOT['wait_traffic'](
                    order_nodes, trade_nodes, datetime.now(timezone.utc), robot_location)
                RPO['require_pause_lease_budget'](root / 'common/config-hostready/trade' / primary_slot / 'application.properties')
                replication_control = '/tmp/t554-reservation-replication-control-' + run_id
                record['replication_delivery_fault'] = RPO['arm_replication_delivery'](
                    primary, target_pids[primary], tools_path, replication_control, args.tools)
                save()
                watchdog = RPO['arm_pause_watchdog'](backup_before['Id'], output)
                policy_overridden = True
                run('docker', 'update', '--restart', 'no', primary)
                client = 'T554RESLOSS-' + run_id
                # Keep the identity before submission: New may arrive after a
                # failed bounded observation, and still needs normal cleanup.
                record['client_order_id'] = client
                save()
                since = datetime.now(timezone.utc)
                begun = time.monotonic()
                try:
                    run('docker', 'pause', backup)
                    RPO['place'](trader, symbol, 'Buy', client, 'GTC')

                    def live_resting_order():
                        rows = CANCEL['own_order'](CANCEL['open_orders'](trader, symbol), client)
                        return rows[0] if len(rows) == 1 and rows[0].get('OrdStatus') == 'New' else None

                    order = until(live_resting_order, 2, 'Order did not observe New within the bounded replica pause')
                    if not inspect(backup)['State']['Paused']:
                        raise RuntimeError('Replica pause ended before the confirmed reservation fault')
                    record.update(client_order_id=client, order_id=order['OrderID'], order_new=order)
                    save()
                    RPO['require_replication_delivery_held'](primary, replication_control)
                    run('docker', 'kill', '--signal', 'KILL', primary)
                    killed = True
                    stopped = inspect(primary)['State']
                    if stopped['Running'] or stopped['ExitCode'] != 137:
                        raise RuntimeError('Original Trade primary did not exit with SIGKILL')
                    raw, backup_head = RPO['copy_wal'](backup, backup_slot, partition, output / 'backup-paused.wal', epoch)
                    if raw != before_raw or backup_head != before_head:
                        raise RuntimeError('The supposedly lost reservation reached the backup')
                    record.update(killed_primary=stopped, backup_certified_head=before_head)
                finally:
                    if inspect(backup)['State']['Paused']:
                        run('docker', 'unpause', backup)
                    record['replica_pause_seconds'] = round(time.monotonic() - begun, 6)
                    save()
                if watchdog.wait(timeout=5) != 0:
                    raise RuntimeError('The bounded replica pause watchdog failed')
                primary_raw, primary_head = RPO['copy_wal'](primary, primary_slot, partition, output / 'primary-local-acked.wal', epoch)
                if primary_head != before_head + 1 or not primary_raw.startswith(before_raw):
                    raise RuntimeError('Expected exactly one genuine locally acknowledged reservation frame')
                record['lost_reservation_identity'] = lost_reservation_identity(
                    primary_raw[len(before_raw):], partition, epoch, primary_head,
                    location, trader[1], order['OrderID'])
                record['primary_local_acked_head'] = primary_head
                record['phase'] = 'WAITING_SURVIVING_NODE_ALL_LOCAL'
                save()
                local = RPO['wait_roles'](root, 'TradeSvr' + backup_slot)
                record['survivor_local'] = local
                post_raw, post_head = RPO['copy_wal'](backup, backup_slot, partition,
                                                    output / 'actual-backup-after-takeover.wal', epoch)
                record['actual_original_backup_head_after_takeover'] = post_head
                record['phase'] = 'CHECKING_REAL_EXCLUSION_AND_ROBOT_LOCAL_BUSINESS'
                save()
                if post_head != before_head or post_raw != before_raw:
                    raise RuntimeError('A late delivered reservation invalidates this actual-loss case')
                if inspect(backup)['State']['StartedAt'] != backup_before['State']['StartedAt']:
                    raise RuntimeError('The surviving backup unexpectedly restarted')
                record['robot_while_local'] = ROBOT['wait_traffic'](
                    order_nodes, [backup], datetime.now(timezone.utc), robot_location, local)
                record['phase'] = 'CHECKING_FUNDS_BEFORE_NORMAL_BUSINESS'
                save()
                trader = RPO['refresh_trader'](trader, run_id, 0, password)
                record['account_after_certified_takeover_before_cancel'] = account(trader)
                if record['account_after_certified_takeover_before_cancel'] != record['account_before']:
                    raise RuntimeError('The lost reservation altered recovered funds before cancellation')
                if args.after_loss == 'cancel':
                    CANCEL['cancel'](trader, symbol, {'order_id': order['OrderID'], 'client_order_id': client})
                    CANCEL['await_order'](trader, symbol, client, False)

                    def cancelled_batch():
                        rows = terminal_cancel_mutations(location, order['OrderID'])
                        if not rows:
                            return None
                        if len(rows) != 2 or {(row[3], row[4]) for row in rows} != {
                                ('OPEN_ORDER', 'REMOVE'), ('DEDUPE_RESULT', 'UPSERT')}:
                            raise RuntimeError('Lost reservation cancel did not persist exactly the two terminal mutations')
                        if len({tuple(row[:3]) for row in rows}) != 1 or int(rows[0][1]) != local[partition]['epoch']:
                            raise RuntimeError('Cancel mutations do not share the genuine LOCAL commit coordinate')
                        receipt = json.loads(next(row[5] for row in rows if row[3] == 'DEDUPE_RESULT'))
                        result = receipt['result']
                        if result.get('info3') != 'LOCAL_DURABLE_ASYNC' or result.get('info4') != '/'.join(rows[0][:3]):
                            raise RuntimeError('Persisted cancellation receipt lost its real local durability coordinate')
                        return rows

                    record['local_cancel_mutations'] = until(cancelled_batch, 60, 'Terminal cancellation did not reach the certified projection')
                    record['account_after_cancel'] = account(trader)
                    if record['account_after_cancel'] != record['account_before']:
                        raise RuntimeError('Cancellation fabricated a second financial release')
                else:
                    counterparty = RPO['refresh_trader'](counterparty, run_id, 1, password)
                    record['matched_after_loss_since'] = datetime.now(timezone.utc).isoformat()
                    matched_since = datetime.now(timezone.utc)
                    taker_client = 'T554RESMATCH-' + run_id
                    record['taker_client_order_id'] = taker_client
                    save()
                    # The original resting Order remains authoritative. Only a
                    # normal new counter-order triggers its original signed match.
                    RPO['place'](counterparty, symbol, 'Sell', taker_client, 'IOC')
                    record['readmitted_match_receipts'] = until(lambda: RPO['final_reports'](
                        order_node, matched_since, {client, taker_client}), 90,
                        'Lost reservation did not automatically re-enter and settle the real original Order')
                    record['original_order_match'] = until(lambda: RPO['match_row'](taker_client), 60,
                        'The settlement has no original durable Order match')
                    if record['original_order_match']['partition'] != order_partition:
                        raise RuntimeError('Restored reservation settled a different Order partition')
                    CANCEL['await_order'](trader, symbol, client, False)
                    CANCEL['await_order'](counterparty, symbol, taker_client, False)

                    def readmission():
                        rows = PRODUCT['readonly_sql'](
                            "SELECT partition_id,source_epoch,journal_seq,entity_type,operation,payload "
                            "FROM dc_trade_projection_mutation "
                            f"WHERE location='{location}' AND request_id='{order['OrderID']}:Newing' "
                            f"AND source_type='NEWING_OPEN_PREPARED' AND source_epoch={local[partition]['epoch']} "
                            "ORDER BY source_epoch,journal_seq,mutation_index")
                        return require_readmitted_reservation(rows, partition, local[partition]['epoch']) if rows else None

                    record['readmitted_original_reservation'] = until(readmission, 60,
                        'The excluded original reservation was not recreated through normal Common persistence')
                    record['matched_accounts_while_local'] = until(lambda: matched_accounts(
                        (trader, counterparty), symbol,
                        (record['account_before'], record['counterparty_account_before'])), 60,
                        'Exact fees, positions, balance or frozen funds differ after matched readmission')
                    record['expected_account_after_business'] = record['matched_accounts_while_local'][0]['balance']
                    record['readmitted_posting_events'] = ROBOT['require_posting_pairs']({
                        'location': location, 'tape_execution_ids': [x['ExecID']
                            for x in record['readmitted_match_receipts'].values()], 'local_trade_commits': []})
                record['local_business_consistent'] = True
                record['phase'] = 'LOCAL_BUSINESS_PROVEN_RETURN_REQUIRED'
                save()
        except BaseException as error:
            failure = error
            record['failure'] = type(error).__name__ + ': ' + str(error)
            save()  # Preserve the actual cause before potentially lengthy safe return.
        finally:
            if primary and record.get('replication_delivery_fault'):
                try:
                    record['replication_delivery_release'] = RPO['release_replication_delivery'](
                        primary, record['replication_delivery_fault']['control'])
                except BaseException as release_error:
                    record['replication_delivery_release_failure'] = type(release_error).__name__
                    failure = failure or release_error
            try:
                if backup and inspect(backup)['State']['Paused']:
                    run('docker', 'unpause', backup)
                if primary and record.get('order_id') and not inspect(primary)['State']['Running']:
                    killed = True
                if not killed and trader and record.get('client_order_id'):
                    remaining = CANCEL['own_order'](CANCEL['open_orders'](
                        trader, record['symbol']), record['client_order_id'])
                    for owned in remaining:
                        CANCEL['cancel'](trader, record['symbol'], {
                            'order_id': owned['OrderID'], 'client_order_id': record['client_order_id']})
                    if remaining:
                        CANCEL['await_order'](trader, record['symbol'], record['client_order_id'], False)
                        record['failed_case_owned_order_cleanup'] = 'NORMAL_API_CANCEL_WITHOUT_PRIMARY_KILL'
                    if account(trader) != record['account_before']:
                        raise RuntimeError('Aborted fault normal cleanup did not restore the original account')
                if killed:
                    if local is None:
                        local = RPO['wait_roles'](root, 'TradeSvr' + backup_slot)
                        record['survivor_local'] = local
                    run('docker', 'update', '--restart', 'on-failure', primary)
                    run('docker', 'start', primary)
                    record['phase'] = 'RETURNING_ORIGINAL_NODE_WAITING_STRICT_HOME'
                    save()
                    home = RPO['wait_roles'](root)
                    record['strict_home'] = home
                    hashes = [RPO['ROLL']['physical_hashes'](node, 'TradeSvr', slot, backup_slot, local, home)
                              for node, slot in ((primary, primary_slot), (backup, backup_slot))]
                    if hashes[0] != hashes[1] or len(hashes[0]) != 512:
                        raise RuntimeError('Returned physical WAL and snapshot pairs differ')
                    record['physical_pairs'] = 512
                    trader = RPO['refresh_trader'](trader, run_id, 0, password)
                    record['account_after_home'] = account(trader)
                    remaining = CANCEL['own_order'](
                        CANCEL['open_orders'](trader, record['symbol']), record['client_order_id'])
                    if remaining:
                        if record.get('local_cancel_mutations'):
                            raise RuntimeError('Cancelled order resurrected after the original primary returned')
                        # An earlier probe failure may have prevented the intended
                        # LOCAL cancellation. Clean up only our order via the normal
                        # API after recovery, without claiming that LOCAL gate passed.
                        CANCEL['cancel'](trader, record['symbol'], {
                            'order_id': record['order_id'], 'client_order_id': record['client_order_id']})
                        CANCEL['await_order'](trader, record['symbol'], record['client_order_id'], False)
                        record['failed_case_owned_order_cleanup'] = 'NORMAL_API_CANCEL_AFTER_HOME'
                        if account(trader) != record['account_before']:
                            raise RuntimeError('Failed-case cleanup altered funds')
                    if (record.get('local_business_consistent')
                            and record['account_after_home'] != record.get('expected_account_after_business', record['account_before'])):
                        raise RuntimeError('Original primary return resurrected or released the lost reservation')
                    if account(trader) != record.get('expected_account_after_business', record['account_before']):
                        raise RuntimeError('Post-recovery normal cleanup changed the exact expected account')
                    if args.after_loss == 'match' and record.get('local_business_consistent'):
                        counterparty = RPO['refresh_trader'](counterparty, run_id, 1, password)
                        checked = matched_accounts((trader, counterparty), record['symbol'],
                            (record['account_before'], record['counterparty_account_before']))
                        if checked != record['matched_accounts_while_local']:
                            raise RuntimeError('Original primary return changed readmitted match fees or positions')
                        record['matched_accounts_after_home'] = checked
                    code, financial, checks = CAPACITY['reconcile_financial_cursor']()
                    record.update(financial_cursor=financial, financial_checks=checks)
                    if code:
                        raise RuntimeError('Certified financial source and projection differ after return')
                    if record.get('robot_while_local'):
                        record['robot_local_postings'] = ROBOT['require_posting_pairs'](record['robot_while_local'])
                    robot_after = inspect('dc-saas-robotsvr')
                    record['same_robot_process'] = (robot_before['Id'] == robot_after['Id']
                        and robot_before['State']['StartedAt'] == robot_after['State']['StartedAt'])
                    if not record['same_robot_process'] or inspect(order_node)['State']['StartedAt'] != order_before['State']['StartedAt']:
                        raise RuntimeError('Unrelated Order or Robot process restarted during the fault')
                    record['robot_during_fault'] = ROBOT['rounds'](robot_location, since, datetime.now(timezone.utc))
            except BaseException as error:
                record['recovery_failure'] = type(error).__name__ + ': ' + str(error)
                failure = failure or error
            finally:
                if policy_overridden:
                    try:
                        run('docker', 'update', '--restart', 'on-failure', primary)
                        record['restart_policy_restored'] = inspect(primary)['HostConfig']['RestartPolicy'] == original_policy
                        if not record['restart_policy_restored']:
                            raise RuntimeError('Original automatic restart contract was not restored')
                    except BaseException as error:
                        record['restart_policy_failure'] = type(error).__name__ + ': ' + str(error)
                        failure = failure or error
            if failure is None and record.get('local_business_consistent') and record.get('physical_pairs') == 512:
                record['status'] = ('UNREPLICATED_RESERVATION_LOSS_NORMAL_CANCEL_FUNDS_AND_HOME_PASS'
                    if args.after_loss == 'cancel' else
                    'UNREPLICATED_RESERVATION_LOSS_NORMAL_MATCH_READMISSION_FUNDS_AND_HOME_PASS')
            record['finished_at'] = datetime.now(timezone.utc).isoformat()
            save()
        print('[mac-demo reservation loss]', record['status'], output, flush=True)
        if failure is not None:
            raise failure
        if record['status'] == 'NO_GO':
            raise RuntimeError('Controlled reservation-loss verification did not finish')


if __name__ == '__main__':
    def terminate(signum, frame):
        raise KeyboardInterrupt('Reservation loss driver termination requested')

    signal.signal(signal.SIGTERM, terminate)
    main()
