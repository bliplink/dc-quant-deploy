"""Validate release entrypoint cannot implicitly change live OrderSvr images."""
from pathlib import Path
import os
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=ROOT/'deploy-saas.sh'


def extract_function(text):
    start=text.index('guard_running_order_cluster_image_change() {')
    end=text.index('\nverify_order_cluster_images() {',start)
    return text[start:end]


def check(case,source):
    func=extract_function(source)
    bash='''set -euo pipefail
log() { :; }
die() { exit 93; }
docker() {
    if [[ "$1" == "image" && "$2" == "inspect" ]]; then
        echo 'sha256:new-image'
        return 0
    fi
    if [[ "$1" == "inspect" && "$#" == 2 ]]; then
        if [[ "${MOCK_EXISTING:-true}" == "false" ]]; then return 1; fi
        return 0
    fi
    if [[ "$1" == "inspect" && "$#" == 4 ]]; then
        if [[ "$2" == "dc-saas-ordersvr-c" && "${MOCK_C_DIFFERENT:-false}" == "true" ]]; then
            echo 'sha256:old-image'
        elif [[ "${MOCK_DIFFERENT:-false}" == "true" ]]; then
            echo 'sha256:old-image'
        else
            echo 'sha256:new-image'
        fi
        return 0
    fi
    return 99
}
'''+func+'''\nORDERSVR_IMAGE_REPOSITORY=ghcr.io/bliplink/ordersvr
ORDERSVR_TAG=sha-latest
guard_running_order_cluster_image_change
'''
    env=dict(os.environ)
    env.update(ORDER_CLUSTER_ENABLED='true',ORDER_CLUSTER_C_ENABLED='false')
    env.update(case)
    return subprocess.run(['bash','-c',bash],env=env,capture_output=True,text=True).returncode


class GuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=ORIGINAL.read_text()

    def test_fresh_install_with_no_existing_order_nodes_allowed(self):
        self.assertEqual(0,check({'MOCK_EXISTING':'false'},self.base))

    def test_identical_images_are_not_force_recreated_by_guard(self):
        self.assertEqual(0,check({},self.base))

    def test_changes_to_any_primary_image_are_denied(self):
        self.assertEqual(93,check({'MOCK_DIFFERENT':'true'},self.base))

    def test_replica_only_c_image_change_is_denied(self):
        self.assertEqual(93,check({'ORDER_CLUSTER_C_ENABLED':'true','MOCK_C_DIFFERENT':'true'},self.base))

    def test_disabled_cluster_unchanged(self):
        self.assertEqual(0,check({'ORDER_CLUSTER_ENABLED':'false'},self.base))

    def test_guard_precedes_compose_infrastructure_up(self):
        self.assertLess(self.base.index('\nguard_running_order_cluster_image_change\n'),
                        self.base.index('\ncompose_up -d mysql clickhouse zookeeper\n'))
        self.assertLess(self.base.index('\nguard_running_order_cluster_image_change\n'),
                        self.base.index('\ncompose_up -d\n'))


if __name__=='__main__':unittest.main()
