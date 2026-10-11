"""Shadow audit never grants MD publication or skips missing/gapped markets."""
import datetime as dt
import importlib.util
from pathlib import Path
import sys
import unittest

PATH=Path(__file__).resolve().parents[1]/"scripts/check-md-recovery-shadow.py"
SPEC=importlib.util.spec_from_file_location("otc_md_shadow", PATH)
gate=importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name]=gate
SPEC.loader.exec_module(gate)

TZ=dt.timezone(dt.timedelta(hours=8))
NOW=dt.datetime(2026,10,12,6,35,0,tzinfo=TZ)


def sample(offset, tracked=10, fresh=10, stale=0, gaps=0, events=0):
    at=NOW-dt.timedelta(seconds=offset)
    return ("%s INFO MD_RECOVERY_SHADOW_OBSERVATION "
            "trackedMarkets=%d, contiguous=%d, stale=%d, gapMarkets=%d, "
            "gapEvents=%d, promotionAuthorized=false (DepthBookFacade:135)" % (
                at.strftime("%Y/%m/%d %H:%M:%S.")+"%03d"%(at.microsecond//1000),
                tracked, fresh, stale, gaps, events))


class ShadowGateTests(unittest.TestCase):
    def check(self, lines):
        return gate.evaluate("\n".join(lines),10,now=NOW)

    def test_two_consecutive_complete_no_gap_are_observational_only(self):
        result=self.check([sample(55),sample(25)])
        self.assertEqual("PASS_LOCAL_OBSERVATION_ONLY",result["decision"])
        self.assertFalse(result["promotionAuthorized"])
        self.assertFalse(result["canInjectMdPrimaryFault"])
        self.assertFalse(result["hasSignedOrderDurableHead"])
        self.assertFalse(result["hasGatewayOldPublisherFence"])

    def test_latest_sample_must_be_complete_even_if_prior_passed(self):
        result=self.check([sample(85),sample(55),sample(25,fresh=9,stale=1)])
        self.assertEqual("BLOCKED",result["decision"])
        self.assertEqual(2,len(result["samples"]))
        self.assertIn("STALE_OR_GAPPED_MARKETS_2",result["blockers"])

    def test_explicit_source_gap_is_blocked(self):
        result=self.check([sample(55),sample(25,fresh=9,gaps=1,events=1)])
        self.assertEqual("BLOCKED",result["decision"])
        self.assertIn("STALE_OR_GAPPED_MARKETS_2",result["blockers"])

    def test_one_sample_or_wrong_count_refuses(self):
        self.assertEqual("BLOCKED",self.check([sample(25)])["decision"])
        self.assertEqual("BLOCKED",self.check([sample(55,tracked=9,fresh=9),
                                                 sample(25)])["decision"])

    def test_expired_future_or_burst_samples_refuse(self):
        self.assertEqual("BLOCKED",self.check([sample(300),sample(25)])["decision"])
        self.assertEqual("BLOCKED",self.check([sample(55),sample(-10)])["decision"])
        self.assertEqual("BLOCKED",self.check([sample(30),sample(25)])["decision"])

    def test_forged_promotion_true_is_not_parsed_as_valid(self):
        forged=sample(55).replace("promotionAuthorized=false",
                                  "promotionAuthorized=true")
        self.assertEqual("BLOCKED",self.check([forged,sample(25)])["decision"])


if __name__=="__main__":
    unittest.main()
