#!/usr/bin/env python3
"""Safety regression tests for isolated Order fault-injection assignment writes."""

import importlib.util
import json
import unittest
from pathlib import Path


SOURCE = Path(__file__).with_name("order_cluster_zk_assignment.py")
SPEC = importlib.util.spec_from_file_location("zk_assignment", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PATH = "/dc/cluster/ordersvr-dev/partitions/P027"


class OrderClusterZkAssignmentTest(unittest.TestCase):
    def sample(self, assignment):
        return "noise\n%s\ncZxid = 0x1\ndataVersion = 8\n" % json.dumps(assignment)

    def test_parses_epoch_first_assignment_and_preserves_extensions(self):
        original = {"epoch": 7, "partitionId": "P027", "primary": "OrderSvrA",
                    "replica": "OrderSvrB", "replicas": ["OrderSvrB"],
                    "assignmentVersion": 4, "state": "READY", "note": "keep"}
        row, version = MODULE.parse_get_output(self.sample(original), "P027")
        command = MODULE.transition(row, version, PATH, 8, "OrderSvrB", "OrderSvrA",
                                    7, "OrderSvrA")
        self.assertTrue(command.startswith("set -v 8 " + PATH + " "))
        payload = json.loads(command.split(" ", 4)[4])
        self.assertEqual("OrderSvrB", payload["primary"])
        self.assertEqual(["OrderSvrA"], payload["replicas"])
        self.assertEqual(5, payload["assignmentVersion"])
        self.assertEqual("keep", payload["note"])

    def test_rejects_missing_or_ambiguous_version(self):
        row = {"partitionId": "P027", "epoch": 7, "state": "READY"}
        with self.assertRaises(ValueError):
            MODULE.parse_get_output(json.dumps(row), "P027")
        with self.assertRaises(ValueError):
            MODULE.parse_get_output(self.sample(row) + "dataVersion = 9\n", "P027")

    def test_rejects_stale_epoch_and_unsupported_topology(self):
        row = {"partitionId": "P027", "epoch": 7, "state": "READY", "replica": "OrderSvrB"}
        with self.assertRaises(ValueError):
            MODULE.transition(row, 8, PATH, 7, "OrderSvrB", "OrderSvrA", 7, "OrderSvrA")
        with self.assertRaises(ValueError):
            MODULE.transition(dict(row, learners=["OrderSvrC"]), 8, PATH, 8,
                              "OrderSvrB", "OrderSvrA", 7, "OrderSvrA")
        with self.assertRaises(ValueError):
            MODULE.transition(row, 8, PATH, 8, "OrderSvrB", "OrderSvrA", 6, "OrderSvrA")


if __name__ == "__main__":
    unittest.main()
