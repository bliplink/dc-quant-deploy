import hashlib
import unittest
from unittest.mock import Mock

from recovery.compiled_source_audit import compare_stored_source, compiled_artifact_audit


class CompiledSourceAuditTest(unittest.TestCase):
    def test_exact_source_and_jar_are_both_attested(self):
        source = b'package x; class Frozen {}\n'
        audit = compare_stored_source(source, source, 'a' * 64, 'a' * 64)
        self.assertEqual('exact', audit['source_normalization'])
        self.assertEqual(hashlib.sha256(source).hexdigest(), audit['stored_source_sha256'])
        self.assertTrue(audit['compiled_source_verified'])

    def test_outer_trim_is_explicit_not_falsely_reported_as_same_source_hash(self):
        upload = b'package x; class Frozen {}\n'
        audit = compare_stored_source(upload, upload.rstrip(), 'a' * 64, 'a' * 64)
        self.assertEqual('outer_ascii_whitespace_trim', audit['source_normalization'])
        self.assertNotEqual(audit['uploaded_source_sha256'], audit['stored_source_sha256'])
        self.assertTrue(audit['source_tokens_unchanged'])

    def test_token_inner_literal_and_artifact_changes_fail_closed(self):
        for stored in (b'class Y {}', b'class X{String s="a";}', b'class  X{String s=" a ";}'):
            with self.assertRaisesRegex(ValueError, 'stored source differs'):
                compare_stored_source(b'class X{String s=" a ";}\n', stored, 'a' * 64, 'a' * 64)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            compare_stored_source(b'class X {}', b'class X {}', 'a' * 64, 'b' * 64)

    def test_path_and_candidate_identity_are_checked_before_remote_reads(self):
        client = Mock()
        with self.assertRaises(ValueError):
            compiled_artifact_audit(client, {'strategy_name': 'wrong', 'strategy_version': 'v1'}, {'strategyName': 'target'})
        candidate = {'strategy_name': 'target', 'strategy_version': 'v1',
                     'artifact_uri': '/srv/target/v1/strategy.jar',
                     'java_source_path': '/etc/passwd', 'entry_class': 'x.GeneratedStrategy'}
        with self.assertRaises(ValueError):
            compiled_artifact_audit(client, candidate, {'strategyName': 'target'})
        client.exec_command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
