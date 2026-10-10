#!/usr/bin/env python3
"""Compile one recovered strategy locally and run the production SIMSvr backtest engine.

The Java process runs on the operator workstation.  Market/scene data is read through
an SSH tunnel from production ClickHouse; the script never submits a task or writes a
backtest result to production.
"""

import argparse
import base64
import copy
import hashlib
import json
import os
import re
import socketserver
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

import paramiko


DEFAULT_HOST = "18.140.45.126"
DEFAULT_USER = "ec2-user"
DEFAULT_KEY = r"C:\Users\ThinkPad\Desktop\id_rsa_2048"
DEFAULT_SEED = "live-strategy-seed-20261009.json"
DEFAULT_SIM_REPO = r"E:\sourcecode\codex\_work\simsrv-signal-economics-20261009"


class ForwardServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class ForwardHandler(socketserver.BaseRequestHandler):
    ssh_transport = None
    remote_host = "127.0.0.1"
    remote_port = 8123

    def handle(self):
        channel = self.ssh_transport.open_channel(
            "direct-tcpip",
            (self.remote_host, self.remote_port),
            self.request.getpeername(),
        )
        if channel is None:
            return
        try:
            while True:
                readable, _, _ = __import__("select").select(
                    [self.request, channel], [], [], 1.0
                )
                if self.request in readable:
                    data = self.request.recv(65536)
                    if not data:
                        break
                    channel.sendall(data)
                if channel in readable:
                    data = channel.recv(65536)
                    if not data:
                        break
                    self.request.sendall(data)
        finally:
            channel.close()
            self.request.close()


def parse_env(text):
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_seed_strategy(seed_path, strategy_name):
    package = json.loads(seed_path.read_text(encoding="utf-8"))
    for item in package.get("strategies") or []:
        if item.get("strategyName") == strategy_name:
            return item
    raise ValueError("strategy is not present in seed: %s" % strategy_name)


def source_identity(source):
    package_match = re.search(r"\bpackage\s+([A-Za-z0-9_.]+)\s*;", source)
    class_match = re.search(r"\bpublic\s+class\s+([A-Za-z0-9_]+)\b", source)
    if not package_match or not class_match:
        raise ValueError("cannot resolve Java package/public class")
    return package_match.group(1), class_match.group(1)


def java_classpath(sim_repo):
    entries = [
        sim_repo / "target" / "test-classes",
        sim_repo / "target" / "classes",
        sim_repo / "target" / "dependency" / "*",
        sim_repo / "target" / "javalib" / "*",
    ]
    return os.pathsep.join(str(path) for path in entries)


def compile_source(source, sim_repo, work_dir):
    package_name, class_name = source_identity(source)
    # javac does not require the source file itself to mirror the package path.
    # Keeping it flat avoids the legacy Windows MAX_PATH limit for long strategy names.
    source_dir = work_dir / "source"
    classes_dir = work_dir / "classes"
    source_dir.mkdir(parents=True, exist_ok=True)
    classes_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / (class_name + ".java")
    source_path.write_text(source, encoding="utf-8")
    subprocess.run(
        [
            "javac",
            "-source",
            "8",
            "-target",
            "8",
            "-encoding",
            "UTF-8",
            "-cp",
            java_classpath(sim_repo),
            "-d",
            str(classes_dir),
            str(source_path),
        ],
        check=True,
    )
    artifact = work_dir / "strategy.jar"
    subprocess.run(
        ["jar", "cf", str(artifact), "-C", str(classes_dir), "."],
        check=True,
    )
    return artifact, package_name + "." + class_name, source_path


def build_parameters(request, locked_params=None):
    schema = copy.deepcopy(request.get("parameterSchema") or {})
    defaults = copy.deepcopy(request.get("defaultParameters") or {})
    profile = copy.deepcopy(request.get("optimizationProfile") or {})
    locked = locked_params or {}
    if locked:
        defaults.update(locked)
        for definition in schema.get("parameters") or []:
            name = definition.get("name")
            if name in locked:
                definition["default"] = locked[name]
                definition["candidates"] = [locked[name]]
    return {
        "parameterSchema": schema,
        "defaultParams": defaults,
        "optimizationProfile": profile,
    }


