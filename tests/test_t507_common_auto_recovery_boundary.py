#!/usr/bin/env python3
"""T507 static negative tests: only Common owns physical HA, no fake GO."""
import importlib.util
import pathlib
import tempfile
import unittest

SCRIPT=pathlib.Path(__file__).with_name('check-certified-auto-recovery-wiring.py')
spec=importlib.util.spec_from_file_location('common_ha_audit_t507',SCRIPT)
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

class CommonOnlyAutoHA(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='otc-t507-')
        self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name)
        self.service=self.root/'order'/'src/main/java/com/app/dc/service/state'
        self.service.mkdir(parents=True)
        self.main=self.service/'OrderCommonNodeRuntimeWiring.java'
        self.main.write_text('''class OrderCommonNodeRuntimeWiring {
            CommonCertifiedNodeBootstrap.CertifiedPhysicalRecoveryPlanFactory bound;
            void start(){ CommonCertifiedNodeBootstrap.openAndStartWithCertifiedAutomaticRecoveryFromOpenedPhysical( ); }
        }''',encoding='utf-8')
    def check(self):
        return audit.check_service('OrderSvr',self.root/'order',self.main.name)
    def test_only_common_after_wal_entry_allowed(self):
        self.assertTrue(self.check()[0],self.check()[1])
    def test_service_specific_physical_proof_bean_forbidden(self):
        (self.service/'OrderLegacy.java').write_text('''class OrderLegacy {
            @Qualifier("orderCommonCertifiedPhysicalRecovery")
            CommonCertifiedAutomaticReplicaPlanWiring.DurablePhysicalRecovery fake;
        }''',encoding='utf-8')
        self.assertFalse(self.check()[0])
    def test_old_preopen_entry_forbidden(self):
        s=self.main.read_text().replace(
            'openAndStartWithCertifiedAutomaticRecoveryFromOpenedPhysical(',
            'openAndStartWithCertifiedAutomaticRecoveryFromPhysicalSources(')
        self.main.write_text(s,encoding='utf-8')
        self.assertFalse(self.check()[0])
    def test_missing_common_production_executor_is_no_go(self):
        result=audit.check_common_executor(self.root/'common')
        self.assertFalse(result[0]);self.assertIn('MISSING',result[1])
    def test_empty_class_does_not_pass_executor_check(self):
        d=self.root/'common'/'src/main/java/com/app/common/replication'
        d.mkdir(parents=True)
        (d/'CommonCertifiedProductionPhysicalRecovery.java').write_text('''
            final class CommonCertifiedProductionPhysicalRecovery {}
        ''',encoding='utf-8')
        result=audit.check_common_executor(self.root/'common')
        self.assertFalse(result[0])
    def test_comments_are_not_producer(self):
        (self.service/'OrderLegacy.java').write_text('''
            // @Qualifier("orderCommonCertifiedPhysicalRecovery")
            /* CommonCertifiedAutomaticReplicaPlanWiring.DurablePhysicalRecovery */
            final class OrderLegacy {}
        ''',encoding='utf-8')
        self.assertTrue(self.check()[0])

if __name__=='__main__':unittest.main()
