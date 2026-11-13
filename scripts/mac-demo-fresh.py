#!/usr/bin/env python3
"""Fresh Mac development generation, using the existing signed Common bootstrap."""
import argparse
import base64
import concurrent.futures
import fcntl
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
LOCAL = Path.home() / ".opentradingcore"
PREVIOUS = "t549-fresh-20261108-r1"
SERVICES = {"order": "OrderSvr", "trade": "TradeSvr"}
SLOTS = ("A", "B")
INFRA = ("mysql", "clickhouse", "zookeeper")
APPS = ("gateway", "loginsvr", "managersvr", "adminsvr", "mdsvr", "apssvr")
PROJECTION = "projectionsvr"
SUPPORT_IMAGES = {
    PROJECTION: ("MAC_DEMO_PROJECTION_IMAGE", "local/otc-t454-projectionsvr:common-zk-rejoin"),
    "robotsvr": ("MAC_DEMO_ROBOT_IMAGE", "local/otc-t438-robotsvr:prewal-auth-refresh"),
    "liqsvr": ("MAC_DEMO_LIQ_IMAGE", "local/otc-t252-liqsvr:installed-image"),
}
VOLUMES = {"born": "/srv/dc/data/t549-born", "ready": "/srv/dc/data/t549-ready-v1",
           "business": "/srv/dc/data/t549-business-v1"}
HA_WITNESS = "/srv/dc/data/t554-witness"
HA_SOURCE_AUTH = "/srv/dc/data/t554-source-auth"
HA_PEER = "/srv/dc/data/t554-peer"
HA_WITNESS_SETTINGS = "/run/common-witness"
DOCKER_LOG_OPTIONS = ("--log-driver", "json-file", "--log-opt", "max-size=50m", "--log-opt", "max-file=5")
MIN_DOCKER_FREE_BYTES = 2 * 1024 ** 3
MIN_HOST_FREE_BYTES = 8 * 1024 ** 3


def run(*args, capture=False, **options):
    return subprocess.run(args, check=True, text=True, capture_output=capture, **options)


def read(*args):
    return run(*args, capture=True).stdout.strip()


def require_docker_space(min_host_free_bytes=MIN_HOST_FREE_BYTES):
    host_available = shutil.disk_usage(LOCAL).free
    if host_available < min_host_free_bytes:
        raise RuntimeError(f"Mac storage has {host_available // 1024 ** 2} MiB available; "
                           f"need at least {min_host_free_bytes // 1024 ** 3} GiB "
                           "for the selected Mac Demo operation")
    root = read("docker", "info", "--format", "{{.DockerRootDir}}")
    if not root.startswith("/"):
        raise RuntimeError("Could not identify the local Colima Docker data directory")
    blocks, block_size = map(int, read("colima", "ssh", "--", "stat", "-f", "-c", "%a %S", "--", root).split())
    available = blocks * block_size
    if available < MIN_DOCKER_FREE_BYTES:
        raise RuntimeError(f"Colima Docker storage has {available // 1024 ** 2} MiB available; "
                           "need at least 2 GiB before starting a new Mac Demo deployment or fault")


def restore_container_restart_policy(container):
    policy = container["HostConfig"]["RestartPolicy"]
    setting = policy["Name"] or "no"
    retries = policy.get("MaximumRetryCount", 0)
    if setting == "on-failure" and retries:
        setting += f":{retries}"
    run("docker", "update", "--restart", setting, container["Id"], capture=True)


