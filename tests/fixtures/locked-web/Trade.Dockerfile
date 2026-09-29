ARG NODE_BUILD_BASE
ARG WEB_RUNTIME_BASE
FROM ${NODE_BUILD_BASE} AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --legacy-peer-deps --no-audit --no-fund --maxsockets=5 --fetch-timeout=180000
COPY . .
RUN unzip -q charting_library-master.zip \
    && mkdir -p src/charting_library \
    && cp charting_library-master/charting_library/charting_library.esm.js src/charting_library/index.js \
    && npm run test:kline && npm run test:orderbook && npm run test:market-health \
    && npm run test:position-risk && npm run test:ticker && npm run test:symbol-catalog \
    && npm run build-prod \
    && mkdir -p dist/public \
    && cp -R charting_library-master/charting_library dist/public/charting_library \
    && cp docker/tradingview-bybit.css dist/public/charting_library/bybit-theme.css
FROM ${WEB_RUNTIME_BASE}
# Retain only the cached nginx runtime, never old web bundles or config.
RUN find /usr/share/nginx/html -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + \
    && find /etc/nginx/templates -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
COPY --from=build /app/dist/ /usr/share/nginx/html/
COPY docker/default.conf.template /etc/nginx/templates/default.conf.template
HEALTHCHECK --interval=15s --timeout=5s --retries=4 CMD wget -qO- "http://127.0.0.1:${WEB_LISTEN_PORT:-18088}/healthz" | grep -q '^ok$'
