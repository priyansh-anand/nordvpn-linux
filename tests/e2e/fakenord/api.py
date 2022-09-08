# SPDX-License-Identifier: GPL-3.0-only
"""Fake NordVPN API and config CDN (HTTPS :443), plus a web server behind the tunnel (HTTP :80)."""

from __future__ import annotations

import json
import re
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

PKI = Path("/pki")
SERVER_IP = "172.28.0.10"
PORTS = {"udp": 1194, "tcp": 1443}
COUNTRIES = [{"id": 999, "name": "Testland", "code": "XX", "serverCount": 2, "cities": []}]
RECOMMENDATION = [
    {
        "hostname": "xx1.nordvpn.com",
        "load": 5,
        "station": SERVER_IP,
        "locations": [{"country": {"id": 999, "name": "Testland", "code": "XX"}}],
    }
]
CONFIG_PATH = re.compile(
    r"/configs/files/ovpn_(udp|tcp)/servers/(xx1|xx666)\.nordvpn\.com\.(udp|tcp)\.ovpn"
)
BLOB = b"x" * (1024 * 1024)


def render_config(proto: str, host: str) -> str:
    """A config shaped like NordVPN's real ones, pointing at this container."""
    ca = (PKI / "ca.crt").read_text().strip()
    tls_auth = (PKI / "ta.key").read_text().strip()
    lines = [
        "client",
        "dev tun",
        f"proto {proto}",
        f"remote {SERVER_IP} {PORTS[proto]}",
        "resolv-retry infinite",
        "remote-random",
        "nobind",
        "tun-mtu 1500",
        "tun-mtu-extra 32",
        "mssfix 1450",
        "persist-key",
        "persist-tun",
        "ping 15",
        "ping-restart 0",
        "ping-timer-rem",
        "reneg-sec 0",
        "comp-lzo no",
        f"verify-x509-name CN={host}.nordvpn.com",
        "remote-cert-tls server",
        "auth-user-pass",
        "verb 3",
        "pull",
        "fast-io",
        "cipher AES-256-CBC",
        "auth SHA512",
    ]
    if host == "xx666":  # a malicious config: tries to run a command as root
        lines += ["script-security 2", "up \"/bin/sh -c 'touch /var/lib/nordvpn/pwn-ran'\""]
    lines += [f"<ca>\n{ca}\n</ca>", "key-direction 1", f"<tls-auth>\n{tls_auth}\n</tls-auth>"]
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def send_body(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ApiHandler(Handler):
    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        match = CONFIG_PATH.fullmatch(path)
        if path == "/v1/servers/countries":
            self.send_body(200, json.dumps(COUNTRIES).encode(), "application/json")
        elif path == "/v1/servers/recommendations":
            self.send_body(200, json.dumps(RECOMMENDATION).encode(), "application/json")
        elif match and match.group(1) == match.group(3):
            config = render_config(match.group(1), match.group(2))
            self.send_body(200, config.encode(), "text/plain")
        else:
            self.send_body(404, b"not found\n", "text/plain")


class TunnelHandler(Handler):
    def do_GET(self) -> None:
        body = BLOB if self.path == "/blob" else b"hello from inside the tunnel\n"
        self.send_body(200, body, "application/octet-stream")


def main() -> None:
    web = ThreadingHTTPServer(("0.0.0.0", 80), TunnelHandler)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    api = ThreadingHTTPServer(("0.0.0.0", 443), ApiHandler)
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(PKI / "web.crt", PKI / "web.key")
    api.socket = context.wrap_socket(api.socket, server_side=True)
    api.serve_forever()


if __name__ == "__main__":
    main()
