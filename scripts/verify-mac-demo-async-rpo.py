#!/usr/bin/env python3
"""Exercise one real locally acknowledged financial fill before replica catchup."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import signal
import struct
import subprocess
import time
import zlib


HERE = Path(__file__).resolve().parent
CANCEL = runpy.run_path(str(HERE / "verify-mac-demo-order-cancel-capacity.py"))
CAPACITY = CANCEL["CAPACITY"]
PRODUCT = CAPACITY["PRODUCT"]
FRESH = CAPACITY["FRESH"]
ROLL = runpy.run_path(str(HERE / "roll-mac-demo-voter.py"))
ROBOT = ROLL["ROBOT_TRAFFIC"]
URL = CANCEL["URL"]
QUANTITY = Decimal("0.001")
RECEIPT_OBSERVATION_SECONDS = 2.0
REPLICA_PAUSE_WATCHDOG_SECONDS = 4.0


class IncompleteWalObservation(RuntimeError):
    pass


def run(*arguments, **options):
    return subprocess.run(arguments, check=True, text=True, capture_output=True, timeout=30, **options).stdout.strip()


def inspect(name):
    return json.loads(run("docker", "inspect", name))[0]


def until(check, timeout, message):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.1)
    raise RuntimeError(message)


def manifest(root, kind):
    port = FRESH["env_pairs"](root / "demo.env")["ZOOKEEPER_PORT"]
    output = run("docker", "exec", "-i", "dc-saas-zookeeper", "zkCli.sh", "-server", "127.0.0.1:" + port,
                 input=f"get /otc/{root.name}/{kind}/manifest\nquit\n")
    return CAPACITY["parse_manifest"](output)


def wait_roles(root, owner=None):
    shown = -1
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        rows = manifest(root, "trade")
        complete = 0
        for partition, row in rows.items():
            expected = owner or ("TradeSvrA" if int(partition[1:]) < 128 else "TradeSvrB")
            policy = "LOCAL_DURABLE_ASYNC" if owner else "STRICT_QUORUM"
            complete += row["state"] == "READY" and row["primary"] == expected and row["policy"] == policy
        if complete // 32 != shown:
            shown = complete // 32
            print("[mac-demo RPO]", "LOCAL" if owner else "HOME", complete, "of 256", flush=True)
        if len(rows) == 256 and complete == 256:
            return rows
        time.sleep(2)
    raise RuntimeError("Common did not complete automatic RPO test recovery")


def position(trader, symbol, side):
    location, _, token = trader
    value = PRODUCT["ok"](URL, "TradeSvr", "queryTradePosition", {"securityid": symbol}, token,
                          route_location=location)
    return Decimal(str(value.get(side + "Position", "0"))) if value else Decimal(0)


def refresh_trader(trader, run_id, index, password):
    location, user, _ = trader
    username = f"cancelcap_{run_id}_{index}"
    token = PRODUCT["ok"](URL, "LoginSvr", "SYS.ATS.LOGIN", {
        "method": "login", "cid": username, "user_id": user, "user_name": username,
        "password": password, "client_type": "WEB", "Location": location,
    })["token"]
    return location, user, token


def place(trader, symbol, side, client, tif):
    location, user, token = trader
    return PRODUCT["ok"](URL, "OrderSvr", "placeOrder", {
        "OCType": "OPEN", "OrderQty": str(QUANTITY), "OrdType": "Limit", "ClOrdID": client,
        "Terminal": "API", "AlgoName": "cross", "Side": side, "Price": "90000", "UserID": user,
        "MarketIndicator": "4", "TimeInForce": tif, "SecurityID": symbol, "Location": location, "Demo": "0",
    }, token)


def match_row(client):
    rows = PRODUCT["readonly_sql"](
        "SELECT partition_id,source_epoch,journal_seq,payload FROM dc_order_projection_event "
        "WHERE event_type='STATE_ATOMIC_MATCH_V1' "
        f"AND payload LIKE '%{client}%' ORDER BY source_epoch DESC,journal_seq DESC LIMIT 2")
    if not rows:
        return None
    if len(rows) != 1:
        raise RuntimeError("Controlled match has multiple physical projection origins")
    partition, epoch, sequence, payload = rows[0]
    return {"partition": partition, "epoch": int(epoch), "sequence": int(sequence),
            "match_key": json.loads(payload)["matchKey"]}


def final_reports(node, since, clients):
    found = {}
    for line in ROBOT["logs"](node, since, datetime.now(timezone.utc)):
        if not any(client in line for client in clients) or '"TradeSettlementRpoRisk":true' not in line:
            continue
        offset = line.find("[{")
        if offset < 0:
            continue
        try:
            reports, _ = json.JSONDecoder().raw_decode(line[offset:])
        except ValueError:
            continue
        for report in reports:
            client = report.get("ClOrdID")
            if (client in clients and report.get("ExecType") == "Trade" and report.get("OrdStatus") == "Filled"
                    and report.get("TradeSettlementDurability") == "LOCAL_DURABLE_ASYNC"
                    and report.get("TradeSettlementQuorumDurable") is False
                    and report.get("TradeSettlementRpoRisk") is True):
                found[client] = {key: report.get(key) for key in (
                    "ClOrdID", "ExecID", "OrdStatus", "TradeSettlementDurability", "TradeSettlementQuorumDurable",
                    "TradeSettlementRpoRisk", "TradeSettlementCommit")}
    return found if found.keys() == clients else None


def wait_final_reports(node, since, clients):
    # Start after Docker has paused the replica and released delivery. Host
    # orchestration time does not measure the business receipt latency.
    deadline = time.monotonic() + RECEIPT_OBSERVATION_SECONDS
    while time.monotonic() < deadline:
        receipts = final_reports(node, since, clients)
        if receipts is not None:
            return receipts
    return None


def require_pause_lease_budget(properties):
    values = re.findall(r'^\s*trade\.common\.control\.leaseTtlMs\s*=\s*(\d+)\s*$',
                        properties.read_text(), re.M)
    if len(values) != 1:
        raise RuntimeError("Controlled replica pause requires one exact configured node lease")
    lease_ttl_ms = int(values[0])
    if lease_ttl_ms < 3 * REPLICA_PAUSE_WATCHDOG_SECONDS * 1000:
        raise RuntimeError("Controlled replica pause requires a sufficient existing node lease")
    return lease_ttl_ms


def observe_physical_head(node, target_pid, tools_path, partition, sequence, prefix):
    output = tools_path + "/physical-head-" + secrets.token_hex(4) + ".txt"
    run("docker", "exec", node, "/opt/java/openjdk/bin/java", "-cp",
        "/opt/java/openjdk/lib/tools.jar:" + tools_path, "T554RpoAttach", target_pid,
        tools_path + "/head-observer.jar", f"{output},{partition},2,{sequence},{prefix}")
    return run("docker", "exec", node, "cat", output)


def copy_wal(node, slot, partition, target):
    base = FRESH["VOLUMES"]["ready"]
    source = f"{base}/TradeSvr/TradeSvr{slot}/TradeSvr/TradeSvr{slot}/{partition}/epoch-2/business.wal"
    run("docker", "cp", node + ":" + source, str(target))
    target.chmod(0o600)
    if target.stat().st_size > 64 * 1024 * 1024:
        raise RuntimeError("Controlled original WAL exceeds this bounded test")
    raw = target.read_bytes()
    offset = 0
    count = 0
    while offset < len(raw):
        if len(raw) - offset < 28:
            raise IncompleteWalObservation("Physical test observation caught an incomplete WAL header")
        magic, epoch, sequence, size, checksum = struct.unpack_from(">IqqII", raw, offset)
        payload = raw[offset + 28:offset + 28 + size]
        if len(payload) != size:
            raise IncompleteWalObservation("Physical test observation caught an incomplete WAL payload")
        if (magic != 0x43425731 or epoch != 2 or sequence != count + 1 or not 0 < size <= 1024 * 1024
                or zlib.crc32(struct.pack(">qq", epoch, sequence) + payload) != checksum):
            raise RuntimeError("Physical test WAL CRC or coordinate is invalid")
        offset += 28 + size
        count += 1
    return raw, count


def arm_pause_watchdog(backup_id, output):
    # Separate process session survives a terminated test driver. It only
    # releases the explicitly selected temporary Docker pause.
    ready = output / "pause-watchdog.armed"
    code = """
