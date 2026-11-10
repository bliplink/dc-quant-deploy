"""Guarded local scheduling tests use synthetic records, never financial qualification evidence."""
from argparse import Namespace
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from recovery import run_runs_profile_slot as slot
from recovery import run_runs_clustering_batch as financial
from recovery import run_ohlcv_profile_proxy_batch as original_case
from recovery.verify_fit_only_risk_contract import sha


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')


class RunsProfileSlotTest(unittest.TestCase):
    def waiter(self,root):
        folder=root/'strategy-runs-clustering-original';folder.mkdir()
        command=['python','-u','-m',slot.WAIT_MODULE]
        for key in slot.PATHS:command+=['--'+key,str(root/key)]
        command+=['--output-dir',str(folder),'--engineering-manifest-sha256','engineering']
        manifest=dict(schema='frozen_runs_clustering_100_scopes_v1',
            queue=[dict(strategy='s'+str(i)) for i in range(100)],verification={},
            parent_identity=dict(pid=90,create_time=90.5,command=['parent']))
        save(folder/'manifest.json',manifest)
        save(folder/'status.json',dict(state='WAITING_FOR_BOUND_CUSUM_BATCH',completed=0,total=100))
        owner=Mock();owner.pid=10;owner.create_time.return_value=10.5;owner.cmdline.return_value=command
        owner.status.return_value='running'
        return folder,manifest,command,owner

    def profile(self,root):
        folder=root/'profile';folder.mkdir()
        rows=[dict(strategy='p'+str(i),symbol='BTCUSDT',scene='range',side=1,mode=i%2,
            hypothesis='profile',family='Profile',mechanism_group='auction') for i in range(200)]
        save(folder/'manifest.json',dict(schema=slot.PROFILE_SCHEMA,queue=rows));digest=sha(folder/'manifest.json')
        save(folder/'FORMAL_COMPLETE.json',dict(manifest_sha256=digest,completed=200,local_formal_qualified=0,production_write=False))
        save(folder/'status.json',dict(completed=200,total=200,local_formal_qualified=0))
        for row in rows:save(folder/'candidates'/row['strategy']/'checkpoint.json',{})
        return folder,rows,dict(pid=20,create_time=20.5,command=['python','-m',slot.PROFILE_MODULE,'--output-dir',str(folder)],
            output_dir=str(folder),manifest_sha256=digest)

    def test_exact_commands_reject_wrong_module_output_or_duplicate_option(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder,_,command,_=self.waiter(root)
            args=slot.context(command,folder);self.assertEqual(root/'protocol',args.protocol)
            self.assertIsNone(args.parent_binding)
            with self.assertRaises(ValueError):slot.context(command+['--protocol','other'],folder)
            with self.assertRaises(ValueError):slot.context(command,root/'wrong')
            with self.assertRaises(ValueError):slot.exact_command(['python','-m','other','--output-dir',str(folder)],slot.WAIT_MODULE,folder)

    def test_zero_count_cannot_hide_started_source_helper_or_finance(self):
        for forbidden in ('classes','frozen','candidates','results.json','FAILED.json','FORMAL_COMPLETE.json'):
            with tempfile.TemporaryDirectory() as temp:
                folder,_,_,_=self.waiter(Path(temp));digest=sha(folder/'manifest.json')
                slot.zero_plan(folder,digest)
                if '.' in forbidden:save(folder/forbidden,{})
                else:(folder/forbidden).mkdir()
                with self.assertRaisesRegex(ValueError,'started'):slot.zero_plan(folder,digest)

    def test_idle_owner_requires_exact_creation_no_children_and_no_prior_suspension(self):
        with tempfile.TemporaryDirectory() as temp:
            folder,_,_,owner=self.waiter(Path(temp));digest=sha(folder/'manifest.json')
            with patch.object(slot.psutil,'Process',return_value=owner),patch.object(slot,'calculation_children',return_value=[]),patch.object(slot,'parent_alive',return_value=True):
                self.assertIs(owner,slot.observe_idle(folder,digest,10,10.5)[0])
                with self.assertRaisesRegex(ValueError,'reused'):slot.observe_idle(folder,digest,10,11)
                owner.status.return_value=slot.psutil.STATUS_STOPPED
                with self.assertRaisesRegex(ValueError,'suspended'):slot.observe_idle(folder,digest,10,10.5)
                slot.observe_idle(folder,digest,10,10.5,allow_paused=True)
            with patch.object(slot.psutil,'Process',return_value=owner),patch.object(slot,'calculation_children',return_value=[{'pid':30}]):
                with self.assertRaises(ValueError):slot.observe_idle(folder,digest,10,10.5,allow_paused=True)
            owner.terminate.assert_not_called()

    def test_parent_release_before_pause_defers_without_stopping_anything(self):
        with tempfile.TemporaryDirectory() as temp:
            folder,_,_,owner=self.waiter(Path(temp));digest=sha(folder/'manifest.json')
            with patch.object(slot.psutil,'Process',return_value=owner),patch.object(slot,'calculation_children',return_value=[]),patch.object(slot,'parent_alive',return_value=False):
                with self.assertRaisesRegex(ValueError,'may release'):slot.observe_idle(folder,digest,10,10.5)
            owner.terminate.assert_not_called()

    def test_profile_slot_cannot_be_replaced_while_exact_owner_still_lives(self):
        with tempfile.TemporaryDirectory() as temp:
            _,_,bound=self.profile(Path(temp))
            with patch.object(slot,'parent_alive',return_value=True),patch.object(slot.original,'completed_case') as checked:
                with self.assertRaisesRegex(ValueError,'exit naturally'):slot.profile_complete(bound)
                checked.assert_not_called()

    def test_profile_requires_all_two_hundred_scope_and_mode_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            folder,rows,bound=self.profile(Path(temp))
            with patch.object(slot,'parent_alive',return_value=False),patch.object(slot.original,'completed_case',
                    side_effect=lambda p,h:dict(rows[int(p.name[1:])],qualified=False)) as checked:
                audit=slot.profile_complete(bound)
                self.assertEqual(200,checked.call_count);self.assertEqual(200,len(audit['checkpoint_sha256']))
                self.assertEqual(0,audit['financial_observations_reexecuted'])
            with patch.object(slot,'parent_alive',return_value=False),patch.object(slot.original,'completed_case',return_value=dict(rows[0],mode=999,qualified=False)):
                with self.assertRaisesRegex(ValueError,'scope or mode'):slot.profile_complete(bound)

    def test_changed_profile_command_does_not_turn_a_live_pid_into_a_free_slot(self):
        with tempfile.TemporaryDirectory() as temp:
            _,_,bound=self.profile(Path(temp))
            with patch.object(slot,'parent_alive',return_value=False),patch.object(slot.psutil,'pid_exists',return_value=True),patch.object(slot.psutil,'Process') as process:
                process.return_value.create_time.return_value=bound['create_time']
                process.return_value.cmdline.return_value=['changed']
                with self.assertRaisesRegex(ValueError,'profile PID still lives'):slot.profile_complete(bound)

    def test_profile_disappearance_partial_marker_failure_or_false_qualification_never_frees_slot(self):
        for kind in ('missing','partial','failed','false_count'):
            with tempfile.TemporaryDirectory() as temp:
                folder,rows,bound=self.profile(Path(temp))
                if kind=='missing':(folder/'FORMAL_COMPLETE.json').unlink()
                if kind=='partial':save(folder/'status.json',dict(completed=199,total=200))
                if kind=='failed':save(folder/'FAILED.json',{})
                if kind=='false_count':save(folder/'status.json',dict(completed=200,total=200,local_formal_qualified=1))
                with patch.object(slot,'parent_alive',return_value=False),patch.object(slot.original,'completed_case',
                        side_effect=lambda p,h:dict(rows[int(p.name[1:])],qualified=False)):
                    with self.assertRaises((ValueError,FileNotFoundError)):slot.profile_complete(bound)

    def test_profile_live_binding_rejects_reused_pid_or_changed_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            folder,_,bound=self.profile(Path(temp));owner=Mock()
            owner.pid=20;owner.create_time.return_value=20.5;owner.cmdline.return_value=bound['command']
            with patch.object(slot.psutil,'Process',return_value=owner):
                self.assertEqual(bound,slot.bind_profile(folder,bound['manifest_sha256'],20,20.5))
                with self.assertRaisesRegex(ValueError,'reused'):slot.bind_profile(folder,bound['manifest_sha256'],20,21)
                with self.assertRaisesRegex(ValueError,'frozen'):slot.bind_profile(folder,'changed',20,20.5)

    def test_old_owner_stop_check_cannot_be_evaded_by_changing_its_command(self):
        bound=dict(pid=10,create_time=10.5,command=['old'])
        with patch.object(slot.psutil,'pid_exists',return_value=True),patch.object(slot.psutil,'Process') as process:
            process.return_value.create_time.return_value=10.5
            process.return_value.cmdline.return_value=['changed']
            with self.assertRaisesRegex(ValueError,'still lives'):slot.old_stopped(bound)
            process.return_value.create_time.return_value=99.5;slot.old_stopped(bound)

    def context_fixture(self,root):
        folder,manifest,command,_=self.waiter(root);old=root/'old-tools';old.mkdir()
        for name in ('run_runs_clustering_batch.py','run_ohlcv_profile_proxy_batch.py'):
            (old/name).write_bytes(Path(slot.__file__).with_name(name).read_bytes())
        before=dict(tool_sha256={str(p):sha(p) for p in old.glob('*.py')},source_sha256={},classes_sha256={},data_sha256={})
        manifest['verification']=before
        native=root/'native.java';native.write_text('original')
        fresh=copy.deepcopy(before);fresh['tool_sha256']={str(Path(slot.__file__)):sha(Path(slot.__file__))}
        return folder,manifest,command,old,native,fresh

    def test_source_context_keeps_all_old_bindings_and_full_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            folder,manifest,command,old,native,fresh=self.context_fixture(Path(temp))
            with patch.object(slot.original,'check_snapshot'),patch.object(slot.original,'verify_context',return_value=(fresh,{'symbols':['BTCUSDT']},{})),patch.object(slot.original,'source_file',return_value=native),patch.object(slot.original,'frozen_queue',return_value=manifest['queue']):
                _,proof,_,_=slot.source_context(command,folder,manifest)
                for path,digest in manifest['verification']['tool_sha256'].items():self.assertEqual(digest,proof['tool_sha256'][path])

    def test_source_context_rejects_byte_changed_dependency_or_even_new_original_python_member(self):
        with tempfile.TemporaryDirectory() as temp:
            folder,manifest,command,old,_,_=self.context_fixture(Path(temp))
            changed=old/'run_ohlcv_profile_proxy_batch.py';changed.write_bytes(b'changed')
            manifest['verification']['tool_sha256'][str(changed)]=sha(changed)
            with patch.object(slot.original,'check_snapshot'):
                with self.assertRaisesRegex(ValueError,'dependency differs'):slot.source_context(command,folder,manifest)
            (old/'unfrozen.py').write_text('extra')
            with patch.object(slot.original,'check_snapshot'):
                with self.assertRaisesRegex(ValueError,'membership changed'):slot.source_context(command,folder,manifest)

    def retirement_fixture(self,root):
        folder,manifest,command,owner=self.waiter(root);control=root/'control';control.mkdir()
        args=Namespace(original_wait_dir=folder,original_manifest_sha256=sha(folder/'manifest.json'),
            waiting_pid=10,waiting_create_time=10.5,output_dir=root/'strategy-runs-clustering-replacement',control_dir=control)
        prepared=dict(old_identity=dict(pid=10,create_time=10.5,command=command),profile_identity={})
        return args,prepared,owner,manifest

    def test_profile_failure_prevents_retirement_and_does_not_create_handoff_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            args,prepared,owner,manifest=self.retirement_fixture(Path(temp))
            with patch.object(slot,'observe_idle',return_value=(owner,manifest,{})),patch.object(slot,'profile_complete',side_effect=ValueError('partial')),patch.object(slot,'drain_and_stop') as stop:
                with self.assertRaisesRegex(ValueError,'partial'):slot.retire(args,prepared,{})
                stop.assert_not_called();self.assertFalse((args.original_wait_dir/'ORCHESTRATION_HANDOFF_CLAIM.json').exists())

    def test_guardian_transfer_callback_rechecks_suspended_zero_finance(self):
        with tempfile.TemporaryDirectory() as temp:
            args,prepared,owner,manifest=self.retirement_fixture(Path(temp))
            def stopped(bound,output,callback,timeout):return callback()
            with patch.object(slot,'observe_idle',side_effect=[(owner,manifest,{}),ValueError('work began')]),patch.object(slot,'profile_complete',return_value={}),patch.object(slot,'source_context',return_value=(None,{},None,None)),patch.object(slot,'drain_and_stop',side_effect=stopped):
                with self.assertRaisesRegex(ValueError,'work began'):slot.retire(args,prepared,{})
            self.assertFalse((args.original_wait_dir/'ORCHESTRATION_HANDOFF.json').exists());owner.terminate.assert_not_called()

    def test_dispatch_calls_unchanged_executor_once_for_entire_original_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            args,prepared,_,_=self.retirement_fixture(Path(temp));prepared['queue']=[dict(strategy='s'+str(i)) for i in range(100)]
            save(args.original_wait_dir/'ORCHESTRATION_HANDOFF.json',{})
            with patch.object(slot,'retire',return_value={}),patch.object(slot,'old_stopped'),patch.object(slot.original,'check_snapshot'),patch.object(slot.original,'run_finance') as executor:
                slot.dispatch(args,prepared,{}, {},{},Namespace())
                executor.assert_called_once()
                self.assertEqual(prepared['queue'],executor.call_args.args[1]['queue'])
                self.assertEqual(0,executor.call_args.args[1]['added_financial_slots'])
            self.assertIs(financial,slot.original);self.assertIs(original_case.run_case,slot.original.run_case)

    def test_existing_financial_root_is_never_replayed_or_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            args,prepared,_,_=self.retirement_fixture(Path(temp));args.output_dir.mkdir()
            with patch.object(slot,'drain_and_stop') as stop:
                with self.assertRaisesRegex(ValueError,'fresh financial'):slot.retire(args,prepared,{})
                stop.assert_not_called()


if __name__=='__main__':unittest.main()
