from pathlib import Path
import unittest

S=(Path(__file__).resolve().parents[1]/'generate-saas-configs.sh').read_text()

class FailClosedDiagnosticDefaults(unittest.TestCase):
    def test_order_head_probe_never_on_by_default(self):
        section=S[S.index('write_cluster_order_config() {'):]
        self.assertIn('order.cluster.mdCheckpointHeadReview.enabled=false',section)
        self.assertIn('order.cluster.mdCheckpointHeadReview.minIntervalMillis=60000',section)
    def test_md_does_not_track_each_depth_diff_by_default(self):
        section=S[S.index('write_md_config() {'):S.index('write_cluster_order_config() {')]
        self.assertIn('md.cluster.replayWitness.enabled=false',section)
    def test_diagnostic_flags_occur_once_not_global_overrides(self):
        for prop in ('md.cluster.replayWitness.enabled=',
                     'order.cluster.mdCheckpointHeadReview.enabled='):
            self.assertEqual(1,S.count(prop))

if __name__=='__main__':unittest.main()
