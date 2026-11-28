#!/usr/bin/env python3
"""Install one release of the single-host T554 simulation from locally verified candidate images."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import simulation_tenants

SCRIPTS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("simulation", SCRIPTS / "verify-clean-simulation.py")
simulation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulation)
call = simulation.call


def inventory(generation):
    nodes = [f"{generation}-{kind}-{slot.lower()}-hostready" for kind in simulation.common.SERVICES
             for slot in simulation.common.SLOTS]
    nodes += [f"{generation}-{kind}-witness" for kind in simulation.common.SERVICES]
    services = [*simulation.common.INFRA, *simulation.APPS]
    compose = ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + generation]
    ids = call(*compose).splitlines()
    rows = json.loads(call("docker", "inspect", *ids, *nodes))
    apps = {row["Config"]["Labels"].get("com.docker.compose.service"): row for row in rows
            if row["Config"]["Labels"].get("com.docker.compose.project") == generation}
    if set(apps) != set(services):
        raise RuntimeError("Installed Compose services differ from the expected release")
    result = {}
    for row in rows:
        state = row["State"]
        if not state["Running"] or state.get("Health", {}).get("Status", "healthy") != "healthy":
            raise RuntimeError(f"{row['Name']} is unavailable")
        result[row["Name"]] = row["Image"]
    for kind, service in simulation.common.SERVICES.items():
        output = call("docker", "exec", "dc-saas-zookeeper", "zkCli.sh", "-server", "127.0.0.1:49181",
                      "get", f"/otc/{generation}/{kind}/manifest")
        partitions = set()
        for row in output.splitlines():
            if re.match(r"^P\d{3}\|", row):
                match = re.fullmatch(r"(P\d{3})\|([1-9]\d*)\|(" + service + r"[AB])\|(" + service +
                                     r"[AB])\|STRICT_QUORUM\|READY", row)
                if not match or match[3] == match[4] or match[1] in partitions:
                    raise RuntimeError(f"{kind} reports unready or inconsistent membership")
                partitions.add(match[1])
        if partitions != {f"P{i:03}" for i in range(256)}:
            raise RuntimeError(f"Incomplete signed {kind} membership")
    return result


def import_bundle(bundle, digest):
    manifest = bundle / "simulation-images.json"
    data = manifest.read_bytes()
    if not re.fullmatch("[a-f0-9]{64}", digest) or hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError("Image manifest checksum differs from the supplied release checksum")
    lock = json.loads(data)
    kinds = set(simulation.APPS.values()) | {"order", "trade"}
    if lock["deploymentRevision"] != call("git", "-C", str(SCRIPTS.parent), "rev-parse", "HEAD") or set(lock["images"]) != kinds:
        raise RuntimeError("Image bundle does not match the deployment checkout")
    if not shutil.which("skopeo"):
        raise RuntimeError("Install skopeo to import the OCI image bundle")
    context = call("docker", "context", "show")
    endpoint = call("docker", "context", "inspect", context, "-f", "{{.Endpoints.docker.Host}}")
    if os.environ.get("DOCKER_HOST") and not os.environ.get("DOCKER_CONTEXT"):
        endpoint = os.environ["DOCKER_HOST"]
    if not endpoint.startswith("unix://"):
        raise RuntimeError("The release must be imported into the local Docker engine")
    platform = call("docker", "version", "-f", "{{.Server.Arch}}")
    if platform not in {"amd64", "arm64"}:
        raise ValueError("Unsupported Docker engine architecture")
    for kind in sorted(kinds):
        pin = call("git", "-C", str(SCRIPTS.parent), "rev-parse", "HEAD:sources/" + kind)
        archive = bundle / f"{kind}-{pin}.oci.tar"
        expected = lock["images"][kind]
        if not re.fullmatch("[a-f0-9]{64}", expected):
            raise ValueError(f"Invalid image checksum for {kind}")
        checksum = hashlib.sha256()
        with archive.open("rb") as stream:
            for block in iter(lambda: stream.read(2 ** 20), b""):
                checksum.update(block)
        if checksum.hexdigest() != expected:
            raise RuntimeError(f"Damaged {kind} archive")
        subprocess.run([sys.executable, str(SCRIPTS / "verify-simulation-oci.py"), str(archive), pin], check=True)
        subprocess.run(["skopeo", "--override-os", "linux", "--override-arch", platform, "copy", "--dest-daemon-host", endpoint,
                        "oci-archive:" + str(archive), f"docker-daemon:otc-simulation/{kind}:{pin}"], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True, help="persistent private installation directory")
    parser.add_argument("--image-bundle", type=Path, help="directory of release OCI images and simulation-images.json")
    parser.add_argument("--bundle-sha256", help="trusted SHA256 of the release image manifest")
    args = parser.parse_args()
    if bool(args.image_bundle) != bool(args.bundle_sha256):
        parser.error("--image-bundle and --bundle-sha256 are required together")
    os.umask(0o077)
    base = args.state_dir.absolute()
    base.mkdir(parents=True, exist_ok=True)
    if base.is_symlink() or base.stat().st_uid != os.getuid() or base.stat().st_mode & 0o077:
        raise ValueError("Use a private installation directory owned by this account")
    with (base / ".installation.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        subprocess.run([sys.executable, str(SCRIPTS / "check-simulation-host.py"), "--data-parent", str(base)],
                       check=True)
        revision = call("git", "-C", str(SCRIPTS.parent), "rev-parse", "HEAD")
        receipt = base / "installation.json"
        checkpoint = base / "cluster-ready.json"
        if receipt.exists() or checkpoint.exists():
            state = json.loads((receipt if receipt.exists() else checkpoint).read_text())
            if state["deploymentRevision"] != revision:
                raise RuntimeError("Existing installation has another deployment revision")
            generation = state["generation"]
            if not re.fullmatch(r"sim-demo-\d{8}-\d{6}", generation):
                raise ValueError("Invalid installation receipt")
            if inventory(generation) != state["runningImages"]:
                raise RuntimeError("Running images differ from the original installation receipt")
            if receipt.exists() and "tenants" in state:
                if simulation_tenants.funded(state["tenants"]) != 10:
                    raise RuntimeError("The installation exists; fewer than ten funded makers are actively quoting")
                print(f"{generation} verified from existing storage with ten funded tenants")
                return
            finish_tenants(base, state)
            return
        if set(p.name for p in base.iterdir()) != {".installation.lock"}:
            raise RuntimeError("Incomplete or foreign installation directory; keeping its evidence and data")
        if call("docker", "ps", "-aq") or call("docker", "volume", "ls", "-q"):
            raise RuntimeError("First installation requires an unused local Docker engine")
        if not args.image_bundle and os.environ.get("GITHUB_ACTIONS") != "true":
            raise RuntimeError("First server installation requires the accepted image bundle and its trusted manifest checksum")
        if args.image_bundle:
            import_bundle(args.image_bundle.resolve(strict=True), args.bundle_sha256)
        images = {kind: simulation.image(kind) for kind in sorted(set(simulation.APPS.values()) | {"order", "trade"})}
        common_digests = set()
        for kind in ("order", "trade", "market-data", "gateway"):
            digest = call("docker", "image", "inspect", "-f", '{{index .Config.Labels "dc.common.jar.sha256"}}', images[kind])
            qualified = call("docker", "image", "inspect", "-f", '{{index .Config.Labels "dc.common.p0.sha256"}}', images[kind])
            if not re.fullmatch("[a-f0-9]{64}", digest) or qualified != digest:
                raise RuntimeError(f"{kind} image has no matching physical recovery qualification")
            common_digests.add(digest)
        if len(common_digests) != 1:
            raise RuntimeError("Core services use different qualified Common builds")
        out = base / datetime.now(timezone.utc).strftime("sim-demo-%Y%m%d-%H%M%S")
        simulation.install(out, control_only=False)
        state = {"generation": out.name, "deploymentRevision": revision, "runningImages": inventory(out.name)}
        write_receipt(checkpoint, state)
        finish_tenants(base, state)


def write_receipt(path, state):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as stream:
        json.dump(state, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def finish_tenants(base, state):
    generation = state["generation"]
    state["tenants"] = simulation_tenants.enroll(base / generation)
    write_receipt(base / "installation.json", state)
    print(f"{generation} installed with verified Order and Trade membership and ten funded makers")


if __name__ == "__main__":
    main()
