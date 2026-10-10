"""Read-only archive hash inventory never grants WAL deletion."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PATH=Path(__file__).resolve().parents[1]/'scripts/manifest-order-archive-segment.py'
SPEC=importlib.util.spec_from_file_location('segment_manifest',PATH)
mod=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive=Path(self.temp.name)/'OrderSvrA'/'journal'/'.archive'/'P246-epoch1-seq578111-42'
        self.archive.mkdir(parents=True)
        self.cq=self.archive/'20261010F.cq4'
        self.cq.write_bytes(b'STATE_COMMIT_TEST_PAYLOAD')

    def test_manifest_has_hash_and_fails_closed_on_cleanup(self):
        manifest=mod.generate(self.archive)
        self.assertEqual('P246',manifest['partition'])
        self.assertEqual(578111,manifest['lastSequenceNameHint'])
        self.assertEqual(hashlib.sha256(self.cq.read_bytes()).hexdigest(),manifest['files'][0]['sha256'])
        self.assertFalse(manifest['deletionAuthorized'])
        self.assertFalse(manifest['externalBackupVerified'])
        self.assertFalse(manifest['replicaAndProjectionWatermarksAttested'])
        self.assertEqual('HOLD',manifest['retentionDecision'])
        self.assertEqual(b'STATE_COMMIT_TEST_PAYLOAD',self.cq.read_bytes())

    def test_manifest_writes_only_outside_wal_and_never_overwrites(self):
        out=Path(self.temp.name)/'manifest.json'
        self.assertEqual(0,mod.main(['--archive',str(self.archive),'--output',str(out)]))
        data=json.loads(out.read_text())
        self.assertFalse(data['deletionAuthorized'])
        with self.assertRaisesRegex(ValueError,'already exists'):
            mod.main(['--archive',str(self.archive),'--output',str(out)])
        with self.assertRaisesRegex(ValueError,'outside the journal'):
            mod.main(['--archive',str(self.archive),'--output',str(self.archive/'bad.json')])

    def test_file_symlink_is_rejected(self):
        (self.archive/'link.cq4').symlink_to(self.cq)
        with self.assertRaisesRegex(ValueError,'unsafe'):
            mod.generate(self.archive)

    def test_wrong_archive_name_is_rejected(self):
        x=self.archive.parent/'P246-corrupted-name'
        x.mkdir()
        (x/'test.cq4').write_bytes(b'abc')
        with self.assertRaisesRegex(ValueError,'unrecognized'):
            mod.generate(x)

    def test_empty_archive_is_rejected(self):
        self.cq.unlink()
        with self.assertRaisesRegex(ValueError,'empty archive'):
            mod.generate(self.archive)

if __name__=='__main__':unittest.main()
