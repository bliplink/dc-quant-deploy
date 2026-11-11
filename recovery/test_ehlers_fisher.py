"""Export/freeze/preflight controls; positive synthetic tests are not financial qualification."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from recovery import export_ehlers_fisher_candidate as export
from recovery import verify_ehlers_fisher as verify
from recovery.verify_fit_only_risk_contract import sha

TEMPLATE = '''package com.app.dc.service.strategy.research;
public class EhlersFisherStrategy extends LegacyLiveSignalAdapter {
private static final String STRATEGY_NAME = "research_ehlers_fisher";
private static final String SYMBOL = "BTCUSDT";
private static final int ENTRY_SIDE = 1;
// shared algorithm body is deliberately never rewritten by the scoped exporter
}
'''


class EhlersFisherControlTest(unittest.TestCase):
    def policy(self):
        return json.loads(Path(export.__file__).with_name('strategy_research_ehlers_fisher_protocol_20261111.json').read_text())

    def test_all_one_hundred_scopes_are_unique_but_one_family(self):
        names=set();groups=set()
        for symbol in ('ADAUSDT','BNBUSDT','BTCUSDT','DOGEUSDT','ETHUSDT','LINKUSDT','SOLUSDT','TRXUSDT','UNIUSDT','XRPUSDT'):
            for scene in ('trend','range','channel','breakout','reversal'):
                for side in export.VARIANTS:
                    source,item,row=export.frozen_source(TEMPLATE,symbol,scene,side)
                    names.add(item['strategyName']);groups.add(row['mechanism_group'])
                    self.assertEqual('ef1_recursive_fisher_'+('long' if side>0 else 'short'),row['hypothesis'])
                    self.assertIn('private static final int ENTRY_SIDE = '+str(side)+';',source)
        self.assertEqual(100,len(names));self.assertEqual({'ehlers_recursive_fisher_reversal'},groups)

    def test_scope_and_direction_cannot_inject_java_or_silently_default(self):
        for symbol,scene,side in [('BTC/USDT','trend',1),('BTCUSDT','unknown',1),('BTCUSDT','trend',True),('BTCUSDT','trend',0)]:
            with self.assertRaises(ValueError):export.frozen_source(TEMPLATE,symbol,scene,side)

    def test_export_preserves_body_bytes_and_only_declared_identity_fields_change(self):
        source,item,row=export.frozen_source(TEMPLATE,'ETHUSDT','range',-1)
        self.assertIn('// shared algorithm body is deliberately never rewritten by the scoped exporter',source)
        self.assertIn('public class GeneratedStrategy extends LegacyLiveSignalAdapter',source)
        self.assertEqual({},item['request']['parameterSchema']);self.assertEqual({},item['request']['defaultParameters'])
        self.assertEqual(.20,item['request']['optimizationProfile']['minForwardContribution'])

    def test_missing_or_duplicated_identity_placeholder_is_rejected(self):
        with self.assertRaises(ValueError):export.frozen_source(TEMPLATE.replace('ENTRY_SIDE','RENAMED'),'BTCUSDT','trend',1)
        with self.assertRaises(ValueError):export.frozen_source(TEMPLATE+TEMPLATE,'BTCUSDT','trend',1)

    def test_crlf_input_normalizes_to_same_exported_source(self):
        self.assertEqual(export.frozen_source(TEMPLATE,'BTCUSDT','trend',1),
            export.frozen_source(TEMPLATE.replace('\n','\r\n'),'BTCUSDT','trend',1))

    def fixture(self,root):
        native=export.source_file(root/'native');native.parent.mkdir(parents=True);native.write_text(TEMPLATE,encoding='utf-8')
        return root/'native',root/'frozen'

    def test_repeated_export_reuses_identical_frozen_bytes_not_a_new_version(self):
        with tempfile.TemporaryDirectory() as temp:
            native,output=self.fixture(Path(temp));first=export.export_candidate(native,output,'BTCUSDT','trend',1)
            before=sha(first[0]/'GeneratedStrategy.java')
            self.assertEqual(first,export.export_candidate(native,output,'BTCUSDT','trend',1))
            self.assertEqual(before,sha(first[0]/'GeneratedStrategy.java'))

    def test_changed_frozen_source_or_seed_is_never_overwritten(self):
        for name in ('GeneratedStrategy.java','seed.json'):
            with tempfile.TemporaryDirectory() as temp:
                native,output=self.fixture(Path(temp));folder,_,_=export.export_candidate(native,output,'BTCUSDT','trend',1)
                (folder/name).write_text('tampered',encoding='utf-8')
                with self.assertRaises((ValueError,json.JSONDecodeError)):export.export_candidate(native,output,'BTCUSDT','trend',1)
                self.assertEqual('tampered',(folder/name).read_text())

    def test_predeclared_risk_and_temporal_separation_are_not_relaxed(self):
        p=self.policy();d=p['fixed_source_defaults']
        self.assertEqual((20,160,180,200),(d['normalizationPeriod'],d['recursiveObservations'],d['warmupBars'],d['maximumVisibleBars']))
        self.assertEqual('0.20',p['minimum_forward_contribution']);self.assertEqual('2025-10-12',p['primary_end_inclusive'])
        self.assertEqual('2025-10-13',p['holdout_begin']);self.assertEqual(62,p['minimum_holdout_calendar_days'])
        self.assertEqual(0,p['holdout_optimizer_invocations']);self.assertEqual({},p['holdout_locked_parameters'])
        self.assertFalse(p['server_codegen_allowed']);self.assertFalse(p['production_write'])

    def test_real_preflight_rejects_altered_policy_before_compilation_or_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);training=root/'training';training.mkdir();bars=training/'BTCUSDT-15m.tsv';bars.write_text('synthetic')
            (training/'READY.json').write_text(json.dumps(dict(purpose='training_only',train_end_exclusive='2024-12-15',
                files={'BTCUSDT':{'bars_sha256':sha(bars)}})))
            altered=copy.deepcopy(self.policy());altered['fixed_source_defaults']['normalizationPeriod']=21
            policy=root/'policy.json';policy.write_text(json.dumps(altered));out=root/'result'
            argv=['verify','--indsvr-repo',str(root/'native'),'--reference-indsvr-repo',str(root/'reference'),
                '--sim-repo',str(root/'sim'),'--training-input-dir',str(training),'--protocol',str(policy),'--output-dir',str(out)]
            with patch('sys.argv',argv),patch.object(verify,'execute') as execute:
                with self.assertRaisesRegex(ValueError,'predeclared'):verify.main()
                execute.assert_not_called()
            self.assertFalse(out.exists())


if __name__=='__main__':unittest.main()
