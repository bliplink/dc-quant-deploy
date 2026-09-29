FROM eclipse-temurin:8-jre
ENV DEPLOY_ROOT=/srv/dc HOME=/srv/dc ATS_ROOT=/srv/dc BACKEND_ROOT=/srv/dc SERVICE_NAME=TradeSvr MAIN_CLASS=TradeSvr TZ=Asia/Shanghai
LABEL org.opencontainers.image.revision="a539940d4b83a1010096b8efae68adce56917b8c"
LABEL dc.trade.candidate.scope="offline recovery qualification; not deployed"
WORKDIR /srv/dc/dc/TradeSvr
COPY target/classes/ classes/
COPY target/dependency-node-recovery-a539940/ lib/
COPY salt-formula/TradeSvr/files/config/ config/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && mkdir -p /srv/dc/control /srv/dc/data /srv/dc/log /srv/dc/tpc/tpc
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
