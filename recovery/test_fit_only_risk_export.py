import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from recovery.export_representative_candidate import candidate_source, export_candidate


SOURCE = '''public class Research {
    interface Hypothesis { int warmupBars(); }
    interface RiskProfileHypothesis extends Hypothesis { Hypothesis withRiskProfile(int profile); }
    static final class FitOnlyRiskExample implements RiskProfileHypothesis {
        FitOnlyRiskExample(String name, double baseStopMultiplier, double baseTakeMultiplier, int riskProfile) { }
    }
    static Setup atrSetup(double entry, double atr, int side, double stopMultiplier, double takeMultiplier) { return null; }
    static final class Setup { static final int EXIT_POLICY_SCHEMA_VERSION = 1; }
    static final class ResearchResult { }
}'''
ROW = {'hypothesis': 'fr1_fixed', 'family': 'FitOnlyRiskExample',
       'parameters': '{"baseStopMultiplier":1.5,"baseTakeMultiplier":3.0,"riskProfile":0}'}


class FitOnlyRiskExportTest(unittest.TestCase):
    def test_runtime_profile_uses_adapter_parameter_contract_and_raw_constructor(self):
        source = candidate_source(SOURCE, ROW, 'BTCUSDT', 'frozen_risk')
        self.assertIn('paramInt("riskProfile", 0)', source)
        self.assertIn('paramValue("riskProfile")', source)
        self.assertIn('((Number) configuredRiskProfile).doubleValue() != riskProfile', source)
        self.assertIn('withRiskProfile(riskProfile)', source)
        self.assertIn('new FitOnlyRiskExample("fr1_fixed", 1.5, 3.0, 0)', source)
        self.assertIn('interface RiskProfileHypothesis', source)
        self.assertIn('Setup setup = selected.setup', source)

    def test_nonzero_catalog_profile_cannot_be_reexported_and_scaled_twice(self):
        for profile in (1, 2, 3):
            parameters = json.loads(ROW['parameters'])
            parameters['riskProfile'] = profile
            with self.assertRaisesRegex(ValueError, 'profile zero'):
                candidate_source(SOURCE, {**ROW, 'parameters': json.dumps(parameters)}, 'BTCUSDT', 'frozen_risk')

    def test_export_preserves_exact_four_joint_coarse_only_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            research = root / 'ind/src/test/java/com/app/dc/service/strategy/research/StrategyResearchBatchCli.java'
            research.parent.mkdir(parents=True)
            research.write_text(SOURCE, encoding='utf-8')
            campaign = root / 'campaign'
            campaign.mkdir()
            manifest = {'catalog': [ROW], 'source_sha256': {
                'StrategyResearchBatchCli': hashlib.sha256(research.read_bytes()).hexdigest()}}
            (campaign / 'campaign.json').write_text(json.dumps(manifest), encoding='utf-8')
            output, _ = export_candidate(campaign, root / 'ind', root / 'output',
                                         'BTCUSDT', 'range', ROW['hypothesis'])
            request = json.loads((output / 'seed.json').read_text(encoding='utf-8'))['strategies'][0]['request']
            self.assertEqual({'riskProfile': 0}, request['defaultParameters'])
            self.assertEqual([{'name': 'riskProfile', 'type': 'int', 'default': 0,
                               'candidates': [0, 1, 2, 3]}], request['parameterSchema']['parameters'])
            profile = request['optimizationProfile']
            self.assertEqual('FEE_ADJUSTED_PROFIT_FIRST', profile['objective'])
            self.assertEqual(['riskProfile'], profile['coarseOnlyParams'])
            self.assertEqual((4, 4, 1), (profile['maxFullGrid'], profile['maxCoarseCandidates'], profile['topN']))


if __name__ == '__main__':
    unittest.main()
