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


if __name__ == '__main__':
    unittest.main()
