import unittest

from tests.trade_recovery_baseline_host import summarize_readiness, timestamp


class TradeRecoveryBaselineTest(unittest.TestCase):
    started = "2026-09-29T00:00:00Z"
    assignment = [{"partitionId": "P122", "primary": "TradeSvrA", "epoch": 4, "state": "READY"}]

    def ready(self, epoch=4, at="00:00:08"):
        return f"2026-09-29T{at}Z INFO TRADE_PARTITION_READY node:TradeSvrA, partition:P122, epoch:{epoch}, committedStateSeq:99, locations:0"

    def test_current_process_and_epoch_only(self):
        result = summarize_readiness(self.ready(3) + "\n" + self.ready(), "TradeSvrA", self.started, self.assignment)
        self.assertEqual(1, result["readyEvidenceCount"])
        self.assertEqual(8, result["lastReadySecondsFromStart"])
        self.assertFalse(result["businessWritableVerified"])

    def test_old_epoch_and_previous_process_are_not_ready(self):
        text = self.ready(3) + "\n" + self.ready().replace("2026-09-29", "2026-09-28")
        result = summarize_readiness(text, "TradeSvrA", self.started, self.assignment)
        self.assertEqual(["P122"], result["missingReadyEvidence"])

    def test_later_failure_revokes_log_evidence(self):
        failure = "2026-09-29T00:00:09Z ERROR TRADE_PARTITION_RECOVERY_FAILED node:TradeSvrA, partition:P122, epoch:4"
        result = summarize_readiness(self.ready() + "\n" + failure, "TradeSvrA", self.started, self.assignment)
        self.assertEqual(0, result["readyEvidenceCount"])
        self.assertEqual({"P122": 1}, result["recoveryFailureCounts"])

    def test_retry_can_restore_readiness(self):
        failure = "2026-09-29T00:00:09Z ERROR TRADE_PARTITION_RECOVERY_FAILED node:TradeSvrA, partition:P122, epoch:4"
        result = summarize_readiness(failure + "\n" + self.ready(at="00:00:12"), "TradeSvrA", self.started, self.assignment)
        self.assertEqual(1, result["readyEvidenceCount"])
        self.assertEqual(12, result["lastReadySecondsFromStart"])

    def test_report_does_not_include_raw_secrets(self):
        text = self.ready() + '\n2026-09-29T00:00:10Z INFO token=SECRET password=SECRET'
        result = summarize_readiness(text, "TradeSvrA", self.started, self.assignment)
        self.assertNotIn("SECRET", str(result))

    def test_docker_nanosecond_timestamp_on_python39(self):
        self.assertEqual(470900, timestamp("2026-09-28T23:53:47.470900254Z").microsecond)


if __name__ == "__main__":
    unittest.main()
