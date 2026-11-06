#!/usr/bin/env python3
"""Read-only deployment guard: preserve real Common data identity across upgrades.

This is a deployment consistency check, NOT RSA recovery verification, an
automatic HA claim, a business READY grant, or a way to reset Projection WAL.
Run before changing Gateway routing and again after a rolling cutover.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROLES = ("order-a", "order-b", "trade-a", "trade-b")
DOCKER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
DATAROOT = re.compile(r"^/srv/dc/data/[A-Za-z0-9_./-]+$")
SERVER = {"order": "OrderSvr", "trade": "TradeSvr"}


def props(path):
    result = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "!")) and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def mount_at(mounts, destination):
    matches = [m for m in mounts if m["Destination"] == destination]
    if len(matches) != 1:
        raise ValueError("EXPECTED_ONE_MOUNT:" + destination)
    return matches[0]["Source"]


def physical_root(mounts, logical_root):
    if not DATAROOT.fullmatch(logical_root) or ".." in PurePosixPath(logical_root).parts:
        raise ValueError("UNTRUSTED_COMMON_DATAROOT")
    candidates = []
    for m in mounts:
        root = m["Destination"].rstrip("/")
        if logical_root.startswith(root + "/"):
            candidates.append((len(root), m))
    if not candidates:
        raise ValueError("COMMON_DATAROOT_NOT_MOUNTED:" + logical_root)
    _, m = sorted(candidates, key=lambda pair: pair[0])[-1]
    # Docker named volumes on the Mac have a stable Docker-managed Source even
    # when the host cannot traverse the Linux VM's /var/lib/docker/volumes.
    suffix = logical_root[len(m["Destination"].rstrip("/")):]
    return os.path.normpath(m["Source"] + suffix)


def role_layout(inspected, role, require_common_jar=True, require_running=True):
    service, node = role.split("-")
    target = "/srv/dc/dc/%s/config/application.properties" % SERVER[service]
    mounts = inspected["Mounts"]
    conf = props(mount_at(mounts, target))
    prefix = service + ".common."
    logical = conf.get(prefix + "nodeRuntime.dataRoot", "")
    if not logical:
        raise ValueError("MISSING_COMMON_DATAROOT:" + role)
    physical = physical_root(mounts, logical)
    jar_dest = "/srv/dc/dc/%s/lib/com.app.common-t520-common-only.jar" % SERVER[service]
    # The actual JAR mount takes precedence over the Docker image label.
    try:
        jar = mount_at(mounts, jar_dest)
    except ValueError:
        if require_common_jar:
            raise
        jar = None  # Older images might bundle Common inside the image.
    if jar is not None and not Path(jar).is_file():
        raise ValueError("COMMON_JAR_MOUNT_MISSING:" + role)
    sha = hashlib.sha256(Path(jar).read_bytes()).hexdigest() if jar else None
    if require_running and inspected["State"].get("Running") is not True:
        raise ValueError("NODE_NOT_RUNNING:" + role)
    # A STARTED container is not a READY business service; this is only a
    # structural preflight. The real business readiness is tested elsewhere.
    return {
        "role": role,
        "logical_root": logical,
        "physical_root": physical,
        "jar_sha256": sha,
        "gateway_enabled": conf.get(prefix + "gatewayDiscovery.enabled") == "true",
        "automatic_recovery": conf.get(prefix + "nodeRuntime.automaticRecovery"),
    }


def inspect(name, docker="docker"):
    if not DOCKER_NAME.fullmatch(name):
        raise ValueError("INVALID_DOCKER_CONTAINER_NAME")
    result = subprocess.run([docker, "inspect", name], capture_output=True,
                            text=True, timeout=20, check=True)
    rows = json.loads(result.stdout)
    if len(rows) != 1:
        raise ValueError("EXPECTED_ONE_DOCKER_INSPECT:" + name)
    return rows[0]


def read_mysql_projection_counts(container, database="dc"):
    """Read-only SQL census; no reset, no projection side effects."""
    user = os.environ.get("MYSQL_USERNAME")
    password = os.environ.get("MYSQL_PASSWORD")
    if not user or not password:
        raise ValueError("MYSQL_CREDENTIALS_ENV_REQUIRED")
    if not DOCKER_NAME.fullmatch(container) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]*", database):
        raise ValueError("INVALID_MYSQL_TARGET")
    sql = (
        "SELECT 'order',COUNT(*) FROM dc_order_projection_watermark;"
        "SELECT 'trade',COUNT(*) FROM dc_trade_projection_watermark;"
    )
    try:
        result = subprocess.run(
            ["docker", "exec", "-i", "-e", "MYSQL_PWD=" + password,
             container, "mysql", "-u" + user, "-N", database, "-e", sql],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        # Never print the subprocess argv: it contains MYSQL_PWD.
        raise ValueError("MYSQL_READONLY_CONNECTION_FAILED") from None
    if result.returncode != 0:
        raise ValueError("MYSQL_READONLY_QUERY_FAILED")
    counts = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 2 or parts[0] not in ("order", "trade"):
            raise ValueError("PROJECTION_SQL_RESPONSE_UNEXPECTED")
        counts[parts[0]] = int(parts[1])
        if counts[parts[0]] < 0:
            raise ValueError("PROJECTION_SQL_NEGATIVE_COUNT")
    if set(counts) != {"order", "trade"}:
        raise ValueError("PROJECTION_SQL_INCOMPLETE_WATERMARK_CENSUS")
    return counts


def check(layouts, old_layouts, projection_source, previous_projection_source,
          robot_running, mode, approved_sha256=None, watermark_counts=None):
    problems = []
    roots = [layouts[role]["physical_root"] for role in ROLES]
    if len(set(roots)) != 4:
        problems.append("SHARED_NODE_BUSINESS_DATAROOT")
    jar_hashes = {layouts[role]["jar_sha256"] for role in ROLES}
    if len(jar_hashes) != 1:
        problems.append("COMMON_JAR_SHA_MISMATCH_ACROSS_ORDER_TRADE")
    if approved_sha256 is not None and jar_hashes != {approved_sha256}:
        problems.append("UNAPPROVED_COMMON_JAR_SHA")
    for role in ROLES:
        if not layouts[role]["gateway_enabled"]:
            problems.append("GATEWAY_NOT_CERTIFIED_PUBLISHED:" + role)
    if mode == "upgrade":
        if set(old_layouts) != set(ROLES):
            problems.append("UPGRADE_REQUIRES_ALL_FOUR_PREVIOUS_NODES")
        else:
            for role in ROLES:
                old = old_layouts[role]["physical_root"]
                new = layouts[role]["physical_root"]
                if old != new:
                    problems.append("BUSINESS_WAL_SNAPSHOT_GENERATION_CHANGED:" + role)
    else:
        # All new nodes must use the same new named-volume generation.
        # Different physical subdirectories are required for A/B.
        # The layout's logical dataRoot is derived from actual mount config.
        generations = {PurePosixPath(layouts[role]["logical_root"]).parts[4]
                       for role in ROLES}
        if len(generations) != 1:
            problems.append("FRESH_NODES_HAVE_DIFFERENT_DATA_GENERATIONS")
        if robot_running:
            problems.append("FRESH_DEPLOYMENT_STILL_HAS_OLD_ROBOT_WRITERS")
    # Projection owns its OWN data volume: it must not be required to mount
    # Order/Trade WAL. Compare its previous consumer state with the new
    # consumer state, not against the producer's WAL volume. Distinct
    # MySQL watermark scopes still need separate verified business E2E.
    if watermark_counts is not None and mode == "fresh" and any(
            watermark_counts.get(service, 0) > 0 for service in ("order", "trade")):
        problems.append("FRESH_MYSQL_HAS_LEGACY_PROJECTION_WATERMARKS")
    if projection_source is None or previous_projection_source is None:
        problems.append("PROJECTION_SOURCE_LINEAGE_NOT_INSPECTED")
    elif mode == "upgrade" and projection_source != previous_projection_source:
        problems.append("PROJECTION_VOLUME_CHANGED_WITHOUT_REPLAY_PROOF")
    elif mode == "fresh" and projection_source == previous_projection_source:
        problems.append("FRESH_PROJECTION_REUSES_LEGACY_CONSUMER_VOLUME")
    return problems


def run(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("upgrade", "fresh"), required=True)
    p.add_argument("--approved-common-sha256", required=True,
                   help="Exact SHA256 of the approved physical Common JAR")
    for role in ROLES:
        p.add_argument("--new-" + role, required=True)
        p.add_argument("--old-" + role)
    p.add_argument("--projection", required=True,
                   help="Target ProjectionSvr container (read-only inspection)")
    p.add_argument("--old-projection", required=True,
                   help="Previous ProjectionSvr container; may be stopped")
    p.add_argument("--mysql-container", required=True,
                   help="Read-only MySQL projection watermark census container")
    p.add_argument("--robot", help="Robot container; required in fresh mode")
    args = p.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{64}", args.approved_common_sha256):
        p.error("--approved-common-sha256 must be the approved 64-digit hex SHA")
    if args.mode == "fresh" and not args.robot:
        p.error("--robot is required for fresh mode")
    if args.mode == "upgrade" and any(
            getattr(args, "old_" + r.replace("-", "_")) is None for r in ROLES):
        p.error("upgrade mode requires all --old-<role> containers")
    errors = []
    current, previous = {}, {}
    for role in ROLES:
        attr = role.replace("-", "_")
        try:
            current[role] = role_layout(inspect(getattr(args, "new_" + attr)), role)
        except (OSError, ValueError, subprocess.SubprocessError, KeyError) as e:
            errors.append("NEW_INSPECTION_FAILED:" + role + ":" + str(e))
        old_name = getattr(args, "old_" + attr)
        if old_name:
            try:
                previous[role] = role_layout(
                    inspect(old_name), role,
                    require_common_jar=False, require_running=False)
            except (OSError, ValueError, subprocess.SubprocessError, KeyError) as e:
                errors.append("OLD_INSPECTION_FAILED:" + role + ":" + str(e))
    projection_source = None
    try:
        projection = inspect(args.projection)
        projection_source = mount_at(projection["Mounts"], "/srv/dc/data")
        if not projection["State"].get("Running"):
            errors.append("PROJECTION_NOT_RUNNING")
    except (OSError, ValueError, subprocess.SubprocessError, KeyError) as e:
        errors.append("PROJECTION_INSPECTION_FAILED:" + str(e))
    previous_projection_source = None
    try:
        previous_projection = inspect(args.old_projection)
        previous_projection_source = mount_at(
            previous_projection["Mounts"], "/srv/dc/data")
    except (OSError, ValueError, subprocess.SubprocessError, KeyError) as e:
        errors.append("PREVIOUS_PROJECTION_INSPECTION_FAILED:" + str(e))
    robot_running = False
    if args.robot:
        try:
            robot_running = bool(inspect(args.robot)["State"]["Running"])
        except (OSError, ValueError, subprocess.SubprocessError, KeyError) as e:
            errors.append("ROBOT_INSPECTION_FAILED:" + str(e))
    watermark_counts = None
    try:
        watermark_counts = read_mysql_projection_counts(args.mysql_container)
    except (OSError, ValueError, subprocess.SubprocessError, KeyError) as e:
        errors.append("PROJECTION_SQL_WATERMARK_READ_FAILED:" + str(e).split("\n")[0])
    if len(current) == 4:
        errors.extend(check(current, previous, projection_source,
                            previous_projection_source, robot_running, args.mode,
                            approved_sha256=args.approved_common_sha256,
                            watermark_counts=watermark_counts))
    else:
        errors.append("INCOMPLETE_FOUR_NODE_COMMON_CENSUS")
    print("T528_MODE=" + args.mode)
    for role, item in current.items():
        print("T528_NODE=%s root=%s commonSHA256=%s gateway=%s" %
              (role, item["logical_root"], item["jar_sha256"],
               item["gateway_enabled"]))
    print("T528_PREVIOUS_PROJECTION_VOLUME=" + str(previous_projection_source))
    print("T528_TARGET_PROJECTION_VOLUME=" + str(projection_source))
    print("T528_PROJECTION_SQL_WATERMARK_COUNTS=" + str(watermark_counts))
    for error in errors:
        print("NO-GO:T528_" + error)
    if errors:
        print("T528_DEPLOYMENT_CONTINUITY_NO_GO; NO_MUTATIONS_PERFORMED")
        return 2
    print("T528_STRUCTURAL_ONLY_PASS; BUSINESS_REPLAY_AND_RSA_E2E_STILL_REQUIRED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
