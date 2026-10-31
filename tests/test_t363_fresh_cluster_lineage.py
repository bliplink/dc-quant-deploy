#!/usr/bin/env python3
"""Unit tests for fail-closed T363 original-Epoch/fresh-WAL guard."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

module = Path(__file__).with_name("verify-t363-fresh-cluster-lineage-readonly.py")
spec = importlib.util.spec_from_file_location("t363_lineage", str(module))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def config():
    services={}
    for svc, prefix in (("ordersvr","order"),("tradesvr","trade")):
        for alias, node in (("A",svc),("B",svc+"-b")):
            services[node]={
                "environment":[f"JAVA_OPTS=-D{prefix}.common.nodeRuntime.dataRoot=/srv/dc/data/t361-fresh/{svc}/{alias}"],
                "volumes":[{"target":"/srv/dc/data/t318-born","source":"ORIGINAL_BIRTH","read_only":True}],
            }
    services["mysql"]={"volumes":[{"target":"/var/lib/mysql","source":"/demo/data/t361-fresh-mysql"}]}
    services["clickhouse"]={"volumes":[{"target":"/var/lib/clickhouse","source":"/demo/data/t361-fresh-clickhouse"}]}
    return {"services":services}

class FreshLineageTest(unittest.TestCase):
    def setUp(self):
        self.dir=TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.order=Path(self.dir.name)/"order.properties"
        self.trade=Path(self.dir.name)/"trade.properties"
        for path,prefix in ((self.order,"order"),(self.trade,"trade")):
            path.write_text(
                f"{prefix}.common.control.manifestPath=/otc/prior-signed/{prefix}/manifest\n"
                f"{prefix}.common.nodeRuntime.freshE1.namespace=/otc/prior-signed/{prefix}\n"
            )
    def test_reused_signed_E2_cannot_authorize_new_empty_WAL(self):
        report=m.audit(config(),self.order,self.trade)
        self.assertEqual(set(report),{"OrderSvr","TradeSvr"})
        self.assertTrue(all(not v["ready"] for v in report.values()))
        self.assertTrue(all(v["reason"]=="FRESH_WAL_REUSES_PRIOR_ZK_EPOCH_WITHOUT_CERTIFIED_CHECKPOINT"
                            for v in report.values()))
    def test_unisolated_A_B_fails_closed(self):
        c=config()
        c["services"]["ordersvr-b"]["environment"]=c["services"]["ordersvr"]["environment"]
        with self.assertRaisesRegex(ValueError,"roots not isolated"):
            m.audit(c,self.order,self.trade)
    def test_wrong_read_only_birth_fails_closed(self):
        c=config()
        c["services"]["tradesvr"]["volumes"][0]["read_only"]=False
        with self.assertRaisesRegex(ValueError,"must be read-only"):
            m.audit(c,self.order,self.trade)
    def test_missing_DB_isolation_fails_closed(self):
        c=config()
        c["services"]["mysql"]["volumes"][0]["source"]="/demo/old-mysql"
        with self.assertRaisesRegex(ValueError,"volume isolation"):
            m.audit(c,self.order,self.trade)
    def test_conflicting_original_manifest_namespace_fails_closed(self):
        self.order.write_text(
            "order.common.control.manifestPath=/otc/another/order/manifest\n"
            "order.common.nodeRuntime.freshE1.namespace=/otc/prior-signed/order\n"
        )
        with self.assertRaisesRegex(ValueError,"lineage inconsistent"):
            m.audit(config(),self.order,self.trade)

if __name__=="__main__":
    unittest.main()
