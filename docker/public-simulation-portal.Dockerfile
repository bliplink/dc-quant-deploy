FROM --platform=$BUILDPLATFORM node:22-alpine AS build
WORKDIR /app
COPY source/package*.json ./
RUN npm ci --no-audit --no-fund
COPY source/ ./
RUN npm run build

FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10
ARG PORT
ENV GATEWAY_HOST=127.0.0.1 GATEWAY_HTTP_PORT=33002 PORT=$PORT
COPY --from=build /app/dist/ /usr/share/nginx/html/
COPY help/ /usr/share/nginx/html/help/
COPY default.conf.template /etc/nginx/templates/default.conf.template
EXPOSE $PORT
HEALTHCHECK --interval=15s --timeout=3s CMD wget -qO- "http://127.0.0.1:${PORT}/healthz" || exit 1
