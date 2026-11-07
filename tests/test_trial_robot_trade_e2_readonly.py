#!/usr/bin/env python3
"""Contract tests for T541 read-only live Robot/Tape/Trade acceptance."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "robot_trade_e2", Path(__file__).with_name("check_trial_robot_trade_e2_readonly.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def counts():
    return {"bootstrap_complete": 6, "robot_live": 6, "robot_quote_orders": 240,
            "posting_rows": 24, "posting_event_ids": 12, "posting_locations": 6,
            "bad_posting_pairs": 0, "balance_locations": 6,
            "projection_age_seconds": 3}


def filled():
    return [("L%05d" % i, "E%04d" % i) for i in range(6)]


class RobotTradeReadOnlyTests(unittest.TestCase):
    def test_happy_path_is_business_only_not_ha(self):
        self.assertEqual(M.assess(counts(), filled(), 6), [])

    def test_rejects_duplicate_execution_id(self):
        events = filled()
        events.append((events[0][0], events[0][1]))
        self.assertIn("TAPE_EXEC_ID_DUPLICATED", M.assess(counts(), events, 6))

    def test_requires_2_postings_per_certified_atomic_match(self):
        stats = counts()
        stats["posting_rows"] = 23
        stats["bad_posting_pairs"] = 1
        self.assertIn("TRADE_ATOMIC_POSTING_PAIR_MISMATCH",
                      M.assess(stats, filled(), 6))

    def test_rejects_stale_funds_and_projection(self):
        stats = counts()
        stats["balance_locations"] = 5
        stats["projection_age_seconds"] = 200
        self.assertIn("TRADE_FINANCIAL_PROJECTION_NOT_CURRENT",
                      M.assess(stats, filled(), 6))

    def test_rejects_missing_live_book(self):
        stats = counts()
        stats["robot_live"] = 0
        self.assertIn("ROBOT_QUOTES_NOT_LIVE", M.assess(stats, filled(), 6))

    def test_filters_real_filled_tape_ioc_events(self):
        yes = ('2026/11/07 INFO publish ->: [gateway],'
               'dc.order.trade.BTCUSDT.0.000100000002.CN8U7C,'
               '[{"ExecID":"Egood","Terminal":"RobotSvr-Tape",'
               '"OrdStatus":"Filled","ExecType":"Trade","TimeInForce":"IOC"}]')
        no = yes.replace('"Filled"', '"New"')
        wrong = yes.replace('"RobotSvr-Tape"', '"Other"')
        self.assertEqual(M.tape_fills([yes, no, wrong, 'bad json'] ),
                         [("CN8U7C", "Egood")])

    def test_no_injection_in_container_and_sql_window(self):
        with self.assertRaises(ValueError):
            M.require_container("x; echo secret")
        with self.assertRaises(ValueError):
            M.sql_for(0)
        with self.assertRaises(ValueError):
            M.sql_for(1441)
        self.assertIn("INTERVAL 5 MINUTE", M.sql_for(5))
        self.assertIn("SELECT 'bad_posting_pairs'", M.sql_for(5))


if __name__ == "__main__":
    unittest.main()