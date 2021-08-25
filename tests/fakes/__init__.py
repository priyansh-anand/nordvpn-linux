# SPDX-License-Identifier: GPL-3.0-only
"""Test doubles shared by the unit and integration tests."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from nordvpn_linux.daemon.nordapi import FetchError

FIXTURES = Path(__file__).parents[1] / "fixtures"
API = "https://api.test"
CDN = "https://cdn.test"
UDP_CONFIG_URL = f"{CDN}/configs/files/ovpn_udp/servers/us12941.nordvpn.com.udp.ovpn"
TCP_CONFIG_URL = f"{CDN}/configs/files/ovpn_tcp/servers/us12941.nordvpn.com.tcp.ovpn"

Route = bytes | Exception


class FakeFetch:
    """A ``fetch`` serving canned responses.

    A route key ending in ``*`` matches by prefix. Unknown URLs are a 404.
    """

    def __init__(self, routes: Mapping[str, Route]) -> None:
        self.routes = dict(routes)
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        for pattern, value in self.routes.items():
            if url == pattern or (pattern.endswith("*") and url.startswith(pattern[:-1])):
                if isinstance(value, Exception):
                    raise value
                return value
        raise FetchError(url, 404, "HTTP 404 Not Found")


def nord_routes() -> dict[str, Route]:
    """Routes that make the fake API behave like the real one, serving us12941."""
    return {
        f"{API}/v1/servers/countries": (FIXTURES / "api" / "countries.json").read_bytes(),
        f"{API}/v1/servers/recommendations?*": (
            FIXTURES / "api" / "recommendations_us.json"
        ).read_bytes(),
        UDP_CONFIG_URL: (FIXTURES / "ovpn" / "us12941.udp.ovpn").read_bytes(),
        TCP_CONFIG_URL: (FIXTURES / "ovpn" / "us12941.tcp.ovpn").read_bytes(),
    }
