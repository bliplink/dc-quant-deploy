#!/usr/bin/env python3
"""Replace one voter in the active, verified Mac Demo; Common does all handoffs."""
import argparse
from datetime import datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys
import tempfile
import time
import zlib


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tests"))
from t457_readonly_common_ha_preflight import common_sha, parse_manifest  # noqa: E402

FRESH = runpy.run_path(str(HERE / "mac-demo-fresh.py"))
ROBOT_TRAFFIC = runpy.run_path(str(HERE / "mac-demo-robot-traffic.py"))
read, run = FRESH["read"], FRESH["run"]


def inspect(name):
    result = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, timeout=15)
    return json.loads(result.stdout)[0] if result.returncode == 0 else None


def physical_hashes(container, service, physical, survivor, local_rows, strict_rows):
    node = service + physical
    root = f"{FRESH['VOLUMES']['ready']}/{service}/{node}"
    files = {}
    for partition, local in sorted(local_rows.items()):
        local_epoch = local["epoch"]
        strict_epoch = strict_rows[partition]["epoch"]
        wal = "local-async-business.wal" if physical == survivor else "local-async-replica.wal"
        files[f"{partition}/wal"] = f"{root}/{service}/{node}/{partition}/epoch-{local_epoch}/{wal}"
        files[f"{partition}/snapshot"] = (f"{root}/recovery-exchange/{service}/{partition}/epoch-{strict_epoch - 1}"
                                          f"/target/original-e{strict_epoch}-{node}.genesis")
    commands = ["set -eu"]
    for label, path in files.items():
        quoted = shlex.quote(path)
        size_test = "-s" if label.endswith("/snapshot") else "-f"
        commands.append(f"test {size_test} {quoted}; test ! -L {quoted}; printf '%s ' {label}; sha256sum {quoted}")
    result = run("docker", "exec", "-i", container, "sh", "-s", input="\n".join(commands) + "\n",
                 capture=True, timeout=180).stdout
    hashes = {}
    for line in result.splitlines():
        label, digest, file = line.split(maxsplit=2)
        if label not in files or label in hashes or files[label] != file or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise RuntimeError("Unexpected physical Common hash response")
        hashes[label] = digest
    if hashes.keys() != files.keys():
        raise RuntimeError("Missing real physical Common WAL or snapshot")
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generation", type=Path)
    parser.add_argument("service", choices=("order", "trade"))
    parser.add_argument("slot", choices=("A", "B"))
    parser.add_argument("--fault", choices=("term", "kill"), default="term")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--hold-local", type=int, default=0, help="Seconds to allow a business probe before return")
    business = parser.add_mutually_exclusive_group()
    business.add_argument("--signed-business", dest="business_mode", action="store_const", const="funded",
                          help="Place one authenticated funded match across the real failover")
    business.add_argument("--order-only-business", dest="business_mode", action="store_const", const="order-only",
                          help="Verify unfunded matching while the Order cluster has one voter")
    parser.add_argument("--robot-traffic", action="store_true", help="Require continuous Robot and Tape evidence across the fault")
    parser.add_argument("--robot-location", help="Track this existing Robot tenant across the fault")
    parser.add_argument("--resume", type=Path, help="Continue a failed exercise from its witnessed LOCAL or already-started return")
    parser.add_argument("--replacement-image", help="Use a reviewed application overlay with the exact original Common and shared JARs")
    args = parser.parse_args()
    root = args.generation.resolve(strict=True)
    generation, kind, slot = root.name, args.service, args.slot
    if (root.parent != FRESH["LOCAL"].resolve() or not re.fullmatch(r"mac-demo-\d{8}-\d{6}", generation)
            or read("uname", "-s") != "Darwin" or read("docker", "context", "show") != "colima"
            or not 60 <= args.timeout <= 3600 or not 0 <= args.hold_local <= 600):
        raise RuntimeError("Expected the exact active Mac generation and bounded recovery waits")
    if args.business_mode == "order-only" and kind != "order":
        raise RuntimeError("Order-only matching exercises the Order cluster")
    if args.robot_location and (not args.robot_traffic or not ROBOT_TRAFFIC["SAFE"].fullmatch(args.robot_location)):
        raise RuntimeError("Robot location requires an exact tenant identifier and --robot-traffic")
    if args.resume and (args.business_mode or args.robot_traffic):
        raise RuntimeError("A fresh rollout is required for the pre-fault business baseline")
    os.umask(0o077)
    with (root.parent / ".mac-demo-fresh.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("A Mac Demo deployment or voter replacement is already running") from exc
        if not args.resume:
            FRESH["require_docker_space"]()
        exercise(root, generation, kind, slot, args)


def exercise(root, generation, kind, slot, args):
    release = root / "common-release.env"
    if not release.is_file():
        raise RuntimeError("This generation was not deployed with verified Common automatic recovery")
    image_meta = FRESH["env_pairs"](release)
    if not FRESH["verified_common_release"](image_meta):
        raise RuntimeError("A passed Common build is required for a real Mac voter replacement")
    client_ack_policy = FRESH["selected_client_ack_policy"](
        image_meta, image_meta.get("client_ack_policy", "STRICT_QUORUM"))
    for service in ("zookeeper", "gateway"):
        item = inspect("dc-saas-" + service)
        if not item or not item["State"]["Running"] or item["Config"]["Labels"].get("com.docker.compose.project") != generation:
            raise RuntimeError("This is not the active Mac Demo generation")
    svc = FRESH["SERVICES"][kind]
    peer = "A" if slot == "B" else "B"
    name = f"{generation}-{kind}-{slot.lower()}-hostready"
    peer_name = f"{generation}-{kind}-{peer.lower()}-hostready"
    witness_name = f"{generation}-{kind}-witness"
    prior = None
    observing_return = False
    if args.resume:
        evidence = args.resume.resolve(strict=True)
        if (evidence.parent.parent != root or evidence.name != "evidence.json"
                or not evidence.parent.name.startswith(f"ha-{kind}-{slot.lower()}-{args.fault}-")):
            raise RuntimeError("Resume requires prior local evidence from this exact active exercise")
        prior = json.loads(evidence.read_text())
        observing_return = bool(prior.get("replacement_id"))
        if observing_return and (args.replacement_image or args.hold_local):
            raise RuntimeError("An already-started return only permits observation of the existing replacement")
    plan = json.loads((root / "common" / "config-hostready" / kind / slot / "voter-launch.json").read_text())
    flags, image = plan["flags"], plan["image"]
    allowed = {"--name", "--network", "--restart", "--label", "--memory", "--cpus", "-e", "-v", "--mount"}
    log_options = FRESH["DOCKER_LOG_OPTIONS"]
    log_flags = set(log_options[::2])
    if (len(flags) % 2 or not all(isinstance(v, str) for v in flags)
            or flags[:2] != ["--name", name] or any(flag not in allowed | log_flags for flag in flags[::2])
            or flags[::2].count("--name") != 1 or not re.fullmatch(r"sha256:[a-f0-9]{64}", image)):
        raise RuntimeError("Unexpected recorded Mac voter launch arguments")
    recorded_logging = tuple(value for i in range(0, len(flags), 2) if flags[i] in log_flags
                             for value in flags[i:i + 2])
    if recorded_logging and recorded_logging != log_options:
        raise RuntimeError("Unexpected recorded Mac voter logging options")
    common = image_meta["common_sha256"]
    approved_overlays = set()

    def verify_overlay(derived, running_container=None, permit_gateway_overlay=False):
        if derived == image or derived in approved_overlays:
            return
        config = json.loads(read("docker", "image", "inspect", derived))[0]["Config"]
        labels = config.get("Labels") or {}
        application_patch = (labels.get(f"dc.demo.recovery.{kind}.application.sha256")
                             or (labels.get("dc.demo.recovery.callback.sha256", "") if kind == "order" else ""))
        if (labels.get("dc.demo.recovery.base") != image
                or not permit_gateway_overlay
                and not re.fullmatch("[a-f0-9]{64}", application_patch)):
            raise RuntimeError("Application overlay does not identify its exact approved base and change")
        for key, jar in (("common_sha256", "com.app.common"), ("shared_sha256", "com.app.dc")):
            expected = image_meta.get(key)
            path = f"/srv/dc/dc/{svc}/lib/{jar}-mac-demo.jar"
            if running_container:
                result = read("docker", "exec", running_container, "sha256sum", path)
            else:
                result = read("docker", "run", "--rm", "--network", "none", "--entrypoint", "sha256sum", derived, path)
            if not expected or result.split()[0] != expected:
                raise RuntimeError("Application overlay changed the verified Common or shared JAR bytes")
        approved_overlays.add(derived)

    old, survivor = inspect(name), inspect(peer_name)
    for container in (name, peer_name, witness_name):
        item = old if container == name else survivor if container == peer_name else inspect(container)
        retired_input = container == name and args.resume is not None and not observing_return
        if (not item or item["State"]["Running"] == retired_input
                or container == witness_name and item["Image"] != image
                or item["Config"]["Labels"].get("otc.mac.demo.generation") != generation
                or not retired_input and common_sha(container, svc) != common):
            raise RuntimeError("All three exact Common processes must be healthy before injecting a fault")
        verify_overlay(item["Image"], None if retired_input else container)
    replacement_image = old["Image"]
    if args.replacement_image:
        replacement_image = read("docker", "image", "inspect", "-f", "{{.Id}}", args.replacement_image)
        verify_overlay(replacement_image, permit_gateway_overlay=bool(args.resume))
    port = int(FRESH["env_pairs"](root / "demo.env")["ZOOKEEPER_PORT"])
    if not 1 <= port <= 65535:
        raise RuntimeError("Invalid active ZooKeeper port")
    ns = f"/otc/{generation}/{kind}"

    def zk(cmd, absent_path=None):
        result = subprocess.run(["docker", "exec", "-i", "dc-saas-zookeeper", "zkCli.sh", "-server", f"127.0.0.1:{port}"],
                                input=f"{cmd}\nquit\n", text=True, capture_output=True, timeout=35)
        if result.returncode == 0:
            return result.stdout
        if (absent_path is not None and result.returncode == 1
                and f"Node does not exist: {absent_path}" in result.stderr.splitlines()):
            return None
        raise RuntimeError("Active ZooKeeper CLI failed while reading the exact HA namespace")

    def manifest():
        result = zk("get " + ns + "/manifest")
        serials = re.findall(r"^NPC1\|([1-9][0-9]*)$", result, re.M)
        if len(serials) != 1:
            raise RuntimeError("Expected one authenticated manifest generation")
        return int(serials[0]), parse_manifest(result)

    def census():
        return manifest()[1]

    def wait_for_gateway_routes(containers, expected, seconds=90):
        generation, rows = manifest()
        if rows != expected:
            raise RuntimeError("The signed census changed before the Gateway routing check")
        marker = f"COMMON_GATEWAY_CERTIFIED_PARTITION_ROUTING_PASS service={svc} partitions=256 manifestGeneration={generation} "
        deadline = time.monotonic() + seconds
        pending = set(containers)
        while pending and time.monotonic() < deadline:
            for container in list(pending):
                logs = subprocess.run(["docker", "logs", "--since", "5m", container],
                                      capture_output=True, text=True, timeout=20, check=True)
                if marker in logs.stdout or marker in logs.stderr:
                    pending.remove(container)
            if pending:
                time.sleep(2)
        if pending or manifest() != (generation, expected):
            raise RuntimeError("Gateway did not certify the exact stable physical census")
        return generation

    def lease(member):
        path = f"{ns}/leases/{member}"
        value = zk(f"stat {path}", absent_path=path)
        if value is None:
            return None
        owner = re.findall(r"^ephemeralOwner\s*=\s*(0x[0-9a-fA-F]+)\s*$", value, re.M)
        if len(owner) != 1 or int(owner[0], 16) == 0:
            raise RuntimeError("Active voter has no unique ephemeral ZooKeeper lease")
        return int(owner[0], 16)

    def home(partition):
        return "A" if int(partition[1:]) < 128 else "B"

    def ready(row, primary, replica, policy, epoch=None):
        return (row["state"] == "READY" and row["primary"] == svc + primary and row["replica"] == svc + replica
                and row["policy"] == policy and (row["epoch"] == epoch if epoch is not None else row["epoch"] >= 2))

    initial = census()
    original_lease, survivor_lease = lease(svc + slot), lease(svc + peer)
    output = Path(tempfile.mkdtemp(prefix=f"ha-{kind}-{slot.lower()}-{args.fault}-", dir=root))
    record = {"generation": generation, "service": svc, "slot": slot, "fault": args.fault,
              "common_sha256": common, "client_ack_policy": client_ack_policy,
              "status": "NO_GO", "original_id": old["Id"], "initial": initial,
              "survivor_id": survivor["Id"], "survivor_lease": survivor_lease,
              "replacement_image": replacement_image}
    if prior is not None:
        saved_initial = prior.get("initial", {})
        saved_local = prior.get("survivor_local", {})
        late_local = (not saved_local and not prior.get("replacement_id")
                      and prior.get("failure") == "RuntimeError: Timed out waiting for Common to publish survivor_local")
        if late_local:
            # Observe the actual now-complete signed LOCAL census. The failed
            # earlier poll remains immutable and is never relabeled PASS.
            saved_local = initial
        if (any(prior.get(key) != record[key] for key in
                ("generation", "service", "slot", "fault", "common_sha256"))
                or prior.get("client_ack_policy", "STRICT_QUORUM") != client_ack_policy
                or any(key in prior and prior[key] != record[key] for key in ("survivor_id", "survivor_lease"))
                or prior.get("stage") != "failed" or prior.get("status") != "NO_GO"
                or not survivor_lease or saved_initial.keys() != initial.keys() or saved_local.keys() != initial.keys()
                or not all(ready(row, home(p), "B" if home(p) == "A" else "A", "STRICT_QUORUM")
                           and ready(saved_local[p], peer, slot, "LOCAL_DURABLE_ASYNC", row["epoch"] + 1)
                           for p, row in saved_initial.items())):
            raise RuntimeError("Previous failure is not the exact current witnessed LOCAL position")
        if observing_return:
            retired_id = prior.get("original_id", "")
            retired_original = inspect(retired_id) if re.fullmatch(r"[a-f0-9]{64}", retired_id) else None
            wait_expired = prior.get("failure") == "RuntimeError: Timed out waiting for Common to publish strict_home"
            poll_expired = prior.get("failure") == "TimeoutExpired" and not prior.get("strict_home")
            if (not (wait_expired or poll_expired)
                    or prior["replacement_id"] != old["Id"] or prior.get("replacement_image") != replacement_image
                    or old.get("RestartCount") != 0
                    or not original_lease or original_lease == survivor_lease or not retired_original
                    or retired_original["State"]["Running"]
                    or retired_original["State"]["ExitCode"] != prior.get("old_exit_code")
                    or retired_original["Config"]["Labels"].get("otc.mac.demo.generation") != generation
                    or not all(saved_local[p]["epoch"] <= row["epoch"] <= saved_initial[p]["epoch"] + 2 + (home(p) == slot)
                               for p, row in initial.items())):
                raise RuntimeError("Cannot observe an unrelated or restarted replacement")
        elif prior.get("original_id") != old["Id"] or saved_local != initial or original_lease is not None:
            raise RuntimeError("Previous failure is not the exact current witnessed LOCAL position")
        record = dict(prior, resumed_from=str(evidence), replacement_image=replacement_image,
                      survivor_id=record["survivor_id"], survivor_lease=survivor_lease,
                      survivor_local=saved_local, client_ack_policy=client_ack_policy)
        if late_local:
            record["survivor_local_observed_after_failed_poll_at"] = datetime.now().astimezone().isoformat()
        record.pop("failure", None)
        initial = saved_initial
    elif not original_lease or not survivor_lease or original_lease == survivor_lease or not all(
            ready(row, home(p), "B" if home(p) == "A" else "A", "STRICT_QUORUM") for p, row in initial.items()):
        raise RuntimeError("The real cluster must start with two independent leases and all 256 Home positions strict")

    def publish(stage):
        record["stage"] = stage
        staged = output / "evidence.tmp"
        staged.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        staged.replace(output / "evidence.json")
        print(f"[mac-demo HA] {svc}{slot}: {stage}; {output}", flush=True)

    def wait(stage, predicate, active_id=None, observed_shard=None):
        start = time.monotonic()
        shown = -32
        while time.monotonic() - start < args.timeout:
            try:
                if active_id is not None:
                    active = inspect(active_id)
                    if not active or not active["State"]["Running"]:
                        code = None if not active else active["State"]["ExitCode"]
                        raise RuntimeError(f"Replacement exited during {stage} (exit {code}); signed recovery left in place")
                rows = census()
            except subprocess.TimeoutExpired:
                time.sleep(2)
                continue
            passed = sum(predicate(partition, row) for partition, row in rows.items())
            if (observed_shard and "robot_partition_local" not in record
                    and predicate(observed_shard, rows[observed_shard])):
                record["robot_partition_local"] = {
                    "partition": observed_shard, "at": utc_now().isoformat(),
                    "ready_partitions": passed, **rows[observed_shard],
                }
                publish("robot_partition_local")
            if passed == 256:
                record[stage] = rows
                record[stage + "_seconds"] = round(time.monotonic() - start, 3)
                publish(stage)
                return
            if passed >= shown + 32:
                print(f"[mac-demo HA] {svc}{slot}: {stage} {passed}/256", flush=True)
                shown = passed
            time.sleep(2)
        raise RuntimeError(f"Timed out waiting for Common to publish {stage}")

    publish("resume_existing_return" if observing_return else "resume_witnessed_local" if args.resume else "before_fault")
    retired = f"{name}-retained-{output.name.rsplit('-', 1)[-1]}"
    renamed = False
    business = None
    robot_problem = None
    order_nodes = [f"{generation}-order-{node}-hostready" for node in ("a", "b")]
    trade_nodes = [f"{generation}-trade-{node}-hostready" for node in ("a", "b")]
    utc_now = ROBOT_TRAFFIC["utc_now"]

    def robot_identity():
        robot = inspect(ROBOT_TRAFFIC["ROBOT"])
        if (not robot or not robot["State"]["Running"]
                or robot["Config"]["Labels"].get("com.docker.compose.project") != generation):
            raise RuntimeError("Expected the running Robot from this exact Mac Demo generation")
        return [robot["Id"], robot["State"]["StartedAt"], robot["RestartCount"]]

    def robot_partition(location):
        route_key = f"{location}\x1f4\x1fBTCUSDT" if kind == "order" else location
        return f"P{zlib.crc32(route_key.encode()) % 256:03d}"

    def wait_business_marker(marker, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (output / (marker + ".json")).is_file():
                return json.loads((output / (marker + ".json")).read_text())
            if business.poll() is not None:
                raise RuntimeError(f"Signed business probe exited before {marker} (exit {business.returncode})")
            time.sleep(1)
        raise RuntimeError(f"Timed out waiting for signed business checkpoint {marker}")

    try:
        if args.business_mode:
            with (output / "signed-business.log").open("w") as transcript:
                business = subprocess.Popen(
                    ["bash", str(HERE / "verify-mac-demo-fresh.sh"), str(root), str(output),
                     str(args.timeout + 300), args.business_mode],
                    stdout=transcript, stderr=subprocess.STDOUT)
            record["business_maker"] = wait_business_marker("business-maker", 360)
            publish("business_maker_resting")
        if not args.resume:
            observed_shard = None
            if args.robot_traffic:
                record["robot_identity"] = robot_identity()
                record["robot_before_fault"] = ROBOT_TRAFFIC["wait_traffic"](
                    order_nodes, trade_nodes, utc_now() - timedelta(minutes=3), args.robot_location,
                    prefer_location=lambda location: initial[robot_partition(location)]["primary"] == svc + slot)
                robot_location = record["robot_before_fault"]["location"]
                observed_shard = robot_partition(robot_location)
                record["robot_partition_before_fault"] = {"partition": observed_shard, **initial[observed_shard]}
                fault_started = utc_now()
                record["robot_fault_started_at"] = fault_started.isoformat()
                publish("robot_before_fault")
            if args.fault == "term":
                run("docker", "stop", "--time", "45", old["Id"], capture=True, timeout=60)
            else:
                run("docker", "kill", "--signal", "KILL", old["Id"], capture=True, timeout=15)
            stopped = inspect(old["Id"])["State"]
            record["old_exit_code"] = stopped["ExitCode"]
            record["old_finished_at"] = stopped["FinishedAt"]
            if record["old_exit_code"] not in ({0, 143} if args.fault == "term" else {137}):
                raise RuntimeError("Voter exit code does not match the requested fault")
            wait("survivor_local", lambda p, row: ready(row, peer, slot, "LOCAL_DURABLE_ASYNC", initial[p]["epoch"] + 1),
                 observed_shard=observed_shard)
        if lease(svc + slot) != (original_lease if observing_return else None) or lease(svc + peer) != survivor_lease:
            raise RuntimeError("Voter or survivor changed physical sessions")
        if args.robot_traffic:
            local_started = utc_now()
            record["robot_local_started_at"] = local_started.isoformat()
            early = record.get("robot_partition_local")
            if early and early["ready_partitions"] < 256:
                try:
                    begin = datetime.fromisoformat(early["at"])
                    quotes, requests, _, fills = ROBOT_TRAFFIC["snapshot"](
                        [peer_name] if kind == "order" else order_nodes,
                        [peer_name] if kind == "trade" else trade_nodes, begin, local_started)
                    record["robot_before_full_takeover"] = {
                        "location": robot_location, "from": early["at"], "until": local_started.isoformat(),
                        "quote_requests": sum(location == robot_location for location, _, _ in quotes),
                        "tape_requests": sum(location == robot_location for location, _ in requests),
                        "tape_execution_ids": sorted({exec_id for location, exec_id in fills
                                                      if location == robot_location}),
                    }
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    record["robot_before_full_takeover_observation_failure"] = type(exc).__name__
        business_problem = None
        if business is not None:
            try:
                record["business_local_ready_manifest"] = wait_for_gateway_routes([peer_name], record["survivor_local"])
                record["business_local_ready"] = record["survivor_local"]
                record["business_local_started_at"] = utc_now().isoformat()
                publish("business_local_ready")
                checkpoint = wait_business_marker("business-local", 240)
                maker = record["business_maker"]
                if (checkpoint.get("location") != maker.get("location")
                        or checkpoint.get("maker_client_order_id") != maker.get("client_order_id")
                        or checkpoint.get("service") != svc or checkpoint.get("slot") != slot
                        or census() != record["survivor_local"]):
                    raise RuntimeError("Business checkpoint did not use the exact witnessed LOCAL census")
                if not checkpoint.get("client_order_id") or checkpoint["client_order_id"] == maker["client_order_id"]:
                    raise RuntimeError("Order did not acknowledge the test counterorder in LOCAL")
                if kind == "trade":
                    if checkpoint.get("verified_accounts") != 2:
                        raise RuntimeError("Trade did not apply both account and position changes while LOCAL")
                    receipts = checkpoint.get("final_local_receipts", {})
                    if set(receipts) != {"maker", "taker"}:
                        raise RuntimeError("Both final LOCAL receipts must arrive before Trade replica return")
                    logs = subprocess.run(["docker", "logs", "--since", "10m", peer_name],
                                          capture_output=True, text=True, timeout=20, check=True)
                    location = re.escape(checkpoint["location"])
                    audit = re.findall(
                        rf"TRADE_LOCAL_MATCH_RECEIPT location={location} symbol=BTC003USDT "
                        r"coordinate=(P[0-9]{3})/([1-9][0-9]*)/([1-9][0-9]*) quorumDurable=false rpoRisk=true",
                        logs.stdout + logs.stderr)
                    if len(audit) != 1:
                        raise RuntimeError("Expected exactly one actual LOCAL Trade commit for the controlled match")
                    partition, epoch, sequence = audit[0]
                    if int(epoch) != record["survivor_local"][partition]["epoch"]:
                        raise RuntimeError("Trade LOCAL receipt did not match the actual witness-authorized Epoch")
                    if any(receipt.get("TradeSettlementCommit") != f"{partition}/{epoch}/{sequence}"
                           or receipt.get("TradeSettlementDurability") != "LOCAL_DURABLE_ASYNC"
                           or receipt.get("TradeSettlementQuorumDurable") is not False
                           or receipt.get("TradeSettlementRpoRisk") is not True
                           for receipt in receipts.values()):
                        raise RuntimeError("Client final receipt differs from the actual LOCAL Trade commit")
                    record["business_local_trade_coordinate"] = [partition, int(epoch), int(sequence)]
                record["business_local"] = checkpoint
                publish("business_local_observed")
            except (RuntimeError, OSError, ValueError) as exc:
                business_problem = str(exc)
                record["business_failure"] = business_problem
        if args.robot_traffic:
            try:
                record["robot_during_takeover"] = ROBOT_TRAFFIC["rounds"](robot_location, fault_started, local_started)
                record["robot_while_local"] = ROBOT_TRAFFIC["wait_traffic"](
                    [peer_name] if kind == "order" else order_nodes,
                    [peer_name] if kind == "trade" else trade_nodes,
                    local_started, robot_location, record["survivor_local"] if kind == "trade" else None,
                    record["robot_before_fault"]["quote_requests"])
                if inspect(old["Id"])["State"]["Running"] or robot_identity() != record["robot_identity"]:
                    raise RuntimeError("Robot or faulted node changed state during the LOCAL measurement")
                publish("robot_local_observed")
            except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
                robot_problem = str(exc)
                record["robot_traffic_failure"] = robot_problem
        if args.hold_local:
            time.sleep(args.hold_local)
        if observing_return:
            new_id = prior["replacement_id"]
        else:
            if args.robot_traffic:
                returning_started = utc_now()
            run("docker", "rename", old["Id"], retired, capture=True)
            renamed = True
            new_id = read("docker", "run", "-d", *flags, replacement_image)
            record["replacement_id"] = new_id
            publish("replacement_started")
        wait("strict_home", lambda p, row: ready(row, home(p), "B" if home(p) == "A" else "A",
                                                  "STRICT_QUORUM", initial[p]["epoch"] + 2 + (home(p) == slot)), active_id=new_id)
        new_lease = lease(svc + slot)
        new = inspect(name)
        valid_new_lease = new_lease == original_lease if observing_return else new_lease != original_lease
        if (not new_lease or not valid_new_lease or new_lease == survivor_lease or lease(svc + peer) != survivor_lease
                or not new or not new["State"]["Running"] or new.get("RestartCount") != 0
                or new["Id"] != new_id or new_id == record["original_id"]
                or new["Image"] != replacement_image or common_sha(name, svc) != common):
            raise RuntimeError("Replacement did not retain the exact identity, runtime JAR and new physical lease")
        returned = physical_hashes(name, svc, slot, peer, record["survivor_local"], record["strict_home"])
        survived = physical_hashes(peer_name, svc, peer, peer, record["survivor_local"], record["strict_home"])
        unequal = sorted(key for key in returned if returned[key] != survived[key])
        record["immutable_wal_and_snapshot_hashes"] = {"returned": returned, "survivor": survived, "unequal": unequal}
        if unequal:
            raise RuntimeError("Retired LOCAL WAL or strict recovery snapshot differs between physical voters")
        record["status"] = "COMMON_PHYSICAL_PAIRS_PASS_BUSINESS_PROOF_PENDING"
        if args.robot_traffic:
            strict_started = utc_now()
        if business is not None and business_problem is None:
            record["business_readback_manifest"] = wait_for_gateway_routes(
                [name, peer_name], record["strict_home"])
            record["business_readback"] = record["strict_home"]
            publish("business_readback")
            if business.wait(timeout=240) != 0:
                raise RuntimeError("Signed business probe failed after physical recovery; see signed-business.log")
            match = json.loads((output / "business-match.json").read_text())
            if match.get("location") != record["business_local"]["location"]:
                raise RuntimeError("Exact signed match evidence was not written for the controlled tenant")
            record["business_match"] = match
            minimum_epoch = match["source_epoch"] if args.business_mode == "funded" else 2
            check = HERE.parent / "tests" / "check_certified_trade_financial_cursor.py"
            for _ in range(8):
                result = subprocess.run([sys.executable, str(check), "--mysql", "dc-saas-mysql",
                                         "--min-epoch", str(minimum_epoch), "--require-predecessors"], capture_output=True, text=True, timeout=130)
                (output / "financial-cursor.json").write_text(result.stdout)
                if result.returncode == 0:
                    break
                time.sleep(3)
            else:
                raise RuntimeError("Certified SQL balances and positions did not reconcile after failover")
            record["business_mode"] = args.business_mode
            record["status"] = "COMMON_PHYSICAL_AND_SIGNED_BUSINESS_PASS_ROBOT_PROOF_PENDING"
        elif business_problem is not None:
            raise RuntimeError("Signed business probe failed during LOCAL; physical recovery was verified")
        if args.robot_traffic:
            if robot_problem:
                raise RuntimeError("Robot traffic probe failed during LOCAL; physical recovery was verified")
            record["robot_during_return"] = ROBOT_TRAFFIC["rounds"](robot_location, returning_started, strict_started)
            previous = record["robot_before_fault"]["quote_requests"] + record["robot_while_local"]["quote_requests"]
            record["robot_after_return"] = ROBOT_TRAFFIC["wait_traffic"](
                order_nodes, trade_nodes, strict_started, robot_location, previous_quotes=previous)
            if robot_identity() != record["robot_identity"]:
                raise RuntimeError("Robot restarted during the real fault and return")
            before_ids = set(record["robot_before_fault"]["tape_execution_ids"])
            local_ids = set(record["robot_while_local"]["tape_execution_ids"])
            after_ids = set(record["robot_after_return"]["tape_execution_ids"])
            if before_ids & local_ids or (before_ids | local_ids) & after_ids:
                raise RuntimeError("A Tape execution was repeated across fault phases")
            for key in ("robot_while_local", "robot_after_return"):
                record[key]["posting_event_ids"] = ROBOT_TRAFFIC["require_posting_pairs"](record[key])
        if business is not None:
            record["status"] = "COMMON_PHYSICAL_MATCH_AND_FINANCIAL_CURSOR_PASS"
        elif args.robot_traffic:
            record["status"] = "COMMON_PHYSICAL_AND_ROBOT_TRAFFIC_PASS"
        publish("complete")
    except (Exception, KeyboardInterrupt) as exc:
        record["failure"] = type(exc).__name__ + (": "+str(exc) if isinstance(exc, RuntimeError) else "")
        publish("failed")
        if renamed and inspect(name) is None:
            run("docker", "rename", old["Id"], name, capture=True)
            renamed = False
        raise
    finally:
        if business is not None and business.poll() is None:
            try:
                business.wait(timeout=25)
            except subprocess.TimeoutExpired:
                business.terminate()
                business.wait(timeout=10)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc) if isinstance(exc, (OSError, RuntimeError)) else "Mac voter command failed; see the local evidence")
