"""Offline eventual-consistency DB evidence classification tests."""
import importlib.util
from pathlib import Path
import unittest

SRC = Path(__file__).with_name("broker-db-evidence-rows.py")
spec = importlib.util.spec_from_file_location("broker_db_rows", SRC)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class BrokerDbEvidenceTests(unittest.TestCase):
    def test_exactly_five_rows_each_one_pass(self):
        self.assertEqual(checker.classify("1\n1\n1\n1\n1\n"), "PASS")

    def test_missing_projection_rows_wait(self):
        self.assertEqual(checker.classify("1\n0\n1\n1\n0\n"), "WAIT")
        self.assertEqual(checker.classify("0\n0\n0\n0\n0\n"), "WAIT")

    def test_duplicates_fail_immediately(self):
        self.assertEqual(checker.classify("2\n1\n1\n1\n1\n"), "FAIL")
        self.assertEqual(checker.classify("1\n1\n1\n1\n2\n"), "FAIL")

    def test_partial_or_corrupted_mysql_output_fails(self):
        for text in ["", "1\n1\n1\n1", "1\n1\n1\n1\nNaN",
                     "1\n1\n1\n1\n-1", "1\n1\n1\n1\n1\n1"]:
            self.assertEqual(checker.classify(text), "FAIL", repr(text))


if __name__ == "__main__":
    unittest.main()
