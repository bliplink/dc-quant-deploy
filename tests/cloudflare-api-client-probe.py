#!/usr/bin/env python3
"""Read-only public API ingress compatibility check. No credentials or writes.

Cloudflare Error 1010 can be triggered by Python's default User-Agent.
Use this probe before and after an API-scoped Browser Integrity Check exception.
"""
import argparse
import json
import urllib.error
import urllib.request


def check(base_url, tenant, proxy, agent):
    body = json.dumps({
        "serverName": "AdminSvr",
        "method": "querySymbol",
        "content": {"location": tenant},
    }, separators=(",", ":")).encode("utf-8")
    url = base_url.rstrip("/") + "/httpapi/"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": proxy}) if proxy else urllib.request.ProxyHandler({})
    )
    request = urllib.request.Request(url, body, headers={
        "Content-Type": "application/json",
        "User-Agent": agent,
    }, method="POST")
    try:
        with opener.open(request, timeout=12) as response:
            raw = response.read(128 * 1024)
            payload = json.loads(raw)
            success = response.status == 200 and str(payload.get("code")) == "0"
            return response.status, success, False
    except urllib.error.HTTPError as error:
        preview = error.read(1024)
        return error.code, False, b"1010" in preview
    except (urllib.error.URLError, ValueError) as error:
        raise SystemExit("Network/response error (no credentials involved): " + type(error).__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://trade.opentradingcore.com")
    parser.add_argument("--location", default="CT1YR5")
    parser.add_argument("--proxy", default=None, help="Optional proxy, e.g. http://127.0.0.1:10808")
    parser.add_argument("--expect-open", action="store_true",
                        help="Require both User-Agents to reach authenticated-independent public data")
    args = parser.parse_args()
    results = []
    for agent in ("Python-urllib/3.9", "OpenTradingCore/1.0"):
        status, success, error1010 = check(args.url, args.location, args.proxy, agent)
        print("agent=", agent, "http=", status, "public_query_ok=", success,
              "cloudflare_1010=", error1010)
        results.append(success)
    if args.expect_open and not all(results):
        raise SystemExit("FAIL: public API rejects a valid Python client User-Agent")
    print("PASS" if all(results) else "BLOCKED: path-scoped Cloudflare rule still required")


if __name__ == "__main__":
    main()
