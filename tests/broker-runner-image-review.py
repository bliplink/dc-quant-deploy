#!/usr/bin/env python3
"""Fail-closed Broker live-runner review gate.

A broker acceptance run deposits demo funds and places orders. Only immutable
Docker image IDs explicitly reviewed for safe cleanup and authoritative
authorization denial may execute this integration check.

Reviewed IDs must be in the repository's approved digest manifest; never use
mutable tags, environment-provided allowlist files, or implicit overrides.
"""
import re
import sys
from pathlib import Path

IMAGE_ID = re.compile(r"^sha256:[a-f0-9]{64}$")


def verify(image_id: str, manifest: Path) -> bool:
    if not IMAGE_ID.fullmatch(image_id):
        return False
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return False
    reviewed = {
        line.strip().split()[0]
        for line in lines if line.strip() and not line.lstrip().startswith("#")
    }
    return image_id in reviewed


def main() -> int:
    if len(sys.argv) != 2:
        print("Broker runner review gate needs deployed Docker image digest", file=sys.stderr)
        return 2
    reviewed = Path(__file__).with_name("broker-runner-approved-images.txt")
    if not verify(sys.argv[1], reviewed):
        print(
            "BLOCKED_UNREVIEWED_BROKER_RUNNER: no audited immutable image "
            "approval for exact currently deployed RobotSvr; refusing "
            "to issue demo funds or place test orders.",
            file=sys.stderr,
        )
        return 2
    print("BROKER_RUNNER_IMMUTABLE_IMAGE_REVIEW_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
