#!/usr/bin/env python3
"""Exercise the protected first installation on a disposable, clean GitHub Linux host."""
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import time
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_simulation", ROOT / "scripts/prepare-simulation-common.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
common = setup.common
GATEWAY_PORTS = {"GW_TCP_PORT": "23000", "GW_WEBSOCKET_PORT": "23001", "GW_HTTP_PORT": "23002"}
APPS = {"web": "trade-web", "public-web": "public-web", "tenant-web": "tenant-web",
        "platform-web": "platform-web", "api-docs": "api-docs", "gateway": "gateway",
        "mdsvr": "market-data", "apssvr": "price-feed", "loginsvr": "login", "liqsvr": "liquidation",
        "managersvr": "manager", "adminsvr": "admin-bootstrap", "projectionsvr": "projection", "robotsvr": "robot"}


class NamespaceAlreadyExists(RuntimeError):
    pass


def call(*args, data=None):
    process = subprocess.run(args, text=True, input=data, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if process.returncode:
        # Container output and the control configuration may contain private values.
        # Print only error types and public build diagnostics in hosted logs.
        if "java.lang.IllegalStateException: refusing existing Demo namespace" in process.stdout:
            raise NamespaceAlreadyExists("Existing simulation namespace")
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
    values.update(GATEWAY_PORTS)
    values.update({"DEPLOY_ROOT": str(runtime), "COMPOSE_PROJECT_NAME": out.name,
                   "MYSQL_IMAGE_REPOSITORY": "mysql", "CLICKHOUSE_IMAGE_REPOSITORY": "clickhouse/clickhouse-server",
                   "ZOOKEEPER_IMAGE_REPOSITORY": "zookeeper", "ORDER_CLUSTER_ENABLED": "true",
                   "TRADE_CLUSTER_ENABLED": "true", "ZOOKEEPER_PORT": "49181",
                   "ORDERSVR_GW_PORT": "49036", "ORDERSVR_B_GW_PORT": "49041",
                   "TRADESVR_GW_PORT": "49037", "TRADESVR_B_GW_PORT": "49046",
                   "PUBLIC_SIMULATION_FUNDED_MAKERS": "true", "TRIAL_LIQUIDITY_BOOTSTRAP_ENABLED": "true",
                   "TRIAL_LIQUIDITY_TAPE_ENABLED": "true", "TRIAL_LIQUIDITY_MASTER_KEY": secrets.token_hex(32)})
    env = out / "demo.env"
    env.write_text("".join(f"{k}={shlex.quote(v)}\n" for k, v in values.items()))
    call("bash", str(ROOT / "generate-saas-configs.sh"), str(env))
    control = runtime / "control"
    projection = control / "overrides/ProjectionSvr/config/application.properties"
    projection.write_text(common.update_properties(projection.read_text(), {"trade.financial.readmodel.enabled": "true"}))
    secret = secrets.token_hex(32)
    client = f'Client {{ org.apache.zookeeper.server.auth.DigestLoginModule required username="demo" password="{secret}"; }};\n'
    server = f'Server {{ org.apache.zookeeper.server.auth.DigestLoginModule required user_demo="{secret}"; }};\n'
    (control / "jaas.ini").write_text(client)
    (control / "zookeeper-jaas.ini").write_text(server)
    override = out / "compose.images.json"
    services = {service: {"image": image(kind)} for service, kind in APPS.items() if include_apps}
    if include_apps:
        # Compose waits for all three actual listeners before tenant provisioning.
        probe = " && ".join("(: > /dev/tcp/127.0.0.1/" + port + ")" for port in GATEWAY_PORTS.values())
        services["gateway"]["healthcheck"] = {
            "test": ["CMD", "bash", "-ec", probe], "interval": "30s", "timeout": "3s",
            "start_period": "30s", "retries": 3,
        }
        path = "/usr/share/nginx/html/assets/js/config.js"
        original = call("docker", "run", "--rm", "--network", "none", "--entrypoint", "cat",
                        services["public-web"]["image"], path)
        default = '"https://trade.opentradingcore.com/#/trade?location="'
        if original.count(default) != 1:
            raise RuntimeError("Public website trading link configuration changed")
        origin = os.environ.get("T554_TRADE_ORIGIN", "")
        if origin:
            url = urlsplit(origin)
            if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
                    or url.path not in {"", "/"} or url.query or url.fragment):
                raise ValueError("Expected a trading website origin")
            trade = json.dumps(origin.rstrip("/") + "/#/trade?location=")
        else:
            trade = 'window.location.protocol+"//"+window.location.hostname+":18088/#/trade?location="'
        public_config = control / "public-site.js"
        public_config.write_text(original.replace(default, trade) + "\n")
        public_config.chmod(0o644)
        services["public-web"]["volumes"] = [f"{public_config}:{path}:ro"]
    override.write_text(json.dumps({"services": services}))
    return ["docker", "compose", "-p", out.name, "--env-file", str(env), "-f", str(ROOT / "compose.yaml"),
            "-f", str(override)]


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux":
        raise SystemExit("Use the clean-linux acceptance job on an ephemeral GitHub runner")
    if call("docker", "ps", "-aq") or call("docker", "volume", "ls", "-q"):
        raise RuntimeError("Clean acceptance requires unused Docker storage")
    out = Path(os.environ["RUNNER_TEMP"]) / datetime.now(timezone.utc).strftime("sim-demo-%Y%m%d-%H%M%S")
    if sys.argv[1:] != ["--check-control"]:
        raise SystemExit("Run install-public-simulation.py for a full installation")
    install(out, control_only=True)


