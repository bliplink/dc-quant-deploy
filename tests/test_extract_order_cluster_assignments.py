import json
import unittest

from extract_order_cluster_assignments import extract


class AssignmentExtractionTest(unittest.TestCase):
    def test_accepts_any_field_order_amid_zookeeper_noise(self):
        lines = [
            "[zk: localhost(CONNECTED) 0] get /dc/cluster/ordersvr/partitions/P019\n",
            '{"epoch":7,"partitionId":"P019","primary":"OrderSvrB","replica":"OrderSvrA","state":"READY"}\n',
            '{"partitionId":"P020","epoch":7,"primary":"OrderSvrA","replica":"OrderSvrB","state":"READY"}\n',
            "WatchedEvent state:Closed type:None path:null\n",
        ]
        assignments = [json.loads(line) for line in extract(lines)]
        self.assertEqual(["P019", "P020"], [row["partitionId"] for row in assignments])

    def test_malformed_assignment_fails_closed(self):
        with self.assertRaises(json.JSONDecodeError):
            list(extract(['{"partitionId":"P019"\n']))


if __name__ == "__main__":
    unittest.main()
