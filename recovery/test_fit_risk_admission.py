import copy
import json
import tempfile
import unittest
from pathlib import Path

from recovery.run_fit_risk_admission import compare_primary_validation, require_proof, validation_passes
from recovery.verify_fit_only_risk_contract import sha


class FitRiskAdmissionTest(unittest.TestCase):
    def screen(self):
        return {'tradeCount': 20, 'profitFactor': 1.2, 'maxDrawdownPct': .15,
            'feeAdjustedValidatePnl': .01, 'forwardMetrics': 'WITHHELD', 'fullPeriodSafety': 'WITHHELD',
            'selectedParameters': {'riskProfile': 2}, 'sliceResults': [{'validateTrades': [{'pnl': 1}]}]}

    def test_validation_screen_keeps_original_necessary_gates(self):
        result = self.screen()
        self.assertTrue(validation_passes(result))
        for key, value in [('tradeCount', 19), ('profitFactor', 1.199999),
                           ('maxDrawdownPct', .150001), ('feeAdjustedValidatePnl', 0)]:
            self.assertFalse(validation_passes(dict(result, **{key: value})))
        for value in (None, True, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                validation_passes(dict(result, profitFactor=value))
        with self.assertRaisesRegex(ValueError, 'withheld'):
            validation_passes(dict(result, forwardMetrics=1))

    def test_primary_cannot_change_representative_or_any_validation_trade(self):
        screen = self.screen()
        primary = {'selectedParameters': {'riskProfile': 2}, 'result': {key: screen[key] for key in
            ('tradeCount', 'profitFactor', 'maxDrawdownPct', 'feeAdjustedValidatePnl')}}
        primary['result']['tradeList'] = [{'pnl': 1}]
        compare_primary_validation(screen, primary)
        changed = copy.deepcopy(primary)
        changed['selectedParameters']['riskProfile'] = 1
        with self.assertRaisesRegex(ValueError, 'representative'):
            compare_primary_validation(screen, changed)
        changed = copy.deepcopy(primary)
        changed['result']['tradeList'][0]['pnl'] = 1.000001
        with self.assertRaisesRegex(ValueError, 'trades'):
            compare_primary_validation(screen, changed)

    def test_proof_requires_all_nine_cases_and_exact_engine_and_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            java, sim, proof = root / 'java', root / 'sim', root / 'proof'
            java.mkdir()
            proof.mkdir()
            (java / 'Helper.java').write_text('frozen', encoding='utf-8')
            engine = sim / 'target/classes/com/app/dc/service/simulation/runtime/Engine.class'
            engine.parent.mkdir(parents=True)
            engine.write_bytes(b'engine')
            properties = sim / 'config/application.properties'
            properties.parent.mkdir()
            properties.write_bytes(b'unchanged')
            manifest = {'java_source_sha256': {'Helper.java': sha(java / 'Helper.java')},
                'formal_class_sha256': {'runtime/Engine.class': sha(engine)},
                'execution_properties_sha256': sha(properties)}
            (proof / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            audit = {'state': 'complete', 'cases': 9, 'manifest_sha256': sha(proof / 'manifest.json'),
                'production_write': False, 'new_holdout_read': False}
            (proof / 'audit.json').write_text(json.dumps(audit), encoding='utf-8')
            passed = {'passed': True, 'trades': 1, 'exactValidationTradesAndFitChoices': True,
                'forwardFenceRejected': True, 'firstFitFuturePerturbationInvariant': True,
                'productionWrite': False, 'newHoldoutRead': False}
            for family in range(3):
                for scene in range(3):
                    folder = proof / 'cases' / str(family) / str(scene)
                    folder.mkdir(parents=True)
                    (folder / 'result.json').write_text(json.dumps(passed), encoding='utf-8')
            require_proof(proof, java, sim)
            engine.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'bytecode'):
                require_proof(proof, java, sim)
            engine.write_bytes(b'engine')
            (proof / 'cases/0/0/result.json').write_text(json.dumps(dict(passed, trades=0)), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                require_proof(proof, java, sim)


if __name__ == '__main__':
    unittest.main()
