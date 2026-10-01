#!/usr/bin/env python3
"""Generate a public method index from the checked OpenAPI YAML catalog."""

import argparse
from pathlib import Path

import yaml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    with args.spec.open(encoding="utf-8") as source:
        spec = yaml.safe_load(source)
    catalog = spec.get("x-dc-v1-catalog")
    schemas = spec.get("x-dc-method-schemas")
    if not isinstance(catalog, dict) or not isinstance(schemas, dict):
        raise SystemExit("OpenAPI method catalog and schema map are required")

    lines = [
        "# Open API v1 method catalog",
        "",
        "This page is generated from `crypto-openapi-v1.yaml`; it is not a separate handwritten API contract.",
        "The current release is a **Developer Preview**, not External GA. See the [release status](../status.md).",
        "",
        "[Download the machine-readable OpenAPI 3.0 YAML](crypto-openapi-v1.yaml)",
        "",
        "Requests use the gateway envelope, not separate REST paths for each method.",
        "Broker calls must also pass the server-side tenant/customer ownership checks described in the [Broker reference](BROKER_REFERENCE_V1.zh-CN.md).",
        "",
        "| Area | Gateway method | Required permission / policy | Request schema |",
        "| --- | --- | --- | --- |",
    ]
    count = 0
    for area, services in catalog.items():
        for service, methods in services.items():
            for method, permission in methods.items():
                key = f"{service}/{method}"
                schema_entry = schemas.get(key)
                if not isinstance(schema_entry, dict):
                    raise SystemExit(f"Missing request schema for {key}")
                schema_ref = schema_entry.get("request", "")
                if not schema_ref.startswith("#/components/schemas/"):
                    raise SystemExit(f"Invalid request schema for {key}")
                schema_name = schema_ref.rsplit("/", 1)[-1]
                lines.append(f"| {area} | `{key}` | `{permission}` | `{schema_name}` |")
                count += 1
    if count != len(schemas):
        raise SystemExit(f"Catalog/schema count mismatch: {count} != {len(schemas)}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[public-api-docs] generated {count} methods from {args.spec}")


if __name__ == "__main__":
    main()
