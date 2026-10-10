"""Cold reset proof tests: never access real Docker or Mac runtime."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('mac_reset',Path(__file__).resolve().parents[1]/'scripts/mac-saas-reset.py')
mod=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

class MacResetSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        self.top=self.home/'.opentradingcore';self.top.mkdir()
        self.root=self.top/'dc-saas-runtime-demo';self.root.mkdir()
        for child in ['data','log','control','e2e-artifacts']:
            (self.root/child).mkdir()
        folder=self.top/'evidence'/'p246-reproducer-20261010';folder.mkdir(parents=True)
        self.proof=folder/mod.PROOF_FILE;self.proof.write_bytes(b'example-old-WAL-archive')
        self.original_proof_sha=mod.PROOF_SHA256
        mod.PROOF_SHA256=hashlib.sha256(self.proof.read_bytes()).hexdigest()
        self.addCleanup(lambda:setattr(mod,'PROOF_SHA256',self.original_proof_sha))
        self.ids=['test-'+str(i) for i in range(10)]
        names=['ordersvr','ordersvr-b','ordersvr-c','mysql','zookeeper','gateway','tradesvr','tradesvr-b','projectionsvr','robotsvr']
        self.members=[]
        for i,service in enumerate(names):
            self.members.append({'Id':self.ids[i],'Name':'/dc-saas-'+service,
                'Config':{'Labels':{'com.docker.compose.project':'dc-saas',
                                     'com.docker.compose.service':service}},
                'Mounts':[{'Type':'bind','Source':str(self.root/'data'), 'Destination':'/srv/data'}],
                'State':{'Running':False}})
        self.runner={'Id':'test-runner','Name':'/dc-saas-web-e2e-runner',
            'Config':{'Labels':{},'Image':'mcr.microsoft.com/playwright:v1.55.0-noble'},
            'Mounts':[{'Type':'bind','Source':str(self.root/'e2e-artifacts'),
                       'Destination':'/artifacts'}], 'State':{'Running':False}}
        self.calls=[]

    def fake_docker(self,*args,stdin=None):
        self.calls.append(args)
        if args[:2]==('ps','-aq'):
            if len(args)==2:return '\n'.join(self.ids+['test-runner'])
            return '\n'.join(self.ids)
        if args[0]=='inspect':
            objects=self.members+[self.runner]
            return json.dumps([v for v in objects if v['Id'] in args[1:]])
        if args[0] in ('stop','rm'):
            return 'success'
        raise AssertionError('unexpected Docker action '+str(args))

    def test_fixed_proof_and_namespace_accepted(self):
        runtime,witness,top=mod.safe_roots(self.home,self.root,self.proof)
        self.assertEqual(runtime,self.root.resolve())
        self.assertEqual(witness,self.proof.resolve())
        self.assertEqual(top,self.top.resolve())
        self.assertEqual(mod.PROOF_SHA256,mod.verify_evidence(self.proof))

    def test_wrong_proof_denied(self):
        self.proof.write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError,'mismatch'):
            mod.verify_evidence(self.proof)

    def test_symlink_and_outside_runtime_denied(self):
        alias=self.top/'dc-saas-runtime-other';alias.symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink'):
            mod.safe_roots(self.home,alias,self.proof)
        outsider=self.home/'dc-saas-runtime-elsewhere';outsider.mkdir()
        for x in ('data','log','control'):(outsider/x).mkdir()
        with self.assertRaisesRegex(ValueError,'immediate'):
            mod.safe_roots(self.home,outsider,self.proof)

    def test_evidence_inside_runtime_denied(self):
        unsafe=self.root/'e2e-artifacts'/mod.PROOF_FILE
        unsafe.write_bytes(b'not-the-real-evidence')
        with self.assertRaisesRegex(ValueError,'outside disposable'):
            mod.safe_roots(self.home,self.root,unsafe)

    def test_project_and_exact_test_runner_detected(self):
        with patch.object(mod,'docker',side_effect=self.fake_docker):
            ids,services,runners=mod.discover_project(self.root)
        self.assertEqual(self.ids,ids)
        self.assertEqual(10,len(services))
        self.assertEqual(['test-runner'],runners)
        self.assertFalse(any(x[0] in ('stop','rm') for x in self.calls))

    def test_foreign_shared_runtime_is_denied(self):
        self.runner['Name']='/foreign-database-service'
        with patch.object(mod,'docker',side_effect=self.fake_docker):
            with self.assertRaisesRegex(ValueError,'unknown non-project'):
                mod.discover_project(self.root)

    def test_unexpected_runner_mount_denied(self):
        self.runner['Mounts'][0]['Source']=str(self.root/'data'/'mysql')
        with patch.object(mod,'docker',side_effect=self.fake_docker):
            with self.assertRaisesRegex(ValueError,'unknown non-project'):
                mod.discover_project(self.root)

    def test_missing_replica_denied(self):
        self.members=self.members[:-1]
        self.ids=self.ids[:-1]
        with patch.object(mod,'docker',side_effect=self.fake_docker):
            with self.assertRaisesRegex(ValueError,'required full-HA'):
                mod.discover_project(self.root)

    def test_stage_stops_only_scope_then_quarantines_without_purging(self):
        quarantine_parent=self.top/'.dc-saas-quarantine'
        quarantine=quarantine_parent/(self.root.name+'-test')
        with patch.object(mod,'docker',side_effect=self.fake_docker):
            self.assertEqual(0,mod.stage(self.root,self.proof,mod.PROOF_SHA256,quarantine_parent,quarantine))
        self.assertFalse(self.root.exists())
        self.assertTrue(quarantine.is_dir())
        self.assertTrue(self.proof.is_file())
        commands=[x[0] for x in self.calls if x[0] in ('stop','rm')]
        self.assertEqual(['stop','stop','rm','rm'],commands)
        self.assertFalse(any(x[0]=='rmi' for x in self.calls))

    def test_plan_does_not_allow_delete_or_claim_backups(self):
        report=mod.build_plan(self.root,mod.PROOF_SHA256,self.ids,['ordersvr'],
                              self.top/'.dc-saas-quarantine'/'sample',['test-runner'])
        self.assertEqual('READ_ONLY',report['mode'])
        self.assertFalse(report['oldDataPurged'])
        self.assertTrue(report['evidenceRetained'])
        self.assertEqual(1,report['disposableTestRunnerCount'])

if __name__=='__main__':unittest.main()
