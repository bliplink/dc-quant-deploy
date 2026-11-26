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
        verified_layers = {}
        def blob_path(descriptor):
            digest = descriptor["digest"]
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError("Invalid OCI digest")
            return "blobs/sha256/" + digest[7:]

        def verify_layer(layer):
            digest = layer["digest"]
            if digest in verified_layers:
                if verified_layers[digest] != layer["size"]:
                    raise ValueError("Inconsistent layer size")
                return
            size = 0
            check = hashlib.sha256()
            with bundle.extractfile(blob_path(layer)) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(block)
                    check.update(block)
            if size != layer["size"] or "sha256:" + check.hexdigest() != digest:
                raise ValueError("Invalid runtime layer")
            verified_layers[digest] = size

        def read_blob(descriptor):
            with bundle.extractfile(blob_path(descriptor)) as stream:
                data = stream.read()
            if len(data) != descriptor["size"] or "sha256:" + hashlib.sha256(data).hexdigest() != descriptor["digest"]:
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
            advertised = descriptor.get("platform", {})
            if advertised and (advertised.get("os"), advertised.get("architecture")) != platform:
                raise ValueError("Manifest platform differs from image configuration")
            if platform in seen:
                raise ValueError("Duplicate architecture")
            if config["config"]["Labels"].get("org.opencontainers.image.revision") != revision:
                raise ValueError("Image source differs from release commit")
            if not node["layers"]:
                raise ValueError("Image has no runtime layers")
            for layer in node["layers"]:
                verify_layer(layer)
            seen.add(platform)

        index = json.load(bundle.extractfile("index.json"))
        for descriptor in index["manifests"]:
            visit(descriptor)
        if seen != {("linux", "amd64"), ("linux", "arm64")}:
            raise ValueError(f"Incomplete platform matrix: {seen}")


if __name__ == "__main__":
    verify(sys.argv[1], sys.argv[2])
