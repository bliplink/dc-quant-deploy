ARG PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim
ARG NGINX_IMAGE=nginx:1.27-alpine
FROM ${PYTHON_IMAGE} AS build
WORKDIR /src
COPY requirements-docs.txt mkdocs.public.yml ./
RUN pip install --no-cache-dir -r requirements-docs.txt
COPY docs ./docs
COPY scripts ./scripts
RUN openapi-spec-validator docs/openapi/crypto-openapi-v1.yaml \
    && python scripts/validate-openapi-catalog.py \
    && python scripts/generate-public-api-catalog.py docs/openapi/crypto-openapi-v1.yaml docs/openapi/CATALOG_GENERATED.md \
    && mkdocs build --config-file mkdocs.public.yml --clean --strict

FROM ${NGINX_IMAGE}
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/site/ /usr/share/nginx/html/
EXPOSE 18096
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q -O - http://127.0.0.1:18096/ >/dev/null || exit 1
