# Security policy

This repository contains deployment files for the standalone DC cryptocurrency
SaaS product. Report vulnerabilities privately to the maintainers.

Never commit:

- `.env.prod` or generated files under `/opt/dc-saas-runtime/control`;
- MySQL or ClickHouse passwords;
- exchange API keys, signing keys, wallet keys, or user credentials;
- production logs, database files, backups, or customer trading data.

The default deployment binds MySQL, ClickHouse, and ZooKeeper to loopback only.
Expose the web/GW ports only through an approved firewall, VPN, TLS reverse
proxy, and tenant-aware rate limiting. Keep APSSvr user-data access disabled
until secrets are supplied by a dedicated secret manager.

Use immutable `sha-*` image tags for staged and production releases. Back up
and restore both MySQL and ClickHouse, and rehearse recovery before accepting
real funds.
