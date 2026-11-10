import struct
import tempfile
from pathlib import Path
import unittest
import zipfile

from recovery.class_identity_equivalence import (
    identity_prefix, jar_class_proof, neutral_source, normalize_class,
    require_jar_identity_equivalence, require_source_identity_equivalence,
)


def utf8(value):
    raw = value.encode('utf-8'); return b'\x01' + struct.pack('>H', len(raw)) + raw


def fixture_class(name, number=.25, tail=None):
    entries = [utf8(identity_prefix(name) + 'GeneratedStrategy'), utf8(name),
        b'\x06' + struct.pack('>d', number), utf8('(L' + identity_prefix(name) + 'GeneratedStrategy$Quotes;)D')]
    # The double occupies two slots: 1+1+2+1 entries plus the unused slot0.
    return b'\xca\xfe\xba\xbe\x00\x00\x00\x34' + struct.pack('>H', 6) + b''.join(entries) + (tail or b'\x00' * 14)


def fixture_source(name):
    return ('package com.app.dc.generated.autogen.' + name + '.v1;\n'
        'public class GeneratedStrategy {\n'
        'private static final String STRATEGY_NAME = "' + name + '";\n'
        'void label() { signal.strategyName = STRATEGY_NAME; }\n'
        'double threshold = .25;\n}\n')


class ClassIdentityEquivalenceTest(unittest.TestCase):
    def test_only_the_two_explicit_source_identity_substitutions_are_allowed(self):
        require_source_identity_equivalence(fixture_source('catalog_one'), 'catalog_one', fixture_source('catalog_two'), 'catalog_two')
        with self.assertRaises(ValueError):
            require_source_identity_equivalence(fixture_source('catalog_one'), 'catalog_one',
                fixture_source('catalog_two').replace('.25', '.26'), 'catalog_two')

    def test_identity_use_in_computation_or_an_extra_literal_is_rejected(self):
        for changed in (fixture_source('catalog_one') + ' if (STRATEGY_NAME.length()>0) {}',
                        fixture_source('catalog_one') + ' "catalog_one"'):
            with self.assertRaises(ValueError): neutral_source(changed, 'catalog_one')

    def test_invalid_exported_identity_is_rejected(self):
        for name in ('../escape', 'normal_name', 'catalog_bad-name', '', None):
            with self.assertRaises(ValueError): identity_prefix(name)

    def test_utf8_names_descriptors_and_labels_normalize_but_numeric_constants_do_not(self):
        self.assertEqual(normalize_class(fixture_class('catalog_one'), 'catalog_one'),
                         normalize_class(fixture_class('catalog_two'), 'catalog_two'))
        self.assertNotEqual(normalize_class(fixture_class('catalog_one'), 'catalog_one'),
                            normalize_class(fixture_class('catalog_two', number=.26), 'catalog_two'))

    def test_remaining_class_bytes_including_code_and_attributes_are_never_removed(self):
        self.assertNotEqual(normalize_class(fixture_class('catalog_one'), 'catalog_one'),
            normalize_class(fixture_class('catalog_two', tail=b'\x01' + b'\x00' * 13), 'catalog_two'))

    def test_unknown_truncated_and_invalid_wide_constant_pools_fail_closed(self):
        original = fixture_class('catalog_one')
        for bad in (b'bad', original[:10], original[:12], original[:-1],
                    original[:10] + b'\xff' + original[11:],
                    original[:8] + b'\x00\x02' + b'\x06' + b'\x00' * 24):
            with self.assertRaises(ValueError): normalize_class(bad, 'catalog_one')

    def archive(self, root, name, number=.25, extra=None):
        path = root / (name + str(number) + '.jar')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('META-INF/MANIFEST.MF', b'Manifest-Version: 1.0\n')
            archive.writestr(identity_prefix(name) + 'GeneratedStrategy.class', fixture_class(name, number))
            archive.writestr(identity_prefix(name) + 'GeneratedStrategy$Quotes.class', fixture_class(name))
            if extra: archive.writestr(extra, b'unexpected')
        return path

    def test_all_generated_classes_and_manifest_are_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); first = self.archive(root, 'catalog_one'); second = self.archive(root, 'catalog_two')
            proof = require_jar_identity_equivalence(first, 'catalog_one', second, 'catalog_two')
            self.assertEqual(2, len(proof['normalized_class_sha256']))
            with self.assertRaises(ValueError):
                require_jar_identity_equivalence(first, 'catalog_one', self.archive(root, 'catalog_bad', .26), 'catalog_bad')

    def test_unexpected_resource_or_external_class_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for extra in ('unexpected.txt', 'outside/Other.class'):
                with self.assertRaises(ValueError): jar_class_proof(self.archive(root, 'catalog_one', extra=extra), 'catalog_one')

    def test_missing_nested_class_is_not_accepted_as_equivalent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); first = self.archive(root, 'catalog_one'); second = root / 'without-nested.jar'
            with zipfile.ZipFile(second, 'w') as archive:
                archive.writestr('META-INF/MANIFEST.MF', b'Manifest-Version: 1.0\n')
                archive.writestr(identity_prefix('catalog_two') + 'GeneratedStrategy.class', fixture_class('catalog_two'))
            with self.assertRaises(ValueError): require_jar_identity_equivalence(first, 'catalog_one', second, 'catalog_two')


if __name__ == '__main__': unittest.main()
