#!/usr/bin/env python3
"""T373 fail-closed Common auto-failover activation audit.

Inspects exact deployed Common bytecode and Order/Trade source wiring.
Read-only: no ZooKeeper, WAL, container restarts, or service mutations.
Nonzero exit means automatic takeover is *not* proven to be armed.
"""
import argparse
import json
import pathlib
import re
import subprocess

BOOTSTRAP = "com.app.common.replication.CommonCertifiedNodeBootstrap"
RUNTIME = "com.app.common.replication.CommonCertifiedNodeRuntime"
WATCH = "com.app.common.replication.CommonCertifiedFailoverWatch"
AUTO_CALL = re.compile(r"\b(?:invokevirtual|invokestatic|invokespecial|invokeinterface)\b[^\n]*//\s*(?:Interface)?Method\s+[^\n]*armAutomatic(?:PhysicalRecovery|HomePhysicalRecovery|HomeReturn|Failover)Watch\b")
METHOD_DECL = re.compile(r"^  (?:public |protected |private |static |final |synchronized )+(?:[^;]+)\)\s*(?:throws [^;]+)?;$")
WATCH_CALL = re.compile(r"\barmAutomatic(?:PhysicalRecovery|HomePhysicalRecovery|HomeReturn|Failover)Watch\s*\(")


def method_chunks(javap_output):
    methods = []
    current_name = None
    current = []
    for line in javap_output.splitlines():
        if METHOD_DECL.match(line):
            if current_name:
                methods.append((current_name, "\n".join(current)))
            current_name = line.strip()
            current = []
        elif current_name:
            current.append(line)
    if current_name:
        methods.append((current_name, "\n".join(current)))
    return methods


def check_startup_disassembly(bootstrap_text, runtime_text):
    bootstrap_methods = method_chunks(bootstrap_text)
    start_methods = [body for title, body in method_chunks(runtime_text)
                     if ("void start()" in title or "void startWithBusinessReplay(" in title)]
    startup_methods = [body for title, body in bootstrap_methods
                       if "openAndStartWithZkFencingAndReplay" in title]
    return {
        "bootstrap_entry_methods": len(startup_methods),
        "bootstrap_arms_watch": any(AUTO_CALL.search(body) for body in startup_methods),
        "node_start_methods": len(start_methods),
        "node_start_arms_watch": any(AUTO_CALL.search(body) for body in start_methods)
    }


def inspect_source_dirs(roots):
    report = {}
    for name, root in roots.items():
        if not root.is_dir():
            report[name] = {"present": False, "wiring_arms_watch": False}
            continue
        found = []
        scanned = 0
        for java in root.rglob("*.java"):
            scanned += 1
            source = java.read_text(encoding="utf-8", errors="replace")
            without_comments = re.sub(r"/[*].*?[*]/", "", source, flags=re.S)
            without_comments = "\n".join(line.split("//", 1)[0] for line in without_comments.splitlines())
            if WATCH_CALL.search(without_comments):
                found.append(str(java.relative_to(root)))
        report[name] = {"present": True, "scanned_java": scanned,
                        "wiring_arms_watch": bool(found), "files": found[:8]}
    return report


def javap(container, jar, classname):
    r = subprocess.run(["docker", "exec", container, "javap", "-c", "-p", "-classpath",
                        jar, classname], capture_output=True, text=True, timeout=35)
    if r.returncode:
        raise RuntimeError("javap failed for " + classname + " (" + r.stderr[-220:] + ")")
    return r.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", required=True, help="running deployed Order/Trade node (read-only)")
    parser.add_argument("--jar", required=True, help="deployed absolute Common JAR path inside container")
    parser.add_argument("--order-src", type=pathlib.Path, required=True)
    parser.add_argument("--trade-src", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if not args.jar.startswith("/") or not args.jar.endswith(".jar"):
        parser.error("--jar must be an absolute .jar")
    bs = javap(args.container, args.jar, BOOTSTRAP)
    runtime = javap(args.container, args.jar, RUNTIME)
    watch = javap(args.container, args.jar, WATCH)
    starts = check_startup_disassembly(bs, runtime)
    sources = inspect_source_dirs({"Order": args.order_src, "Trade": args.trade_src})
    watch_class_exists = "public void start();" in watch
    watcher_armed = (starts["bootstrap_arms_watch"] or starts["node_start_arms_watch"]
                     or any(v["wiring_arms_watch"] for v in sources.values()))
    result = {
        "check": "T373_DEPLOYED_COMMON_AUTOMATIC_TAKEOVER_ACTIVATION",
        "status": "SOURCE_WIRING_PRESENT_NEEDS_REAL_FAILOVER_TEST" if watcher_armed
                  else "NO_GO_NO_AUTO_FAILOVER_WATCH_WIRED",
        "watch_class_present": watch_class_exists,
        "start_path": starts,
        "business_sources": sources,
        "safety": "read_only_bytecode_and_source_audit; no authorization or failover attempted"
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if watcher_armed and watch_class_exists and starts["bootstrap_entry_methods"] >= 1 else 2


if __name__ == "__main__":
    raise SystemExit(main())
