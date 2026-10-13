#!/usr/bin/env python3
"""Run a long local strategy queue through short-lived shared SSH tunnels."""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def result_path(stdout):
    for line in reversed(stdout.splitlines()):
        if line.startswith("BATCH_SUMMARY="):
            return Path(line.split("=", 1)[1].strip())
    return None


def aggregate_results(attempts):
    selected = {}
    for attempt in attempts:
        path_text = attempt.get("summaryPath")
        if not path_text:
            continue
        path = Path(path_text)
        if not path.is_file():
            continue
        summary = json.loads(path.read_text(encoding="utf-8"))
        for row in summary.get("results") or []:
            if row.get("executionError"):
                continue
            selected[row["strategyName"]] = row
    return sorted(selected.values(), key=lambda row: (
        str(row.get("symbol")), str(row.get("scene")),
        str(row.get("strategyName"))))


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--begin-date", default="2025-10-08")
    parser.add_argument("--end-date", default="2026-10-08")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--chunk-size", type=int, default=3)
    parser.add_argument("--retry-limit", type=int, default=5)
    parser.add_argument("--retry-delay-seconds", type=int, default=60)
    parser.add_argument("--max-retry-delay-seconds", type=int, default=300)
    args = parser.parse_args()

    queue = json.loads(args.queue.resolve().read_text(encoding="utf-8"))
    total_available = len(queue.get("items") or [])
    start_offset = max(0, args.offset)
    end_offset = total_available
    if args.limit > 0:
        end_offset = min(end_offset, start_offset + args.limit)
    chunk_size = max(1, args.chunk_size)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    runner = here / "run_local_strategy_batch.py"
    offset = start_offset
    attempts = []
    consecutive_errors = 0

    while offset < end_offset:
        requested = min(chunk_size, end_offset - offset)
        attempt_no = len(attempts) + 1
        chunk_dir = output_dir / ("offset-%04d-attempt-%03d" % (offset, attempt_no))
        command = [
            sys.executable,
            str(runner),
            "--queue", str(args.queue.resolve()),
            "--seed", str(args.seed.resolve()),
            "--workers", "1",
            "--tunnel-scope", "batch",
            "--max-execution-errors", "1",
            "--begin-date", args.begin_date,
            "--end-date", args.end_date,
            "--offset", str(offset),
            "--limit", str(requested),
            "--output-dir", str(chunk_dir),
        ]
        process = subprocess.run(
            command, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=1800)
        chunk_dir.mkdir(parents=True, exist_ok=True)
        (chunk_dir / "chunk.log").write_text(process.stdout, encoding="utf-8")
        summary_file = result_path(process.stdout)
        summary = {}
        if summary_file is not None and summary_file.is_file():
            summary = json.loads(summary_file.read_text(encoding="utf-8"))
        completed = int(summary.get("completedCount") or 0)
        execution_errors = int(summary.get("executionErrorCount") or 0)
        successful = max(0, completed - execution_errors)
        attempts.append({
            "offset": offset,
            "requestedCount": requested,
            "completedCount": completed,
            "successfulCount": successful,
            "executionErrorCount": execution_errors,
            "returnCode": process.returncode,
            "summaryPath": str(summary_file or ""),
            "logPath": str(chunk_dir / "chunk.log"),
        })
        print("offset=%d requested=%d completed=%d executionErrors=%d" % (
            offset, requested, completed, execution_errors), flush=True)

        if successful:
            offset += successful
        if execution_errors or not summary:
            consecutive_errors += 1
            if consecutive_errors >= max(1, args.retry_limit):
                break
            retry_delay = min(
                max(0, args.max_retry_delay_seconds),
                max(0, args.retry_delay_seconds) * (2 ** (consecutive_errors - 1)),
            )
            print("retrying offset=%d after %d seconds" % (offset, retry_delay),
                  flush=True)
            time.sleep(retry_delay)
            continue
        if completed != requested:
            break
        offset += requested - successful
        consecutive_errors = 0
        if offset < end_offset:
            time.sleep(min(30, max(0, args.retry_delay_seconds)))

    results = aggregate_results(attempts)
    master = {
        "packageVersion": "local_chunked_batch_summary_v1",
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(
            timespec="seconds"),
        "queue": str(args.queue.resolve()),
        "seed": str(args.seed.resolve()),
        "startOffset": start_offset,
        "endOffsetExclusive": end_offset,
        "nextOffset": offset,
        "complete": offset >= end_offset,
        "completedStrategyCount": len(results),
        "qualifiedCount": sum(1 for row in results if row.get("qualified")),
        "attempts": attempts,
        "results": results,
    }
    master_path = output_dir / "chunked-batch-summary.json"
    master_path.write_text(
        json.dumps(master, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("CHUNKED_BATCH_SUMMARY=" + str(master_path), flush=True)
    return 0 if master["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
