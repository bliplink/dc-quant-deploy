"""No false PASS when Trade node lacks independent recovery or signing roles."""
import unittest
from tests.trade_ab_auto_ha_preflight import blockers, PREFIX


class TradeABAutoHaPreflightTest(unittest.TestCase):
    def config(self, node):
        other = "TradeSvrB" if node == "A" else "TradeSvrA"
        port = "19222" if node == "A" else "19221"
        x = {}
        for suffix in (
            "certifiedRecipient.enabled", "head.enabled", "data.enabled",
            "manifest.enabled", "replica.autoWarm.enabled",
            "replica.electedBootstrap.enabled",
            "replica.electedBootstrap.fleetEnabled",
            "replica.genesisReceipt.enabled", "genesisObserver.enabled",
            "replica.physicalReceipt.enabled", "replica.physicalHealth.enabled",
            "replica.physicalHealth.fleetEnabled",
            "genesisObserver.fleetEnabled",
            "genesisObserver.replicaHealthEnabled",
        ):
            x[PREFIX + suffix] = "true"
        x.update({
            PREFIX + "replica.autoWarm.sourceNode": other,
            PREFIX + "replica.autoWarm.sourcePort": port,
            PREFIX + "genesisObserver.targetNode": other,
            PREFIX + "genesisObserver.targetPort": port,
            PREFIX + "genesisObserver.transferEnabled": "false",
            PREFIX + "replica.autoWarm.pilotPartition": "P090",
        })
        for suffix in (
            "head.rsaPrivateKeyBase64", "read.readerPublicKeyBase64",
            "replica.autoWarm.sourcePublicKeyBase64",
            "replica.autoWarm.readerRsaPrivateKeyBase64",
            "certifiedRecipient.privateRoot",
        ):
            x[PREFIX + suffix] = "<nonempty-test-placeholder>"
        return x

    def test_symmetric_preconfigured_nodes_only_preenrollment_pass(self):
        a, b = self.config("A"), self.config("B")
        self.assertEqual([], blockers("A", a, b))
        self.assertEqual([], blockers("B", b, a))

    def test_missing_receiver_key_blocks_without_value_leak(self):
        a, b = self.config("A"), self.config("B")
        a[PREFIX + "replica.autoWarm.readerRsaPrivateKeyBase64"] = ""
        errors = blockers("A", a, b)
        self.assertTrue(any("readerRsaPrivateKeyBase64" in x for x in errors))
        self.assertNotIn("<nonempty-test-placeholder>", repr(errors))

    def test_peer_without_source_signer_blocks(self):
        a, b = self.config("A"), self.config("B")
        b[PREFIX + "head.rsaPrivateKeyBase64"] = ""
        self.assertTrue(any("peer.head.rsaPrivateKey" in x for x in blockers("A", a, b)))

    def test_disabled_autowarm_blocks(self):
        a, b = self.config("A"), self.config("B")
        a[PREFIX + "replica.autoWarm.enabled"] = "false"
        self.assertTrue(any("autoWarm.enabled" in x for x in blockers("A", a, b)))

    def test_stale_peer_and_wrong_port_block(self):
        a, b = self.config("A"), self.config("B")
        a[PREFIX + "replica.autoWarm.sourceNode"] = "TradeSvrA"
        a[PREFIX + "replica.autoWarm.sourcePort"] = "19221"
        problems = blockers("A", a, b)
        self.assertTrue(any("sourceNode" in x for x in problems))
        self.assertTrue(any("sourcePort" in x for x in problems))

    def test_genesis_auto_handoff_disabled_for_repair(self):
        a, b = self.config("A"), self.config("B")
        a[PREFIX + "genesisObserver.transferEnabled"] = "true"
        self.assertTrue(any("transferEnabled" in x for x in blockers("A", a, b)))

    def test_missing_explicit_pilot_is_not_implicitly_safe(self):
        a, b = self.config("A"), self.config("B")
        a[PREFIX + "replica.autoWarm.pilotPartition"] = ""
        self.assertTrue(any("pilotPartition" in x for x in blockers("A", a, b)))


    def test_pilot_p090_with_fleet_off_can_pass_only_config_gate(self):
        a, b = self.config("A"), self.config("B")
        for x in (a, b):
            x[PREFIX + "replica.electedBootstrap.fleetEnabled"] = "false"
            x[PREFIX + "genesisObserver.fleetEnabled"] = "false"
            x[PREFIX + "genesisObserver.pilotPartition"] = "P090"
            x[PREFIX + "replica.physicalHealth.fleetEnabled"] = "false"
            x[PREFIX + "replica.physicalHealth.pilotPartition"] = "P090"
        self.assertEqual([], blockers("A", a, b, mode="pilot", partition="P090"))
        self.assertEqual([], blockers("B", b, a, mode="pilot", partition="P090"))
        self.assertTrue(any("fleetEnabled" in p for p in blockers("A", a, b, mode="fleet")))

    def test_pilot_cannot_run_with_fleet_enabled(self):
        a, b = self.config("A"), self.config("B")
        a[PREFIX + "genesisObserver.pilotPartition"] = "P090"
        a[PREFIX + "replica.physicalHealth.pilotPartition"] = "P090"
        self.assertTrue(any("fleetEnabled" in p for p in blockers("A", a, b, mode="pilot", partition="P090")))

    def test_wrong_pilot_cannot_silently_run_other_partition(self):
        a, b = self.config("A"), self.config("B")
        for x in (a,b):
            x[PREFIX + "replica.electedBootstrap.fleetEnabled"] = "false"
            x[PREFIX + "genesisObserver.fleetEnabled"] = "false"
            x[PREFIX + "genesisObserver.pilotPartition"] = "P001"
            x[PREFIX + "replica.physicalHealth.fleetEnabled"] = "false"
            x[PREFIX + "replica.physicalHealth.pilotPartition"] = "P001"
        issues=blockers("A",a,b,mode="pilot",partition="P090")
        self.assertTrue(any("genesisObserver.pilotPartition" in p for p in issues))

    def test_physical_health_must_not_scan_fleet_during_pilot(self):
        a, b = self.config("A"), self.config("B")
        for x in (a, b):
            x[PREFIX + "replica.electedBootstrap.fleetEnabled"] = "false"
            x[PREFIX + "genesisObserver.fleetEnabled"] = "false"
            x[PREFIX + "genesisObserver.pilotPartition"] = "P090"
            x[PREFIX + "replica.physicalHealth.pilotPartition"] = "P090"
        a[PREFIX + "replica.physicalHealth.fleetEnabled"] = "true"
        self.assertTrue(any("replica.physicalHealth.fleetEnabled" in p
                            for p in blockers("A", a, b, mode="pilot", partition="P090")))
        a[PREFIX + "replica.physicalHealth.fleetEnabled"] = "false"
        self.assertEqual([], blockers("A", a, b, mode="pilot", partition="P090"))
        a[PREFIX + "replica.physicalHealth.pilotPartition"] = "P091"
        self.assertTrue(any("replica.physicalHealth.pilotPartition" in p
                            for p in blockers("A", a, b, mode="pilot", partition="P090")))

    def test_invalid_pilot_partitions_are_rejected(self):
        a, b = self.config("A"), self.config("B")
        with self.assertRaises(ValueError):
            blockers("A", a, b, mode="pilot", partition="../../P090")
        with self.assertRaises(ValueError):
            blockers("A", a, b, mode="unknown")

if __name__ == "__main__":
    unittest.main()