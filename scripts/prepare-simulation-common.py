#!/usr/bin/env python3
"""Prepare one fresh single-host simulation's protected Order and Trade voter configuration."""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess

SCRIPT_DIR = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("mac_demo_fresh", SCRIPT_DIR / "mac-demo-fresh.py")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


def recovery_keys():
    pem = subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048"],
                         capture_output=True, check=True).stdout

    def encode(*args):
        data = subprocess.run(["openssl", *args, "-outform", "DER"], input=pem,
                              capture_output=True, check=True).stdout
        return base64.b64encode(data).decode("ascii")

    return encode("pkcs8", "-topk8", "-nocrypt"), encode("pkey", "-pubout")


def manifest(service):
    lines = ["NPC1|1"]
    for i in range(256):
        first, second = ("A", "B") if i < 128 else ("B", "A")
        lines.append(f"P{i:03d}|1|{service}{first}|{service}{second}|STRICT_QUORUM|RECOVERING")
    return "\n".join(lines)


def expand(template, slot, phase, kind, substitutions):
    node = template["slots"][slot]
    config = node["phases"][phase]
    values = {**template["common"], **node["common"], **config["properties"]}
    for i in range(256):
        part = f"P{i:03d}"
        group = "first" if i < 128 else "second"
        for suffix, value in config.get("partitions", {}).get(group, {}).items():
            values[f"{kind}.common.nodeRuntime.freshE1.{part}.{suffix}"] = value.replace("@PARTITION@", part)
    for key, value in values.items():
        def replace(match):
            return substitutions[match.group()]
        values[key] = re.sub(r"@[A-Z_]+@", replace, value)
    return values


def prepare(out, zk_port, voter_service_ports=None):
    if not re.fullmatch(r"sim-demo-[0-9]{8}-[0-9]{6}", out.name):
        raise ValueError("Expected a new sim-demo-YYYYMMDD-HHMMSS directory")
    if not 1 <= zk_port <= 65535:
        raise ValueError("Invalid ZooKeeper port")
    os.umask(0o077)
    out.mkdir(mode=0o700)
    namespace = "/otc/" + out.name
    credentials = common.provision_control_identities(out)
    common.new_demo_signers(out)
    recovery = {slot: recovery_keys() for slot in common.SLOTS}
    manifests = out / "common/tools/manifests"
    manifests.mkdir(parents=True)
    for kind, service in common.SERVICES.items():
        template = json.loads((SCRIPT_DIR.parent / f"config/simulation-common/{kind}.json").read_text())
        (manifests / f"{kind}-e1-recovering.manifest").write_text(manifest(service))
        for slot in common.SLOTS:
            peer = "B" if slot == "A" else "A"
            subs = {"@NAMESPACE@": namespace, "@ZK_ADDRESS@": f"127.0.0.1:{zk_port}",
                    "@OWNER_TOKEN@": secrets.token_hex(32),
                    "@LOCAL_HEAD_SECRET@": base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
                    "@LOCAL_PRIVATE_KEY@": recovery[slot][0], "@PEER_PUBLIC_KEY@": recovery[peer][1]}
            for phase in template["slots"][slot]["phases"]:
                properties = expand(template, slot, phase, kind, subs)
                properties.update(common.common_replication_settings(kind, slot, phase))
                discovery_port = f"{kind}.common.gatewayDiscovery.port"
                if voter_service_ports is not None and discovery_port in properties:
                    properties[discovery_port] = str(voter_service_ports[kind, slot])
                properties.update({f"{kind}.common.control.zkUser": f"t554-{kind}",
                                   f"{kind}.common.control.zkPassword": credentials[kind]})
                if phase == "hostready":
                    prefix = f"{kind}.common.nodeRuntime."
                    properties.update({prefix + key: value for key, value in {
                        "automaticRecovery": "true", "witnessRoot": common.HA_WITNESS,
                        "signedSourceHmacDir": common.HA_SOURCE_AUTH, "peerDataRoot": common.HA_PEER,
                        "recoveryWatchMs": "200", "snapshotSweepMs": "300000" if kind == "trade" else "60000",
                        "originalHomeLedgerDir": f"{common.VOLUMES['born']}/{service}/original-home"
                    }.items()})
                    if kind == "order":
                        properties.update({"order.orderOnly.certifiedDefault.enabled": "true",
                                           "order.projection.enabled": "true"})
                directory = out / "common" / f"config-{phase}" / kind / slot
                directory.mkdir(parents=True)
                header = "[Cron]\n" if kind == "trade" else ""
                (directory / "application.properties").write_text(
                    header + "".join(f"{key}={value}\n" for key, value in sorted(properties.items())))
        common.configure_common_witness(out / "common", kind, namespace, str(zk_port), credentials[kind + "-reader"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--zk-port", type=int, default=49181)
    args = parser.parse_args()
    prepare(args.directory.absolute(), args.zk_port)
