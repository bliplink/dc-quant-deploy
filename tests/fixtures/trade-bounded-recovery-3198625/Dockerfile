FROM eclipse-temurin:8-jre
ENV DEPLOY_ROOT=/srv/dc ATS_ROOT=/srv/dc BACKEND_ROOT=/srv/dc SERVICE_NAME=TradeSvr MAIN_CLASS=TradeSvr TZ=Asia/Shanghai
LABEL org.opencontainers.image.revision="31986253ed36117104b5b67b6d3cb2f3e0fefbfb"
LABEL dc.trade.recovery.extension="3.0.14-recovery-e95850b-1"
LABEL dc.trade.recovery.bounded.default="false"
WORKDIR /srv/dc/dc/TradeSvr
COPY target/classes/ classes/
COPY target/dependency/ lib/
COPY salt-formula/TradeSvr/files/config/ config/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && mkdir -p /srv/dc/control /srv/dc/data /srv/dc/log /srv/dc/tpc/tpc
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
