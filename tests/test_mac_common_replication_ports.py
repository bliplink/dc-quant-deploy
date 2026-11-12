from pathlib import Path
import runpy
import unittest


FRESH = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/mac-demo-fresh.py'))


class ReplicationPortsTest(unittest.TestCase):
    def test_each_phase_has_four_unique_endpoints_below_the_vm_ephemeral_range(self):
        for phase in ('birth', 'install', 'home', 'stage', 'hostready'):
            ports = set()
            for kind, service in FRESH['SERVICES'].items():
                for slot in FRESH['SLOTS']:
                    values = FRESH['common_replication_settings'](kind, slot, phase)
                    port = int(values[kind + '.common.nodeRuntime.bindPort'])
                    self.assertGreater(port, 1024)
                    self.assertLess(port, 32768)
                    self.assertIn(service + slot + '@127.0.0.1:' + str(port),
                                  values[kind + '.common.nodeRuntime.nettyPeers'].split(','))
                    ports.add(port)
            self.assertEqual(4, len(ports))

    def test_bootstrap_phases_share_the_same_peers_and_runtime_uses_distinct_ports(self):
        for kind in FRESH['SERVICES']:
            for slot in FRESH['SLOTS']:
                initial = FRESH['common_replication_settings'](kind, slot, 'birth')
                for phase in ('install', 'home', 'stage'):
                    self.assertEqual(initial, FRESH['common_replication_settings'](kind, slot, phase))
                self.assertNotEqual(initial, FRESH['common_replication_settings'](kind, slot, 'hostready'))

    def test_unknown_voters_and_phases_fail_closed(self):
        for args in [('other', 'A', 'birth'), ('trade', 'C', 'birth'), ('trade', 'A', 'other')]:
            with self.assertRaises(ValueError):
                FRESH['common_replication_settings'](*args)

    def test_generated_properties_replace_the_old_port_and_peer_list_once(self):
        original = ('trade.common.nodeRuntime.bindPort=48422\n'
                    'trade.common.nodeRuntime.nettyPeers=old-peer\n')
        values = FRESH['common_replication_settings']('trade', 'A', 'hostready')
        updated = FRESH['update_properties'](original, values)
        self.assertNotIn('48422', updated)
        self.assertNotIn('old-peer', updated)
        for key, value in values.items():
            self.assertEqual(1, updated.count(key + '='))
            self.assertIn(key + '=' + value + '\n', updated)


if __name__ == '__main__':
    unittest.main()
