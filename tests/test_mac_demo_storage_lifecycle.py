from pathlib import Path
from contextlib import contextmanager
import runpy
import tempfile
import json
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


FRESH = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/mac-demo-fresh.py'))
SPACE = FRESH['require_docker_space']
RESTORE = FRESH['restore_container_restart_policy']
PREPARE_RUNTIME = FRESH['prepare_voter_runtime_storage']
BOUNDED_LOGGING = FRESH['bounded_application_logging']
CORE_LOGGING = FRESH['configured_core_logging']
CAPACITY = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/verify-mac-demo-robot-capacity.py'))
CONTROL = CAPACITY['require_strict_demo']
GIB = 1024 ** 3


class StorageLifecycleTest(unittest.TestCase):
    def test_core_overrides_keep_robot_ingress_and_publication_evidence(self):
        image=('log4j.rootLogger=INFO,file,stdout\n'
               'log4j.appender.file=org.apache.log4j.FileAppender\n'
               'log4j.appender.file.File=../../log/Trade2Svr.log\n')
        override=('log4j.logger.com.app.dc.handler.UpdateOrderHandler=WARN\n'
                  'log4j.logger.com.gateway.connector.tcp.client.GateWayApi=ERROR\n'
                  'log4j.logger.com.app.dc.service.check.ProcessOrder=WARN\n')
        configured=CORE_LOGGING(image,override)
        values=dict(line.split('=',1) for line in configured.splitlines() if '=' in line)
        self.assertEqual('INFO',values['log4j.logger.com.app.dc.handler.UpdateOrderHandler'])
        self.assertEqual('ERROR',values['log4j.logger.com.gateway.connector.tcp.client.GateWayApi'])
        self.assertEqual('INFO',values['log4j.logger.com.gw.common.utils'])
        self.assertEqual('INFO',values['log4j.logger.com.gw.common.utils.GwServerResource'])
        self.assertEqual('WARN',values['log4j.logger.com.gw.common.utils.BaseApi'])
        self.assertEqual('WARN',values['log4j.logger.com.app.dc.service.check.ProcessOrder'])
        self.assertEqual('../../log/Trade2Svr.log',values['log4j.appender.file.File'])
        self.assertEqual(configured,CORE_LOGGING(configured,override))

    def test_compact_tape_observer_disables_transport_payloads_on_both_appenders(self):
        image = ('log4j.rootLogger=INFO,file,stdout\n'
                 'log4j.appender.file=org.apache.log4j.FileAppender\n')
        current = CORE_LOGGING(image, '', tape_audit=True)
        values = dict(line.split('=',1) for line in current.splitlines() if '=' in line)
        self.assertEqual('WARN', values['log4j.logger.com.gw.common.utils'])
        self.assertEqual('WARN', values['log4j.logger.com.gw.common.utils.GwServerResource'])
        self.assertEqual('DEBUG', values['log4j.logger.com.app.dc.service.publish.TapeExecution'])
        self.assertEqual('INFO', values['log4j.logger.com.app.dc.handler.UpdateOrderHandler'])
        self.assertEqual(current, CORE_LOGGING(current, '', tape_audit=True))

    def test_application_log_rotation_keeps_levels_and_file_path(self):
        original = ('log4j.rootLogger=INFO,file,stdout\n'
                    'log4j.appender.file=org.apache.log4j.DailyRollingFileAppender\n'
                    'log4j.appender.file.File=../../log/OrderSvr.log\n'
                    'log4j.appender.file.DatePattern=yyyy-MM-dd\n'
                    'log4j.appender.file.layout.ConversionPattern=%d %p %m (%C{1}:%L)%n\n'
                    'log4j.appender.stdout.layout.ConversionPattern=%d %p %m (%C{1}:%L)%n\n'
                    'log4j.logger.Common=DEBUG\n')
        bounded = BOUNDED_LOGGING(original)
        self.assertIn('log4j.rootLogger=INFO,file,stdout\n', bounded)
        self.assertIn('log4j.logger.Common=DEBUG\n', bounded)
        self.assertIn('log4j.appender.file.File=../../log/OrderSvr.log\n', bounded)
        self.assertIn('log4j.appender.file=org.apache.log4j.RollingFileAppender\n', bounded)
        self.assertIn('log4j.appender.file.MaxFileSize=50MB\n', bounded)
        self.assertIn('log4j.appender.file.MaxBackupIndex=5\n', bounded)
        self.assertNotIn('DatePattern', bounded)
        self.assertEqual(2, bounded.count('ConversionPattern=%d %p %m (%c{1})%n'))
        self.assertEqual(bounded, BOUNDED_LOGGING(bounded))

    def test_unknown_or_duplicate_file_appenders_fail_before_deployment(self):
        for content in ('', 'log4j.appender.file=custom.Appender\n',
                        'log4j.appender.file=org.apache.log4j.FileAppender\n' * 2):
            with self.subTest(content=content), self.assertRaises(RuntimeError):
                BOUNDED_LOGGING(content)

    def test_voter_logs_and_both_runtime_data_paths_use_persistent_native_volume(self):
        run = Mock()
        with patch.dict(PREPARE_RUNTIME.__globals__, run=run):
            flags = PREPARE_RUNTIME('mac-demo-20261113-000000', 'order', 'A', 'sha256:fixture')
        mounts = dict(zip(flags[1::2], flags[::2]))
        self.assertEqual(2, len(mounts))
        for subpath, target in [('data', '/srv/dc/data'), ('log', '/srv/dc/log')]:
            specification = (f'type=volume,source=mac-demo-20261113-000000-order-a-runtime,'
                             f'target={target},volume-subpath={subpath}')
            self.assertEqual('--mount', mounts[specification])
        initializer = run.call_args_list[1].args
        self.assertIn('volume-nocopy', initializer[initializer.index('--mount') + 1])

    def test_each_physical_voter_gets_its_own_runtime_volume(self):
        run = Mock()
        with patch.dict(PREPARE_RUNTIME.__globals__, run=run):
            a = PREPARE_RUNTIME('mac-demo-20261113-000000', 'trade', 'A', 'sha256:fixture')
            b = PREPARE_RUNTIME('mac-demo-20261113-000000', 'trade', 'B', 'sha256:fixture')
        self.assertTrue(all('-trade-a-runtime,' in value for value in a[1::2]))
        self.assertTrue(all('-trade-b-runtime,' in value for value in b[1::2]))

    def test_low_host_space_rejects_before_querying_the_guest(self):
        read = Mock()
        with patch.object(FRESH['shutil'], 'disk_usage', return_value=SimpleNamespace(free=8 * GIB - 1)), \
                patch.dict(SPACE.__globals__, read=read):
            with self.assertRaisesRegex(RuntimeError, 'Mac storage'):
                SPACE()
        read.assert_not_called()

    def test_both_minimums_accept_their_exact_boundary(self):
        read = Mock(side_effect=['/var/lib/docker', f'{2 * GIB // 4096} 4096'])
        with patch.object(FRESH['shutil'], 'disk_usage', return_value=SimpleNamespace(free=8 * GIB)), \
                patch.dict(SPACE.__globals__, read=read):
            SPACE()
        self.assertEqual(2, read.call_count)

    def test_guest_space_still_requires_two_gib(self):
        read = Mock(side_effect=['/var/lib/docker', f'{2 * GIB // 4096 - 1} 4096'])
        with patch.object(FRESH['shutil'], 'disk_usage', return_value=SimpleNamespace(free=10 * GIB)), \
                patch.dict(SPACE.__globals__, read=read):
            with self.assertRaisesRegex(RuntimeError, 'Colima Docker storage'):
                SPACE()

    def test_pressure_can_use_its_explicit_four_gib_reserve(self):
        read = Mock(side_effect=['/var/lib/docker', f'{2 * GIB // 4096} 4096'])
        with patch.object(FRESH['shutil'], 'disk_usage', return_value=SimpleNamespace(free=4 * GIB)), \
                patch.dict(SPACE.__globals__, read=read):
            SPACE(min_host_free_bytes=4 * GIB)

    def test_unknown_guest_root_fails_closed(self):
        with patch.object(FRESH['shutil'], 'disk_usage', return_value=SimpleNamespace(free=10 * GIB)), \
                patch.dict(SPACE.__globals__, read=Mock(return_value='')):
            with self.assertRaisesRegex(RuntimeError, 'Docker data directory'):
                SPACE()

    def test_rollback_preserves_each_restart_policy_and_retry_limit(self):
        for name, retries, expected in [('no', 0, 'no'), ('always', 0, 'always'),
                                        ('unless-stopped', 0, 'unless-stopped'),
                                        ('on-failure', 0, 'on-failure'),
                                        ('on-failure', 7, 'on-failure:7'), ('', 0, 'no')]:
            run = Mock()
            container = {'Id': 'original-id', 'HostConfig': {
                'RestartPolicy': {'Name': name, 'MaximumRetryCount': retries}}}
            with self.subTest(policy=name, retries=retries), patch.dict(RESTORE.__globals__, run=run):
                RESTORE(container)
            run.assert_called_once_with('docker', 'update', '--restart', expected,
                                        'original-id', capture=True)


