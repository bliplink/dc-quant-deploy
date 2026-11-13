from pathlib import Path
from contextlib import contextmanager
import runpy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


FRESH = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/mac-demo-fresh.py'))
SPACE = FRESH['require_docker_space']
RESTORE = FRESH['restore_container_restart_policy']
PREPARE_RUNTIME = FRESH['prepare_voter_runtime_storage']
CAPACITY = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/verify-mac-demo-robot-capacity.py'))
CONTROL = CAPACITY['require_strict_demo']
GIB = 1024 ** 3


class StorageLifecycleTest(unittest.TestCase):
    def test_voter_logs_and_both_runtime_data_paths_use_persistent_native_volume(self):
        run = Mock()
        with patch.dict(PREPARE_RUNTIME.__globals__, run=run):
            flags = PREPARE_RUNTIME('mac-demo-20261113-000000', 'order', 'A', 'sha256:fixture')
        mounts = dict(zip(flags[1::2], flags[::2]))
        self.assertEqual(4, len(mounts))
        for subpath, target in [('data', '/srv/dc/data'), ('log', '/srv/dc/log'),
                                ('service-data', '/srv/dc/dc/OrderSvr/data'),
                                ('service-log', '/srv/dc/dc/OrderSvr/log')]:
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
        self.manifest = {f'P{index:03d}': {'state': 'READY', 'policy': 'STRICT_QUORUM'}
                         for index in range(256)}
        self.fresh = {'LOCAL': self.root.parent,
                      'env_pairs': Mock(return_value={'ZOOKEEPER_PORT': '2181'}),
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


if __name__ == '__main__':
    unittest.main()
