#!/usr/bin/env python3
"""Bounded HTTP load for the isolated OrderSvr cluster data path."""

import argparse
import concurrent.futures
import http.client
import json
import math
import threading
import time


THREAD_LOCAL = threading.local()


def percentile(values, ratio):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * ratio) - 1))]


def connection(host, port, timeout):
    current = getattr(THREAD_LOCAL, "connection", None)
    if current is None:
        current = http.client.HTTPConnection(host, port, timeout=timeout)
        THREAD_LOCAL.connection = current
    return current


def request(args, index, warmup=False):
    symbol = "BTCUSDT" if index % 2 == 0 else "ETHUSDT"
    prefix = "WARM-%s" % args.run_id if warmup else "MEASURE-%s" % args.run_id
    payload = {
        "serverName": "OrderSvr",
        "method": "__cluster_perf_probe__",
        "content": {
            "ClOrdID": "%s-%07d" % (prefix, index), "Terminal": "ClusterPerf",
            "MarketIndicator": "4", "SecurityID": symbol, "Location": "WEB_E2E",
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    started = time.perf_counter_ns()
    try:
        conn = connection(args.host, args.port, args.timeout)
        conn.request("POST", "/", body=body, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        response_body = response.read()
        try:
            value = json.loads(response_body.decode("utf-8"))
        except Exception:
            value = {}
        code = value.get("code")
        ok = 200 <= response.status < 300 and str(code) == "0"
        error = "" if ok else "HTTP_%d_CODE_%s:%s" % (
            response.status, code, response_body[:200].decode("utf-8", errors="replace"))
    except Exception as exc:
        ok = False
        error = type(exc).__name__ + ":" + str(exc)
        current = getattr(THREAD_LOCAL, "connection", None)
        if current is not None:
            try:
                current.close()
            except Exception:
                pass
            THREAD_LOCAL.connection = None
    return ok, (time.perf_counter_ns() - started) / 1_000_000.0, error


def execute(args, count, warmup=False):
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(request, args, index, warmup) for index in range(count)]
        return [future.result() for future in futures]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=33302)
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--warmup", type=int, default=200)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--mode", choices=("single-primary", "split-primary"), required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.warmup < 0:
        raise SystemExit("requests/concurrency must be positive and warmup cannot be negative")

    if args.warmup:
        execute(args, args.warmup, warmup=True)
    started = time.perf_counter_ns()
    results = execute(args, args.requests)
    wall_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    latencies = [item[1] for item in results]
    errors = [item[2] for item in results if not item[0]]
    report = {
        "result": "PASS" if not errors else "FAIL",
        "scope": "gw-routing-order-shadow-journal-synchronous-replication",
        "mode": args.mode, "runId": args.run_id, "requests": args.requests,
        "concurrency": args.concurrency, "warmupRequests": args.warmup,
        "success": args.requests - len(errors), "failed": len(errors), "wallMs": wall_ms,
        "tps": args.requests * 1000.0 / wall_ms,
        "latencyMs": {"p50": percentile(latencies, 0.50), "p95": percentile(latencies, 0.95),
                      "p99": percentile(latencies, 0.99), "max": max(latencies) if latencies else 0.0},
        "failureSamples": errors[:10],
    }
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False))
    if errors:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