def env_pairs(file):
    return dict(line.split("=", 1) for line in file.read_text().splitlines()
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", line))


def verified_common_release(images):
    status, result = images.get("common_fault_verification"), images.get("common_fault_result")
    if status is None and result is None:
        return False
    if status != "PASS" or not result or not Path(result).is_absolute():
        raise RuntimeError("Expected the exact passed Common fault verification directory")
    evidence = Path(result)
    identity = env_pairs(evidence / "candidate.env")
    transcript = (evidence / "failover.log").read_bytes()
    seal = json.loads((evidence / "verification.seal.json").read_text())
    if ((evidence / "status").read_text().strip() != "PASS"
            or identity.get("common_revision") != images.get("common_revision")
            or identity.get("common_sha256") != images.get("common_sha256")
            or seal.get("common_revision") != images.get("common_revision")
            or seal.get("common_sha256") != images.get("common_sha256")
            or seal.get("transcript_sha256") != hashlib.sha256(transcript).hexdigest()
            or seal.get("both_directions_and_repeated_home") is not True
            or (images.get("common_interrupted_rearm_verified") == "true"
                and (seal.get("interrupted_local_rearm") is not True
                     or transcript.splitlines().count(
                         b"T554_INTERRUPTED_LOCAL_TO_STRICT_SIGNED_STAGE_RESUMED_PASS") != 1))
            or hashlib.sha256((evidence / "common.jar").read_bytes()).hexdigest() != images["common_sha256"]
            or b"OK (1 test)" not in transcript.splitlines()):
        raise RuntimeError("Common physical fault evidence does not match this image build")
    return True


def selected_client_ack_policy(images, selected):
    if selected not in ("STRICT_QUORUM", "LOCAL_DURABLE_ASYNC"):
        raise ValueError("Expected STRICT_QUORUM or LOCAL_DURABLE_ASYNC client confirmation")
    if selected == "LOCAL_DURABLE_ASYNC":
        if not verified_common_release(images):
            raise RuntimeError("Normal asynchronous confirmation requires exact Common physical verification")
        seal = json.loads((Path(images["common_fault_result"]) / "verification.seal.json").read_text())
        scenarios = {"normal-dual-async", "normal-dual-async-primary-kill", "normal-dual-async-backup-expiry"}
        if (seal.get("normal_dual_async") is not True
                or seal.get("normal_dual_async_max_pending_per_partition") != 1
                or seal.get("normal_dual_async_recovery_head") != "backup_certified_committed"
                or not scenarios <= seal.get("live_poison_recovery_evidence", {}).keys()):
            raise RuntimeError("Common verification is missing normal asynchronous recovery evidence")
    return selected


def client_ack_environment(original, selected):
    if selected not in ("STRICT_QUORUM", "LOCAL_DURABLE_ASYNC"):
        raise ValueError("Unknown Common client confirmation policy")
    property_name = "common.certified.clientAckPolicy"
    option = r"-Dcommon\.certified\.clientAckPolicy"
    pattern = re.compile(r"(?<!\S)(?:\"" + option + r"(?:=[^\"]*)?\"|'" + option
                         + r"(?:=[^']*)?'|" + option
                         + r"(?:=(?:\"[^\"]*\"|'[^']*'|[^\s\"']*))?)(?=\s|$)")
    forwarded = []
    tool_options = ""
    for entry in original:
        key, value = entry.split("=", 1)
        if key not in {"JAVA_OPTS", "EXTRA_JAVA_OPTS", "JAVA_TOOL_OPTIONS", "MAIN_CLASS", "SERVICE_NAME", "APP_ARGS"}:
            continue
        if key in {"JAVA_OPTS", "EXTRA_JAVA_OPTS", "JAVA_TOOL_OPTIONS"}:
            value = pattern.sub("", value).strip()
            if property_name in value:
                raise RuntimeError("Inherited Common client confirmation option has ambiguous quoting")
        if key == "JAVA_TOOL_OPTIONS":
            tool_options = value
        else:
            forwarded.append(key + "=" + value)
    forwarded.append("JAVA_TOOL_OPTIONS=" + (tool_options + " -D" + property_name + "=" + selected).strip())
    return forwarded


def update_properties(content, values):
    for key, value in values.items():
        content = re.sub(rf"^{re.escape(key)}=.*(?:\n|$)", "", content, flags=re.M)
        content = content.rstrip("\n") + f"\n{key}={value}\n"
    return content


def common_replication_settings(kind, slot, phase):
    if kind not in SERVICES or slot not in SLOTS or phase not in (
            "birth", "install", "home", "stage", "hostready"):
        raise ValueError("Expected one actual Mac Common voter and bootstrap phase")
    base = (28220 if phase == "hostready" else 28120) + (2 if kind == "trade" else 0)
    service = SERVICES[kind]
    prefix = kind + ".common.nodeRuntime."
    return {
        prefix + "bindPort": str(base + (slot == "B")),
        prefix + "nettyPeers": f"{service}A@127.0.0.1:{base},{service}B@127.0.0.1:{base + 1}",
    }


def require_common_replication_ports(phase):
    ports = sorted(int(common_replication_settings(kind, slot, phase)[kind + ".common.nodeRuntime.bindPort"])
                   for kind in SERVICES for slot in SLOTS)
    # Probe in the same VM network namespace as the physical voters. The
    # bootstrap and runtime endpoints stay below the VM ephemeral range.
    script = "import pathlib, socket\nports = " + repr(ports) + "\n" + """
low, high = map(int, pathlib.Path('/proc/sys/net/ipv4/ip_local_port_range').read_text().split())
sockets = []
try:
    for port in ports:
        if low <= port <= high:
            raise RuntimeError('Common port overlaps the VM ephemeral range: ' + str(port))
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sockets.append(probe)
        try:
            probe.bind(('0.0.0.0', port))
        except OSError as error:
            raise RuntimeError('Common replication endpoint is occupied: ' + str(port)) from error
finally:
    for probe in sockets:
        probe.close()
print('COMMON_INTERNAL_ENDPOINTS_AVAILABLE ' + ','.join(map(str, ports)))
"""
    run("colima", "ssh", "--", "python3", "-", input=script, capture=True)


def owned_mount(volume, subpath, target, read_only=False):
    if any("," in str(value) for value in (volume, subpath, target)):
        raise RuntimeError("Invalid character in Common volume mount")
    return ["--mount", f"type=volume,source={volume},target={target},volume-subpath={subpath}"
            + (",readonly" if read_only else "")]


def prepare_voter_runtime_storage(generation, kind, slot, image):
    volume = f"{generation}-{kind}-{slot.lower()}-runtime"
    # The existing entrypoint links each service's data/log to these roots.
    paths = {"data": "/srv/dc/data", "log": "/srv/dc/log"}
    run("docker", "volume", "create", "--label", f"otc.mac.demo.generation={generation}", volume,
        capture=True)
    run("docker", "run", "--rm", "--network", "none", "--entrypoint", "mkdir", "--mount",
        f"type=volume,source={volume},target=/runtime,volume-nocopy", image, "-p",
        *(f"/runtime/{path}" for path in paths), capture=True)
    return [argument for path, target in paths.items()
            for argument in owned_mount(volume, path, target)]


def bounded_application_logging(content):
    appender = re.compile(r"^log4j\.appender\.file\s*=\s*(\S+)\s*$", re.M)
    matches = list(appender.finditer(content))
    supported = {"org.apache.log4j." + name for name in
                 ("FileAppender", "DailyRollingFileAppender", "RollingFileAppender")}
    if len(matches) != 1 or matches[0].group(1) not in supported:
        raise RuntimeError("Expected one supported application file logger")
    content = appender.sub("log4j.appender.file=org.apache.log4j.RollingFileAppender", content)
    content = re.sub(r"^log4j\.appender\.file\.(?:DatePattern|MaxFileSize|MaxBackupIndex)\s*=.*\n?",
                     "", content, flags=re.M)
    return (content.rstrip("\n") + "\nlog4j.appender.file.MaxFileSize=50MB\n"
            "log4j.appender.file.MaxBackupIndex=5\n")


def public_pins(node):
    paths = [m["Source"] for m in node["Mounts"] if m["Destination"] == "/read-only-original-rsa/public"
             and m["Type"] == "bind" and not m["RW"]]
    if len(paths) != 1:
        raise RuntimeError("Expected exactly one read-only Demo public signer mount")
    return Path(paths[0])


def rotate_recovery_rsa_keys(configuration_root):
    """Keep legacy recovery peer relationships while giving each generation fresh keys."""
    field = re.compile(
        r"^((?:order|trade)\.cluster\.recovery\.(?:head\.rsaPrivateKeyBase64|"
        r"read\.readerPublicKeyBase64|replica\.autoWarm\.(?:readerRsaPrivateKeyBase64|"
        r"sourcePublicKeyBase64)))=([A-Za-z0-9+/=]+)$", re.M)
    files = {path: path.read_text() for path in sorted(configuration_root.rglob("*.properties"))
             if path.is_file()}
    private_values = {match.group(2) for text in files.values() for match in field.finditer(text)
                      if match.group(1).endswith("PrivateKeyBase64")}
    replacements, rotations = {}, {}
    for encoded in sorted(private_values):
        public = subprocess.run(["openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"],
                                input=base64.b64decode(encoded, validate=True), capture_output=True,
                                check=True, timeout=30).stdout
        previous = hashlib.sha256(public).hexdigest()
        if previous not in rotations:
            pem = subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048"],
                                 capture_output=True, check=True, timeout=30).stdout
            private = subprocess.run(["openssl", "pkcs8", "-topk8", "-nocrypt", "-outform", "DER"],
                                     input=pem, capture_output=True, check=True, timeout=30).stdout
            fresh_public = subprocess.run(["openssl", "pkey", "-pubout", "-outform", "DER"],
                                          input=pem, capture_output=True, check=True, timeout=30).stdout
            rotations[previous] = (base64.b64encode(private).decode(), base64.b64encode(fresh_public).decode())
        replacements[encoded] = rotations[previous][0]

    def replace(match):
        key, encoded = match.groups()
        if key.endswith("PrivateKeyBase64"):
            updated = replacements.get(encoded)
            if updated is None:
                raise RuntimeError("Recovery private-key rotation mapping is incomplete")
        else:
            previous = hashlib.sha256(base64.b64decode(encoded, validate=True)).hexdigest()
            pair = rotations.get(previous)
            updated = pair[1] if pair else encoded
        return key + "=" + updated

    for path, text in files.items():
        updated = field.sub(replace, text)
        if updated != text:
            path.write_text(updated)
    return [{"previous_public_sha256": previous,
             "current_public_sha256": hashlib.sha256(base64.b64decode(pair[1])).hexdigest()}
            for previous, pair in sorted(rotations.items())]


