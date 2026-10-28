#!/usr/bin/env python3
"""Static regression: Common's certified persistence interface cannot depend on business types.

This only tests a necessary architectural property, not HA/E2E behavior.
"""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
COMMON=Path("/Users/kong/.opentradingcore/t177-common-saas-crypto-integration-20261027/src/main/java/com/app/common/replication")
ORDER=ROOT/".work/ordersvr/src/main/java/com/app/dc/service/state/OrderStateJournal.java"
TRADE=ROOT/".work/tradesvr/src/main/java/com/app/dc/service/state/TradeStateCoordinator.java"

class BusinessNeutralCommonTest(unittest.TestCase):
    def test_common_partition_writer_takes_callback_not_order_type(self):
        r=COMMON/"CertifiedBusinessCommandRegistry.java"
        if not r.is_file():
            self.skipTest("Common workspace not mounted in this environment")
        source=r.read_text()
        self.assertIn("commitThenApply(",source)
        self.assertIn("CertifiedBusinessCommandBoundary.CommandEncoder",source)
        self.assertIn("CertifiedBusinessCommandBoundary.StateApplier",source)
        for forbidden in ("TimeInForce","OrderType","GTC","IOC","FOK","PostOnly","ACCOUNT_BALANCE","POSITION","com.app.dc."):
            self.assertNotIn(forbidden,source,forbidden)

    def test_business_services_use_same_opaque_common_commit_boundary(self):
        for filename in (ORDER,TRADE):
            if not filename.is_file():
                self.skipTest("business service workspace not mounted")
            source=filename.read_text()
            self.assertIn("CertifiedBusinessCommandRegistry",source)
            self.assertIn("commitThenApply(",source)
            self.assertIn("encode().getBytes(StandardCharsets.UTF_8)",source)

    def test_matching_type_policy_remains_business_owned(self):
        source=(ROOT/".work/ordersvr/src/main/java/com/app/dc/service/strategy/CrossStrategy.java").read_text()
        self.assertIn("isRestingTimeInForce",source)
        self.assertIn("TimeInForce.PO",source)
        self.assertIn("TimeInForce.GFD",source)

if __name__=="__main__":
    unittest.main()
