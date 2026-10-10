"""Fail-closed quarantine purge proofs: synthetic temp files, mocked Docker."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('purge_old_mac_saas',Path(__file__).resolve().parents[1]/'scripts/mac-saas-purge-quarantine.py')
mod=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(mod)

class FakeHttp:
    status=200
    def __enter__(self):return self
    def __exit__(self,*_):return False

class PurgeGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        top=self.home/'.opentradingcore';top.mkdir()
        parent=top/'.dc-saas-quarantine';parent.mkdir()
        self.old=parent/'dc-saas-runtime-fresh2-20261005-20261010T064806Z';self.old.mkdir()
        self.fresh=top/'dc-saas-runtime-clean-20261010';self.fresh.mkdir()
        for path in ('data','log','control','data/mysql','data/zookeeper'):
            (self.fresh/path).mkdir(exist_ok=True,parents=True)
        folder=top/'evidence'/'p246-reproducer-20261010';folder.mkdir(parents=True)
        self.proof=folder/'P246-primary-archived-commit.tar.gz';self.proof.write_bytes(b'independent-old-P246-evidence')
        self.real_sha=mod.PROOF_SHA256
        mod.PROOF_SHA256=hashlib.sha256(self.proof.read_bytes()).hexdigest()
        self.addCleanup(lambda:setattr(mod,'PROOF_SHA256',self.real_sha))
        names=['ordersvr','ordersvr-b','ordersvr-c','mysql','zookeeper','robotsvr','tradesvr','tradesvr-b','gateway','projectionsvr',
               'loginsvr','mdsvr','mdsvr-b','mdsvr-c','liqsvr','adminsvr','managersvr','apssvr','clickhouse','api-docs','web','platform-web','tenant-web','public-web']
        self.ids=['new-'+str(i) for i in range(len(names))]
        self.items=[]
        for i,n in enumerate(names):
            self.items.append({'Id':self.ids[i],'Name':'/dc-saas-'+n,
                'State':{'Running':True},
                'Config':{'Image':mod.EXPECTED.get(n,'fixed-unrelated-test-image'),
                          'Labels':{'com.docker.compose.project':'dc-saas','com.docker.compose.service':n}},
                'Mounts':[{'Type':'bind','Source':str(self.fresh/'data'), 'Destination':'/app/data'}]})
        self.docs={'Id':'independent-docs','Name':'/old-api-docs','Mounts':[],
                   'Config':{'Image':'docs:old','Labels':{}},'State':{'Running':False}}

    def fake_list(self,*args):
        if args[:2]==('ps','-q'):
            return list(self.ids)
        if args[:2]==('ps','-aq'):
            return self.ids+['independent-docs']
        raise AssertionError('unexpected Docker listing')

    def fake_json(self,*args):
        if args[0]!='inspect':raise AssertionError('unexpected Docker inspection')
        return [x for x in self.items+[self.docs] if x['Id'] in args[1:]]

    def validate(self):
        with patch.object(mod,'docker_list',side_effect=self.fake_list),\
             patch.object(mod,'docker_json',side_effect=self.fake_json),\
             patch.object(mod.urllib.request,'urlopen',return_value=FakeHttp()):
            return mod.validate_running_stack(self.old,self.fresh)

    def test_valid_new_stack_and_backup_path(self):
        old,new,proof=mod.prove_paths(self.home,self.old,self.fresh,self.proof)
        self.assertEqual(old,self.old.resolve())
        self.assertEqual(new,self.fresh.resolve())
        mod.confirm_proof(proof)
        report=self.validate()
        self.assertEqual(24,report['newComposeServices'])
        self.assertEqual(6,report['validatedImagePins'])
        self.assertEqual([18088,18090,18092,18094],report['freshHttpHealthyPorts'])
        self.assertTrue(self.old.exists())

    def test_unexpected_root_or_symlink_cannot_purge(self):
        wrong=self.home/'dc-saas-runtime-outside';wrong.mkdir()
        with self.assertRaisesRegex(ValueError,'exact staged'):
            mod.prove_paths(self.home,wrong,self.fresh,self.proof)
        alias=self.old.parent/'dc-saas-runtime-fresh2-20261005-20261010T070000Z'
        alias.symlink_to(self.old,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink'):
            mod.prove_paths(self.home,alias,self.fresh,self.proof)

    def test_bad_proof_fails_closed(self):
        self.proof.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'mismatch'):
            mod.confirm_proof(self.proof)

    def test_missing_running_member_refuses(self):
        self.ids.pop()
        with self.assertRaisesRegex(ValueError,'incomplete'):
            self.validate()

    def test_unexpected_new_image_refuses(self):
        self.items[0]['Config']['Image']='ordersvr:unreviewed'
        with self.assertRaisesRegex(ValueError,'unreviewed image'):
            self.validate()

    def test_quarantine_still_mounted_by_any_container_refuses(self):
        self.docs['Mounts']=[{'Type':'bind','Source':str(self.old/'data'), 'Destination':'/old'}]
        with self.assertRaisesRegex(ValueError,'referenced by Docker'):
            self.validate()

    def test_fresh_must_be_current_bind_mount(self):
        for entry in self.items:
            if entry['Config']['Labels']['com.docker.compose.service']=='zookeeper':
                entry['Mounts']=[]
        with self.assertRaisesRegex(ValueError,'not mounted on new runtime'):
            self.validate()

    def test_http_failure_refuses(self):
        class NotOK(FakeHttp):status=503
        with patch.object(mod,'docker_list',side_effect=self.fake_list),\
             patch.object(mod,'docker_json',side_effect=self.fake_json),\
             patch.object(mod.urllib.request,'urlopen',return_value=NotOK()):
            with self.assertRaisesRegex(ValueError,'endpoint unavailable'):
                mod.validate_running_stack(self.old,self.fresh)

if __name__=='__main__':unittest.main()
