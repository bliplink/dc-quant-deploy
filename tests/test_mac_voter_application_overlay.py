import ast
import copy
import json
from pathlib import Path
import re
import unittest


TREE=ast.parse((Path(__file__).parents[1]/'scripts/roll-mac-demo-voter.py').read_text())
VERIFY=next(node for node in ast.walk(TREE) if isinstance(node,ast.FunctionDef) and node.name=='verify_overlay')


class OverlayTest(unittest.TestCase):
    def check(self,kind,labels,wrong_jar=False):
        def read(*args):
            if args[1:3]==('image','inspect'):
                return json.dumps([{'Config':{'Labels':labels}}])
            value='a'*64 if 'common' in args[-1] else 'b'*64
            return ('c'*64 if wrong_jar else value)+'  '+args[-1]
        context=dict(json=json,re=re,image='base-image',approved_overlays=set(),
                     kind=kind,svc='OrderSvr' if kind=='order' else 'TradeSvr',read=read,
                     image_meta={'common_sha256':'a'*64,'shared_sha256':'b'*64})
        exec(compile(ast.fix_missing_locations(ast.Module(body=[VERIFY],type_ignores=[])),
                     'actual-overlay-guard','exec'),context)
        context['verify_overlay']('candidate-image')

    def test_both_business_services_accept_their_exact_application_overlay(self):
        for kind in ('order','trade'):
            self.check(kind,{'dc.demo.recovery.base':'base-image',
                            f'dc.demo.recovery.{kind}.application.sha256':'d'*64})

    def test_wrong_service_label_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.check('trade',{'dc.demo.recovery.base':'base-image',
                               'dc.demo.recovery.order.application.sha256':'d'*64})

    def test_wrong_base_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.check('trade',{'dc.demo.recovery.base':'other-image',
                               'dc.demo.recovery.trade.application.sha256':'d'*64})

    def test_changed_common_or_shared_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.check('trade',{'dc.demo.recovery.base':'base-image',
                               'dc.demo.recovery.trade.application.sha256':'d'*64},True)


class LateLocalCensusTest(unittest.TestCase):
    def context(self):
        context=dict(svc='TradeSvr',peer='B',slot='A',survivor_lease=12345,
                     client_ack_policy='STRICT_QUORUM')
        helpers=[node for node in ast.walk(TREE) if isinstance(node,ast.FunctionDef)
                 and node.name in ('ready','home')]
        exec(compile(ast.fix_missing_locations(ast.Module(body=helpers,type_ignores=[])),
                     'actual-census-helpers','exec'),context)
        original={}
        for index in range(256):
            slot='A' if index<128 else 'B'
            original[f'P{index:03d}']=dict(state='READY',primary='TradeSvr'+slot,
                replica='TradeSvr'+('B' if slot=='A' else 'A'),policy='STRICT_QUORUM',epoch=4)
        live={partition:dict(state='READY',primary='TradeSvrB',replica='TradeSvrA',
                            policy='LOCAL_DURABLE_ASYNC',epoch=5) for partition in original}
        metadata=dict(generation='same-generation',service='TradeSvr',slot='A',
                      fault='term',common_sha256='a'*64,survivor_id='same-physical-node',survivor_lease=12345)
        context.update(record=dict(metadata),prior=dict(metadata,stage='failed',status='NO_GO'),
                       saved_initial=original,initial=live,saved_local=copy.deepcopy(live))
        return context

    def rejected(self,context):
        guard=next(node for node in ast.walk(TREE) if isinstance(node,ast.If)
                   and 'saved_initial.keys' in ast.unparse(node.test)
                   and 'survivor_lease' in ast.unparse(node.test))
        return eval(compile(ast.Expression(guard.test),'actual-resume-census-guard','eval'),context)

    def test_exact_complete_witnessed_local_census_is_admissible(self):
        self.assertFalse(self.rejected(self.context()))

    def test_client_ack_mode_changes_are_rejected_and_legacy_strict_is_supported(self):
        context=self.context()
        context['client_ack_policy']='LOCAL_DURABLE_ASYNC'
        self.assertTrue(self.rejected(context))
        context['prior']['client_ack_policy']='LOCAL_DURABLE_ASYNC'
        self.assertFalse(self.rejected(context))

    def test_partial_or_wrong_epoch_census_is_rejected(self):
        for field,value in [('state','RECOVERING'),('epoch',4),('policy','STRICT_QUORUM')]:
            context=self.context()
            context['saved_local']['P008'][field]=value
            self.assertTrue(self.rejected(context))

    def test_changed_survivor_session_or_missing_partition_is_rejected(self):
        context=self.context()
        context['prior']['survivor_lease']=99999
        self.assertTrue(self.rejected(context))
        context=self.context()
        del context['initial']['P008']
        self.assertTrue(self.rejected(context))


if __name__=='__main__':unittest.main()
