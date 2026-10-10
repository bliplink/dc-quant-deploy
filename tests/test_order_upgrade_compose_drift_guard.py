"""Prove that a live Order HA cluster cannot be implicitly recreated by Compose config drift."""
from pathlib import Path
import os
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]


def function_source():
    s=(ROOT/'deploy-saas.sh').read_text()
    begin=s.index('guard_running_order_cluster_compose_change() {')
    end=s.index('\nverify_order_cluster_images() {',begin)
    return s[begin:end]


def execute(overrides=None):
    shell=r'''set -euo pipefail
log() { :; }
die() { exit 93; }
docker() {
    if [[ "$1" != "inspect" ]]; then return 99; fi
    local name="$2"
    if [[ "$#" == 2 ]]; then
        if [[ "${MOCK_ALL_MISSING:-false}" == "true" ]]; then return 1; fi
        if [[ "$name" == "dc-saas-ordersvr-c" && "${MOCK_C_EXISTS:-false}" != "true" ]]; then return 1; fi
        if [[ "$name" == "dc-saas-ordersvr-b" && "${MOCK_B_MISSING:-false}" == "true" ]]; then return 1; fi
        return 0
    fi
    if [[ "$#" == 4 && "$4" == *config-hash* ]]; then
        if [[ "${MOCK_UNKNOWN_HASH:-false}" == "true" ]]; then echo '<no value>'; else printf '%064d\n' 0 | tr 0 a; fi
        return 0
    fi
    return 99
}
compose() {
    [[ "$1" == config && "$2" == --hash ]] || return 99
    if [[ "${MOCK_CONFIG_MISSING:-false}" == "true" ]]; then return 1; fi
    if [[ "${MOCK_HASH_DRIFT:-false}" == "true" ]]; then
        printf '%s %064d\n' "$3" 0 | sed 's/0/b/g'
    else
        printf '%s %064d\n' "$3" 0 | sed 's/0/a/g'
    fi
}
'''+function_source()+r'''
ORDER_CLUSTER_ENABLED=${ORDER_CLUSTER_ENABLED:-true}
ORDER_CLUSTER_C_ENABLED=${ORDER_CLUSTER_C_ENABLED:-false}
guard_running_order_cluster_compose_change
'''
    env=dict(os.environ)
    env.update(ORDER_CLUSTER_ENABLED='true',ORDER_CLUSTER_C_ENABLED='false')
    env.update(overrides or {})
    result=subprocess.run(['bash','-c',shell],env=env,text=True,capture_output=True)
    return result.returncode


class ComposeProtectionTests(unittest.TestCase):
    def test_same_running_configuration_accepted(self):
        self.assertEqual(0,execute())

    def test_hash_drift_rejected(self):
        self.assertEqual(93,execute({'MOCK_HASH_DRIFT':'true'}))

    def test_running_c_not_in_configured_topology_rejected(self):
        self.assertEqual(93,execute({'MOCK_C_EXISTS':'true'}))

    def test_all_three_can_be_verified_when_profile_enabled(self):
        self.assertEqual(0,execute({'ORDER_CLUSTER_C_ENABLED':'true','MOCK_C_EXISTS':'true'}))

    def test_missing_running_replica_rejected(self):
        self.assertEqual(93,execute({'MOCK_B_MISSING':'true'}))

    def test_fresh_install_without_running_nodes_accepted(self):
        self.assertEqual(0,execute({'MOCK_ALL_MISSING':'true'}))

    def test_missing_or_unknown_hash_rejected(self):
        self.assertEqual(93,execute({'MOCK_UNKNOWN_HASH':'true'}))
        self.assertEqual(93,execute({'MOCK_CONFIG_MISSING':'true'}))

    def test_cluster_disabled_while_b_running_rejected(self):
        self.assertEqual(93,execute({'ORDER_CLUSTER_ENABLED':'false'}))

    def test_guard_invoked_before_any_compose_up(self):
        source=(ROOT/'deploy-saas.sh').read_text()
        invoke=source.index('\nguard_running_order_cluster_compose_change\n')
        self.assertLess(invoke,source.index('\ncompose_up -d mysql clickhouse zookeeper\n'))
        self.assertLess(invoke,source.index('\ncompose_up -d\n'))


if __name__=='__main__':unittest.main()
