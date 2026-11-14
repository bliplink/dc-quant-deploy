"""Compare original match outcomes with committed SQL archives and configured views."""
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation


def demo(value):
    return str(value).lower() in {'true', '1'}


def amount(value):
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError('Non-finite economic amount')
    return number


def audit(expected, archive, materialized, save_demo):
    if type(save_demo) is not bool or not expected:
        raise ValueError('An explicit actual view policy and original expectations are required')
    seen, views, violations, groups = {}, {}, [], defaultdict(set)
    fees = Decimal(0)
    for row in archive:
        try:
            payload = json.loads(row['payload'])
            report, result = payload['report'], payload['result']
            identity = report['ExecID']
            if identity not in expected:
                continue
            if identity in seen:
                violations.append('DUPLICATE_ARCHIVED_EXECUTION:' + identity)
                continue
            original = expected[identity]
            event = json.loads(row['event_payload'])
            mutation = event['mutations'][int(row['mutation_index'])]
            if (row['operation'] != 'UPSERT' or mutation['entityType'] != 'DEDUPE_RESULT'
                    or mutation['operation'] != row['operation'] or mutation['entityKey'] != row['entity_key']
                    or mutation['payload'] != row['payload'] or event['location'] != original['location']
                    or event['requestId'] != row['request_id'] or event['sourceType'] != row['source_type']
                    or row['request_id'] not in original['request_ids']
                    or row['entity_key'] != original['location'] + '\x1f' + identity
                    or row['source_type'] != ('TRADE_ATOMIC_MATCH_PAIR_PREPARED'
                        if row['request_id'].startswith('PAIR:') else 'TRADE_ATOMIC_MATCH_GROUP_PREPARED')
                    or row['partition_id'] != original['trade_partition']
                    or int(row['source_epoch']) < 2 or int(row['journal_seq']) < 1
                    or report.get('ExecType') != 'Trade' or result.get('code') != 0):
                raise ValueError('Committed event/settlement origin mismatch')
            for field, key in [('Location', 'location'), ('OrderID', 'order_id'), ('UserID', 'user_id'),
                               ('SecurityID', 'security_id'), ('Side', 'side')]:
                if str(report[field]) != str(original[key]):
                    raise ValueError('Original execution identity mismatch')
            if (amount(report['LastQty']) != amount(original['last_qty'])
                    or amount(report['LastPx']) != amount(original['last_px'])
                    or demo(report.get('Demo')) != demo(original['demo'])):
                raise ValueError('Original execution economics or Demo policy mismatch')
            fee, pnl = amount(result['info1']), amount(result['info2'])
            seen[identity] = (fee, pnl, str(report.get('Currency') or ''))
            groups[original['match_key']].add((row['partition_id'], int(row['source_epoch']), int(row['journal_seq'])))
            fees += fee
        except (KeyError, ValueError, TypeError, IndexError, InvalidOperation) as error:
            violations.append('INVALID_ARCHIVED_EXECUTION:' + str(error))
    for row in materialized:
        identity = row['exec_id']
        if identity not in expected:
            continue
        if identity in views:
            violations.append('DUPLICATE_MATERIALIZED_EXECUTION:' + identity)
        views[identity] = row
    wanted = {key for key, value in expected.items() if save_demo or not demo(value['demo'])}
    if set(seen) != set(expected):
        violations.append('MISSING_COMMITTED_ARCHIVE_EXECUTIONS')
    if set(views) != wanted:
        violations.append('MATERIALIZED_VIEW_POLICY_OR_COUNT_MISMATCH')
    for identity in wanted & set(views) & set(seen):
        row, original = views[identity], expected[identity]
        try:
            if (any(str(row[key]) != str(original[key]) for key in
                    ['order_id', 'user_id', 'security_id', 'side'])
                    or amount(row['last_qty']) != amount(original['last_qty'])
                    or amount(row['last_px']) != amount(original['last_px'])
                    or (amount(row['fee']), amount(row['realized_pnl']), row.get('currency', '')) != seen[identity]):
                raise ValueError('Materialized execution differs from committed financial mutation')
        except (ValueError, TypeError, KeyError, InvalidOperation) as error:
            violations.append('INVALID_MATERIALIZED_EXECUTION:' + str(error))
    if (set(groups) != {x['match_key'] for x in expected.values()}
            or any(len(positions) != 1 for positions in groups.values())
            or len({next(iter(x)) for x in groups.values() if x}) != len(groups)):
        violations.append('ORIGINAL_MATCH_ATOMIC_COMMIT_BOUNDARIES_DIFFER')
    return {'passed': not violations, 'original_client_executions': len(expected),
            'archived_client_executions': len(seen), 'original_match_commits': len(groups),
            'materialized_client_executions': len(views), 'expected_materialized_client_executions': len(wanted),
            'actual_save_demo': save_demo, 'archived_fee_sum': str(fees), 'violations': violations}
