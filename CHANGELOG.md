# Changelog

## Unreleased

- Added sample-aware and source-versioned strategy repair tooling, fail-fast local batches, and short-lived SSH tunnel chunking for long production-equivalent revalidation queues.
- Completed deterministic revalidation for all 91 failed strategies and promoted the only strictly qualified repair, `lcr1_xrp_cha_c10143d0@v6`, through server-side `REVALIDATE` and automatic publication.
- Hardened the production GW tunnel with SSH keepalive and exponential connection retry, and made repair submission bind the source parent version and local backtest window.
- Added an operations record for the APSSvr daily 01:00 Asia/Shanghai restart schedule.
- Added user-facing Chinese documentation for system overview, post-deployment quick start, core flows, data model, reports, troubleshooting, MCP tools, and security.
- Reworked `README.md` into a deployment and usage navigation entry point.
- Added English README navigation, contribution guide, and security policy.
- Reorganized documentation into newcomer-friendly sections under `docs/`, with a dedicated documentation hub and clearer QuantSvr EMS/Risk/Telegram guidance.
