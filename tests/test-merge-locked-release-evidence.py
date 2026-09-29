#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    'merge_locked_release_evidence', Path(__file__).with_name('merge-locked-release-evidence.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MergeLockedReleaseEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.lock = {'releaseId': 'next', 'components': [
            {'name': 'common', 'revision': 'a', 'type': 'library'},
            {'name': 'projection', 'revision': 'c', 'type': 'java'}]}
        self.base = {'releaseId': 'prior', 'components': {
            'common': {'revision': 'a', 'tests': {'failures': 0}},
            'projection': {'revision': 'b', 'imageId': 'old', 'tests': {'failures': 0}}}}
        self.delta = {'releaseId': 'next', 'components': {
            'projection': {'revision': 'c', 'imageId': 'new', 'tests': {'failures': 0}}}}

    def test_reuses_unchanged_component_and_replaces_rebuilt_component(self):
        result = module.merge(self.lock, self.base, self.delta)
        self.assertEqual('a', result['components']['common']['revision'])
        self.assertEqual('new', result['components']['projection']['imageId'])
        self.assertEqual('prior', result['baseReleaseId'])

    def test_rejects_revision_mismatch(self):
        self.delta['components']['projection']['revision'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'source revision'):
            module.merge(self.lock, self.base, self.delta)

    def test_rejects_missing_base_component(self):
        del self.base['components']['common']
        with self.assertRaisesRegex(ValueError, 'every locked component'):
            module.merge(self.lock, self.base, self.delta)


if __name__ == '__main__':
    unittest.main()
