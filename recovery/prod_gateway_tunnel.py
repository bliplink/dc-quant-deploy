#!/usr/bin/env python3
"""Open a local-only SSH tunnel to the production GW HTTP endpoint.

The private-key passphrase is read from STC_PROD_KEY_PASSPHRASE and is never
persisted. This helper performs no trading-system request itself.
"""

import argparse
import os
import select
import socketserver
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
    args = parser.parse_args()

    passphrase = os.environ.get("STC_PROD_KEY_PASSPHRASE")
    if not passphrase:
        raise SystemExit("STC_PROD_KEY_PASSPHRASE is required")

    client = paramiko.SSHClient()
    client.load_host_keys(str(Path.home() / ".ssh" / "known_hosts"))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        args.host,
        username=args.user,
        key_filename=str(args.key.resolve()),
        passphrase=passphrase,
        timeout=30,
        banner_timeout=30,
        auth_timeout=30,
    )

    ForwardHandler.transport = client.get_transport()
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