def configure_common_witness(config_root, kind, namespace, zk_port):
    service = SERVICES[kind]
    runtime_key = f"{kind}.common.nodeRuntime."
    properties = [dict(line.split("=", 1) for line in
                       (config_root / "config-hostready" / kind / slot / "application.properties").read_text().splitlines()
                       if re.match(r"^[A-Za-z_][A-Za-z0-9_.-]*=", line)) for slot in SLOTS]

    def member_value(key, slot):
        a, b = (item[runtime_key + key] for item in properties)
        if a != b:
            raise RuntimeError(f"{service} disagrees on Common physical members: {key}")
        entries = a.split(",")
        if len(entries) != 2 or any(not re.fullmatch(r"[A-Za-z0-9]+@[A-Za-z0-9_.-]+", entry) for entry in entries):
            raise RuntimeError(f"Invalid {service} Common physical members: {key}")
        members = dict(entry.split("@", 1) for entry in entries)
        if set(members) != {service + s for s in SLOTS} or len(set(members.values())) != 2:
            raise RuntimeError(f"Expected distinct {service} A/B physical identities")
        return members[service + slot]

    root = config_root / "ha" / kind
    for path in (root / "identity", root / "public", root / "source-auth"):
        path.mkdir(parents=True)
    pem = subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048"],
                         check=True, capture_output=True).stdout
    subprocess.run(["openssl", "pkcs8", "-topk8", "-nocrypt", "-outform", "DER", "-out",
                    str(root / "identity/witness.pk8")], input=pem, capture_output=True, check=True)
    subprocess.run(["openssl", "pkey", "-pubout", "-outform", "DER", "-out",
                    str(root / "public/witness.pub.der")], input=pem, capture_output=True, check=True)
    for slot in SLOTS:
        (root / "source-auth" / f"{service}{slot}.hmac").write_text(secrets.token_hex(32) + "\n")
    values = {
        "service": service, "namespace": f"{namespace}/{kind}", "birth.root": VOLUMES["born"],
        "birth.signer": service + "A", "witness.node": service + "Witness",
        "witness.privateKey": f"{HA_WITNESS_SETTINGS}/identity/witness.pk8",
        "witness.publicKey": f"{HA_WITNESS}/witness.pub.der", "receipt.root": f"{HA_WITNESS}/receipts",
        "zk.hosts": f"127.0.0.1:{zk_port}", "wal.maxBytes": 8 * 1024 ** 3, "pollMillis": 250,
    }
    for slot, props in zip(SLOTS, properties):
        node = service + slot
        prefix = f"voter.{slot.lower()}."
        node_root = f"/srv/dc/data/t554-voter-{slot.lower()}"
        expected_data = f"{VOLUMES['ready']}/{service}/{node}"
        if props[runtime_key + "dataRoot"] != expected_data or props[runtime_key + "freshE1.birthRoot"] != VOLUMES["born"]:
            raise RuntimeError(f"Unexpected signed data or birth root for {node}")
        values.update({prefix + key: value for key, value in {
            "node": node, "host": member_value("physicalHosts", slot),
            "publicKey": f"/public/{member_value('rsaAliases', slot)}.pub.der", "data": node_root,
            "stages": f"{node_root}/recovery-stages", "installs": f"{node_root}/recovery-installs",
            "snapshots": f"{node_root}/replica-snapshots",
            "snapshotMaxBytes": int(props.get(runtime_key + "snapshotMaxBytes", "67108864")),
        }.items()})
    (root / "witness.properties").write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    return root


def report(message):
    print(f"[mac-demo] {message}", flush=True)


