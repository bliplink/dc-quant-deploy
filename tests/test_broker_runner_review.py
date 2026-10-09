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
    def test_current_manifest_has_no_approved_unsafe_images(self):
        manifest = SRC.with_name("broker-runner-approved-images.txt")
        self.assertFalse(gate.verify("sha256:" + "a" * 64, manifest))
        contents = manifest.read_text()
        self.assertIn("EMPTY BY DESIGN", contents)

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
                        parent.index('[[ "$(id -u)" -eq 0 ]]'))
        self.assertLess(parent.index('broker-runner-image-review.py'),
                        parent.index('application_a="$(submit_application'))
        self.assertLess(child.index('broker-runner-image-review.py'),
                        child.index('[[ -r "${ENV_FILE}" ]]'))
        self.assertLess(child.index('broker-runner-image-review.py'),
                        child.index('docker run --rm --network host'))
if __name__ == "__main__":
    unittest.main()
