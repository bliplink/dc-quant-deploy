#!/usr/bin/env python3
"""Run the local Codex pre-admission queue with bounded workstation concurrency."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import paramiko

import local_strategy_backtest as local_runner


def run_one(script, queue_path, seed_path, output_dir, item, begin_date, end_date, db_config):
    name = item["strategyName"]
    command = [
        sys.executable,
        str(script),
        "--strategy", name,
        "--seed", str(seed_path),
        "--output-dir", str(output_dir / "work"),
        "--begin-date", begin_date,
        "--end-date", end_date,
        "--db-config", str(db_config),
    ]
    attempts = []
    process = None
    result_path = ""
    for attempt in range(1, 3):
        process = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, timeout=900)
        attempts.append("=== attempt %d returnCode=%d ===\n%s" % (
            attempt, process.returncode, process.stdout))
        for line in process.stdout.splitlines():
            if line.startswith("LOCAL_PRE_ADMISSION_RESULT="):
                result_path = line.split("=", 1)[1].strip()
        if process.returncode in (0, 2) and result_path:
            break
    log_dir = output_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / (name + ".log")).write_text("\n".join(attempts), encoding="utf-8")
    execution_error = process.returncode not in (0, 2) or not result_path
    result = {}
    if result_path and Path(result_path).is_file():
        result = json.loads(Path(result_path).read_text(encoding="utf-8")).get("result") or {}
    return {
        "strategyName": name,
        "symbol": item.get("symbol"),
        "scene": item.get("scene"),
        "baselineReason": item.get("baselineReason"),
        "returnCode": process.returncode,
        "executionError": execution_error,
        "resultPath": result_path,
        "qualified": bool(result.get("qualified")),
        "qualificationReason": result.get("qualificationReason") or (
            "execution_error" if execution_error else "unknown"),
        "metrics": result,
    }


def main():
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=base / "local-strategy-queue-20261009.json")
    parser.add_argument("--seed", type=Path, default=base / "live-strategy-seed-20261009.json")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--begin-date", default="2025-10-08")
    parser.add_argument("--end-date", default="2026-10-08")
    parser.add_argument("--output-dir", type=Path, default=base / "local-backtest-batches")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--host", default=local_runner.DEFAULT_HOST)
    parser.add_argument("--user", default=local_runner.DEFAULT_USER)
    parser.add_argument("--key", type=Path, default=Path(local_runner.DEFAULT_KEY))
    args = parser.parse_args()
    workers = max(1, min(args.workers, 4))
    queue = json.loads(args.queue.read_text(encoding="utf-8"))
    items = queue.get("items") or []
    if args.limit > 0:
        items = items[:args.limit]
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir.resolve() / batch_id
    output_dir.mkdir(parents=True)
    script = base / "local_strategy_backtest.py"
    passphrase = os.environ.get("STC_PROD_KEY_PASSPHRASE")
    if not passphrase:
        raise SystemExit("STC_PROD_KEY_PASSPHRASE is required")
    client = paramiko.SSHClient()
    client.load_host_keys(str(Path.home() / ".ssh" / "known_hosts"))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(args.host, username=args.user, key_filename=str(args.key),
                   passphrase=passphrase, timeout=30, banner_timeout=30, auth_timeout=30)
    server = None
    db_config = None
    results = []
    try:
        remote_env = local_runner.read_remote_env(client)
        local_runner.ForwardHandler.ssh_transport = client.get_transport()
        local_runner.ForwardHandler.remote_port = int(
            remote_env.get("CLICKHOUSE_HTTP_PORT") or 8123)
        server = local_runner.ForwardServer(("127.0.0.1", 0), local_runner.ForwardHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.NamedTemporaryFile(prefix="dc-local-batch-", suffix=".ini", delete=False) as handle:
            db_config = Path(handle.name)
        local_runner.write_db_config(db_config, server.server_address[1], remote_env)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(run_one, script, args.queue.resolve(), args.seed.resolve(),
                                output_dir, item, args.begin_date, args.end_date, db_config): item
                for item in items
            }
            completed = 0
            for future in as_completed(futures):
                completed += 1
                item = futures[future]
                try:
                    result = future.result()
                except Exception as error:
                    result = {
                        "strategyName": item.get("strategyName"),
                        "symbol": item.get("symbol"),
                        "scene": item.get("scene"),
                        "baselineReason": item.get("baselineReason"),
                        "executionError": True,
                        "qualified": False,
                        "qualificationReason": "execution_error",
                        "error": str(error),
                    }
                results.append(result)
                print("[%d/%d] %s %s" % (
                    completed, len(items), result["strategyName"], result["qualificationReason"]),
                    flush=True,
                )
    finally:
        if db_config and db_config.exists():
            db_config.unlink()
        if server is not None:
            server.shutdown()
            server.server_close()
        client.close()
    results.sort(key=lambda row: (str(row.get("symbol")), str(row.get("scene")),
                                  str(row.get("strategyName"))))
    summary = {
        "packageVersion": "local_codex_pre_admission_batch_v1",
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "batchId": batch_id,
        "beginDate": args.begin_date,
        "endDate": args.end_date,
        "workers": workers,
        "requestedCount": len(items),
        "completedCount": len(results),
        "qualifiedCount": sum(1 for row in results if row.get("qualified")),
        "executionErrorCount": sum(1 for row in results if row.get("executionError")),
        "productionWrite": False,
        "results": results,
    }
    summary_path = output_dir / "batch-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "results"},
                     ensure_ascii=False, indent=2))
    print("BATCH_SUMMARY=" + str(summary_path))
    return 1 if summary["executionErrorCount"] else 0


if __name__ == "__main__":
    sys.exit(main())
