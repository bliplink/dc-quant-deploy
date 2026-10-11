#!/usr/bin/env python3
"""Install/uninstall the macOS daily calendar-retention watcher.

Uses user LaunchAgent (no root, no Docker restart). The config remains editable
in ~/.opentradingcore/maintenance/retention-demo.json and survives repo updates.
"""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

LABEL = "com.bliplink.opentradingcore-demo-retention"

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root")
    parser.add_argument("--interval-seconds", type=int, default=86400)
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args(argv)
    if args.interval_seconds < 900 or args.interval_seconds > 86400:
        parser.error("interval must be 900..86400 seconds")
    if sys.platform != "darwin":
        parser.error("LaunchAgent installation requires macOS")
    maintenance = Path.home()/".opentradingcore"/"maintenance"
    plist = Path.home()/"Library"/"LaunchAgents"/(LABEL+".plist")
    domain = "gui/"+str(os.getuid())
    target = domain+"/"+LABEL
    if args.uninstall:
        subprocess.run(["launchctl", "bootout", domain, str(plist)],
                       capture_output=True, check=False)
        plist.unlink(missing_ok=True)
        print("UNINSTALLED: preserved config and status under", maintenance)
        return 0
    if not args.runtime_root:
        parser.error("--runtime-root is required")
    runtime = Path(args.runtime_root).expanduser().resolve(strict=True)
    if not (runtime/"data").is_dir() or not (runtime/"log").is_dir():
        parser.error("runtime root must contain data and log directories")
    source = Path(__file__).with_name("auto-reclaim-demo.py")
    default = Path(__file__).resolve().parents[1]/"config"/"retention-demo.json"
    if not source.is_file() or not default.is_file():
        parser.error("missing bundled scripts/config")
    maintenance.mkdir(mode=0o700, parents=True, exist_ok=True)
    script_dir = maintenance/"bin"
    script_dir.mkdir(mode=0o700, exist_ok=True)
    installed_script = script_dir/"auto-reclaim-demo.py"
    config = maintenance/"retention-demo.json"
    status = maintenance/"retention-status.json"
    shutil.copy2(source, installed_script)
    if not config.exists():
        shutil.copy2(default, config)
    else:
        # One-time migration from the older disk-pressure version. Keep the
        # existing retention days and enabled switch, drop only obsolete
        # threshold knobs, preserving a small backup for operator rollback.
        import json
        previous = json.loads(config.read_text(encoding="utf8"))
        obsolete = ("highWatermarkPercent", "criticalWatermarkPercent", "minFreeGiB")
        if isinstance(previous, dict) and any(k in previous for k in obsolete):
            backup = maintenance / "retention-demo.disk-threshold-policy.backup.json"
            if not backup.exists():
                shutil.copy2(config, backup)
            for key in obsolete:
                previous.pop(key, None)
            previous.setdefault("maxCandidatesPerRun", 150)
            replacement = config.with_suffix(".json.new")
            replacement.write_text(json.dumps(previous, indent=2) + "\n", encoding="utf8")
            replacement.replace(config)
    # Fail installation before mutating launchd when current options invalid.
    sys.path.insert(0,str(script_dir))
    import importlib.util
    spec = importlib.util.spec_from_file_location("otc_retention_config",installed_script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    validated = mod.load_config(config)
    if validated["environment"]!="demo":
        parser.error("the installed policy is not a demo policy")
    plist.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "Label": LABEL,
        "ProgramArguments": [
            sys.executable, str(installed_script), "--config", str(config),
            "--runtime-root", str(runtime), "--status-path", str(status)],
        "StartInterval": args.interval_seconds,
        "RunAtLoad": True,
        "Nice": 15,
        "StandardOutPath": str(maintenance/"retention.stdout.log"),
        "StandardErrorPath": str(maintenance/"retention.stderr.log"),
    }
    tmp = plist.with_name(plist.name+".new")
    tmp.write_bytes(plistlib.dumps(record))
    # Editing/updating an existing installed agent: bootout beforehand.
    if plist.exists():
        subprocess.run(["launchctl", "bootout", domain, str(plist)],
                       capture_output=True, check=False)
    tmp.replace(plist)
    result = subprocess.run(["launchctl", "bootstrap", domain, str(plist)],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print("INSTALL_CREATED_BUT_NOT_LOADED", result.stderr.strip(), file=sys.stderr)
        return 2
    print("INSTALLED "+target+" every "+str(args.interval_seconds)+"s")
    print("config="+str(config))
    print("status="+str(status))
    return 0

if __name__=="__main__":
    sys.exit(main())
