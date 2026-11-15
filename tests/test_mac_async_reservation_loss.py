import importlib.util
import base64
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/verify-mac-demo-async-reservation-loss.py'
SPEC = importlib.util.spec_from_file_location('mac_async_reservation_loss', SCRIPT)
LOSS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LOSS)


class ReservationLossPreflightTest(unittest.TestCase):
    def accepted_fixture(self):
        sha = 'a' * 64
        command = self.reservation_frame()[28:]
        fields = command.decode().split('\t')
        fields[1:3] = ['5', '1']
        batch = json.loads(base64.b64decode(fields[6]))
        batch['mutations'][0]['payload'] = '{}'
        fields[6] = base64.b64encode(json.dumps(batch).encode()).decode()
        command = '\t'.join(fields).encode()
        text = ('SCOPE COMMON_ACCEPTED_BYTES_NOT_QUORUM_OR_NEW_AUTHORITY\nCOMMON ' + sha
                + '\nHEAD P079 5 1\nFRAME 5 1 ' + base64.b64encode(command).decode())
        return sha, text

    def test_accepted_source_rejects_wrong_sha_epoch_account_and_incomplete_window(self):
        sha, text = self.accepted_fixture()
        args = [sha, 'P079', 5, 'ABC123', 'fixture-user', '1234567890123456789', 'match']
        self.assertEqual(1, len(LOSS.accepted_mutations(text, *args)))
        for bad in [text.replace(sha, 'b' * 64), text.replace('HEAD P079 5 1', 'HEAD P079 4 1'),
                    text.replace('HEAD P079 5 1', 'HEAD P079 5 2'), text.replace('FRAME 5 1', 'FRAME 5 2')]:
            with self.assertRaises(RuntimeError):
                LOSS.accepted_mutations(bad, *args)
        args[4] = 'another-user'
        with self.assertRaises(RuntimeError):
            LOSS.accepted_mutations(text, *args)

    def test_projection_comparison_preserves_payload_values_but_ignores_json_formatting(self):
        a = [['P079', '5', '1', 'DEDUPE_RESULT', 'UPSERT', '{"a":1,"b":2}']]
        b = [['P079', '5', '1', 'DEDUPE_RESULT', 'UPSERT', '{ "b": 2, "a": 1 }']]
        self.assertEqual(LOSS.semantic_mutations(a), LOSS.semantic_mutations(b))
        a[0][5], b[0][5] = '{"balance":9007199254740992.1}', '{"balance":9007199254740992.2}'
        self.assertNotEqual(LOSS.semantic_mutations(a), LOSS.semantic_mutations(b))
        a[0][5], b[0][5] = '{"balance":9.0}', '{"balance":9}'
        self.assertEqual(LOSS.semantic_mutations(a), LOSS.semantic_mutations(b))
        a[0][5], b[0][5] = '{"balance":1}', '{"balance":true}'
        self.assertNotEqual(LOSS.semantic_mutations(a), LOSS.semantic_mutations(b))
        b[0][5] = '{"a":1,"b":3}'
        self.assertNotEqual(LOSS.semantic_mutations(a), LOSS.semantic_mutations(b))
        a = [['P079', '5', '1', 'OPEN_ORDER', 'REMOVE', None]]
        b = [['P079', '5', '1', 'OPEN_ORDER', 'REMOVE', 'NULL']]
        self.assertEqual(LOSS.semantic_mutations(a), LOSS.semantic_mutations(b))

    def test_mysql_transport_preserves_original_backslashes_and_control_characters(self):
        payload = json.dumps({'executionKey': 'ABC123\\u001f123\x1fTrade_Cancel'})
        rows = [['P079', '5', '1', 'DEDUPE_RESULT', 'UPSERT', payload.encode().hex()],
                ['P079', '5', '1', 'OPEN_ORDER', 'REMOVE', 'NULL']]
        with patch.dict(LOSS.PRODUCT, readonly_sql=Mock(return_value=rows)):
            actual = LOSS.terminal_cancel_mutations('ABC123', '123')
        self.assertEqual(payload, actual[0][5])
        self.assertIsNone(actual[1][5])
        self.assertEqual('ABC123\\u001f123\x1fTrade_Cancel', json.loads(actual[0][5])['executionKey'])

    def readmission_rows(self):
        receipt = json.dumps({'result': {'info3': 'LOCAL_DURABLE_ASYNC', 'info4': 'P079/5/1'}})
        return [['P079', '5', '1', kind, 'UPSERT', receipt if kind == 'DEDUPE_RESULT' else '{}']
                for kind in ('ACCOUNT_BALANCE', 'POSITION', 'OPEN_ORDER', 'DEDUPE_RESULT')]

    def pair_fixture(self):
        sha, _ = self.accepted_fixture()
        b64 = lambda value: base64.b64encode(value.encode()).decode()
        maker = '1234567890123456789'
        held = [{'entityType': row[3], 'operation': row[4], 'payload': row[5],
                 'entityKey': 'ABC123\x1ffixture-user\x1f' + maker if row[3] == 'OPEN_ORDER' else 'fixture'}
                for row in self.readmission_rows()]
        reservation = {'location': 'ABC123', 'requestId': maker + ':Newing',
                       'sourceType': 'NEWING_OPEN_PREPARED', 'mutations': held}
        mutations = []
        for user, order, execution in [('fixture-user', maker, 'MX'), ('counter-user', '987', 'TX')]:
            payloads = [json.dumps({'userID': user}), json.dumps({'userID': user}), None,
                json.dumps({'userID': user, 'sourceID': execution, 'amount': '-.02', 'location': 'ABC123'}),
                json.dumps({'report': {'UserID': user, 'OrderID': order, 'ExecID': execution},
                    'result': {'info3': 'LOCAL_DURABLE_ASYNC', 'info4': 'P079/5/2'}})]
            for kind, operation, payload in zip(('ACCOUNT_BALANCE', 'POSITION', 'OPEN_ORDER', 'POSTING', 'DEDUPE_RESULT'),
                                               ('UPSERT', 'UPSERT', 'REMOVE', 'UPSERT', 'UPSERT'), payloads):
                mutations.append({'entityType': kind, 'operation': operation, 'payload': payload,
                                  'entityKey': '\x1f'.join(('ABC123', user, order))})
        pair = {'location': 'ABC123', 'requestId': 'PAIR:fixture-match',
                'sourceType': 'TRADE_ATOMIC_MATCH_PAIR_PREPARED', 'mutations': mutations}
        text = 'SCOPE COMMON_ACCEPTED_BYTES_NOT_QUORUM_OR_NEW_AUTHORITY\nCOMMON ' + sha + '\nHEAD P079 5 2\n'
        for sequence, batch in enumerate((reservation, pair), 1):
            command = '\t'.join((b64('P079'), '5', str(sequence), b64('STATE_BATCH'),
                                   b64(batch['requestId']), '123', b64(json.dumps(batch))))
            text += 'FRAME 5 ' + str(sequence) + ' ' + b64(command) + '\n'
        receipts = {execution: {'ExecID': execution, 'TradeSettlementCommit': 'P079/5/2'} for execution in ('MX', 'TX')}
        return text, [sha, 'P079', 5, 'ABC123', 'fixture-user', maker,
                      {'fixture-user', 'counter-user'}, receipts, 'fixture-match']

    def test_local_pair_fees_bind_both_customers_to_their_original_real_receipt_coordinate(self):
        text, args = self.pair_fixture()
        self.assertEqual({'fixture-user': '-0.02', 'counter-user': '-0.02'}, LOSS.accepted_pair_fees(text, *args))
        args[-2]['TX']['TradeSettlementCommit'] = 'P079/5/3'
        with self.assertRaises(RuntimeError):
            LOSS.accepted_pair_fees(text, *args)
        args[-2]['TX'] = {'ExecID': 'MX', 'TradeSettlementCommit': 'P079/5/2'}
        with self.assertRaises(RuntimeError):
            LOSS.accepted_pair_fees(text, *args)

    def test_readmission_requires_all_four_mutations_at_one_actual_local_coordinate(self):
        rows = self.readmission_rows()
        self.assertEqual(rows, LOSS.require_readmitted_reservation(rows, 'P079', 5))
        candidates = [rows[:-1], rows + rows, [row[:] for row in rows], [row[:] for row in rows]]
        candidates[2][0][1] = '4'
        candidates[3][-1][5] = json.dumps({'result': {'info3': 'STRICT_QUORUM', 'info4': 'P079/5/1'}})
        for bad in candidates:
            with self.subTest(rows=bad), self.assertRaises(RuntimeError):
                LOSS.require_readmitted_reservation(bad, 'P079', 5)

    def test_matched_recovery_checks_both_accounts_exact_fees_no_freeze_and_position_margin(self):
        traders = [('ABC123', 'buyer', 'fixture'), ('ABC123', 'seller', 'fixture')]
        before = [{'Balance': '10000'}, {'Balance': '10000'}]
        balance = {'Balance': '9999.98', 'UsedMargin': '9', 'FreezedMargin': '0', 'FreezedCommission': '0'}
        positions = [dict(LongPosition='.001', ShortPosition='0', LongUsedMargin='9', ShortUsedMargin='0'),
                     dict(LongPosition='0', ShortPosition='.001', LongUsedMargin='0', ShortUsedMargin='9')]
        def verify(current, accepted_fees=None):
            with patch.object(LOSS, 'account', return_value=current), \
                    patch.dict(LOSS.PRODUCT, ok=Mock(side_effect=positions),
                               readonly_sql=Mock(side_effect=AssertionError('LOCAL must not read certified SQL'))
                               if accepted_fees is not None else Mock(return_value=[['-.02', '1', '1']])):
                return LOSS.matched_accounts(traders, 'BTC004USDT', before, accepted_fees)
        self.assertEqual(2, len(verify(balance)))
        self.assertEqual(2, len(verify(balance, {'buyer': '-.02', 'seller': '-.02'})))
        for key, value in [('Balance', '10000'), ('UsedMargin', '8'), ('FreezedMargin', '9')]:
            with self.subTest(field=key):
                self.assertIsNone(verify(dict(balance, **{key: value})))

    def reservation_frame(self, request='1234567890123456789:Newing', user='fixture-user'):
        batch = {'location': 'ABC123', 'requestId': request, 'sourceType': 'NEWING_OPEN_PREPARED',
                 'mutations': [{'entityType': 'OPEN_ORDER', 'operation': 'UPSERT',
                                'entityKey': 'ABC123\x1f' + user + '\x1f1234567890123456789'}]}
        b64 = lambda value: base64.b64encode(value.encode()).decode()
        payload = '\t'.join([b64('P079'), '4', '118', b64('STATE_BATCH'), b64(request),
                             '1794643232773', b64(json.dumps(batch))]).encode()
        crc = zlib.crc32(struct.pack('>qq', 4, 118) + payload)
        return struct.pack('>IqqII', 0x43425731, 4, 118, len(payload), crc) + payload

    def test_base64_journal_identifies_the_real_reservation_without_plaintext_search(self):
        frame = self.reservation_frame()
        self.assertNotIn(b'1234567890123456789', frame)
        result = LOSS.lost_reservation_identity(
            frame, 'P079', 4, 118, 'ABC123', 'fixture-user', '1234567890123456789')
        self.assertEqual('1234567890123456789:Newing', result['event_id'])
        self.assertEqual(118, result['sequence'])

    def test_another_order_or_account_cannot_satisfy_the_loss_proof(self):
        for frame in [self.reservation_frame('OTHER:Newing'), self.reservation_frame(user='other-user')]:
            with self.assertRaisesRegex(RuntimeError, 'does not identify'):
                LOSS.lost_reservation_identity(
                    frame, 'P079', 4, 118, 'ABC123', 'fixture-user', '1234567890123456789')

    def test_lost_reservation_rejects_wrong_physical_epoch_and_damaged_crc(self):
        frame = self.reservation_frame()
        for candidate, epoch in [(frame, 5), (frame[:-1] + bytes([frame[-1] ^ 1]), 4)]:
            with self.assertRaisesRegex(RuntimeError, 'coordinate or CRC'):
                LOSS.lost_reservation_identity(
                    candidate, 'P079', epoch, 118, 'ABC123', 'fixture-user', '1234567890123456789')

    def test_strict_confirmation_refuses_to_mutate_or_inject_a_loss(self):
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary)
            root = local / 'mac-demo-20261114-000000'
            root.mkdir()
            fault = Mock(side_effect=AssertionError('Fault injection was reached'))
            customer = Mock(side_effect=AssertionError('Customer mutation was reached'))
            with patch.dict(LOSS.RPO['FRESH'], LOCAL=local), \
                    patch.dict(LOSS.CAPACITY, require_strict_demo=Mock(), common_release_identity=lambda root: {
                        'client_ack_policy': 'STRICT_QUORUM'}), \
                    patch.dict(LOSS.PRODUCT, ok=customer), \
                    patch.object(LOSS, 'run', fault), \
                    patch.object(sys, 'argv', [str(SCRIPT), str(root)]):
                with self.assertRaisesRegex(RuntimeError, 'normal dual-node asynchronous'):
                    LOSS.main()
            fault.assert_not_called()
            customer.assert_not_called()
            self.assertEqual([], list(root.iterdir()))

    def test_financial_comparison_uses_the_live_trade_service_and_exact_account(self):
        reply = {'Balance': '10000.00', 'UsedMargin': '0.00', 'FreezedMargin': '9.0000',
                 'FreezedCommission': '0.123'}
        call = Mock(return_value=reply)
        with patch.dict(LOSS.PRODUCT, ok=call):
            account = LOSS.account(('TENANT', 'USER', 'in-memory-fixture-session'))
        self.assertEqual('9', account['FreezedMargin'])
        self.assertEqual('0.123', account['FreezedCommission'])
        self.assertEqual(('TradeSvr', 'queryAccountBalance'), call.call_args.args[1:3])
        self.assertEqual({'location': 'TENANT', 'userid': 'USER'}, call.call_args.args[3])
        self.assertEqual('TENANT', call.call_args.kwargs['route_location'])

    def test_missing_frozen_funds_cannot_be_treated_as_zero(self):
        with patch.dict(LOSS.PRODUCT, ok=Mock(return_value={'Balance': '10000'})):
            with self.assertRaisesRegex(RuntimeError, 'missing an exact financial field'):
                LOSS.account(('TENANT', 'USER', 'in-memory-fixture-session'))

    def test_matched_readmission_also_refuses_strict_mode_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'mac-demo-20261116-000000'
            root.mkdir()
            customer = Mock(side_effect=AssertionError('A business mutation was reached'))
            with patch.dict(LOSS.RPO['FRESH'], LOCAL=Path(temporary)), \
                    patch.dict(LOSS.CAPACITY, require_strict_demo=Mock(), common_release_identity=lambda root: {
                        'client_ack_policy': 'STRICT_QUORUM'}), \
                    patch.dict(LOSS.PRODUCT, ok=customer), \
                    patch.object(sys, 'argv', [str(SCRIPT), str(root), '--after-loss', 'match']):
                with self.assertRaisesRegex(RuntimeError, 'normal dual-node asynchronous'):
                    LOSS.main()
            customer.assert_not_called()
            self.assertEqual([], list(root.iterdir()))


if __name__ == '__main__':
    unittest.main()
