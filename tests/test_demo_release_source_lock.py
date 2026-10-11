#!/usr/bin/env python3
"""Read-only regression tests for the fresh Demo source/image lock gate."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

MODULE = Path(__file__).resolve().parent.parent / "scripts" / "check-demo-release-source-lock.py"
SPEC = importlib.util.spec_from_file_location("release_source_lock", MODULE)
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class ReleaseSourceLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="demo-image-source-lock-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.roots = {}
        self.heads = {}
        for name in ("Order", "Trade", "MD"):
            root = self.root / name
            root.mkdir()
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
            (root / "pom.xml").write_text("<project/>")
            subprocess.run(["git", "-C", str(root), "add", "pom.xml"], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Test",
                            "-c", "user.email=test@invalid.local", "commit", "-qm",
                            "initial"], check=True)
            self.roots[name] = root
            self.heads[name] = GATE.source_head(root)
        self.lock = self.root / "release.env"
        self.write_lock()

    def write_lock(self, trade_tag=None):
        items = ["IMAGE_SOURCE=registry", "REQUIRE_GHCR_LOGIN=true"]
        for name, (prefix, image_name) in GATE.SERVICES.items():
            items.extend([
                prefix + "_IMAGE_REPOSITORY=ghcr.io/bliplink/" + image_name,
                prefix + "_TAG=" + (trade_tag if name == "Trade" and trade_tag is not None
                                      else "sha-" + self.heads[name][:8]),
            ])
        self.lock.write_text("\n".join(items) + "\n")

    def test_exact_committed_source_tags_pass(self):
        result = GATE.inspect(self.lock, self.roots)
        self.assertEqual("PASS_SOURCE_LOCK_ONLY", result["decision"])
        self.assertEqual([], result["blockers"])

    def test_stale_image_tag_blocks_clean_reset(self):
        self.write_lock(trade_tag="sha-0000000")
        result = GATE.inspect(self.lock, self.roots)
        self.assertEqual("BLOCKED", result["decision"])
        self.assertIn("TRADE_IMAGE_REVISION_MISMATCH", result["blockers"])

    def test_floating_tag_blocks(self):
        self.write_lock(trade_tag="saas-crypto")
        result = GATE.inspect(self.lock, self.roots)
        self.assertIn("TRADE_IMAGE_REVISION_MISMATCH", result["blockers"])

    def test_dirty_tracked_file_never_matches_committed_source(self):
        (self.roots["Order"] / "pom.xml").write_text("<project>dirty</project>")
        with self.assertRaises(subprocess.CalledProcessError):
            GATE.inspect(self.lock, self.roots)

    def test_untracked_source_is_rejected_but_maven_target_is_allowed(self):
        (self.roots["MD"] / "NewSource.java").write_text("class NewSource {}")
        with self.assertRaises(ValueError):
            GATE.source_head(self.roots["MD"])
        (self.roots["MD"] / "NewSource.java").unlink()
        generated = self.roots["MD"] / "target" / "classes"
        generated.mkdir(parents=True)
        (generated / "Generated.class").write_bytes(b"compiled")
        self.assertEqual(self.heads["MD"], GATE.source_head(self.roots["MD"]))

    def test_duplicate_lock_entries_fail(self):
        with self.lock.open("a") as stream:
            stream.write("IMAGE_SOURCE=registry\n")
        with self.assertRaises(ValueError):
            GATE.parse_lock(self.lock)


if __name__ == "__main__":
    unittest.main()
