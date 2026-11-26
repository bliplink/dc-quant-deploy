ARG NGINX_IMAGE=nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10
FROM ${NGINX_IMAGE}
ENV GATEWAY_HOST=127.0.0.1 GATEWAY_HTTP_PORT=33002
COPY default.conf.template /etc/nginx/templates/default.conf.template
COPY site/ /usr/share/nginx/html/
EXPOSE 18094
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:18094/healthz || exit 1
