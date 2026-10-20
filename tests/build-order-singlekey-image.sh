#!/usr/bin/env bash
set -euo pipefail

# Local demo-only image overlay. Uses independently compiled Common class files.
# The entire original Common jar and Order application image remain unchanged.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLASS_DIR="${ORDER_QUEUE_PATCH_CLASS_DIR:-${ROOT}/.work/app-common-queue-fix-20261020/target/classes/com/app/common/thread}"
CONTEXT="${ROOT}/.work/order-singlekey-image-20261020"
IMAGE="${ORDER_QUEUE_IMAGE:-local/dc-saas-ordersvr:single-key-queue-b0be90c-20261020}"

for name in 'AsyncSingleSeqThreadGroup.class' 'AsyncSingleSeqThreadGroup$1.class'; do
  [[ -s "${CLASS_DIR}/${name}" ]] || {
    printf 'Missing compiled Java 8 class: %s\n' "${CLASS_DIR}/${name}" >&2
    exit 1
  }
done
mkdir -p "${CONTEXT}/classes/com/app/common/thread"
cp "${CLASS_DIR}/AsyncSingleSeqThreadGroup.class" \
   "${CLASS_DIR}/AsyncSingleSeqThreadGroup\$1.class" \
   "${CONTEXT}/classes/com/app/common/thread/"

docker build -f "${ROOT}/docker/order-queue-hotfix/Dockerfile" \
  -t "${IMAGE}" "${CONTEXT}"

echo "Built ${IMAGE} from existing Order image and only two Common queue classes."