def until(predicate, description, timeout=180):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(2)
    raise RuntimeError(f"Timed out: {description}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", help="New absolute run directory")
    parser.add_argument("build", type=Path, help="Directory from build-mac-demo-core.sh")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify-business", action="store_true", help="Verify the new Demo before releasing rollback")
    parser.add_argument("--template", type=Path, default=LOCAL / "t549-fresh-business-demo")
    args = parser.parse_args()
    out = Path(args.run)
    if (not out.is_absolute() or out.exists() or not re.fullmatch(r"mac-demo-[a-z0-9-]+", out.name)
            or read("uname", "-s") != "Darwin" or read("docker", "context", "show") != "colima"):
        raise RuntimeError("Use a new mac-demo-* directory on the local Colima context")
    generation = out.name
    namespace = "/otc/" + generation
    os.umask(0o077)
    lock = (LOCAL / ".mac-demo-fresh.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise RuntimeError("Another Mac Demo deployment is in progress") from exc
    if args.apply:
        require_docker_space()
    for key in (*VOLUMES, *(f"{kind}-witness" for kind in SERVICES)):
        probe = subprocess.run(["docker", "volume", "inspect", f"{generation}-{key}"],
                               capture_output=True)
        if probe.returncode == 0:
            raise RuntimeError(f"Existing storage for {generation}; choose a new generation")
    if read("docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={generation}"):
        raise RuntimeError(f"Existing Compose project for {generation}")
    bootstrap = args.template / "common-bootstrap"
    images = env_pairs(args.build / "images.env")
    automatic_common = verified_common_release(images)
    client_ack_policy = selected_client_ack_policy(images, os.environ.get("MAC_DEMO_CLIENT_ACK_POLICY", "STRICT_QUORUM"))
    recovery_watch_ms = os.environ.get("MAC_DEMO_RECOVERY_WATCH_MS", "200")
    if not re.fullmatch(r"[0-9]{3,4}", recovery_watch_ms) or not 100 <= int(recovery_watch_ms) <= 5000:
        raise RuntimeError("Common recovery watch interval must be 100–5000 milliseconds")
    image_refs = {kind: images[f"{kind}_IMAGE"] for kind in SERVICES}
    image_ids = {kind: read("docker", "image", "inspect", "-f", "{{.Id}}", image)
                 for kind, image in image_refs.items()}
    pairs = [(kind, slot) for kind in SERVICES for slot in SLOTS]
    active_projects = read("docker", "inspect", "-f", '{{index .Config.Labels "com.docker.compose.project"}}',
                           "dc-saas-gateway", "dc-saas-mysql").splitlines()
    mac_projects = {project for project in active_projects if re.fullmatch(r"mac-demo-[0-9]{8}-[0-9]{6}", project)}
    active_generation = None
    if mac_projects:
        if len(active_projects) != 2 or active_projects[0] != active_projects[1]:
            raise RuntimeError("Gateway and MySQL disagree on the active Mac Demo generation")
        active_generation = active_projects[0]
        # The stopped voter's launch and signer mounts still belong to this
        # generation. Preserve it without borrowing an unrelated running node.
        old_core = {(kind, slot): f"{active_generation}-{kind}-{slot.lower()}-hostready" for kind, slot in pairs}
    else:
        running = read("docker", "ps", "--format", "{{.Names}}").splitlines()
        old_core = {}
        for kind, slot in pairs:
            suffix = f"-{kind}-{slot.lower()}-hostready"
            found = [name for name in running if name == "otc-t549" + suffix
                     or (name.endswith(suffix) and re.fullmatch(r"mac-demo-[0-9]{8}-[0-9]{6}", name[:-len(suffix)]))]
            if len(found) != 1:
                raise RuntimeError(f"Expected exactly one active {kind}/{slot} Mac Demo voter")
            old_core[kind, slot] = found[0]
    old_core_names = list(old_core.values())
    old_names = [f"dc-saas-{name}" for name in (*INFRA, *APPS)] + old_core_names
    all_names = set(read("docker", "ps", "-a", "--format", "{{.Names}}").splitlines())
    old_witness_names = []
    for kind in SERVICES:
        name = old_core[kind, "A"][:-len(f"-{kind}-a-hostready")] + f"-{kind}-witness"
        if name in all_names:
            old_witness_names.append(name)
    old_names.extend(old_witness_names)
    support_names = [f"dc-saas-{name}" for name in SUPPORT_IMAGES
                     if subprocess.run(["docker", "inspect", f"dc-saas-{name}"],
                                       capture_output=True).returncode == 0]
    old_names.extend(support_names)
    old = {item["Name"].lstrip("/"): item for item in json.loads(read("docker", "inspect", *old_names))}
    if any(not old[f"dc-saas-{name}"]["State"]["Running"] for name in (*INFRA, *APPS)):
        raise RuntimeError("Expected the reviewed active Mac Demo containers")
    running_old_core = [name for name in old_core_names if old[name]["State"]["Running"]]
    if active_generation:
        if any(old[name]["Config"]["Labels"].get("otc.mac.demo.generation") != active_generation
               or old[name]["State"]["Status"] not in ("running", "exited") for name in old_core_names):
            raise RuntimeError("Expected the exact active generation's two retained voters per service")
        # An exact physically verified replacement can start from a failed Demo.
        # Retain the failed voters and their volumes as the original rollback state.
        if not automatic_common and any(not any(old_core[kind, slot] in running_old_core for slot in SLOTS)
                                        for kind in SERVICES):
            raise RuntimeError("Recovering a fully stopped service requires a physically verified Common release")
    if not active_generation and len(running_old_core) != len(old_core_names):
        raise RuntimeError("Expected all reviewed legacy Mac Demo voters to be running")
    running_support = [name for name in support_names if old[name]["State"]["Running"]]
    running_old_witnesses = [name for name in old_witness_names if old[name]["State"]["Running"]]
    embedded_jars = [("Common", "common", "com.app.common-mac-demo.jar")]
    if "shared_sha256" in images:
        embedded_jars.append(("shared business", "shared", "com.app.dc-mac-demo.jar"))
    checked_images = [(service, image_refs[kind]) for kind, service in SERVICES.items()]
    if "md_IMAGE" in images:
        checked_images.append(("MDSvr", images["md_IMAGE"]))
    if "gateway_IMAGE" in images:
        checked_images.append(("GW", images["gateway_IMAGE"]))
    for service, image in checked_images:
        for title, jar_kind, file_name in embedded_jars:
            expected_sha = images[f"{jar_kind}_sha256"]
            if read("docker", "image", "inspect", "-f",
                    '{{index .Config.Labels "dc.' + jar_kind + '.jar.sha256"}}',
                    image) != expected_sha:
                raise RuntimeError(f"Wrong {title} image identity: {image}")
            checksum = read("docker", "run", "--rm", "--network", "none", "--entrypoint", "sha256sum",
                            image, f"/srv/dc/dc/{service}/lib/{file_name}").split()[0]
            if checksum != expected_sha:
                raise RuntimeError(f"Wrong {title} bytes: {image}")

    out.mkdir()
    if automatic_common:
        shutil.copyfile(args.build / "images.env", out / "common-release.env")
        with (out / "common-release.env").open("a") as release:
            release.write(f"\nclient_ack_policy={client_ack_policy}\n")
    runtime = out / "runtime"
    gateway = old["dc-saas-gateway"]
    previous_generation = gateway["Config"]["Labels"].get("com.docker.compose.project", "")
    control = Path(next(m["Source"] for m in gateway["Mounts"] if m["Destination"] == "/srv/dc/control"))
    shutil.copytree(control, runtime / "control")
    projection_config = runtime / "control/overrides/ProjectionSvr/config/application.properties"
    projection = projection_config.read_text()
    for key in ("projection.binary.enabled", "projection.trade.binary.enabled"):
        if not re.search(rf"^{re.escape(key)}=(?:true|false)$", projection, re.M):
            raise RuntimeError(f"Missing ProjectionSvr setting: {key}")
        projection = re.sub(rf"^{re.escape(key)}=(?:true|false)$", key + "=true", projection, flags=re.M)
    readmodel = "trade.financial.readmodel.enabled"
    if re.search(rf"^{re.escape(readmodel)}=", projection, re.M):
        projection = re.sub(rf"^{re.escape(readmodel)}=.*$", readmodel + "=true", projection, flags=re.M)
    else:
        projection = projection.rstrip("\n") + "\n" + readmodel + "=true\n"
    projection_config.write_text(projection)
    for child in ("data/mysql", "data/clickhouse", "data/zookeeper", "log/clickhouse", "log/zookeeper"):
        (runtime / child).mkdir(parents=True)
    original_env = (args.template / "t549-services.env").read_text()
    # Carry forward the reviewed running quotas when replacing this Demo.
    # Keep credentials and namespace settings sourced from the template.
    for service, key in (("gateway", "GW_CPU_LIMIT"), ("mdsvr", "MDSVR_CPU_LIMIT"),
                         ("apssvr", "APSSVR_CPU_LIMIT"), ("adminsvr", "ADMINSVR_CPU_LIMIT"),
                         ("mysql", "MYSQL_CPU_LIMIT"), ("projectionsvr", "PROJECTIONSVR_CPU_LIMIT")):
        quota = old[f"dc-saas-{service}"]["HostConfig"]["NanoCpus"]
        if quota:
            original_env = update_properties(original_env, {key: str(quota / 1e9)})
    env = out / "demo.env"
    env.write_text(re.sub(r"^(?:DEPLOY_ROOT|COMPOSE_PROJECT_NAME)=.*\n", "", original_env, flags=re.M)
                   + f"\nDEPLOY_ROOT={runtime}\nCOMPOSE_PROJECT_NAME={generation}\n")
    config = env_pairs(env)
    zk_port = config["ZOOKEEPER_PORT"]
    if not zk_port.isdigit():
        raise RuntimeError("Invalid ZooKeeper port")
    config_root = out / "common"
    logging_config = {kind: bounded_application_logging(read(
        "docker", "run", "--rm", "--network", "none", "--entrypoint", "cat", image_ids[kind],
        f"/srv/dc/dc/{service}/config/log4j.ini")) for kind, service in SERVICES.items()}
    for phase in ("birth", "home", "install", "stage", "hostready"):
        for kind, slot in (pairs if phase != "stage" else [(kind, "A") for kind in SERVICES]):
            target = config_root / f"config-{phase}" / kind / slot / "application.properties"
            target.parent.mkdir(parents=True)
            source = bootstrap / f"config-{phase}" / kind / slot / target.name
            content = source.read_text()
            if f"/otc/{PREVIOUS}/{kind}" not in content:
                raise RuntimeError(f"Template is missing the expected signed Common namespace: {source}")
            content = update_properties(content, common_replication_settings(kind, slot, phase))
            if phase == "hostready" and kind == "order":
                # Enable the certified Default execution delivery only in
                # this disposable development generation so its real smoke
                # verifies SQL execution history and MD publication.
                for key in ("order.orderOnly.certifiedDefault.enabled", "order.projection.enabled"):
                    content = re.sub(rf"^{re.escape(key)}=.*\n", "", content, flags=re.M)
                    content = content.rstrip("\n") + f"\n{key}=true\n"
            if phase == "hostready" and automatic_common:
                prefix = f"{kind}.common.nodeRuntime."
                content = update_properties(content, {prefix + key: value for key, value in {
                    "automaticRecovery": "true", "witnessRoot": HA_WITNESS,
                    "signedSourceHmacDir": HA_SOURCE_AUTH, "peerDataRoot": HA_PEER,
                    "recoveryWatchMs": recovery_watch_ms,
                    "snapshotSweepMs": "60000",
                    "originalHomeLedgerDir": f"{VOLUMES['born']}/{SERVICES[kind]}/original-home",
                }.items()})
            target.write_text(content.replace(PREVIOUS, generation))
            target.with_name("log4j.ini").write_text(logging_config[kind])
    rotations = rotate_recovery_rsa_keys(out)
    (out / "recovery-rsa-rotation.json").write_text(json.dumps(rotations, indent=2) + "\n")
    witness_roots = {kind: configure_common_witness(config_root, kind, namespace, zk_port)
                     for kind in SERVICES} if automatic_common else {}
    witness_pins = {}
    for kind, root in witness_roots.items():
        a, b = (public_pins(old[old_core[kind, slot]]) for slot in SLOTS)
        names = re.findall(r"^voter\.[ab]\.publicKey=/public/([A-Za-z0-9_.-]+)$",
                           (root / "witness.properties").read_text(), re.M)
        if len(set(names)) != 2 or any(not (folder / key).is_file()
                                      for folder in (a, b) for key in names) or any(
                                          (a / key).read_bytes() != (b / key).read_bytes() for key in names):
            raise RuntimeError(f"{SERVICES[kind]} voters disagree on the pinned public RSA identities")
        witness_pins[kind] = a
    for file in (runtime / "control").rglob("*"):
        if file.is_file() and file.suffix in {".ini", ".xml", ".properties"}:
            data = file.read_bytes()
            updated = data.replace(f"/otc/{PREVIOUS}".encode(), namespace.encode())
            if re.fullmatch(r"mac-demo-[0-9]{8}-[0-9]{6}", previous_generation):
                updated = updated.replace(f"/otc/{previous_generation}".encode(), namespace.encode())
            if file.name == "log4j.ini":
                updated = bounded_application_logging(updated.decode()).encode()
            if updated != data:
                file.write_bytes(updated)

    tools = config_root / "tools"
    tools.mkdir()
    shutil.copytree(bootstrap / "manifests", tools / "manifests")
    sources = []
    for name in ("T530VirginZkManifestInstaller.java", "T530OriginalE1DualPhysicalGenesisSeal.java"):
        source = tools / name
        source.write_text((bootstrap / "tools" / name).read_text().replace(PREVIOUS, generation))
        sources.append(str(source))
    java_home = Path(read("/usr/libexec/java_home", "-v", "1.8"))
    image_libraries = args.build / "order/image/lib"
    maven_dependencies = args.build / "order/target/dependency"
    dependency_root = maven_dependencies if maven_dependencies.is_dir() else image_libraries
    project_libraries = sorted(path for path in image_libraries.glob("*.jar")
                               if path.name.startswith(("com.app.common-", "com.app.dc-")))
    third_party_libraries = sorted(path for path in dependency_root.glob("*.jar")
                                   if not path.name.startswith(("com.app.common-", "com.app.dc-")))
    classpath = os.pathsep.join(str(path) for path in (*project_libraries, *third_party_libraries))
    run(str(java_home / "bin/javac"), "-cp", classpath,
        "-d", str(tools), *sources)

    # Pin ancillary services to the precise images that serve this Mac today.
    # Compose supplies all normal container wiring. The retired project is
    # preserved under its existing labels and never selected by this project.
    override = out / "compose.images.json"
    pinned = {}
    for name in (*INFRA, *APPS):
        reference = f"local/{generation}-{name}:retained"
        image = old[f"dc-saas-{name}"]["Image"]
        if name == "mdsvr" and "md_IMAGE" in images:
            image = images["md_IMAGE"]
            reference = f"local/{generation}-{name}:built"
        if name == "gateway" and "gateway_IMAGE" in images:
            image = images["gateway_IMAGE"]
            reference = f"local/{generation}-{name}:built"
        run("docker", "image", "tag", image, reference)
        pinned[name] = {"image": reference}
    for name, (setting, default) in SUPPORT_IMAGES.items():
        reference = f"local/{generation}-{name}:retained"
        image = images.get(setting) if name == PROJECTION else None
        if image is not None:
            projection_sha = images.get("projection_history_sha256")
            if (not projection_sha or not re.fullmatch(r"[0-9a-f]{64}", projection_sha)
                    or read("docker", "image", "inspect", "-f",
                            '{{index .Config.Labels "dc.demo.projection.history.sha256"}}', image) != projection_sha):
                raise RuntimeError("Projection image identity differs from the certified build")
            projection_check = read("docker", "run", "--rm", "--network", "none", "--entrypoint", "sh",
                                    image, "-ec", "cd /srv/dc/dc/ProjectionSvr/classes && "
                                    "sha256sum -c ../t554-compiled.sha256 >/dev/null && "
                                    "sha256sum ../t554-compiled.sha256").split()[0]
            if projection_check != projection_sha:
                raise RuntimeError("Projection class bytes differ from the certified build")
        else:
            previous = old.get(f"dc-saas-{name}")
            image = os.environ.get(setting, previous["Image"] if previous else default)
        run("docker", "image", "tag", read("docker", "image", "inspect", "-f", "{{.Id}}", image), reference)
        pinned[name] = {"image": reference}
    override.write_text(json.dumps({"services": pinned}))
    compose = ("docker", "compose", "-p", generation, "--env-file", str(env),
               "-f", str(REPO / "compose.yaml"), "-f", str(override))
    run(*compose, "config", "--quiet")
    old_manifest = out / "retired-containers.json"
    rollback_names = {name: f"{generation}-retired-{name}" for name in old_names}
    old_manifest.write_text(json.dumps({name: {"id": old[name]["Id"], "retired": rollback_names[name],
                                               "running": old[name]["State"]["Running"],
                                               "restart_policy": old[name]["HostConfig"]["RestartPolicy"]}
                                       for name in old_names}, indent=2))
    report(f"Prepared {generation}, Common {images['common_sha256'][:12]}, client confirmation {client_ack_policy}")
    if not args.apply:
        report("Prepared configuration only. Supply --apply with a new run directory to replace the Mac Demo.")
        return

    def docker_name(phase, kind, slot):
        return f"{generation}-{kind}-{slot.lower()}-{phase}"

    def start(phase, kind, slot):
        old_node = old[old_core[kind, slot]]
        service = SERVICES[kind]
        name = docker_name(phase, kind, slot)
        config_file = config_root / f"config-{phase}" / kind / slot / "application.properties"
        restart_policy = "on-failure" if phase == "hostready" and automatic_common else "no"
        flags = ["--name", name, "--network", "host", "--restart", restart_policy, *DOCKER_LOG_OPTIONS, "--label",
                 f"otc.mac.demo.generation={generation}"]
        for key, flag in (("Memory", "--memory"), ("NanoCpus", "--cpus")):
            value = old_node["HostConfig"][key]
            if value:
                flags.extend([flag, str(value if key == "Memory" else value / 1e9)])
        phase_policy = client_ack_policy if phase == "hostready" and automatic_common else "STRICT_QUORUM"
        for entry in client_ack_environment(old_node["Config"]["Env"], phase_policy):
            flags.extend(["-e", entry])
        flags.extend(["--label", f"otc.common.client_ack_policy={phase_policy}"])
        flags.extend(voter_runtime_mounts[kind, slot])
        for mount in old_node["Mounts"]:
            dest = mount["Destination"]
            if dest.startswith("/read-only-original-rsa/"):
                if mount["Type"] != "bind" or mount["RW"]:
                    raise RuntimeError("Expected independent read-only Demo signer mounts")
                flags.extend(["-v", f"{mount['Source']}:{dest}:ro"])
        if phase == "hostready" and automatic_common:
            volume = f"{generation}-ready"
            peer = "B" if slot == "A" else "A"
            local = f"{service}/{service}{slot}"
            flags.extend(owned_mount(volume, local, f"{VOLUMES['ready']}/{local}"))
            flags.extend(owned_mount(volume, f"{service}/{service}{peer}", HA_PEER, read_only=True))
            root = witness_roots[kind]
            flags.extend(["-v", f"{generation}-born:{VOLUMES['born']}:ro", "-v",
                          f"{root}/public/witness.pub.der:{HA_WITNESS}/witness.pub.der:ro", "-v",
                          f"{generation}-{kind}-witness:{HA_WITNESS}/receipts:ro", "-v",
                          f"{root}/source-auth:{HA_SOURCE_AUTH}:ro"])
        else:
            for key, dest in VOLUMES.items():
                flags.extend(["-v", f"{generation}-{key}:{dest}"])
        flags.extend(["-v", f"{runtime}/control:/srv/dc/control:ro", "-v",
                      f"{config_file}:/srv/dc/dc/{service}/config/application.properties:ro", "-v",
                      f"{config_file.with_name('log4j.ini')}:/srv/dc/dc/{service}/config/log4j.ini:ro"])
        if phase == "hostready" and automatic_common:
            (config_file.parent / "voter-launch.json").write_text(json.dumps({"flags": flags, "image": image_ids[kind]}))
        run("docker", "run", "-d", *flags, image_ids[kind], capture=True)
        return name

    def start_witness(kind):
        service, root = SERVICES[kind], witness_roots[kind]
        name = f"{generation}-{kind}-witness"
        flags = ["--name", name, "--network", "host", "--restart", "no", *DOCKER_LOG_OPTIONS,
                 "--memory", "512m", "--label",
                 f"otc.mac.demo.generation={generation}", "-v", f"{generation}-born:{VOLUMES['born']}:ro",
                 "-v", f"{runtime}/control:/control:ro", "-v", f"{witness_pins[kind]}:/public:ro", "-v",
                 f"{root}/identity:{HA_WITNESS_SETTINGS}/identity:ro", "-v",
                 f"{root}/witness.properties:{HA_WITNESS_SETTINGS}/witness.properties:ro", "-v",
                 f"{root}/public/witness.pub.der:{HA_WITNESS}/witness.pub.der:ro", "-v",
                 f"{generation}-{kind}-witness:{HA_WITNESS}/receipts"]
        for slot in SLOTS:
            flags.extend(owned_mount(f"{generation}-ready", f"{service}/{service}{slot}",
                                     f"/srv/dc/data/t554-voter-{slot.lower()}", read_only=True))
        run("docker", "run", "-d", *flags, "--entrypoint", "java", image_ids[kind], "-Xms32m", "-Xmx384m",
            "-Djava.security.auth.login.config=/control/jaas.ini", "-cp", f"/srv/dc/dc/{service}/lib/*",
            "com.app.common.replication.CommonCertifiedFirstReadyE2WitnessProcess",
            f"{HA_WITNESS_SETTINGS}/witness.properties", capture=True)
        return name

    def start_phase(phase, selected=pairs):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            return list(executor.map(lambda item: start(phase, *item), selected))

    def logs(name):
        result = subprocess.run(["docker", "logs", name], text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, check=True)
        return result.stdout

    def wait_log(nodes, marker, timeout=180):
        def logged():
            complete = True
            for node in nodes:
                if marker in logs(node):
                    continue
                status = read("docker", "inspect", "-f", "{{.State.Status}}", node)
                if status == "exited":
                    raise RuntimeError(f"{node} exited before {marker}. See docker logs {node}")
                complete = False
            return complete
        until(logged, f"{marker} in {nodes}", timeout)

    def leases_released(selected):
        for kind in {kind for kind, _ in selected}:
            result = read("docker", "exec", "dc-saas-zookeeper", "zkCli.sh",
                          "-server", f"127.0.0.1:{zk_port}", "ls", f"{namespace}/{kind}/leases")
            matches = [line.strip() for line in result.splitlines()
                       if re.fullmatch(r"\[[A-Za-z0-9_, .-]*\]", line.strip())]
            if not matches or any(SERVICES[kind] + slot in matches[-1]
                                  for group, slot in selected if group == kind):
                return False
        return True

    def wait_lease_release(selected):
        until(lambda: leases_released(selected), f"ZooKeeper leases released for {selected}", 75)

    def stop(nodes):
        if nodes:
            run("docker", "stop", "--time", "8", *nodes, capture=True)

    def sql(text):
        run("docker", "exec", "-i", "dc-saas-mysql", "sh", "-c",
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --protocol=TCP '
            '-h127.0.0.1 -P"$MYSQL_TCP_PORT" -uroot dc', input=text, capture=True)

    def rollback():
        new_nodes = read("docker", "ps", "-aq", "--filter", f"label=otc.mac.demo.generation={generation}").splitlines()
        new_services = read("docker", "ps", "-aq", "--filter",
                            f"label=com.docker.compose.project={generation}").splitlines()
        failed_containers = sorted(set(new_nodes + new_services))
        if failed_containers:
            run("docker", "update", "--restart", "no", *failed_containers, capture=True)
        stop(new_nodes)
        stop(new_services)
        held = {}
        for identifier in new_services:
            name = read("docker", "inspect", "-f", "{{.Name}}", identifier).lstrip("/")
            if not re.fullmatch(r"dc-saas-[a-z0-9-]+", name):
                raise RuntimeError(f"Unexpected service in the failed Mac Demo: {name}")
            retained_name = f"{generation}-held-{name}"
            run("docker", "rename", identifier, retained_name, capture=True)
            held[name] = {"id": identifier, "held": retained_name}
        if held:
            (out / "held-failed-generation.json").write_text(json.dumps(held, indent=2, sort_keys=True) + "\n")
        for name in old_names:
            identifier = old[name]["Id"]
            if read("docker", "inspect", "-f", "{{.Name}}", identifier) != "/" + name:
                run("docker", "rename", identifier, name)
        for container in old.values():
            restore_container_restart_policy(container)
        for group in (INFRA, APPS):
            run("docker", "start", *(f"dc-saas-{x}" for x in group), capture=True)
        if running_old_witnesses:
            run("docker", "start", *running_old_witnesses, capture=True)
        if running_old_core:
            run("docker", "start", *running_old_core, capture=True)
        if running_support:
            run("docker", "start", *running_support, capture=True)

    def tool(class_name, *arguments, native_volume=False):
        old_a = old[old_core["order", "A"]]
        public = next(m["Source"] for m in old_a["Mounts"] if m["Destination"] == "/read-only-original-rsa/public")
        flags = ["--network", "host", "-v", f"{tools}:/tools:ro", "-v",
                 f"{runtime}/control:/control:ro", "-v", f"{public}:/public:ro"]
        if native_volume:
            flags.extend(["-v", f"{generation}-born:{VOLUMES['born']}"])
        run("docker", "run", "--rm", *flags, "--entrypoint", "java", image_refs["order"],
            "-Djava.security.auth.login.config=/control/jaas.ini", "-cp",
            "/tools:/srv/dc/dc/OrderSvr/lib/*", class_name, *arguments)

    try:
        report("Taking the old Mac Demo offline. Its containers and data remain available for rollback.")
        run("docker", "update", "--restart", "no", *(old[name]["Id"] for name in old_names), capture=True)
        stop(running_old_witnesses)
        stop([*running_old_core, *(f"dc-saas-{x}" for x in APPS)])
        stop(running_support)
        stop([f"dc-saas-{x}" for x in INFRA])
        for name, retired in rollback_names.items():
            run("docker", "rename", old[name]["Id"], retired)
        require_common_replication_ports("birth")
        run(*compose, "up", "-d", "--pull", "never", "--wait", "--wait-timeout", "360", *INFRA)
        if read("docker", "inspect", "-f", '{{index .Config.Labels "com.docker.compose.project"}}',
                "dc-saas-mysql") != generation:
            raise RuntimeError("Refusing to initialize a MySQL container outside the new generation")
        report("Fresh MySQL, ClickHouse and ZooKeeper are healthy")
        for migration in sorted((REPO / "mysql/migrations").glob("*.sql")):
            report(f"Applying {migration.name}")
            sql(migration.read_text())
        admin = shlex.split(config["PLATFORM_ADMIN_USERNAME"])[0]
        password = shlex.split(config["PLATFORM_ADMIN_PASSWORD"])[0]
        if not re.fullmatch(r"[A-Za-z0-9_.@-]{3,64}", admin) or not password or password == "replace-with-generated-secret":
            raise RuntimeError("Missing protected platform administrator credentials")
        digest = hashlib.sha256(password.encode()).hexdigest()
        sql("INSERT INTO dc_users(user_id,user_name,name,password,user_type,enable,remark,create_time,"
            "update_time,enable_trade,enable_cash_in,enable_cash_out,close_by,location) "
            f"VALUES('{admin}','{admin}','Platform Administrator','{digest}','1','1','Mac Demo',"
            "NOW(3),NOW(3),'0','0','0','mac-demo','PLATFORM') "
            "ON DUPLICATE KEY UPDATE password=VALUES(password),enable='1',update_time=NOW(3);")
        run(sys.executable, str(REPO / "scripts/provision-robot-service-user.py"),
            "--env-file", str(env), "--mysql-container", "dc-saas-mysql")
        # Login can initialize while the physical voters are being installed.
        # It needs the migrated SQL schema and the Robot identity above.
        run(*compose, "up", "-d", "--pull", "never", "--no-deps", "loginsvr")
        volume_keys = [*VOLUMES, *(f"{kind}-witness" for kind in witness_roots)]
        for key in volume_keys:
            run("docker", "volume", "create", "--label", f"otc.mac.demo.generation={generation}",
                f"{generation}-{key}", capture=True)
        voter_runtime_mounts = {(kind, slot): prepare_voter_runtime_storage(generation, kind, slot, image_ids[kind])
                                for kind, slot in pairs}
        tool("T530VirginZkManifestInstaller", f"127.0.0.1:{zk_port}",
             "/tools/manifests/order-e1-recovering.manifest", "/tools/manifests/trade-e1-recovering.manifest")
        birth = start_phase("birth")
        wait_log(birth, "COMMON_FIRST_BOOT_ONLY_LOCAL_RSA_E1_VOTER_FLEET_FSYNC_PASS")
        until(lambda: all(read("docker", "inspect", "-f",
                              "{{.State.Status}}:{{.State.ExitCode}}", node) == "exited:0"
                          for node in birth), "four successful birth processes", 75)
        wait_lease_release(pairs)
        tool("com.app.common.replication.T530OriginalE1DualPhysicalGenesisSeal",
             VOLUMES["born"], "/public", native_volume=True)
        run("docker", "run", "--rm", "--network", "none", "--entrypoint", "mkdir",
            "-v", f"{generation}-born:{VOLUMES['born']}", image_refs["order"], "-p",
            *(f"{VOLUMES['born']}/{service}/original-home" for service in SERVICES.values()),
            *(f"{VOLUMES['born']}/{SERVICES[kind]}/{SERVICES[kind]}{slot}/transactions/P{i:03d}"
              for kind, slot in pairs for i in range(256)), capture=True)
        install = start_phase("install")
        def durable_install():
            for kind, slot in pairs:
                service = SERVICES[kind]
                result = subprocess.run(["docker", "exec", docker_name("install", kind, slot), "sh", "-c",
                                         f"find {VOLUMES['born']}/{service}/{service}{slot}/transactions"
                                         " -name '*.recovery' -exec grep -l '^phase=REPLAY_COMPLETE$' {} + | wc -l"],
                                        capture_output=True, text=True)
                if result.returncode or result.stdout.strip() != "256":
                    name = docker_name("install", kind, slot)
                    if read("docker", "inspect", "-f", "{{.State.Status}}", name) == "exited":
                        raise RuntimeError(f"{name} exited before its durable business install. See docker logs {name}")
                    return False
            return True
        until(durable_install, "256 persisted recovery ledgers on each physical voter", 480)
        stop(install)
        wait_lease_release(pairs)
        home = start_phase("home")
        wait_log(home, "COMMON_ORIGINAL_HOME_E1_PHYSICAL_RSA_FSYNC_PASS")
        stop([docker_name("home", kind, "A") for kind in SERVICES])
        wait_lease_release([(kind, "A") for kind in SERVICES])
        stage = start_phase("stage", [("order", "A"), ("trade", "A")])
        wait_log(stage, "COMMON_ORIGINAL_FIRST_E2_READY_CAS_PASS", 240)
        stop([*stage, *(docker_name("home", kind, "B") for kind in SERVICES)])
        wait_lease_release(pairs)
        report("Both Common clusters published their signed first READY generation")
        run("docker", "run", "--rm", "--network", "none", "--entrypoint", "mkdir",
            "-v", f"{generation}-ready:{VOLUMES['ready']}", image_refs["order"], "-p",
            *(f"{VOLUMES['ready']}/{SERVICES[kind]}/{SERVICES[kind]}{slot}/snapshots"
              for kind, slot in pairs), capture=True)
        run(*compose, "up", "-d", "--pull", "never", "--no-deps",
            *(app for app in APPS if app != "loginsvr"), PROJECTION)
        if automatic_common:
            for kind, service in SERVICES.items():
                witness_name = start_witness(kind)
                wait_log([witness_name], "COMMON_FIRST_READY_E2_WITNESS_STARTED service=" + service, 180)
                if read("docker", "exec", witness_name, "sha256sum",
                        f"/srv/dc/dc/{service}/lib/com.app.common-mac-demo.jar").split()[0] != images["common_sha256"]:
                    raise RuntimeError(f"{service}: witness Common bytes differ from the verified build")
        require_common_replication_ports("hostready")
        ready = start_phase("hostready")
        for name, (kind, slot) in zip(ready, pairs):
            wait_log([name], f"Started {SERVICES[kind]}", 240)
            service = SERVICES[kind]
            wait_log([name], f"COMMON_GATEWAY_DISCOVERY_CERTIFIED service={service} node={service}{slot}", 180)
            count = read("docker", "exec", name, "sh", "-c", 'find "$1" -name business.wal | wc -l',
                         "--", f"{VOLUMES['ready']}/{service}/{service}{slot}/{service}/{service}{slot}")
            if count != "256":
                raise RuntimeError(f"{name}: expected 256 opened physical WALs, found {count}")
            for title, jar_kind, file_name in embedded_jars:
                running_sha = read("docker", "exec", name, "sha256sum",
                                   f"/srv/dc/dc/{service}/lib/{file_name}").split()[0]
                if running_sha != images[f"{jar_kind}_sha256"]:
                    raise RuntimeError(f"{name}: runtime {title} bytes differ from the build")
            if automatic_common:
                threads = read("docker", "exec", name, "jstack", "1")
                if ('"common-witnessed-return"' not in threads
                        or not re.search(r'^"common-failover-cold-\d+"', threads, re.M)):
                    raise RuntimeError(f"{name}: Common automatic recovery threads are not running")
        for kind, service in SERVICES.items():
            manifest = read("docker", "exec", "dc-saas-zookeeper", "zkCli.sh", "-server",
                            f"127.0.0.1:{zk_port}", "get", f"{namespace}/{kind}/manifest")
            expected = {f"P{i:03d}|2|{service}{'A' if i < 128 else 'B'}|"
                        f"{service}{'B' if i < 128 else 'A'}|STRICT_QUORUM|READY" for i in range(256)}
            actual = {line for line in manifest.splitlines() if re.match(r"^P[0-9]{3}\|", line)}
            if actual != expected:
                raise RuntimeError(f"{service}: unexpected live E2 manifest")
        wait_log(["dc-saas-projectionsvr"], "Started ProjectionSvr", 180)
        wait_log(["dc-saas-projectionsvr"], "CERTIFIED_TRADE_FINANCIAL_READMODEL_STARTED", 180)
        wait_log(["dc-saas-projectionsvr"], "Projection binary consumer started", 180)
        wait_log(["dc-saas-projectionsvr"], "Trade projection binary consumer started", 180)
        wait_log(["dc-saas-loginsvr"], "ZK_CLUSTER_STATUS_LOG_STARTED service:LoginSvr", 240)
        run(*compose, "up", "-d", "--pull", "never", "--no-deps", "robotsvr", "liqsvr")
        report("Four new JVMs and ProjectionSvr started. Business verification can run on this generation.")
        if args.verify_business:
            started = time.monotonic()
            run("bash", str(REPO / "scripts/verify-mac-demo-fresh.sh"), str(out))
            report(f"Business verification passed in {int(time.monotonic() - started)}s")
    except (Exception, KeyboardInterrupt):
        report(f"Fresh startup or baseline verification failed. Rolling back with {old_manifest}")
        try:
            rollback()
            report("Restored the original containers and their recorded running state")
        except (RuntimeError, subprocess.CalledProcessError):
            report(f"Rollback needs attention. Container IDs and names are recorded in {old_manifest}")
        raise


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(f"{' '.join(map(str, exc.cmd[:2]))} failed with exit {exc.returncode}")
    except RuntimeError as exc:
        sys.exit(str(exc))
