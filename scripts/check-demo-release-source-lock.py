#!/usr/bin/env python3
"""Read-only release provenance gate. NEVER stops containers or edits a lock.

Proves only that the GHCR lock references the exact desired committed source
revisions. Image existence, platform manifest, readiness and tenancy smoke
tests are separate mandatory gates before staging a disposable Demo reset.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

SERVICES = {
    "Order": ("ORDERSVR", "ordersvr"),
    "Trade": ("TRADESVR", "tradesvr"),
    "MD": ("MDSVR", "mdsvr"),
}
HEX_SHA = re.compile(r"^sha-([a-f0-9]{7,40})$")


def parse_lock(path):
    values = {}
    for lineno, raw in enumerate(Path(path).read_text().splitlines(), 1):
        item = raw.strip()
        if not item or item.startswith("#"):
            continue
        if "=" not in item:
            raise ValueError("invalid image lock line " + str(lineno))
        key, value = item.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
            raise ValueError("invalid/duplicate image lock key line " + str(lineno))
        values[key] = value
    return values


def source_head(path):
    root = Path(path).expanduser().resolve(strict=True)
    if not (root / "pom.xml").is_file():
        raise ValueError("source not a Maven checkout")
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
        capture_output=True, text=True, timeout=15, check=True,
    )
    head = result.stdout.strip().lower()
    if not re.fullmatch(r"[a-f0-9]{40}", head):
        raise ValueError("source HEAD not a commit")
    # A release cannot infer provenance from a revision with uncommitted files.
    subprocess.run(
        ["git", "-C", str(root), "diff", "--quiet", "--"],
        capture_output=True, timeout=15, check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--quiet", "--"],
        capture_output=True, timeout=15, check=True,
    )
    untracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, timeout=15, check=True,
    )
    for candidate in untracked.stdout.splitlines():
        if not (candidate.startswith("target/") or "/target/" in candidate
                or candidate == "Dockerfile.local"
                or candidate.endswith("/.DS_Store") or candidate == ".DS_Store"):
            raise ValueError("uncommitted source file: " + candidate)
    return head


def inspect(lock_path, sources):
    lock = parse_lock(lock_path)
    problems = []
    details = {}
    if lock.get("IMAGE_SOURCE") != "registry":
        problems.append("IMAGE_SOURCE_NOT_REGISTRY")
    if lock.get("REQUIRE_GHCR_LOGIN") != "true":
        problems.append("GHCR_LOGIN_GATE_DISABLED")
    for name, (prefix, image_name) in SERVICES.items():
        head = source_head(sources[name])
        tag = lock.get(prefix + "_TAG", "")
        repository = lock.get(prefix + "_IMAGE_REPOSITORY", "")
        match = HEX_SHA.fullmatch(tag)
        if repository != "ghcr.io/bliplink/" + image_name:
            problems.append(name.upper() + "_IMAGE_REPOSITORY_MISMATCH")
        if not match or not head.startswith(match.group(1)):
            problems.append(name.upper() + "_IMAGE_REVISION_MISMATCH")
        details[name] = {
            "sourceCommit": head,
            "lockedImage": repository + ":" + tag,
            "sameSourceCommit": bool(match and head.startswith(match.group(1))),
        }
    return {
        "decision": "PASS_SOURCE_LOCK_ONLY" if not problems else "BLOCKED",
        "blockers": problems,
        "images": details,
        "disclaimer": "No GHCR manifest, multiarch, credentials, Compose, database or live HA health verified.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-lock", required=True)
    for name in SERVICES:
        parser.add_argument("--" + name.lower() + "-source", required=True)
    args = parser.parse_args(argv)
    sources = {n: getattr(args, n.lower() + "_source") for n in SERVICES}
    try:
        result = inspect(args.release_lock, sources)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        result = {
            "decision": "BLOCKED",
            "blockers": ["INVALID_PROVENANCE_INPUT"],
            "error": str(error),
        }
    print(json.dumps(result, indent=2))
    return 0 if result["decision"] == "PASS_SOURCE_LOCK_ONLY" else 2


if __name__ == "__main__":
    sys.exit(main())