def wait_marker(node, marker, timeout=240):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        logs = call("docker", "logs", node)
        if marker in logs:
            return
        if call("docker", "inspect", "-f", "{{.State.Running}}", node) != "true":
            break
        time.sleep(2)
    raise RuntimeError(f"{node} did not reach {marker}")


def install(out, control_only):
    if not control_only:
        common.require_common_replication_ports("birth", [int(port) for port in GATEWAY_PORTS.values()])
        common.require_common_replication_ports("hostready")
    setup.prepare(out, 49181)
    namespace = "/otc/" + out.name
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
        zk_lib = call("docker", "exec", container, "sh", "-c", 'cd "$(dirname "$(command -v zkServer.sh)")/../lib" && pwd -P')
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
    origins = common.bind_witness_origins(result, roots)
    print("Both protected 256-partition E1 manifests verified, including writer isolation", flush=True)
    if control_only:
        # Re-running the installer must fail without replacing either original manifest.
        try:
            tool(*install_args)
        except NamespaceAlreadyExists:
            pass
        else:
            raise RuntimeError("Existing namespace was accepted for reinstallation")
        for kind, service in common.SERVICES.items():
            actual = call("docker", "exec", "dc-saas-zookeeper", "zkCli.sh", "-server",
                          "127.0.0.1:49181", "get", "-s", f"{namespace}/{kind}/manifest")
            origin = re.search(r"^cZxid = (0x[0-9a-fA-F]+)$", actual, re.M)
            if (setup.manifest(service) not in actual or not origin or int(origin[1], 16) != origins[kind]
                    or not re.search(r"^dataVersion = 0$", actual, re.M)
                    or not re.search(r"^aclVersion = 0$", actual, re.M)):
                raise RuntimeError(f"Refused reinstallation changed {kind}")
        print("Repeated namespace initialization refused; both original manifests intact", flush=True)
        return
    refs = {kind: image(kind) for kind in common.SERVICES}
    values = common.env_pairs(out / "demo.env")
    admin = values["PLATFORM_ADMIN_USERNAME"]
    if not re.fullmatch(r"[a-zA-Z0-9_.@-]{3,64}", admin):
        raise ValueError("Invalid platform administrator")
    digest = hashlib.sha256(values["PLATFORM_ADMIN_PASSWORD"].encode()).hexdigest()
    call("docker", "exec", "-i", "dc-saas-mysql", "sh", "-c",
         'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --protocol=TCP -h127.0.0.1 -P"$MYSQL_TCP_PORT" -uroot dc',
         data="INSERT INTO dc_users(user_id,user_name,name,password,user_type,enable,remark,create_time,"
              "update_time,enable_trade,enable_cash_in,enable_cash_out,close_by,location) "
              f"VALUES('{admin}','{admin}','Platform Administrator','{digest}','1','1','Simulation',"
              "NOW(3),NOW(3),'0','0','0','sim-demo','PLATFORM') "
              "ON DUPLICATE KEY UPDATE password=VALUES(password),enable='1',update_time=NOW(3);")
    call(sys.executable, str(ROOT / "scripts/provision-robot-service-user.py"),
         "--env-file", str(out / "demo.env"), "--mysql-container", "dc-saas-mysql")
    call(*compose, "up", "-d", "--no-deps", "--pull", "never", "loginsvr")
    run_core(out, compose, refs, roots, control, namespace, tool)
    call(*compose, "up", "-d", "--no-deps", "--pull", "never", "--wait", "--wait-timeout", "300", *APPS)
    for marker in ("Started ProjectionSvr", "CERTIFIED_TRADE_FINANCIAL_READMODEL_STARTED",
                   "Projection binary consumer started", "Trade projection binary consumer started"):
        wait_marker("dc-saas-projectionsvr", marker, 180)
    print("Application services started with Order and Trade projection readers ready", flush=True)
    if os.environ.get("GITHUB_ENV"):
        with open(os.environ["GITHUB_ENV"], "a") as env:
            env.write(f"SIMULATION_GENERATION={out.name}\n")



