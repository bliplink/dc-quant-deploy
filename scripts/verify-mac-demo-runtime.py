#!/usr/bin/env python3
"""Verify actual Common roles and writer admission in the current Mac voters."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import tempfile
import traceback

REPO = Path(__file__).resolve().parent.parent
KEYS = {"node", "role_ok", "writer_ok", "expected_writers", "opened_partitions", "reservations"}


def validate_observation(text, node, expected_writers):
    """A READY manifest alone must never count as installed runtime readiness."""
    values = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key not in KEYS or key in values:
            raise ValueError("Incomplete, duplicate or rejected physical runtime observation")
        values[key] = value
    expected = {"node": node, "role_ok": "256", "writer_ok": str(expected_writers),
                "expected_writers": str(expected_writers), "opened_partitions": "256", "reservations": "0"}
    if expected_writers != 128 or values != expected:
        raise ValueError("Physical roles, Primary admission or recovery reservations are incomplete")
    return values


def run(*command):
    return subprocess.check_output(list(map(str, command)), text=True, stderr=subprocess.PIPE, timeout=90)


def inspect(name):
    return json.loads(run("docker", "inspect", name))[0]


def process_identity(container):
    return container["Id"], container["State"]["StartedAt"], container["RestartCount"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    root = args.root.resolve(strict=True)
    if (root.parent != (Path.home() / ".opentradingcore").resolve()
            or not re.fullmatch(r"mac-demo-\d{8}-\d{6}", root.name)):
        parser.error("Expected the original active Mac Demo directory")
    capacity = runpy.run_path(str(REPO / "scripts/verify-mac-demo-robot-capacity.py"))
    rpo = runpy.run_path(str(REPO / "scripts/verify-mac-demo-async-rpo.py"))
    work = Path(tempfile.mkdtemp(prefix="physical-runtime-", dir=root))
    proof = work / "proof.json"
    report = {"passed": False, "started_at": datetime.now(timezone.utc).isoformat(),
              "scope": "Read-only actual installed Common roles and Primary writer admission; no ACK or business mutation",
              "participants": [], "application_mutations": False}

    def save():
        pending = proof.with_suffix(".pending")
        pending.write_text(json.dumps(report, indent=2) + "\n")
        pending.replace(proof)

    save()
    try:
        before = capacity["require_strict_demo"](root, check_space=False)
        release = capacity["common_release_identity"](root)
        report.update(common_release=release, control_before=before)
        source = REPO / "tests/fixtures/async-rpo"
        agent = "T554CommonPhysicalCensusReadAgent"
        java = Path(run("/usr/libexec/java_home", "-v", "1.8").strip())
        run(java / "bin/javac", "-cp", java / "lib/tools.jar", "-d", work,
            source / (agent + ".java"), source / "T554RpoAttach.java")
        manifest_file = work / "MANIFEST.MF"
        manifest_file.write_text("Manifest-Version: 1.0\nAgent-Class: " + agent + "\n\n")
        run(java / "bin/jar", "cfm", work / "observer.jar", manifest_file, "-C", work, agent + ".class")
        report["agent_source_sha256"] = hashlib.sha256((source / (agent + ".java")).read_bytes()).hexdigest()
        report["agent_jar_sha256"] = hashlib.sha256((work / "observer.jar").read_bytes()).hexdigest()
        for kind, service in [("order", "OrderSvr"), ("trade", "TradeSvr")]:
            assignments = rpo["manifest"](root, kind)
            for partition, route in assignments.items():
                primary = service + ("A" if int(partition[1:]) < 128 else "B")
                replica = service + ("B" if int(partition[1:]) < 128 else "A")
                if (route["state"] != "READY" or route["policy"] != "STRICT_QUORUM"
                        or route["primary"] != primary or route["replica"] != replica):
                    raise ValueError("Actual signed assignment has not returned to strict Home placement")
            for slot in ["a", "b"]:
                name = root.name + "-" + kind + "-" + slot + "-hostready"
                container = inspect(name)
                common_path = "/srv/dc/dc/" + service + "/lib/com.app.common-mac-demo.jar"
                if (not container["State"]["Running"]
                        or container["Config"]["Labels"].get("dc.common.jar.sha256") != release["common_sha256"]
                        or run("docker", "exec", name, "sha256sum", common_path).split()[0] != release["common_sha256"]):
                    raise ValueError("Actual voter differs from the qualified Common release")
                processes = run("docker", "exec", name, "jcmd", "-l").splitlines()
                pids = [line.split()[0] for line in processes if len(line.split()) > 1 and line.split()[1] == service]
                if len(pids) != 1 or not pids[0].isdigit():
                    raise ValueError("Expected one actual business JVM")
                remote = "/tmp/" + work.name
                run("docker", "cp", work, name + ":" + remote)
                run("docker", "exec", name, "java", "-cp", "/opt/java/openjdk/lib/tools.jar:" + remote,
                    "T554RpoAttach", pids[0], remote + "/observer.jar", remote + "/census.txt")
                text = run("docker", "exec", name, "cat", remote + "/census.txt")
                (work / (kind + "-" + slot + ".txt")).write_text(text)
                node = service + slot.upper()
                expected = sum(route["primary"] == node for route in assignments.values())
                values = validate_observation(text, node, expected)
                current = inspect(name)
                if (not current["State"]["Running"] or process_identity(current) != process_identity(container)
                        or run("docker", "exec", name, "sha256sum", common_path).split()[0] != release["common_sha256"]):
                    raise ValueError("Observed physical process or Common changed during the read")
                report["participants"].append({"name": name, "id": current["Id"], "image": current["Image"],
                                               "started_at": current["State"]["StartedAt"],
                                               "restarts": current["RestartCount"], "values": values})
                save()
            if rpo["manifest"](root, kind) != assignments:
                raise ValueError("Signed assignment changed during physical observation")
        after = capacity["require_strict_demo"](root, check_space=False)
        if before != after or capacity["common_release_identity"](root) != release:
            raise ValueError("Control generation or release changed during observation")
        report.update(passed=True, control_after=after)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as failure:
        # Tool stderr can contain private runtime details. Keep it out of the
        # console; callers receive only the failure class and private proof.
        report["failure_type"] = type(failure).__name__
        detail = traceback.format_exc()
        if isinstance(failure, subprocess.CalledProcessError) and failure.stderr:
            detail += "\n" + failure.stderr
        private_log = work / "failure-private.txt"
        private_log.write_text(detail)
        report["failure_evidence"] = str(private_log)
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
    print(("PASS " if report["passed"] else "NO_GO ") + str(proof), flush=True)
    raise SystemExit(0 if report["passed"] else 2)


if __name__ == "__main__":
    main()