def resolve_window_days(item, args):
    global_defaults = (120, 30, 14)
    scene = str(item.get("scene") or "").strip().lower()
    text = str(item.get("text") or "").strip().lower()
    if text == "15m" and scene == "range":
        fallback = (90, 30, 14)
    elif text == "15m" and scene in ("breakout", "reversal"):
        fallback = (120, 20, 10)
    else:
        fallback = global_defaults

    profile = (item.get("request") or {}).get("optimizationProfile") or {}
    keys = ("fitWindowDays", "validateWindowDays", "forwardWindowDays")
    explicit = (args.fit_window_days, args.validate_window_days, args.forward_window_days)
    resolved = []
    for index, key in enumerate(keys):
        raw = explicit[index] if explicit[index] is not None else profile.get(key, global_defaults[index])
        value = max(1, int(raw))
        if explicit[index] is None and value == global_defaults[index] and fallback[index] != global_defaults[index]:
            value = fallback[index]
        resolved.append(value)
    return tuple(resolved)


def read_remote_env(client):
    command = "cat /home/ec2-user/dc-quant-deploy/.env.prod"
    _, stdout, stderr = client.exec_command(command, timeout=30)
    code = stdout.channel.recv_exit_status()
    content = stdout.read().decode("utf-8", "replace")
    error = stderr.read().decode("utf-8", "replace")
    if code != 0:
        raise RuntimeError("cannot read remote deployment environment: " + error)
    return parse_env(content)


def write_db_config(path, local_port, values):
    database = values.get("CLICKHOUSE_DB_NAME") or "dc"
    username = values.get("CLICKHOUSE_USERNAME") or "default"
    password = values.get("CLICKHOUSE_PASSWORD") or ""
    content = "\n".join([
        "[DBPOOL]",
        "DBPOOL.DBCount=0",
        "CLICKHOUSE.DBCount=1",
        "CLICKHOUSE.DBSourceName_0=ClickHouse1",
        "CLICKHOUSE.DBUrl_0=jdbc:clickhouse://127.0.0.1:%d/%s?compression=true" % (
            local_port, database),
        "CLICKHOUSE.DBUsername_0=" + username,
        "CLICKHOUSE.DBPasswd_0=" + password,
        "CLICKHOUSE.DBIsEncrypt_0=false",
        "CLICKHOUSE.DBMaxCount_0=20",
        "CLICKHOUSE.DBMinCount_0=1",
        "CLICKHOUSE.DBConnOutTime_0=5000",
        "CLICKHOUSE.DBAsyncInsert_0=1",
        "CLICKHOUSE.DBAsyncInsertMaxInternet_0=2000",
        "",
    ])
    path.write_text(content, encoding="utf-8")


