import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('ports', Path(__file__).with_name('reserve-saas-service-ports.py'))
ports = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ports)


class PortReservationsTest(unittest.TestCase):
    def test_preserves_and_merges_ranges(self):
        existing = ports.parse_ports('33035-33037,40000')
        merged = ports.format_ports(existing | {33038, 33039, 19121})
        self.assertEqual('19121,33035-33039,40000', merged)
        self.assertTrue(existing <= ports.parse_ports(merged))

    def test_invalid_ranges_fail(self):
        for value in ('0', '65536', '100-90', '1-2-3', 'abc'):
            with self.assertRaises(ValueError):
                ports.parse_ports(value)

    def test_only_scoped_numeric_ports(self):
        result = ports.service_ports({'LIQSVR_GW_PORT': '33038', 'OTHER_PORT': '9999',
                                     'MYSQL_PASSWORD': 'not-a-number', 'TRADESVR_A_REPLICATION_PORT': '19221'})
        self.assertEqual({18090, 18092, 33038, 19221}, result)

    def test_invalid_service_port_fails(self):
        with self.assertRaises(ValueError):
            ports.service_ports({'LIQSVR_GW_PORT': '33038;anything'})


if __name__ == '__main__':
    unittest.main()
