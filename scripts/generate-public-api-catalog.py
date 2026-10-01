#!/usr/bin/env python3
"""Generate a public method index from the checked OpenAPI YAML catalog."""

import argparse
from pathlib import Path

import yaml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--language", choices=("en", "zh"), default="en")
    args = parser.parse_args()

    with args.spec.open(encoding="utf-8") as source:
        spec = yaml.safe_load(source)
    catalog = spec.get("x-dc-v1-catalog")
    schemas = spec.get("x-dc-method-schemas")
    if not isinstance(catalog, dict) or not isinstance(schemas, dict):
        raise SystemExit("OpenAPI method catalog and schema map are required")

    if args.language == "zh":
        lines = [
            "# Open API v1 方法目录",
            "",
            "本页由 `crypto-openapi-v1.yaml` 自动生成，不是另一份手写接口契约。当前为**开发者预览版**，尚未达到 External GA；请阅读[发布状态](../status.md)。",
            "",
            "[下载 OpenAPI 3.0 YAML](crypto-openapi-v1.yaml)",
            "",
            "所有方法共用 GW 请求 envelope，不存在每个方法独立的 REST 路径。Broker 调用还必须通过服务端的租户和客户归属校验，详见 [Broker 字段参考](BROKER_REFERENCE_V1.zh-CN.md)。",
            "",
            "| 分类 | GW 方法 | 权限 / 策略 | 请求 schema |",
            "| --- | --- | --- | --- |",
        ]
        areas = {"authentication": "认证", "market": "行情", "trading": "交易", "account": "账户", "history": "历史", "tenant": "租户"}
    else:
        lines = [
            "# Open API v1 method catalog",
            "",
            "This page is generated from `crypto-openapi-v1.yaml`; it is not a separate handwritten API contract.",
            "The current release is a **Developer Preview**, not External GA. See the [release status](../status.md).",
            "",
            "[Download the machine-readable OpenAPI 3.0 YAML](crypto-openapi-v1.yaml)",
            "",
            "Requests use the gateway envelope, not separate REST paths for each method.",
            "Broker calls must also pass the server-side tenant/customer ownership checks described in the [Broker reference](/zh/openapi/BROKER_REFERENCE_V1.zh-CN/).",
            "",
            "| Area | Gateway method | Required permission / policy | Request schema |",
            "| --- | --- | --- | --- |",
        ]
        areas = {}
    count = 0
    for area, services in catalog.items():
        if args.language == "zh" and area not in areas:
            raise SystemExit(f"Missing Chinese area label for {area}")
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
                lines.append(f"| {areas.get(area, area)} | `{key}` | `{permission}` | `{schema_name}` |")
                count += 1
    if count != len(schemas):
        raise SystemExit(f"Catalog/schema count mismatch: {count} != {len(schemas)}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[public-api-docs] generated {count} {args.language} methods from {args.spec}")


if __name__ == "__main__":
    main()
