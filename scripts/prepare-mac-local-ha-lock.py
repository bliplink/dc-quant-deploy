#!/usr/bin/env python3
"""Prepare an explicit MAC-LOCAL dev image lock, never edit the GHCR release lock.

Only supports a complete, source-proven, same-Common Gateway/Order/Trade/MD
image family, and writes inside the immutable local build's artifacts dir.
Use RELEASE_IMAGE_LOCK=<generated lock> only for a disposable cold Demo.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

IMAGE_NAMES = {
    "gw": "GW",
    "ordersvr": "ORDERSVR",
    "tradesvr": "TRADESVR",
    "mdsvr": "MDSVR",
}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def parse_env(path):
    output = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("invalid immutable image lock syntax")
        key, value = line.split("=", 1)
        if key in output or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key):
            raise ValueError("invalid/duplicate image lock key")
        output[key] = value
    return output


def inspect_image(ref):
    done = subprocess.run(
        ["docker", "image", "inspect", ref, "--format", "{{json .Config.Labels}}"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    labels = json.loads(done.stdout)
    if not isinstance(labels, dict):
        raise ValueError("image missing labels: " + ref)
    return labels


def prepare(base, manifest, output):
    base, manifest, output = (p.expanduser().resolve() for p in (base, manifest, output))
    if not base.is_file() or not manifest.is_file():
        raise ValueError("missing source image lock or local build manifest")
    # Intentionally NEVER create/overwrite the official release lock, nor
    # touch a working repository's tracked configuration or .env.prod.
    if (manifest.name != "local-ha-images.env"
            or manifest.parent.name != "artifacts"
            or output.parent != manifest.parent
            or output.name != "local-ha-release-lock.env"
            or output == base or output.exists() or output.is_symlink()):
        raise ValueError("dev lock can only be created beside local build manifest")
    values = parse_env(base)
    dev = parse_env(manifest)
    required = set(IMAGE_NAMES) | {"COMMON_GAV", "COMMON_JAR_SHA256"}
    if not required.issubset(dev):
        raise ValueError("local build manifest must include Gateway + three services")
    sha = dev["COMMON_JAR_SHA256"]
    gav = dev["COMMON_GAV"]
    if not SHA_RE.fullmatch(sha) or not re.fullmatch(
            r"io[.]github[.]bliplink:com[.]app[.]common:3[.]0[.]17-dev[a-f0-9]+-SNAPSHOT", gav):
        raise ValueError("invalid local Common artifact provenance")
    expected_revision = None
    tags = set()
    for module, prefix in IMAGE_NAMES.items():
        ref = dev[module]
        repo, separator, tag = ref.partition(":")
        if not separator or repo != "dc-saas/" + module or not tag.startswith("cluster-dev-"):
            raise ValueError("not an immutable locally built image: " + module)
        tags.add(tag)
        label = inspect_image(ref)
        source_file = manifest.parent / (module + ".sha")
        expected_source = source_file.read_text().strip().lower()
        if not COMMIT_RE.fullmatch(expected_source):
            raise ValueError("source SHA missing: " + module)
        if (label.get("dc.common.jar.sha256") != sha
                or label.get("dc.common.gav") != gav
                or label.get("dc.source.revision") != expected_source
                or label.get("dc.build.kind") != "mac-local-ha-demo"):
            raise ValueError("container image/source/common binary mismatch: " + module)
        revision = label.get("dc.common.revision")
        if not revision or revision == "unknown":
            raise ValueError("unattested Common source revision: " + module)
        if expected_revision is None:
            expected_revision = revision
        elif revision != expected_revision:
            raise ValueError("Gateway/Order/Trade/MD Common revision conflict")
        values[prefix + "_IMAGE_REPOSITORY"] = repo
        values[prefix + "_TAG"] = tag
    if len(tags) != 1:
        raise ValueError("service images were not built as one immutable group")
    values["IMAGE_SOURCE"] = "local"
    values["REQUIRE_GHCR_LOGIN"] = "false"
    # These are explicitly supported keys of apply-release-image-lock.sh.
    for key in values:
        if key not in {"IMAGE_SOURCE", "REQUIRE_GHCR_LOGIN"} and not (
                key.endswith("_TAG") or key.endswith("_IMAGE_REPOSITORY")):
            raise ValueError("unexpected key inherited from release lock")
    data = ("# MAC DEVELOPMENT ONLY. This is NOT the production GHCR image lock.\n"
            + "# Exact local build Common revision: " + expected_revision + "\n"
            + "\n".join(key + "=" + value for key, value in values.items()) + "\n")
    fd = os.open(str(output), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return {"lock": str(output), "tag": next(iter(tags)),
            "commonRevision": expected_revision, "commonJarSha256": sha,
            "services": sorted(IMAGE_NAMES), "productionLockUnchanged": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-lock", type=Path, required=True)
    parser.add_argument("--local-build-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.release_lock, args.local_build_manifest, args.output)
    except (ValueError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print("LOCAL_DEV_LOCK_DENIED: " + str(error)[:300], file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