import json, pathlib, re, subprocess, sys, time
identifier, marker, pause_seconds = sys.argv[1:]
assert re.fullmatch(r'[0-9a-f]{64}', identifier)
pathlib.Path(marker).write_text('armed\\n')
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    state = json.loads(subprocess.check_output(['docker', 'inspect', identifier], text=True))[0]['State']
    if state['Paused']:
        time.sleep(float(pause_seconds))
        state = json.loads(subprocess.check_output(['docker', 'inspect', identifier], text=True))[0]['State']
        if state['Paused']:
            subprocess.run(['docker', 'unpause', identifier], check=True)
            print('T554_TEST_PAUSE_DEADLINE_RELEASED', flush=True)
        else:
            print('T554_TEST_DRIVER_ALREADY_RELEASED_PAUSE', flush=True)
        break
    time.sleep(0.01)
else:
    print('T554_TEST_PAUSE_NOT_STARTED', flush=True)
"""
    with (output / "pause-watchdog.log").open("x") as log:
        process = subprocess.Popen(["colima", "ssh", "--", "sudo", "python3", "-c", code, backup_id, str(ready),
                                    str(REPLICA_PAUSE_WATCHDOG_SECONDS)],
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    until(ready.exists, 5, "Temporary replica pause watchdog did not arm")
    return process


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generation", type=Path)
    parser.add_argument("--tools", type=Path,
                        default=Path.home() / ".opentradingcore/t554-rpo-delivery-fault-agent-20261112-v2")
    args = parser.parse_args()
    root = args.generation.resolve(strict=True)
    os.umask(0o077)
    with (FRESH["LOCAL"] / ".mac-demo-fresh.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        CAPACITY["require_strict_demo"](root)
        release = CAPACITY["common_release_identity"](root)
        if release["client_ack_policy"] != "LOCAL_DURABLE_ASYNC":
            raise RuntimeError("This case requires verified normal dual-node asynchronous confirmation")
        initial = {kind: manifest(root, kind) for kind in ("order", "trade")}
        if any(row["epoch"] != 2 for rows in initial.values() for row in rows.values()):
            raise RuntimeError("Run this controlled loss case on fresh Home E2 before other fault exercises")
        if any((args.tools / name).read_text().strip() != "PASS"
               for name in ("self-test.status", "linux-self-test.status",
                            "head-observer-self-test.status", "head-observer-linux-self-test.status")):
            raise RuntimeError("The bounded delivery fault helper must pass its standalone release tests")
        run_id = secrets.token_hex(4)
        output = root / ("async-rpo-" + run_id)
        output.mkdir(mode=0o700)
        record = {"generation": root.name, "common_release": release, "status": "NO_GO", "initial": initial,
                  "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "product_helper_sha256": hashlib.sha256((HERE / "verify-mac-demo-order-cancel-capacity.py").read_bytes()).hexdigest(),
                  "head_observer_sha256": hashlib.sha256((args.tools / "head-observer.jar").read_bytes()).hexdigest(),
                  "fault_helper_sha256": hashlib.sha256((args.tools / "fault-agent.jar").read_bytes()).hexdigest()}

        def save():
            temporary = output / "evidence.tmp"
            temporary.write_text(json.dumps(record, indent=2, default=str) + "\n")
            temporary.replace(output / "evidence.json")

        original_robots = CAPACITY["demo_tenants"]()
        robot_before = inspect("dc-saas-robotsvr")
        password = secrets.token_urlsafe(24)
        primary = backup = order_node = control = None
        robot_location = None
        killed = False
        kill_attempted = False
        restart_override_attempted = False
        original_restart_policy = None
        pause_attempted = False
        local = None
        failure = None
        since = datetime.now(timezone.utc)
        save()
        try:
            with CANCEL["controlled_products"](run_id, record, password) as (location, products):
                symbol = next(symbol for mode, symbol in products if mode == "TRADE")
                until(lambda: set(CAPACITY["demo_tenants"]()) == set(original_robots), 60,
                      "Controlled tenant Robot did not stop without changing the original cohort")
                until(lambda: PRODUCT["readonly_sql"]("SELECT enabled FROM dc_tenant_robot "
                    f"WHERE location='{location}' AND robot_id='trial-liquidity-BTCUSDT'") == [["0"]],
                    60, "Controlled Robot remains enabled")
                until(lambda: PRODUCT["readonly_sql"]("SELECT COUNT(*) FROM dc_orders "
                    f"WHERE location='{location}' AND ord_status NOT IN ('Filled','Cancelled','Canceled','Rejected','Expired')")
                    == [["0"]], 60, "Controlled Robot left live orders")
                partition = "P%03d" % (zlib.crc32(location.encode("utf-8")) % 256)
                collisions = [other for other in original_robots
                              if zlib.crc32(other.encode("utf-8")) % 256 == int(partition[1:])]
                record["controlled_partition"] = partition
                if collisions:
                    raise RuntimeError("Controlled Trade partition shares the active Robot cohort")
                maker_password, taker_password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
                maker = CANCEL["new_trader"](location, symbol, "TRADE", run_id, 0, maker_password)
                taker = CANCEL["new_trader"](location, symbol, "TRADE", run_id, 1, taker_password)
                record.update(location=location, symbol=symbol, maker=maker[1], taker=taker[1])
                warm = "T554RPO-" + run_id + "-WARM"
                place(maker, symbol, "Sell", warm + "-M", "GTC")
                CANCEL["await_order"](maker, symbol, warm + "-M", True)
                place(taker, symbol, "Buy", warm + "-T", "IOC")
                until(lambda: position(maker, symbol, "Short") == QUANTITY
                      and position(taker, symbol, "Long") == QUANTITY, 60, "Warmup did not settle both controlled accounts")
                warm_origin = until(lambda: match_row(warm + "-T"), 60, "Warmup original Order match was not certified")
                partitions = until(lambda: PRODUCT["readonly_sql"](
                    f"SELECT DISTINCT partition_id FROM dc_trade_projection_mutation WHERE location='{location}'"),
                    60, "Warmup financial state did not reach its certified SQL projection")
                if len(partitions) != 1:
                    raise RuntimeError("Controlled financial state has no unique Trade partition")
                if partitions[0][0] != partition:
                    raise RuntimeError("Observed financial partition differs from the Common location hash")
                owner = initial["trade"][partition]["primary"]
                primary_slot = owner[-1]
                backup_slot = "B" if primary_slot == "A" else "A"
                primary = f"{root.name}-trade-{primary_slot.lower()}-hostready"
                backup = f"{root.name}-trade-{backup_slot.lower()}-hostready"
                order_slot = initial["order"][warm_origin["partition"]]["primary"][-1]
                order_node = f"{root.name}-order-{order_slot.lower()}-hostready"
                robot_location = next(location for location in sorted(original_robots)
                                      if original_robots[location] == "RUNNING")
                order_nodes = [f"{root.name}-order-{slot}-hostready" for slot in "ab"]
                trade_nodes = [f"{root.name}-trade-{slot}-hostready" for slot in "ab"]
                record["robot_before_fault"] = ROBOT["wait_traffic"](
                    order_nodes, trade_nodes, since, robot_location)
                record.update(partition=partition, primary=primary, backup=backup, order_node=order_node,
                              primary_before=inspect(primary)["State"], backup_before=inspect(backup)["State"],
                              order_started_at=inspect(order_node)["State"]["StartedAt"],
                              backup_restart_count=inspect(backup)["RestartCount"])
                original_restart_policy = inspect(primary)["HostConfig"]["RestartPolicy"]
                if original_restart_policy != {"Name": "on-failure", "MaximumRetryCount": 0}:
                    raise RuntimeError("RPO case requires the existing unlimited on-failure restart contract")
                record["original_restart_policy"] = original_restart_policy
                tools_path = "/tmp/t554-rpo-tools-" + run_id
                control = "/tmp/t554-rpo-control-" + run_id
                run("docker", "exec", order_node, "mkdir", "-m", "700", tools_path)
                for name in ("fault-agent.jar", "T554RpoAttach.class"):
                    run("docker", "cp", str(args.tools / name), order_node + ":" + tools_path + "/" + name)
                head_observers = {}
                for node in (primary, backup):
                    run("docker", "exec", node, "mkdir", "-m", "700", tools_path)
                    for name in ("head-observer.jar", "T554RpoAttach.class"):
                        run("docker", "cp", str(args.tools / name), node + ":" + tools_path + "/" + name)
                    jvms = run("docker", "exec", node, "/opt/java/openjdk/bin/jps", "-l").splitlines()
                    target_pids = [line.split()[0] for line in jvms if "sun.tools.jps.Jps" not in line]
                    if len(target_pids) != 1:
                        raise RuntimeError("Physical head observation requires one exact live Trade JVM")
                    head_observers[node] = target_pids[0]
                jvms = run("docker", "exec", order_node, "/opt/java/openjdk/bin/jps", "-l").splitlines()
                targets = [line.split()[0] for line in jvms if "sun.tools.jps.Jps" not in line]
                if len(targets) != 1:
                    raise RuntimeError("Delivery fault has no unique actual Order JVM")
                run("docker", "exec", order_node, "/opt/java/openjdk/bin/java", "-cp",
                    "/opt/java/openjdk/lib/tools.jar:" + tools_path, "T554RpoAttach", targets[0],
                    tools_path + "/fault-agent.jar", control + ",30000")
                status = run("docker", "exec", order_node, "cat", control + "/status")
                if not status.startswith("PAUSED delivery=2 scheduler=1"):
                    raise RuntimeError("Bounded delivery hold was not established")
                record["delivery_fault"] = status
                clients = {"T554RPO-" + run_id + "-M", "T554RPO-" + run_id + "-T"}
                maker_client, taker_client = "T554RPO-" + run_id + "-M", "T554RPO-" + run_id + "-T"
                place(maker, symbol, "Sell", maker_client, "GTC")
                CANCEL["await_order"](maker, symbol, maker_client, True)
                place(taker, symbol, "Buy", taker_client, "IOC")
                match_wait_started = time.monotonic()
                record["original_order_match"] = until(lambda: match_row(taker_client), 20,
                    "Order match was not physically certified during the bounded delivery hold")
                record["order_projection_wait_seconds"] = round(time.monotonic() - match_wait_started, 6)

                def fully_copied_reservations():
                    try:
                        a, head = copy_wal(primary, primary_slot, partition, output / "primary-before.wal")
                        b, other = copy_wal(backup, backup_slot, partition, output / "backup-before.wal")
                    except IncompleteWalObservation:
                        return None
                    cursor = PRODUCT["readonly_sql"]("SELECT source_epoch,journal_seq FROM dc_trade_projection_watermark "
                        f"WHERE partition_id='{partition}'")
                    if a != b or head != other or cursor != [["2", str(head)]]:
                        return None
                    prefix = hashlib.sha256(a).hexdigest()
                    expected = f"READY epoch=2 sequence={head} sha256={prefix} pending=false"
                    observations = {}
                    for node in (primary, backup):
                        observations[node] = observe_physical_head(
                            node, head_observers[node], tools_path, partition, head, prefix)
                    record["physical_head_checks_before_pause"] = observations
                    save()
                    return head if all(value == expected for value in observations.values()) else None

                before_head = until(fully_copied_reservations, 10, "Trade reservations were not fully certified before replica pause")
                if position(maker, symbol, "Short") != QUANTITY or position(taker, symbol, "Long") != QUANTITY:
                    raise RuntimeError("Financial settlement ran before the controlled replica fault")
                if not run("docker", "exec", order_node, "cat", control + "/status").startswith("PAUSED "):
                    raise RuntimeError("Delivery hold expired before the controlled replica fault")
                save()
                lease_ttl_ms = require_pause_lease_budget(
                    root / "common/config-hostready/trade" / primary_slot / "application.properties")
                record.update(receipt_observation_seconds=RECEIPT_OBSERVATION_SECONDS,
                              replica_pause_watchdog_seconds=REPLICA_PAUSE_WATCHDOG_SECONDS,
                              configured_node_lease_ttl_ms=lease_ttl_ms)
                watchdog = arm_pause_watchdog(inspect(backup)["Id"], output)
                begun = time.monotonic()
                pause_attempted = True
                run("docker", "pause", backup)
                try:
                    record["docker_pause_call_seconds"] = round(time.monotonic() - begun, 6)
                    run("docker", "exec", order_node, "touch", control + "/resume.request")
                    record["pause_and_delivery_release_call_seconds"] = round(time.monotonic() - begun, 6)
                    observation_started = time.monotonic()
                    receipts = wait_final_reports(order_node, since, clients)
                    record["receipt_observation_seconds_actual"] = round(time.monotonic() - observation_started, 6)
                    if receipts is None:
                        raise RuntimeError("Normal async final fill did not publish within the bounded replica pause")
                    coordinates = {receipt["TradeSettlementCommit"] for receipt in receipts.values()}
                    if coordinates != {f"{partition}/2/{before_head + 1}"}:
                        raise RuntimeError("Final LOCAL reports do not identify the one outstanding actual Trade frame")
                    record["final_local_published_before_peer"] = receipts
                    if not inspect(backup)["State"]["Paused"]:
                        raise RuntimeError("Bounded replica pause ended before the controlled primary fault")
                    restart_override_attempted = True
                    record["restart_override_attempted"] = True
                    save()
                    run("docker", "update", "--restart", "no", primary)
                    kill_attempted = True
                    record["primary_kill_attempted"] = True
                    save()
                    run("docker", "kill", "--signal", "KILL", primary)
                    killed = True
                    state = inspect(primary)["State"]
                    if state["ExitCode"] != 137 or state["Running"]:
                        raise RuntimeError("Original Trade primary did not actually exit 137")
                    record["killed_primary"] = state
                    _, backup_head = copy_wal(backup, backup_slot, partition, output / "backup-while-paused.wal")
                    if backup_head != before_head:
                        raise RuntimeError("Replica copied the supposedly unreplicated acknowledged frame")
                    record.update(backup_certified_head=before_head, original_local_acked_head=before_head + 1)
                finally:
                    if inspect(backup)["State"]["Paused"]:
                        run("docker", "unpause", backup)
                    record["replica_pause_seconds"] = round(time.monotonic() - begun, 6)
                    save()
                if watchdog.wait(timeout=5) != 0:
                    raise RuntimeError("Temporary replica pause watchdog failed")
                _, actual_head = copy_wal(primary, primary_slot, partition, output / "primary-local-acked.wal")
                if actual_head != before_head + 1:
                    raise RuntimeError("Original local ACK does not match its genuine fsynced WAL")
                local = wait_roles(root, "TradeSvr" + backup_slot)
                record["survivor_local"] = local
                if inspect(backup)["RestartCount"] != record["backup_restart_count"]:
                    raise RuntimeError("The controlled case unexpectedly expired the surviving backup process")
                record["robot_while_local"] = ROBOT["wait_traffic"](
                    order_nodes, [backup], datetime.now(timezone.utc), robot_location, local)
                maker = refresh_trader(maker, run_id, 0, maker_password)
                taker = refresh_trader(taker, run_id, 1, taker_password)
                consistent = False
                for attempt in range(45):
                    observed = [position(maker, symbol, "Short"), position(taker, symbol, "Long")]
                    if observed == [QUANTITY * 2, QUANTITY * 2]:
                        consistent = True
                        break
                    time.sleep(2)
                record["local_positions"] = [str(value) for value in observed]
                record["expected_positions"] = [str(QUANTITY * 2)] * 2
                if not consistent:
                    raise RuntimeError("Final acknowledged Order fill survived but its Trade financial after-state did not reconcile")
                record["local_business_consistent"] = True
        except BaseException as error:
            failure = error
            record["failure"] = type(error).__name__ + ": " + str(error)
            save()
        finally:
            save()
            if order_node and control:
                try:
                    subprocess.run(["docker", "exec", order_node, "touch", control + "/resume.request"],
                                   capture_output=True, timeout=10)
                except (OSError, subprocess.SubprocessError) as cleanup_error:
                    record["delivery_release_warning"] = type(cleanup_error).__name__
            try:
                if backup and inspect(backup)["State"]["Paused"]:
                    run("docker", "unpause", backup)
                if order_node and record.get("delivery_fault"):
                    def released_delivery():
                        status = run("docker", "exec", order_node, "cat", control + "/status")
                        return status if status.startswith("RESUMED delivery=2 scheduler=1") else None

                    try:
                        record["delivery_fault_release"] = until(released_delivery, 5,
                            "Bounded delivery fault did not release all workers")
                    except BaseException as release_error:
                        record["delivery_release_failure"] = type(release_error).__name__ + ": " + str(release_error)
                        failure = failure or release_error
                # A command can fail after Docker has applied the kill. Inspect
                # actual state so cleanup still owns that interrupted fault.
                if kill_attempted and not inspect(primary)["State"]["Running"]:
                    killed = True
                if killed:
                    if local is None:
                        local = wait_roles(root, "TradeSvr" + backup_slot)
                        record["survivor_local"] = local
                    run("docker", "update", "--restart", "on-failure", primary)
                    run("docker", "start", primary)
                    home = wait_roles(root)
                    record["strict_home"] = home
                    hashes = [ROLL["physical_hashes"](node, "TradeSvr", slot, backup_slot, local, home)
                              for node, slot in ((primary, primary_slot), (backup, backup_slot))]
                    if hashes[0] != hashes[1]:
                        record["recovery_failure"] = "Recovered physical WAL or snapshot pairs differ"
                    else:
                        record["physical_pairs"] = len(hashes[0])
                    maker = refresh_trader(maker, run_id, 0, maker_password)
                    taker = refresh_trader(taker, run_id, 1, taker_password)
                    record["home_positions"] = [str(position(maker, symbol, "Short")), str(position(taker, symbol, "Long"))]
                    if record["home_positions"] != [str(QUANTITY * 2)] * 2:
                        record["business_failure"] = "Recovered Home retains final Order fills without the expected Trade positions"
                        failure = failure or RuntimeError("Recovered Home changed the expected financial positions")
                        record["failure"] = type(failure).__name__ + ": " + str(failure)
                    elif record.get("local_business_consistent"):
                        record["posting_events"] = ROBOT["require_posting_pairs"]({"location": location,
                            "tape_execution_ids": [receipt["ExecID"] for receipt in receipts.values()],
                            "local_trade_commits": []})
                    if record.get("robot_while_local"):
                        record["robot_local_posting_events"] = ROBOT["require_posting_pairs"](record["robot_while_local"])
                    code, financial, checks = CAPACITY["reconcile_financial_cursor"]()
                    record.update(home_financial_cursor=financial, home_financial_checks=checks)
                    if code:
                        raise RuntimeError("Recovered Home financial source and projection differ")
                elif pause_attempted:
                    time.sleep(2)
                    record["strict_home"] = wait_roles(root)
                robot_after = inspect("dc-saas-robotsvr")
                record["same_robot_process"] = (robot_before["Id"] == robot_after["Id"]
                    and robot_before["State"]["StartedAt"] == robot_after["State"]["StartedAt"])
                if killed and robot_location:
                    record["same_order_process"] = inspect(order_node)["State"]["StartedAt"] == record["order_started_at"]
                    if not record["same_order_process"]:
                        raise RuntimeError("Unrelated Order process restart changed the controlled RPO case")
                    try:
                        record["robot_during_fault"] = ROBOT["rounds"](robot_location, since, datetime.now(timezone.utc))
                    except RuntimeError as availability_error:
                        record["availability_failure"] = str(availability_error)
                        failure = failure or availability_error
            except BaseException as recovery_error:
                record["recovery_failure"] = type(recovery_error).__name__ + ": " + str(recovery_error)
                failure = failure or recovery_error
            finally:
                if restart_override_attempted:
                    try:
                        run("docker", "update", "--restart", "on-failure", primary)
                        record["restart_policy_restored"] = (
                            inspect(primary)["HostConfig"]["RestartPolicy"] == original_restart_policy)
                        if not record["restart_policy_restored"]:
                            raise RuntimeError("Original primary restart policy was not restored")
                    except BaseException as policy_error:
                        record["restart_policy_failure"] = type(policy_error).__name__ + ": " + str(policy_error)
                        failure = failure or policy_error
            if (failure is None and record.get("local_business_consistent")
                    and record.get("posting_events") and record.get("robot_local_posting_events")
                    and record.get("physical_pairs") == 512 and record["same_robot_process"]):
                record["status"] = "NORMAL_ASYNC_UNREPLICATED_FILL_RPO_BUSINESS_AND_HOME_PASS"
            save()
        print("[mac-demo RPO]", record["status"], output, flush=True)
        if failure is not None:
            raise failure
        if record["status"] == "NO_GO":
            raise RuntimeError("RPO verification did not complete all physical and business evidence")


if __name__ == "__main__":
    def terminate_with_cleanup(signum, frame):
        raise KeyboardInterrupt("RPO driver termination requested")

    signal.signal(signal.SIGTERM, terminate_with_cleanup)
    main()