def run_local_backtest(args, item, artifact, entry_class, work_dir, local_port, db_config):
    request = item.get("request") or {}
    fit_window_days, validate_window_days, forward_window_days = resolve_window_days(item, args)
    result_file = work_dir / "result.json"
    parameters = json.dumps(
        build_parameters(request, args.locked_params),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    payload = json.dumps({
        "sourceRef": request.get("sourceRef") or "local-codex",
        "logicSummary": request.get("logicSummary") or "",
        "optimizationProfile": request.get("optimizationProfile") or {},
    }, ensure_ascii=False, separators=(",", ":"))
    java = [
        "java",
        "-Xms128m",
        "-Xmx768m",
        "-Dtrainer.backtest.strategyName=" + item["strategyName"],
        "-Dtrainer.backtest.strategyVersion=" + item["sourceStrategyVersion"],
        "-Dtrainer.backtest.symbol=" + item["symbol"],
        "-Dtrainer.backtest.text=" + item.get("text", "15m"),
        "-Dtrainer.backtest.beginDate=" + args.begin_date,
        "-Dtrainer.backtest.endDate=" + args.end_date,
        "-Dtrainer.backtest.fitWindowDays=%d" % fit_window_days,
        "-Dtrainer.backtest.validateWindowDays=%d" % validate_window_days,
        "-Dtrainer.backtest.forwardWindowDays=%d" % forward_window_days,
        "-Dtrainer.backtest.entryMakerFeeRatePct=0.02",
        "-Dtrainer.backtest.exitTakerFeeRatePct=0.05",
        "-Dtrainer.backtest.candidateArtifactUri=" + str(artifact),
        "-Dtrainer.backtest.candidateEntryClass=" + entry_class,
        "-Dtrainer.backtest.candidateScene=" + item["scene"],
        "-Dtrainer.backtest.candidateParametersJson=" + parameters,
        "-Dtrainer.backtest.candidatePayload=" + payload,
        "-Dtrainer.backtest.resultFile=" + str(result_file),
        "-cp",
        java_classpath(args.sim_repo),
        "com.app.dc.service.simulation.LocalBacktestCli",
        "--spring.config.location=file:" + str(args.sim_repo / "config" / "application.properties"),
        "--dbpool.cfg=" + str(db_config),
        "--log4j.file=" + str(args.sim_repo / "config" / "log4j.ini"),
        "--storePath=" + str(work_dir / "data"),
        "--binanceBacktestReportDir=" + str(work_dir / "reports"),
        "--clickhouse.default=ClickHouse1",
        "--strategy.backtest.task.enabled=false",
        "--strategy.live.recheck.enabled=false",
        "--strategy.auto-publish.enabled=false",
        "--debug=false",
        "--logging.level.root=WARN",
    ]
    process = subprocess.run(java, cwd=str(work_dir), text=True)
    if process.returncode != 0:
        raise RuntimeError("local Java backtest failed with exit code %d" % process.returncode)
    if not result_file.is_file():
        raise RuntimeError("local Java backtest did not write result: %s" % result_file)
    return json.loads(result_file.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--seed", type=Path,
                        default=Path(__file__).resolve().parent / DEFAULT_SEED)
    parser.add_argument("--sim-repo", type=Path, default=Path(DEFAULT_SIM_REPO))
    parser.add_argument("--source", type=Path,
                        help="Use a Codex-repaired Java source instead of the embedded seed source")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parent / "local-backtest-work")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--key", type=Path, default=Path(DEFAULT_KEY))
    parser.add_argument("--db-config", type=Path,
                        help="Reuse an existing tunneled ClickHouse config; skips SSH setup")
    parser.add_argument("--begin-date", default="2025-10-08")
    parser.add_argument("--end-date", default="2026-10-08")
    parser.add_argument("--fit-window-days", type=int)
    parser.add_argument("--validate-window-days", type=int)
    parser.add_argument("--forward-window-days", type=int)
    parser.add_argument(
        "--locked-params-json",
        default="{}",
        help="JSON object whose values replace defaults and collapse matching candidates",
    )
    args = parser.parse_args()
    args.seed = args.seed.resolve()
    args.sim_repo = args.sim_repo.resolve()
    args.output_dir = args.output_dir.resolve()
    args.locked_params = json.loads(args.locked_params_json)
    if not isinstance(args.locked_params, dict):
        raise SystemExit("--locked-params-json must decode to an object")

    passphrase = os.environ.get("STC_PROD_KEY_PASSPHRASE")
    if not args.db_config and not passphrase:
        raise SystemExit("STC_PROD_KEY_PASSPHRASE is required")
    item = load_seed_strategy(args.seed, args.strategy)
    if args.source:
        source = args.source.resolve().read_text(encoding="utf-8")
    else:
        source = base64.b64decode(item["request"]["javaSourceBase64"]).decode("utf-8")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    strategy_dir = hashlib.sha256(args.strategy.encode("utf-8")).hexdigest()[:12]
    work_dir = args.output_dir / strategy_dir / run_id
    work_dir.mkdir(parents=True)
    artifact, entry_class, source_path = compile_source(source, args.sim_repo, work_dir)

    client = None
    server = None
    config_path = None
    try:
        if args.db_config:
            config_path = args.db_config.resolve()
            if not config_path.is_file():
                raise ValueError("db config does not exist: %s" % config_path)
        else:
            client = paramiko.SSHClient()
            client.load_host_keys(str(Path.home() / ".ssh" / "known_hosts"))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.connect(
                args.host,
                username=args.user,
                key_filename=str(args.key),
                passphrase=passphrase,
                timeout=30,
                banner_timeout=30,
                auth_timeout=30,
            )
            remote_env = read_remote_env(client)
            ForwardHandler.ssh_transport = client.get_transport()
            ForwardHandler.remote_port = int(remote_env.get("CLICKHOUSE_HTTP_PORT") or 8123)
            server = ForwardServer(("127.0.0.1", 0), ForwardHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            local_port = server.server_address[1]
            with tempfile.NamedTemporaryFile(prefix="dc-local-backtest-", suffix=".ini", delete=False) as handle:
                config_path = Path(handle.name)
            write_db_config(config_path, local_port, remote_env)
        result = run_local_backtest(
            args, item, artifact, entry_class, work_dir, 0, config_path)
    finally:
        if config_path and config_path.exists() and not args.db_config:
            config_path.unlink()
        if server is not None:
            server.shutdown()
            server.server_close()
        if client is not None:
            client.close()

    envelope = {
        "mode": "LOCAL_CODEX_PRE_ADMISSION",
        "productionWrite": False,
        "strategyName": item["strategyName"],
        "sourceStrategyVersion": item["sourceStrategyVersion"],
        "symbol": item["symbol"],
        "scene": item["scene"],
        "sourceFile": str(source_path),
        "artifactFile": str(artifact),
        "result": result,
    }
    summary_file = work_dir / "local-pre-admission.json"
    summary_file.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    print("LOCAL_PRE_ADMISSION_RESULT=" + str(summary_file))
    return 0 if result.get("qualified") else 2


if __name__ == "__main__":
    sys.exit(main())
