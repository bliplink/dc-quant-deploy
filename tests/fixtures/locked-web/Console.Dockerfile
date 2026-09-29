ARG NODE_BUILD_BASE
ARG WEB_RUNTIME_BASE
FROM ${NODE_BUILD_BASE} AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build
FROM ${WEB_RUNTIME_BASE}
RUN find /usr/share/nginx/html -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
ARG WEB_PORT
ENV WEB_PORT=${WEB_PORT}
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD wget -qO- "http://127.0.0.1:${WEB_PORT}/healthz" || exit 1