class CompletedWindowControlTest(unittest.TestCase):
    def setUp(self):
        self.root = Path('/tmp').resolve() / 'mac-demo-20261112-000000'
        self.storage = Mock(side_effect=RuntimeError('New deployment needs more storage'))
        self.policy = Mock()
        self.witness = Mock()
        self.manifest = {f'P{index:03d}': {'state': 'READY', 'policy': 'STRICT_QUORUM'}
                         for index in range(256)}
        self.fresh = {'LOCAL': self.root.parent,
                      'env_pairs': Mock(return_value={'ZOOKEEPER_PORT': '2181', 'common_sha256': 'fixture-sha'}),
                      'require_witness_runtime_storage': self.witness,
                      'verified_common_release': Mock(return_value=True),
                      'require_docker_space': self.storage,
                      'read': Mock(side_effect=['Darwin', 'colima'])}

    def check(self, **options):
        with patch.dict(CONTROL.__globals__, FRESH=self.fresh,
                        require_client_ack_policy=self.policy,
                        parse_manifest=Mock(return_value=self.manifest)), \
                patch.object(CAPACITY['subprocess'], 'check_output',
                             return_value='\n'.join([self.root.name] * 3)), \
                patch.object(CAPACITY['subprocess'], 'run',
                             return_value=SimpleNamespace(stdout='NPC1|2\n')):
            return CONTROL(self.root, **options)

    def test_completed_window_validates_control_without_a_new_deployment_space_check(self):
        self.assertEqual({'order': 2, 'trade': 2}, self.check(check_space=False))
        self.storage.assert_not_called()
        self.policy.assert_called_once()

    def test_load_admission_still_requires_storage_by_default(self):
        with self.assertRaisesRegex(RuntimeError, 'New deployment needs more storage'):
            self.check()
        self.storage.assert_called_once()

    def test_completed_window_still_rejects_a_nonready_partition(self):
        self.manifest['P000']['state'] = 'RECOVERING'
        with self.assertRaisesRegex(RuntimeError, 'partitions to be strict'):
            self.check(check_space=False)

    def test_completed_window_still_rejects_an_invalid_client_ack_policy(self):
        self.policy.side_effect = RuntimeError('Actual voter policy differs')
        with self.assertRaisesRegex(RuntimeError, 'Actual voter policy differs'):
            self.check(check_space=False)

    def test_bad_witness_storage_rejects_before_the_pressure_window(self):
        self.witness.side_effect = RuntimeError('Witness original read-only voter volume subpath differs')
        with self.assertRaisesRegex(RuntimeError, 'volume subpath'):
            self.check(check_space=False)
        self.witness.assert_called_once_with(self.root, 'fixture-sha')


    def test_completed_samples_survive_a_later_control_failure(self):
        @contextmanager
        def resources(generation):
            yield [{'at': 'fixture-window', 'containers': [{'Name': 'fixture-order'}]}]

        main = CAPACITY['main']
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            root = parent / 'mac-demo-20261112-000000'
            root.mkdir()
            control = Mock(side_effect=[{}, {'order': 2, 'trade': 2},
                                        RuntimeError('Physical control changed')])
            with patch.dict(main.__globals__, FRESH={'LOCAL': parent},
                            require_strict_demo=control, enroll=Mock(return_value={'ABC123'}),
                            demo_tenants=Mock(return_value={'ABC123': 'RUNNING'}),
                            MEASURE={'sample_resources': resources}), \
                    patch.object(CAPACITY['sys'], 'argv', ['capacity', str(root), '10']), \
                    patch.object(CAPACITY['time'], 'sleep'):
                with self.assertRaisesRegex(RuntimeError, 'Physical control changed'):
                    main()
            reports = list(root.glob('robot-steady-10-*.json'))
            self.assertEqual(1, len(reports))
            saved = CAPACITY['json'].loads(reports[0].read_text())
            self.assertFalse(saved['passed'])
            self.assertEqual('MEASUREMENT_COMPLETE_VALIDATION_PENDING', saved['status'])
            self.assertEqual('fixture-window', saved['resource_samples'][0]['at'])
            self.assertEqual({'order': 2, 'trade': 2}, saved['control_generation_before'])
            self.assertIn('from', saved)
            self.assertIn('until', saved)


