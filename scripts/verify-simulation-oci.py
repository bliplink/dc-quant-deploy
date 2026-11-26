#!/usr/bin/env python3
"""Check OCI image manifests, config digests and revisions on both server architectures."""
import hashlib
import json
import re
import sys
import tarfile


def verify(archive, revision):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("An exact source revision is required")
    with tarfile.open(archive) as bundle:
        def read_blob(descriptor):
            alg, digest = descriptor["digest"].split(":", 1)
            if alg != "sha256" or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Invalid OCI digest")
            data = bundle.extractfile("blobs/sha256/" + digest).read()
            if len(data) != descriptor["size"] or hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("OCI blob mismatch")
            return json.loads(data)

        seen = set()
        def visit(descriptor):
            if descriptor.get("annotations", {}).get("vnd.docker.reference.type") == "attestation-manifest":
                return
            node = read_blob(descriptor)
            if "manifests" in node:
                for child in node["manifests"]:
                    visit(child)
                return
            config = read_blob(node["config"])
            platform = (config["os"], config["architecture"])
            if platform in seen:
                raise ValueError("Duplicate architecture")
            if config["config"]["Labels"].get("org.opencontainers.image.revision") != revision:
                raise ValueError("Image source differs from release commit")
            if not node["layers"]:
                raise ValueError("Image has no runtime layers")
            seen.add(platform)

        index = json.load(bundle.extractfile("index.json"))
        for descriptor in index["manifests"]:
            visit(descriptor)
        if seen != {("linux", "amd64"), ("linux", "arm64")}:
            raise ValueError(f"Incomplete platform matrix: {seen}")


if __name__ == "__main__":
    verify(sys.argv[1], sys.argv[2])
