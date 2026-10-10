import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
class MdLearnerBootstrapTests(unittest.TestCase):
    def test_new_three_node_deploy_stages_c_as_learner_not_primary(self):
        s=(ROOT/'deploy-saas.sh').read_text()
        fragment=s[s.index('ensure_md_cluster_assignments() {'):s.index('wait_for_port() {')]
        self.assertIn('if [[ "${MD_CLUSTER_C_ENABLED:-false}" == "true" ]]', fragment)
        self.assertIn('"learners":["MDSvrC"]',fragment)
        self.assertNotIn('replica=MDSvrC',fragment)
        self.assertIn('node=MDSvrA',fragment)
        self.assertIn('node=MDSvrB',fragment)
        self.assertIn('non-voting LEARNER',fragment)
    def test_existing_assignments_are_not_overwritten(self):
        s=(ROOT/'deploy-saas.sh').read_text()
        fragment=s[s.index('ensure_md_cluster_assignments() {'):s.index('wait_for_port() {')]
        self.assertIn('if [[ "${existing_count}" == "256" ]]; then',fragment)
        self.assertIn('already ready: 256 partitions',fragment)
        self.assertNotIn('set /dc/cluster/mdsvr/partitions',fragment)
    def test_legacy_two_node_initialization_remains_available(self):
        s=(ROOT/'deploy-saas.sh').read_text()
        fragment=s[s.index('ensure_md_cluster_assignments() {'):s.index('wait_for_port() {')]
        self.assertIn('else\n        printf', fragment)
        self.assertIn('"replica":"%s","state":"READY"',fragment)
if __name__=='__main__':unittest.main()
