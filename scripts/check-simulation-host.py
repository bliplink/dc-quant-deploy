#!/usr/bin/env python3
"""Report the native host and its Docker engine before a simulation release install."""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def output(*args):
    return subprocess.check_output(args, text=True, timeout=20, stderr=subprocess.PIPE).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-parent", type=Path, default=Path.cwd(),
                        help="existing filesystem directory that would hold simulation data")
    args = parser.parse_args()
    host_os = platform.system()
    names = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
    host_arch = names.get(platform.machine().lower())
    if host_os not in {"Linux", "Darwin"} or not host_arch:
        raise ValueError("Expected Linux or macOS on x86_64 or ARM64")
    context = output("docker", "context", "show")
    endpoint = json.loads(output("docker", "context", "inspect", context))[0]["Endpoints"]["docker"]["Host"]
    if os.environ.get("DOCKER_HOST") and not os.environ.get("DOCKER_CONTEXT"):
        endpoint = os.environ["DOCKER_HOST"]
    if not endpoint.startswith("unix://"):
        raise ValueError("This check requires the local host's Docker engine")
    info = json.loads(output("docker", "info", "--format", "{{json .}}"))
    engine_arch = names.get(info["Architecture"].lower())
    if info["OSType"] != "linux" or not engine_arch:
        raise ValueError("Expected a Linux container engine on ARM64 or AMD64")
    data = args.data_parent.resolve(strict=True)
    if not data.is_dir():
        raise ValueError("--data-parent must be a directory")
    print(json.dumps({
        "host": ("macos" if host_os == "Darwin" else "linux") + "/" + host_arch,
        "imagePlatform": "linux/" + engine_arch,
        "dockerContext": context,
        "dockerEngine": info["ServerVersion"],
        "compose": output("docker", "compose", "version", "--short"),
        "engineCPUs": info["NCPU"],
        "engineMemoryGiB": round(info["MemTotal"] / 2**30, 2),
        "dataFilesystemFreeGiB": round(shutil.disk_usage(data).free / 2**30, 2),
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f"Host check failed: {error}")
