#!/usr/bin/env python3
import sys
from pathlib import Path
import yaml

SPEC = Path('docs/openapi/crypto-openapi-v1.yaml')

def fail(msg: str) -> None:
    print(f'[openapi-catalog] ERROR: {msg}', file=sys.stderr)
    raise SystemExit(1)

with SPEC.open('r', encoding='utf-8') as fh:
    doc = yaml.safe_load(fh)

catalog = doc.get('x-dc-v1-catalog') or {}
schemas = doc.get('x-dc-method-schemas') or {}

catalog_methods = []
for section, services in catalog.items():
    if not isinstance(services, dict):
        fail(f'catalog section {section!r} must be an object')
    for service, methods in services.items():
        if not isinstance(methods, dict):
            fail(f'catalog service {service!r} must be an object')
        for method in methods:
            catalog_methods.append(f'{service}/{method}')

mapped_methods = sorted(schemas.keys())
catalog_methods = sorted(catalog_methods)

missing = sorted(set(catalog_methods) - set(mapped_methods))
unknown = sorted(set(mapped_methods) - set(catalog_methods))

if missing:
    fail('methods missing request schemas: ' + ', '.join(missing))
if unknown:
    fail('x-dc-method-schemas contains methods absent from catalog: ' + ', '.join(unknown))

for method, entry in schemas.items():
    if not isinstance(entry, dict) or 'request' not in entry:
        fail(f'{method} has no request schema reference')
    ref = entry['request']
    if not isinstance(ref, str) or not ref.startswith('#/components/schemas/'):
        fail(f'{method} request schema is not a local components ref: {ref!r}')
    schema_name = ref.rsplit('/', 1)[-1]
    if schema_name not in (doc.get('components', {}).get('schemas', {}) or {}):
        fail(f'{method} refers to missing schema {schema_name}')

print(f'[openapi-catalog] PASS: {len(catalog_methods)} catalog methods all have request schemas')
