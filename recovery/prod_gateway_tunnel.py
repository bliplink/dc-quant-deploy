#!/usr/bin/env python3
"""Open a local-only SSH tunnel to the production GW HTTP endpoint.

The private-key passphrase is read from STC_PROD_KEY_PASSPHRASE and is never
persisted. This helper performs no trading-system request itself.
"""

import argparse
import os
import select
import socketserver
import time
from pathlib import Path

import paramiko


class ForwardServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class ForwardHandler(socketserver.BaseRequestHandler):
    transport = None
    remote_host = "127.0.0.1"
    remote_port = 31002

    def handle(self):
        channel = self.transport.open_channel(
            "direct-tcpip",
            (self.remote_host, self.remote_port),
            self.request.getpeername(),
        )
        if channel is None:
            return
        try:
            while True:
                readable, _, _ = select.select([self.request, channel], [], [], 1.0)
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="18.140.45.126")
    parser.add_argument("--user", default="ec2-user")
    parser.add_argument(
        "--key", type=Path, default=Path(r"C:\Users\ThinkPad\Desktop\id_rsa_2048")
    )
    parser.add_argument("--local-host", default="127.0.0.1")
    parser.add_argument("--local-port", type=int, default=13002)
    parser.add_argument("--remote-host", default="127.0.0.1")
    parser.add_argument("--remote-port", type=int, default=31002)
    parser.add_argument("--connect-attempts", type=int, default=6)
    args = parser.parse_args()

    passphrase = os.environ.get("STC_PROD_KEY_PASSPHRASE")
    if not passphrase:
        raise SystemExit("STC_PROD_KEY_PASSPHRASE is required")

    client = None
    for attempt in range(1, args.connect_attempts + 1):
        candidate = paramiko.SSHClient()
        candidate.load_host_keys(str(Path.home() / ".ssh" / "known_hosts"))
        candidate.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            candidate.connect(
                args.host,
                username=args.user,
                key_filename=str(args.key.resolve()),
                passphrase=passphrase,
                timeout=30,
                banner_timeout=30,
                auth_timeout=30,
            )
            client = candidate
            break
        except Exception as error:
            candidate.close()
            if attempt >= args.connect_attempts:
                raise
            delay = min(30 * (2 ** (attempt - 1)), 120)
            print(
                "GW_TUNNEL_CONNECT_RETRY attempt=%d delay=%d error=%s"
                % (attempt, delay, error),
                flush=True,
            )
            time.sleep(delay)
    if client is None:
        raise RuntimeError("SSH client was not initialized")
    transport = client.get_transport()
    if transport is None or not transport.is_active():
        raise RuntimeError("SSH transport is not active after connect")
    transport.set_keepalive(30)

    ForwardHandler.transport = transport
    ForwardHandler.remote_host = args.remote_host
    ForwardHandler.remote_port = args.remote_port
    server = ForwardServer((args.local_host, args.local_port), ForwardHandler)
    print(
        "GW_TUNNEL_READY %s:%d -> %s:%d"
        % (args.local_host, args.local_port, args.remote_host, args.remote_port),
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
        client.close()


if __name__ == "__main__":
    main()