def run_core(out, compose, refs, roots, control, namespace, tool):
    pairs = [(kind, slot) for kind in common.SERVICES for slot in common.SLOTS]
    for key in common.VOLUMES:
        call("docker", "volume", "create", "--label", f"otc.mac.demo.generation={out.name}", f"{out.name}-{key}")
    signers = out / "common/physical-signers"
    mounts = {(kind, slot): common.prepare_voter_runtime_storage(out.name, kind, slot, refs[kind]) for kind, slot in pairs}
    cpus = min(4, int(call("docker", "info", "-f", "{{.NCPU}}")))

    def start(phase, kind, slot):
        service = common.SERVICES[kind]
        name = f"{out.name}-{kind}-{slot.lower()}-{phase}"
        props = out / "common" / f"config-{phase}" / kind / slot / "application.properties"
        flags = [*mounts[kind, slot], "-v", f"{control}:/srv/dc/control:ro", "-v",
                 f"{props}:/srv/dc/dc/{service}/config/application.properties:ro"]
        if phase == "hostready":
            peer = "B" if slot == "A" else "A"
            local = service + "/" + service + slot
            volume = out.name + "-ready"
            ready = common.VOLUMES["ready"]
            flags += common.owned_mount(volume, local, ready + "/" + local)
            flags += common.owned_mount(volume, service + "/" + service + peer, common.HA_PEER, True)
            flags += ["-v", f"{out.name}-born:{common.VOLUMES['born']}:ro",
                      "-v", f"{roots[kind]}/public/witness.pub.der:{common.HA_WITNESS}/witness.pub.der:ro",
                      "-v", f"{out.name}-{kind}-witness:{common.HA_WITNESS}/receipts:ro",
                      "-v", f"{roots[kind]}/source-auth:{common.HA_SOURCE_AUTH}:ro", "--restart", "on-failure"]
        else:
            for key, path in common.VOLUMES.items():
                flags += ["-v", f"{out.name}-{key}:{path}"]
        for entry in (slot.lower(), "public"):
            flags += ["-v", f"{signers}/{entry}:/read-only-original-rsa/{entry}:ro"]
        heap = "-Xmx1g"
        memory = "2g"
        if kind == "trade":
            heap, memory = ("-Xmx3g", "4g") if phase == "hostready" else ("-Xmx2g", "3g")
            heap += " -XX:MaxDirectMemorySize=512m"
        java = common.client_ack_environment(
            [f"JAVA_OPTS=-Xms128m {heap} -Djava.security.auth.login.config=/srv/dc/control/jaas.ini"],
            "STRICT_QUORUM")
        for setting in common.low_pause_gc_environment(common.gc_observation_environment(java)):
            flags.extend(["-e", setting])
        call("docker", "run", "-d", "--network", "host", "--name", name, *common.DOCKER_LOG_OPTIONS,
             "--cpus", str(cpus), "--memory", memory, *flags,
             "-e", f"OTC_PROTECTED_CONTROL_NAMESPACE={namespace}/{kind}", refs[kind])
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

    def await_leases(selected):
        def clear():
            for kind in sorted({kind for kind, _ in selected}):
                listing = call("docker", "exec", "dc-saas-zookeeper", "zkCli.sh", "-server", "127.0.0.1:49181",
                               "ls", f"{namespace}/{kind}/leases")
                rows = re.findall(r"^\[([A-Za-z0-9_, .-]*)\]$", listing, re.M)
                if not rows or any(common.SERVICES[kind] + slot in rows[-1] for k, slot in selected if k == kind):
                    return False
            return True
        common.until(clear, "actual voter leases released", 75)

    def stop(nodes, selected):
        call("docker", "stop", "--time", "8", *[nodes[pair] for pair in selected])
        await_leases(selected)

    await_leases(pairs)
    call("docker", "run", "--rm", "--network", "none", "--entrypoint", "mkdir", "-v",
         f"{out.name}-born:{born}", refs["order"], "-p",
         *(f"{born}/{service}/original-home" for service in common.SERVICES.values()),
         *(f"{born}/{common.SERVICES[kind]}/{common.SERVICES[kind]}{slot}/transactions/P{i:03}"
           for kind, slot in pairs for i in range(256)))
    installing = {pair: start("install", *pair) for pair in pairs}
    def replayed():
        for (kind, slot), node in installing.items():
            service = common.SERVICES[kind]
            directory = f"{born}/{service}/{service}{slot}/transactions"
            count = call("docker", "exec", node, "sh", "-c",
                         """find "$1" -name '*.recovery' -exec grep -l '^phase=REPLAY_COMPLETE$' {} + | wc -l""",
                         "--", directory)
            if count != "256":
                return False
        return True
    common.until(replayed, "256 durable replay ledgers per voter", 480)
    stop(installing, pairs)
    home = {pair: start("home", *pair) for pair in pairs}
    for node in home.values():
        wait_marker(node, "COMMON_ORIGINAL_HOME_E1_PHYSICAL_RSA_FSYNC_PASS")
    a = [pair for pair in pairs if pair[1] == "A"]
    b = [pair for pair in pairs if pair[1] == "B"]
    stop(home, a)
    stage = {pair: start("stage", *pair) for pair in a}
    for node in stage.values():
        wait_marker(node, "COMMON_ORIGINAL_FIRST_E2_READY_CAS_PASS")
    stop({**{p: home[p] for p in b}, **stage}, pairs)
    ready = common.VOLUMES["ready"]
    call("docker", "run", "--rm", "--network", "none", "--entrypoint", "mkdir", "-v",
         f"{out.name}-ready:{ready}", refs["order"], "-p",
         *(f"{ready}/{common.SERVICES[kind]}/{common.SERVICES[kind]}{slot}/snapshots" for kind, slot in pairs))
    for kind, service in common.SERVICES.items():
        root = roots[kind]
        name = f"{out.name}-{kind}-witness"
        call("docker", "volume", "create", "--label", f"otc.mac.demo.generation={out.name}", name)
        flags = []
        for slot in common.SLOTS:
            flags += common.owned_mount(out.name + "-ready", f"{service}/{service}{slot}",
                                        f"/srv/dc/data/t554-voter-{slot.lower()}", True)
        call("docker", "run", "-d", "--network", "host", "--name", name, "--restart", "unless-stopped",
             *common.DOCKER_LOG_OPTIONS, *flags, "-v", f"{out.name}-born:{born}:ro",
             "-v", f"{control}:/control:ro", "-v", f"{signers}/public:/public:ro",
             "-v", f"{root}/identity:{common.HA_WITNESS_SETTINGS}/identity:ro",
             "-v", f"{root}/witness.properties:{common.HA_WITNESS_SETTINGS}/witness.properties:ro",
             "-v", f"{root}/public/witness.pub.der:{common.HA_WITNESS}/witness.pub.der:ro",
             "-v", f"{name}:{common.HA_WITNESS}/receipts", "--entrypoint", "java", refs[kind],
             "-Xms32m", "-Xmx384m", "-Djava.security.auth.login.config=/control/jaas.ini",
             "-cp", f"/srv/dc/dc/{service}/lib/*", "com.app.common.replication.CommonCertifiedFirstReadyE2WitnessProcess",
             f"{common.HA_WITNESS_SETTINGS}/witness.properties")
        wait_marker(name, "COMMON_FIRST_READY_E2_WITNESS_STARTED service=" + service)
    common_sha = call("docker", "image", "inspect", "-f", '{{index .Config.Labels "dc.common.p0.sha256"}}',
                      refs["order"])
    if not re.fullmatch(r"[0-9a-f]{64}", common_sha):
        raise RuntimeError("Missing qualified Common identity")
    common.require_witness_runtime_storage(out, common_sha)
    # The MD process installs its Order subscriptions during startup. Both
    # physical Order publishers must be registered before the first subscribe.
    core_dependencies = [service for service in common.APPS if service != "mdsvr"]
    call(*compose, "up", "-d", "--no-deps", "--pull", "never", *core_dependencies, common.PROJECTION)
    nodes = {pair: start("hostready", *pair) for pair in pairs}
    for (kind, slot), node in nodes.items():
        service = common.SERVICES[kind]
        wait_marker(node, f"COMMON_GATEWAY_DISCOVERY_CERTIFIED service={service} node={service}{slot}")
        checksum = call("docker", "exec", node, "sh", "-c",
                        'set -- "$1"/com.app.common-*.jar; test "$#" -eq 1 && sha256sum "$1"',
                        "--", f"/srv/dc/dc/{service}/lib").split()[0]
        if checksum != common_sha:
            raise RuntimeError(f"{node} runs a different Common JAR from physical qualification")
        directory = f"{ready}/{service}/{service}{slot}/{service}/{service}{slot}"
        if call("docker", "exec", node, "sh", "-c", 'find "$1" -name business.wal | wc -l', "--", directory) != "256":
            raise RuntimeError(f"{node} failed to open its physical WALs")
    for kind, service in common.SERVICES.items():
        actual = call("docker", "exec", "dc-saas-zookeeper", "zkCli.sh", "-server", "127.0.0.1:49181",
                      "get", f"{namespace}/{kind}/manifest")
        rows = [line for line in actual.splitlines() if re.match(r"^P[0-9]{3}\|", line)]
        expected = setup.manifest(service).splitlines()[1:]
        if rows != [row.replace("|1|", "|2|").replace("RECOVERING", "READY") for row in expected]:
            raise RuntimeError(f"{service} failed the signed 256-partition READY check")
    print("Both signed E2 fleets READY; four voters opened 1,024 business WALs", flush=True)


if __name__ == "__main__":
    main()
