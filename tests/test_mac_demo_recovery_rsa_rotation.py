import base64
import hashlib
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

FRESH = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/mac-demo-fresh.py'))


def keypair():
    pem = subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048'],
                         capture_output=True, check=True).stdout
    private = subprocess.run(['openssl', 'pkcs8', '-topk8', '-nocrypt', '-outform', 'DER'],
                             input=pem, capture_output=True, check=True).stdout
    public = subprocess.run(['openssl', 'pkey', '-pubout', '-outform', 'DER'],
                            input=pem, capture_output=True, check=True).stdout
    return base64.b64encode(private).decode(), base64.b64encode(public).decode()


def public_of(encoded_private):
    return subprocess.run(['openssl', 'pkey', '-inform', 'DER', '-pubout', '-outform', 'DER'],
                          input=base64.b64decode(encoded_private), capture_output=True, check=True).stdout


class RecoveryRsaRotationTest(unittest.TestCase):
    def test_new_generations_rotate_private_keys_and_all_matching_peer_pins(self):
        a, b = keypair(), keypair()
        fingerprints = {hashlib.sha256(base64.b64decode(key[1])).hexdigest() for key in (a, b)}
        with tempfile.TemporaryDirectory() as directory:
            generations = []
            for generation in ('one', 'two'):
                root = Path(directory) / generation
                originals = {}
                for phase in ('birth', 'hostready'):
                    for slot, own, peer in (('A', a, b), ('B', b, a)):
                        path = root / f'config-{phase}/trade/{slot}/application.properties'
                        path.parent.mkdir(parents=True)
                        content = '\n'.join([
                            'trade.cluster.recovery.head.rsaPrivateKeyBase64=' + own[0],
                            'trade.cluster.recovery.replica.autoWarm.readerRsaPrivateKeyBase64=' + own[0],
                            'trade.cluster.recovery.read.readerPublicKeyBase64=' + peer[1],
                            'trade.cluster.recovery.replica.autoWarm.sourcePublicKeyBase64=' + peer[1],
                            'trade.common.existingRsa.localPrivateDir=/read-only-original-rsa/' + slot.lower(),
                            'unrelated.pinned.publicKey=' + own[1],
                            '',
                        ])
                        path.write_text(content)
                        originals[path] = content
                physical = root / 'ha/original-physical-rsa.pub.der'
                physical.parent.mkdir(parents=True)
                physical.write_bytes(base64.b64decode(a[1]))
                rotation = FRESH['rotate_recovery_rsa_keys'](root)
                self.assertEqual(fingerprints, {row['previous_public_sha256'] for row in rotation})
                self.assertEqual(2, len(rotation))
                fresh = {row['current_public_sha256'] for row in rotation}
                self.assertTrue(fresh.isdisjoint(fingerprints))
                generations.append(fresh)
                by_slot = {}
                for path, original in originals.items():
                    config = dict(line.split('=', 1) for line in path.read_text().splitlines())
                    private = config['trade.cluster.recovery.head.rsaPrivateKeyBase64']
                    self.assertTrue(private == config['trade.cluster.recovery.replica.autoWarm.readerRsaPrivateKeyBase64'],
                                    'Recovery producer and reader identities diverged')
                    self.assertTrue(private not in (a[0], b[0]), 'Previous recovery private key was retained')
                    public = base64.b64encode(public_of(private)).decode()
                    expected_public = by_slot.setdefault(path.parent.name, public)
                    self.assertEqual(expected_public, public)
                    self.assertIn('trade.common.existingRsa.localPrivateDir=/read-only-original-rsa/'
                                  + path.parent.name.lower(), path.read_text())
                    self.assertIn('unrelated.pinned.publicKey=' + (a if path.parent.name == 'A' else b)[1],
                                  path.read_text())
                for path in originals:
                    config = dict(line.split('=', 1) for line in path.read_text().splitlines())
                    expected = by_slot['B' if path.parent.name == 'A' else 'A']
                    self.assertEqual(expected, config['trade.cluster.recovery.read.readerPublicKeyBase64'])
                    self.assertEqual(expected, config['trade.cluster.recovery.replica.autoWarm.sourcePublicKeyBase64'])
                self.assertEqual(base64.b64decode(a[1]), physical.read_bytes())
            self.assertTrue(generations[0].isdisjoint(generations[1]))


if __name__ == '__main__':
    unittest.main()
