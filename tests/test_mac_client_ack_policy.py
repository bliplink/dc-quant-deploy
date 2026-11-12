import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


FRESH = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/mac-demo-fresh.py'))
SELECT = FRESH['selected_client_ack_policy']
ENVIRONMENT = FRESH['client_ack_environment']
PROPERTY = '-Dcommon.certified.clientAckPolicy'


class ClientAckPolicyTest(unittest.TestCase):
    def test_default_strict_accepts_existing_releases(self):
        self.assertEqual('STRICT_QUORUM', SELECT({}, 'STRICT_QUORUM'))
        with self.assertRaises(ValueError):
            SELECT({}, 'async')
        with self.assertRaises(RuntimeError):
            SELECT({}, 'LOCAL_DURABLE_ASYNC')

    def test_async_requires_complete_exact_jar_recovery_evidence(self):
        seal = {
            'normal_dual_async': True,
            'normal_dual_async_max_pending_per_partition': 1,
            'normal_dual_async_recovery_head': 'backup_certified_committed',
            'live_poison_recovery_evidence': dict.fromkeys((
                'normal-dual-async', 'normal-dual-async-primary-kill',
                'normal-dual-async-backup-expiry'), {}),
        }
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / 'verification.seal.json'
            images = {'common_fault_result': directory}
            with patch.dict(SELECT.__globals__, verified_common_release=lambda images: True):
                evidence.write_text(json.dumps(seal))
                self.assertEqual('LOCAL_DURABLE_ASYNC', SELECT(images, 'LOCAL_DURABLE_ASYNC'))
                for key in seal:
                    incomplete = dict(seal)
                    del incomplete[key]
                    evidence.write_text(json.dumps(incomplete))
                    with self.subTest(missing=key), self.assertRaises(RuntimeError):
                        SELECT(images, 'LOCAL_DURABLE_ASYNC')

    def test_replaces_old_flags_across_all_jvm_option_sources(self):
        for old in (PROPERTY, PROPERTY + '=STRICT_QUORUM',
                    '"' + PROPERTY + '=LOCAL_DURABLE_ASYNC"',
                    "'" + PROPERTY + "=STRICT_QUORUM'",
                    PROPERTY + '="LOCAL_DURABLE_ASYNC"', PROPERTY + "='STRICT_QUORUM'"):
            inherited = ['JAVA_OPTS=-Xms64m ' + old, 'EXTRA_JAVA_OPTS=' + old + ' -ea',
                         'JAVA_TOOL_OPTIONS=-Dunrelated=preserved ' + old,
                         'MAIN_CLASS=example.Main', 'APP_ARGS=--fixture', 'PASSWORD=excluded']
            with self.subTest(old=old):
                entries = ENVIRONMENT(inherited, 'LOCAL_DURABLE_ASYNC')
                values = dict(entry.split('=', 1) for entry in entries)
                self.assertEqual('-Xms64m', values['JAVA_OPTS'])
                self.assertEqual('-ea', values['EXTRA_JAVA_OPTS'])
                self.assertEqual('-Dunrelated=preserved ' + PROPERTY + '=LOCAL_DURABLE_ASYNC',
                                 values['JAVA_TOOL_OPTIONS'])
                self.assertEqual('example.Main', values['MAIN_CLASS'])
                self.assertNotIn('PASSWORD', values)
                self.assertEqual(entries, ENVIRONMENT(entries, 'LOCAL_DURABLE_ASYNC'))
                strict = ENVIRONMENT(entries, 'STRICT_QUORUM')
                self.assertEqual(1, '\n'.join(strict).count(PROPERTY))
                self.assertIn(PROPERTY + '=STRICT_QUORUM', '\n'.join(strict))

    def test_ambiguous_quoting_and_unknown_modes_fail_closed(self):
        with self.assertRaises(RuntimeError):
            ENVIRONMENT(['JAVA_OPTS="' + PROPERTY + '=STRICT_QUORUM'], 'STRICT_QUORUM')
        with self.assertRaises(ValueError):
            ENVIRONMENT([], 'async')


if __name__ == '__main__':
    unittest.main()
