# Security Policy

## Supported Usage

This repository contains deployment scripts, example configuration, and documentation for DC Quant. It must not contain private production configuration or runtime data.

## Reporting A Vulnerability

If you find a security issue, please report it privately through GitHub Security Advisory when available, or contact the project maintainer through a private channel.

Please do not publish real credentials, API keys, server addresses, or exploit details in a public issue.

## Secret Handling

Never commit:

- `.env.prod`
- real API keys
- Telegram bot tokens
- exchange API keys or secrets
- ClickHouse production credentials
- production logs, backups, reports, or private trading data

Use placeholder values such as `replace-with-*`, `change-me`, or `example-*` in committed files.

## Operational Recommendations

- Enable API-key authentication before exposing MCP tools.
- Restrict public network access with firewall rules, VPN, or a trusted reverse proxy.
- Rotate API keys when sharing access with third parties.
- Keep ClickHouse off the public internet unless there is an explicit hardened access model.