class WitnessMountFidelityTest(unittest.TestCase):
    def setUp(self):
        self.root = Path('/tmp/mac-demo-20261115-000000')
        self.witnesses = []
        for kind, service in FRESH['SERVICES'].items():
            configured = []
            visible = []
            for slot in FRESH['SLOTS']:
                target = '/srv/dc/data/t554-voter-' + slot.lower()
                configured.append({'Type': 'volume', 'Source': self.root.name + '-ready', 'Target': target,
                                   'ReadOnly': True, 'VolumeOptions': {'Subpath': service + '/' + service + slot}})
                visible.append({'Type': 'volume', 'Name': self.root.name + '-ready', 'Destination': target, 'RW': False})
            self.witnesses.append({'Name': '/' + self.root.name + '-' + kind + '-witness',
                                   'State': {'Running': True}, 'Config': {'Labels': {'dc.common.jar.sha256': 'exact'}},
                                   'HostConfig': {'Mounts': configured}, 'Mounts': visible})

    def check(self, values):
        function = FRESH['require_witness_runtime_storage']
        with patch.dict(function.__globals__, read=Mock(return_value=json.dumps(values))):
            function(self.root, 'exact')

    def test_exact_original_subpaths_are_accepted(self):
        self.check(self.witnesses)

    def test_flattening_to_the_whole_volume_is_rejected_even_when_read_only(self):
        changed = copy.deepcopy(self.witnesses)
        changed[0]['HostConfig']['Mounts'][0].pop('VolumeOptions')
        with self.assertRaisesRegex(RuntimeError, 'volume subpath'):
            self.check(changed)

    def test_wrong_voter_and_writable_data_are_rejected(self):
        for key, value in [('Subpath', 'TradeSvr/TradeSvrB'), ('ReadOnly', False), ('RW', True)]:
            changed = copy.deepcopy(self.witnesses)
            if key == 'Subpath':
                changed[0]['HostConfig']['Mounts'][0]['VolumeOptions'][key] = value
            elif key == 'ReadOnly':
                changed[0]['HostConfig']['Mounts'][0][key] = value
            else:
                changed[0]['Mounts'][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, 'volume subpath'):
                self.check(changed)



if __name__ == '__main__':
    unittest.main()
