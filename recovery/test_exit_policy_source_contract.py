import unittest

from recovery.export_representative_candidate import exit_policy_contract_version


class ExitPolicySourceContractTest(unittest.TestCase):
    def test_historical_source_keeps_explicit_legacy_contract(self):
        source = 'public class Outer {\n    static final class Setup { int side; }\n}'
        self.assertEqual(0, exit_policy_contract_version(source))

    def test_supported_policy_schema_is_explicit(self):
        source = 'public class Outer {\n    static final class Setup { static final int EXIT_POLICY_SCHEMA_VERSION = 1; }\n}'
        self.assertEqual(1, exit_policy_contract_version(source))

    def test_unknown_schema_is_rejected_not_silently_exported_as_legacy(self):
        source = 'public class Outer {\n    static final class Setup { static final int EXIT_POLICY_SCHEMA_VERSION = 2; }\n}'
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            exit_policy_contract_version(source)


if __name__ == '__main__':
    unittest.main()
