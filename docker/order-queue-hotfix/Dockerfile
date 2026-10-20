FROM local/dc-saas-ordersvr:tenant-symbol-fullimage-20261019
# Java starts with -cp classes:config:lib/*; shadow ONLY the patched Common
# queue classes. Do not replace/merge the Common HA snapshot/WAL JAR.
COPY classes/ /srv/dc/dc/OrderSvr/classes/
LABEL otc.common.queue-fix="b0be90c" otc.base-image="local/dc-saas-ordersvr:tenant-symbol-fullimage-20261019"
