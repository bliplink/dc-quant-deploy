#!/usr/bin/env python3
"""Fail-closed, read-only SaaS deployment config preflight (NOT a HA proof).

Run after generate-saas-configs.sh and BEFORE starting Order/Trade or Gateway.
Supports single-node and A/B without hard-coding either mode. Never modifies
ZooKeeper, data, Docker containers, or any authentication/ACK state.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


def read_properties(path):
    result = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "!")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in result:
            raise ValueError("DUPLICATE_CONFIG_KEY:" + key.strip())
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def check_static(env, conf, runtime_root=None):
    issues = []
    def need(condition, code):
        if not condition:
            issues.append(code)

    expected_zk = "127.0.0.1:" + env.get("ZOOKEEPER_PORT", "")
    need(bool(env.get("ZOOKEEPER_PORT")) and
         conf.get("REGISTER.Svr1.Host") == expected_zk,
         "ZK_HOST_MISMATCH")
    service_defs = (
        ("order", "OrderSvr", "ORDERSVR_GW_PORT", "ORDERSVR_B_GW_PORT",
         "ORDER_CLUSTER_ENABLED"),
        ("trade", "TradeSvr", "TRADESVR_GW_PORT", "TRADESVR_B_GW_PORT",
         "TRADE_CLUSTER_ENABLED"),
    )
    ports = {}
    def expected_port(role, value):
        need(bool(value and value.isdigit() and 1 <= int(value) <= 65535),
             "MISSING_OR_INVALID_PORT:" + role)
        if not value or not value.isdigit():
            return
        if value in ports:
            issues.append("PORT_COLLISION:" + ports[value] + ":" + role)
        ports[value] = role

    for key in ("GW_TCP_PORT", "GW_WEBSOCKET_PORT", "GW_HTTP_PORT",
                "PROJECTIONSVR_GW_PORT", "APSSVR_GW_PORT", "MDSVR_GW_PORT"):
        if env.get(key):
            expected_port(key, env[key])

    for label, name, key_a, key_b, enabled in service_defs:
        mode = env.get(enabled, "false").lower()
        need(mode in ("true", "false"), "INVALID_CLUSTER_MODE:" + enabled)
        cluster = mode == "true"
        expected_port(name + "A" if cluster else name, env.get(key_a, ""))
        node_a = name + "A" if cluster else name
        need(conf.get("SERVER." + node_a + ".Host") ==
             "127.0.0.1:" + env.get(key_a, ""),
             "GATEWAY_NODE_A_MISSING_OR_WRONG:" + name)
        need(conf.get("SERVER." + node_a + ".RegType") == "2",
             "GATEWAY_NODE_A_REGTYPE_WRONG:" + name)
        need(conf.get("SERVER." + name + ".RegType") == ("0" if cluster else "2"),
             "GATEWAY_GROUP_MODE_MISMATCH:" + name)
        if cluster:
            expected_port(name + "B", env.get(key_b, ""))
            need(conf.get("SERVER." + name + "B.Host") ==
                 "127.0.0.1:" + env.get(key_b, ""),
                 "GATEWAY_NODE_B_MISSING_OR_WRONG:" + name)
            need(conf.get("SERVER." + name + "B.RegType") == "2",
                 "GATEWAY_NODE_B_REGTYPE_WRONG:" + name)
            need(conf.get("LBConfig." + name) == "Partition",
                 "PARTITION_LB_MISSING:" + name)
            need(conf.get("Cluster." + name + ".Enabled") == "true",
                 "CLUSTER_FLAG_MISSING:" + name)
        else:
            need("SERVER." + name + "B.Host" not in conf,
                 "SINGLE_NODE_HAS_STALE_B_ENTRY:" + name)
            need(conf.get("LBConfig." + name) != "Partition",
                 "SINGLE_NODE_HAS_PARTITION_LB:" + name)
            need(conf.get("Cluster." + name + ".Enabled") != "true",
                 "SINGLE_NODE_HAS_STALE_CLUSTER_FLAG:" + name)
    if runtime_root:
        namespace = {}
        bind_ports = {}
        for service, name, _, _, mode in service_defs:
            if env.get(mode, "false") != "true":
                continue
            for node in "AB":
                filename = (Path(runtime_root) / "config-hostready" /
                            service / node / "application.properties")
                if not filename.is_file():
                    issues.append("MISSING_NODE_RUNTIME:" + service + node)
                    continue
                props = read_properties(filename)
                key = service + ".common."
                need(props.get(key + "control.zkHosts") == expected_zk,
                     "STALE_RUNTIME_ZK:" + service + node)
                ns = props.get(key + "nodeRuntime.freshE1.namespace", "")
                need(bool(ns) and ns.startswith("/otc/") and ns.endswith("/" + service),
                     "INVALID_COMMON_NAMESPACE:" + service + node)
                if node == "A":
                    namespace[service] = ns
                else:
                    need(ns == namespace.get(service), "AB_NAMESPACE_MISMATCH:" + service)
                port = props.get(key + "nodeRuntime.bindPort", "")
                if port:
                    need(port.isdigit() and int(port) > 0,
                         "INVALID_REPLICATION_PORT:" + service + node)
                    if port in bind_ports:
                        issues.append("REPLICATION_PORT_COLLISION:" +
                                      bind_ports[port] + ":" + service + node)
                    bind_ports[port] = service + node
        if "order" in namespace and "trade" in namespace:
            need(namespace["order"] != namespace["trade"],
                 "ORDER_TRADE_NAMESPACE_COLLISION")
    return issues


def check_gateway_md_mode(env, control_dir):
    """Require XML to agree with declared MD topology, not default silently."""
    xml = Path(control_dir) / "overrides" / "GW" / "config" / "spring-gw-client.xml"
    if not xml.is_file():
        return ["MISSING_GATEWAY_MODE_CONFIG"]
    root = ET.parse(str(xml)).getroot()
    ns = "{http://www.springframework.org/schema/beans}"
    bean = root.find(ns + "bean[@id='proxy']")
    if bean is None:
        return ["MISSING_GATEWAY_PROXY_BEAN"]
    values = [prop.get("value") for prop in bean.findall(ns + "property")
              if prop.get("name") == "mdClusterEnabled"]
    expected = env.get("MD_CLUSTER_ENABLED", "false").lower()
    if expected not in ("true", "false"):
        return ["INVALID_MD_CLUSTER_MODE"]
    if values != [expected]:
        return ["GATEWAY_MD_MODE_MISMATCH:expected_" + expected +
                ":observed_" + (",".join(str(x) for x in values) or "MISSING")]
    return []


def check_business_md_client_mode(env, control_dir):
    """Fail closed if Trade/Liq client mode differs from Gateway MD topology."""
    expected = env.get("MD_CLUSTER_ENABLED", "false").lower()
    if expected not in ("true", "false"):
        return ["INVALID_MD_CLUSTER_MODE"]
    services = ["TradeSvr", "LiqSvr"]
    if env.get("TRADE_CLUSTER_ENABLED", "false").lower() == "true":
        services.extend(("TradeSvrA", "TradeSvrB"))
    issues = []
    for service in services:
        filename = (Path(control_dir) / "overrides" / service / "config" /
                    "application.properties")
        if not filename.is_file():
            issues.append("MISSING_BUSINESS_MD_MODE_CONFIG:" + service)
            continue
        actual = read_properties(filename).get("md.cluster.enabled")
        if actual != expected:
            issues.append("BUSINESS_MD_MODE_MISMATCH:" + service + ":expected_" +
                          expected + ":observed_" + (actual or "MISSING"))
    return issues


def check_zk_types(zk_container, cli, zk_addr, env):
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", zk_container):
        raise ValueError("INVALID_ZK_CONTAINER")
    if not re.fullmatch(r"[a-zA-Z0-9_./-]+", cli) or ".." in cli:
        raise ValueError("INVALID_ZK_CLI")
    if not re.fullmatch(r"[a-zA-Z0-9_.:-]+", zk_addr):
        raise ValueError("INVALID_ZK_ADDRESS")
    issues = []
    for service, mode in (("OrderSvr", "ORDER_CLUSTER_ENABLED"),
                          ("TradeSvr", "TRADE_CLUSTER_ENABLED")):
        expected = "ALL" if env.get(mode, "false") == "true" else "STANDBY"
        result = subprocess.run(
            ["docker", "exec", "-i", zk_container, cli, "-server", zk_addr],
            input="get /MDTService/" + service + "\nquit\n",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        if result.returncode:
            issues.append("ZK_QUERY_FAILED:" + service)
            continue
        values = [line.strip() for line in result.stdout.splitlines()
                  if line.strip() in ("ALL", "STANDBY")]
        if values != [expected]:
            issues.append("ZK_DISCOVERY_MODE_MISMATCH:" + service +
                          ":expected_" + expected + ":observed_" +
                          (",".join(values) or "MISSING"))
    return issues


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--env", required=True, help="deployed environment file, read-only")
    p.add_argument("--control-dir", required=True)
    p.add_argument("--runtime-root", help="optional Common staged config root")
    p.add_argument("--zk-container", help="optional live ZK metadata verification")
    p.add_argument("--zk-cli", default="zkCli.sh")
    args = p.parse_args()
    try:
        env = read_properties(args.env)
        config = read_properties(Path(args.control_dir) / "ATSConfig.ini")
        issues = check_static(env, config, args.runtime_root)
        issues.extend(check_gateway_md_mode(env, args.control_dir))
        issues.extend(check_business_md_client_mode(env, args.control_dir))
        if args.zk_container:
            issues.extend(check_zk_types(
                args.zk_container, args.zk_cli,
                "127.0.0.1:" + env["ZOOKEEPER_PORT"], env))
        if issues:
            for issue in issues:
                print("SAAS_DEPLOYMENT_PREFLIGHT_NO_GO:" + issue, file=sys.stderr)
            return 1
        print("SAAS_DEPLOYMENT_PREFLIGHT_PASS config_mode_aware" +
              (" runtime_roots_checked" if args.runtime_root else "") +
              (" zk_discovery_checked" if args.zk_container else ""))
        print("NOT_A_TRADE_ACK_OR_AUTO_HA_PROOF")
        return 0
    except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as exc:
        print("SAAS_DEPLOYMENT_PREFLIGHT_NO_GO:" + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())