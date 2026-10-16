import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/check-trade-failback-preflight.py"
spec = importlib.util.spec_from_file_location("trade_failback_preflight", str(SOURCE))
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def assignments():
    result = []
    for i in range(256):
        p = "P%03d" % i
        result.append({
            "partitionId": p, "primary": "TradeSvrA",
            "replica": "TradeSvrB", "replicas": ["TradeSvrB"],
            "epoch": 2 if i % 2 else 1, "state": "READY",
        })
    return result


def healthy(part, epoch=2, now=100000):
    return {"partitionId": part, "epoch": epoch, "primary": "TradeSvrA",
            "replica": "TradeSvrB", "degraded": False,
            "replicatedSeq": 200, "updatedAt": now}


class TradeFailbackPreflightTest(unittest.TestCase):
    def test_controller_ready_256_does_not_authorize_failback(self):
        result = gate.assess(assignments(), {}, now_ms=100000)
        self.assertEqual(result["primaryCounts"], {"TradeSvrA": 256})
        self.assertEqual(result["stateCounts"], {"READY": 256})
        self.assertEqual(result["inferredFormerBPrimaryCandidates"], 128)
        self.assertEqual(result["candidateBlockerCounts"]["REPLICATION_HEALTH_MISSING"], 128)
        self.assertFalse(result["automaticPrimaryChangeAuthorized"])

    def test_even_complete_healthy_replication_does_not_authorize_handoff(self):
        health = {r["partitionId"]: healthy(r["partitionId"])
                  for r in assignments() if int(r["partitionId"][1:]) % 2}
        result = gate.assess(assignments(), health, now_ms=100000)
        self.assertEqual(result["candidatesWithCleanPreliminaryHealth"], 128)
        self.assertEqual(result["candidateBlockerCounts"], {})
        self.assertFalse(result["automaticPrimaryChangeAuthorized"])
        self.assertIn("LIVE_PRIMARY_WRITE_DRAIN_AND_EPOCH_FENCE_HANDOFF_NOT_IMPLEMENTED",
                      result["mandatoryBlockers"])

    def test_stale_wrong_epoch_or_degraded_blocks_preliminary_proof(self):
        h = healthy("P001", epoch=1, now=1000)
        h["degraded"] = True
        result = gate.assess(assignments(), {"P001": h}, now_ms=100000, max_health_age_ms=10000)
        reasons = result["candidateBlockerCounts"]
        self.assertIn("REPLICATION_HEALTH_ROLE_OR_EPOCH_MISMATCH", reasons)
        self.assertIn("REPLICATION_HEALTH_STALE", reasons)
        self.assertIn("REPLICATION_DEGRADED_OR_UNKNOWN", reasons)

    def test_refuses_incomplete_partition_inventory(self):
        with self.assertRaises(ValueError):
            gate.assess(assignments()[:255], {}, now_ms=100000)

    def test_untrusted_health_response_rejected(self):
        raw = '[zk: x(CONNECTED) 0] ls /a\n[P001, P002]\n'
        self.assertEqual(gate.parse_health_children(raw), ["P001", "P002"])
        with self.assertRaises(ValueError):
            gate.parse_health_records('{"partitionId":"P001"}\n', {"P001", "P002"})
        with self.assertRaises(ValueError):
            gate.parse_health_children("[P001, invalid]\n")

    def test_only_reads_zk_and_never_calls_cas_or_set(self):
        class Stub:
            def __init__(self): self.commands = []
            def _zk(self, command, timeout=30):
                self.commands.append(command)
                if command.startswith("ls "): return "[P001]\n"
                return '{"partitionId":"P001","epoch":2,"primary":"TradeSvrA","replica":"TradeSvrB","degraded":false,"replicatedSeq":5,"updatedAt":100000}\n'
        fake = Stub()
        self.assertEqual(set(gate.read_health(fake)), {"P001"})
        self.assertTrue(all(line.startswith(("ls ", "get ")) for command in fake.commands
                            for line in command.splitlines()))


if __name__ == "__main__":
    unittest.main()
