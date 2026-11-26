#!/usr/bin/env python3
"""Exercise the protected first installation on a disposable, clean GitHub Linux host."""
import importlib.util
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_simulation", ROOT / "scripts/prepare-simulation-common.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
common = setup.common
APPS = {"web": "trade-web", "public-web": "public-web", "tenant-web": "tenant-web",
        "platform-web": "platform-web", "api-docs": "api-docs", "gateway": "gateway",
        "mdsvr": "market-data", "apssvr": "price-feed", "loginsvr": "login", "liqsvr": "liquidation",
        "managersvr": "manager", "adminsvr": "admin-bootstrap", "projectionsvr": "projection", "robotsvr": "robot"}


def call(*args, data=None):
    process = subprocess.run(args, text=True, input=data, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if process.returncode:
        # Container output and the control configuration may contain private values.
        # Print only error types and public build diagnostics in hosted logs.
        errors = re.findall(r'(?:[a-zA-Z][\w$]*\.)+[A-Za-z][\w$]*(?:Exception|Error)', process.stdout)
        raise RuntimeError(f"{args[0]} {args[1]} failed ({process.returncode}); {', '.join(dict.fromkeys(errors))}")
    return process.stdout.strip()


def image(kind):
    pin = call("git", "-C", str(ROOT), "rev-parse", "HEAD:sources/" + kind)
    ref = f"otc-simulation/{kind}:{pin}"
    found = call("docker", "image", "inspect", "-f", '{{index .Config.Labels "org.opencontainers.image.revision"}}', ref)
    if found != pin:
        raise RuntimeError(f"Incorrect {kind} candidate")
    return ref


def environment(out, include_apps=True):
    runtime = out / "runtime"
    values = common.env_pairs(ROOT / ".env.example")
    for key, value in values.items():
        if value.startswith(('"', "'")):
            parsed = shlex.split(value)
            if len(parsed) != 1:
                raise ValueError(f"Invalid example setting {key}")
            values[key] = parsed[0]
    for key in values:
        if key.endswith(("_PASSWORD", "_SECRET", "_MASTER_KEY", "_API_KEY")):
            values[key] = secrets.token_hex(32)
    values.update({"DEPLOY_ROOT": str(runtime), "COMPOSE_PROJECT_NAME": out.name,
                   "MYSQL_IMAGE_REPOSITORY": "mysql", "CLICKHOUSE_IMAGE_REPOSITORY": "clickhouse/clickhouse-server",
                   "ZOOKEEPER_IMAGE_REPOSITORY": "zookeeper", "ORDER_CLUSTER_ENABLED": "true",
                   "TRADE_CLUSTER_ENABLED": "true", "ZOOKEEPER_PORT": "49181",
                   "ORDERSVR_GW_PORT": "49036", "ORDERSVR_B_GW_PORT": "49041",
                   "TRADESVR_GW_PORT": "49037", "TRADESVR_B_GW_PORT": "49046",
                   "PUBLIC_SIMULATION_FUNDED_MAKERS": "true", "TRIAL_LIQUIDITY_BOOTSTRAP_ENABLED": "true",
                   "TRIAL_LIQUIDITY_MASTER_KEY": secrets.token_hex(32)})
    env = out / "demo.env"
    env.write_text("".join(f"{k}={shlex.quote(v)}\n" for k, v in values.items()))
    call("bash", str(ROOT / "generate-saas-configs.sh"), str(env))
    control = runtime / "control"
    secret = secrets.token_hex(32)
    client = f'Client {{ org.apache.zookeeper.server.auth.DigestLoginModule required username="demo" password="{secret}"; }};\n'
    server = f'Server {{ org.apache.zookeeper.server.auth.DigestLoginModule required user_demo="{secret}"; }};\n'
    (control / "jaas.ini").write_text(client)
    (control / "zookeeper-jaas.ini").write_text(server)
    override = out / "compose.images.json"
    override.write_text(json.dumps({"services": {service: {"image": image(kind)} for service, kind in APPS.items() if include_apps}}))
    return ["docker", "compose", "-p", out.name, "--env-file", str(env), "-f", str(ROOT / "compose.yaml"),
            "-f", str(override)]


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux":
        raise SystemExit("Use the clean-linux acceptance job on an ephemeral GitHub runner")
    if call("docker", "ps", "-aq") or call("docker", "volume", "ls", "-q"):
        raise RuntimeError("Clean acceptance requires unused Docker storage")
    out = Path(os.environ["RUNNER_TEMP"]) / datetime.now(timezone.utc).strftime("sim-demo-%Y%m%d-%H%M%S")
    setup.prepare(out, 49181)
    namespace = "/otc/" + out.name
    control_only = sys.argv[1:] == ["--check-control"]
    compose = environment(out, include_apps=not control_only)
    call(*compose, "up", "-d", "--wait", "--wait-timeout", "360", *common.INFRA)
    print("Clean MySQL, ClickHouse and ZooKeeper healthy", flush=True)
    for file in sorted((ROOT / "mysql/migrations").glob("*.sql")):
        call("docker", "exec", "-i", "dc-saas-mysql", "sh", "-c",
             'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --protocol=TCP -h127.0.0.1 -P"$MYSQL_TCP_PORT" -uroot dc',
             data=file.read_text())
    tools = out / "common/tools"
    control = out / "runtime/control"
    tool_flags = ["--network", "host", "-v", f"{tools}:/tools:ro", "-v", f"{control}:/control:ro"]
    entry = "/srv/dc/dc/OrderSvr"
    if control_only:
        container = "dc-saas-zookeeper"
        zk_lib = call("docker", "exec", container, "sh", "-c", 'cd "$ZOO_HOME/lib" && pwd')
        call("docker", "cp", f"{container}:{zk_lib}", str(out / "zk-lib"))
        call("javac", "-cp", str(out / "zk-lib/*"), "-d", str(tools),
             str(ROOT / "scripts/java/T554ProtectedNamespaceInstaller.java"))
        tool_classpath = "/tools:" + zk_lib + "/*"
        tool_image = call("docker", "inspect", "-f", "{{.Image}}", container)
    else:
        tool_image = image("order")
        tool_classpath = entry + "/classes:" + entry + "/lib/*"
    def tool(flags, java_class, *args):
        return call("docker", "run", "--rm", *tool_flags, *flags, "--entrypoint", "java", tool_image,
                    "-Djava.security.auth.login.config=/control/jaas.ini", "-cp", tool_classpath, java_class, *args)
    install_args = (["-v", f"{out}/install-control.properties:/run/install.properties:ro"],
                    "T554ProtectedNamespaceInstaller", "127.0.0.1:49181", namespace, "/run/install.properties",
                    *[f"/tools/manifests/{kind}-e1-recovering.manifest" for kind in common.SERVICES])
    result = tool(*install_args)
    roots = {kind: out / "common/ha" / kind for kind in common.SERVICES}
    common.bind_witness_origins(result, roots)
    print("Both protected 256-partition E1 manifests verified, including writer isolation", flush=True)
    if control_only:
        # Re-running the installer must fail without replacing either original manifest.
        try:
            tool(*install_args)
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Existing namespace was accepted for reinstallation")
        for kind, service in common.SERVICES.items():
            actual = call("docker", "exec", "dc-saas-zookeeper", "zkCli.sh", "-server",
                          "127.0.0.1:49181", "get", f"{namespace}/{kind}/manifest")
            if setup.manifest(service) not in actual:
                raise RuntimeError(f"Refused reinstallation changed {kind}")
        print("Repeated namespace initialization refused; both original manifests intact", flush=True)
        return
    refs = {kind: image(kind) for kind in common.SERVICES}
    pairs = [(kind, slot) for kind in common.SERVICES for slot in common.SLOTS]
    for key in common.VOLUMES:
        call("docker", "volume", "create", "--label", f"otc.mac.demo.generation={out.name}", f"{out.name}-{key}")
    signers = out / "common/physical-signers"
    mounts = {(kind, slot): common.prepare_voter_runtime_storage(out.name, kind, slot, refs[kind]) for kind, slot in pairs}
    def start(phase, kind, slot):
        service = common.SERVICES[kind]
        name = f"{out.name}-{kind}-{slot.lower()}-{phase}"
        props = out / "common" / f"config-{phase}" / kind / slot / "application.properties"
        flags = [*mounts[kind, slot], "-v", f"{control}:/srv/dc/control:ro", "-v",
                 f"{props}:/srv/dc/dc/{service}/config/application.properties:ro"]
        for key, path in common.VOLUMES.items():
            flags += ["-v", f"{out.name}-{key}:{path}"]
        for entry in (slot.lower(), "public"):
            flags += ["-v", f"{signers}/{entry}:/read-only-original-rsa/{entry}:ro"]
        call("docker", "run", "-d", "--network", "host", "--name", name, *common.DOCKER_LOG_OPTIONS, *flags,
             "-e", f"OTC_PROTECTED_CONTROL_NAMESPACE={namespace}/{kind}",
             "-e", "JAVA_TOOL_OPTIONS=-Dcommon.certified.clientAckPolicy=STRICT_QUORUM",
             "-e", "JAVA_OPTS=-Xms128m -Xmx1g -Djava.security.auth.login.config=/srv/dc/control/jaas.ini",
             refs[kind])
        return name
    nodes = [start("birth", kind, slot) for kind, slot in pairs]
    for node in nodes:
        until = time.monotonic() + 180
        while call("docker", "inspect", "-f", "{{.State.Running}}", node) == "true" and time.monotonic() < until:
            time.sleep(1)
        logs = call("docker", "logs", node)
        if (call("docker", "inspect", "-f", "{{.State.Status}}:{{.State.ExitCode}}", node) != "exited:0"
                or "COMMON_FIRST_BOOT_ONLY_LOCAL_RSA_E1_VOTER_FLEET_FSYNC_PASS" not in logs):
            errors = re.findall(r'(?:[\w$]+\.)+[\w$]+(?:Exception|Error)', logs)
            raise RuntimeError(f"{node} failed durable genesis: {', '.join(dict.fromkeys(errors))}")
    born = common.VOLUMES["born"]
    result = tool(["-v", f"{out.name}-born:{born}", "-v", f"{signers}/public:/public:ro"],
                  "com.app.common.replication.T530OriginalE1DualPhysicalGenesisSeal", born, "/public", namespace)
    for service in common.SERVICES.values():
        if f"service={service} phase=1 partitions=256 READY=false" not in result:
            raise RuntimeError(f"Missing verified physical seals for {service}")
    print("Physical genesis passed for both services, two voters and 256 partitions each", flush=True)


if __name__ == "__main__":
    main()
