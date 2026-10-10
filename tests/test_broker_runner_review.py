"""Offline broker live-runner guardrail (no Docker credentials or orders)."""
from pathlib import Path
import importlib.util
import tempfile
import unittest

SRC = Path(__file__).with_name("broker-runner-image-review.py")
spec = importlib.util.spec_from_file_location("broker_image_review", SRC)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class BrokerRunnerReviewTests(unittest.TestCase):
    def test_reviewed_arm64_image_allowed_but_previous_unsafe_image_rejected(self):
        manifest = SRC.with_name("broker-runner-approved-images.txt")
        new_id = "sha256:4ccac4846d00051053e9fb89ae1ca4e0f89f9124b6e16a3045ea3f967428f75e"
        colima_import_id = "sha256:98c3a2bb1793b06b0c369f00372d18dee54da31363fc9525e268fd6783210a9a"
        self.assertTrue(gate.verify(new_id, manifest))
        self.assertTrue(gate.verify(colima_import_id, manifest))
        self.assertFalse(gate.verify("sha256:24bb08e1ac73783f87e8c1ac32391004e5bfe4661b9ecc6b72ef2912c45f81fc", manifest))
        self.assertFalse(gate.verify("sha256:" + "a" * 64, manifest))
        self.assertEqual(
            [line for line in manifest.read_text().splitlines() if line.startswith("sha256:")],
            [new_id, colima_import_id],
        )


    def test_fail_closed_when_manifest_is_missing(self):
        self.assertFalse(gate.verify("sha256:" + "f" * 64, Path("/missing/broker-images.txt")))

    def test_rejects_mutable_tags_or_short_shas(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reviewed.txt"
            path.write_text("sha256:" + "a" * 64 + "\n")
            for value in ["latest", "sha-abd7efa1", "sha256:abc", "a" * 64, "sha256:" + "Z" * 64]:
                self.assertFalse(gate.verify(value, path))

    def test_exact_manifest_match_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reviewed.txt"
            path.write_text("# reviewed\nsha256:" + "1" * 64 + " # java source verified\n")
            self.assertTrue(gate.verify("sha256:" + "1" * 64, path))
            self.assertFalse(gate.verify("sha256:" + "2" * 64, path))



    def test_parent_and_child_fail_before_credentials_or_side_effects(self):
        parent = SRC.with_name("run-tenant-lifecycle-e2e-host.sh").read_text()
        child = SRC.with_name("run-broker-api-e2e-host.sh").read_text()
        self.assertLess(parent.index('broker-runner-image-review.py'),
                        parent.index('[[ -O "${ENV_FILE}" ]]'))
        self.assertLess(parent.index('broker-runner-image-review.py'),
                        parent.index('application_a="$(submit_application'))
        self.assertLess(child.index('broker-runner-image-review.py'),
                        child.index('[[ -r "${ENV_FILE}" ]]'))
        self.assertLess(child.index('broker-runner-image-review.py'),
                        child.index('docker run --rm --network host'))

    def test_explicit_candidate_requires_immutable_commit_sha_tag(self):
        parent = SRC.with_name("run-tenant-lifecycle-e2e-host.sh").read_text()
        child = SRC.with_name("run-broker-api-e2e-host.sh").read_text()
        for content in (parent, child):
            self.assertIn('BROKER_E2E_RUNNER_IMAGE_REF', content)
            self.assertIn('ghcr[.]io/bliplink/robotsvr:sha-[0-9a-f]{40}', content)
            self.assertIn('docker image inspect', content)
            self.assertIn('docker inspect', content)
        self.assertIn(
            'BROKER_E2E_RUNNER_IMAGE_REF="${BROKER_E2E_RUNNER_IMAGE_REF:-}"',
            parent,
        )
if __name__ == "__main__":
    unittest.main()
