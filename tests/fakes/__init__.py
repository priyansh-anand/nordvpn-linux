# SPDX-License-Identifier: GPL-3.0-only
"""Test doubles shared by the unit and integration tests."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from nordvpn_linux.daemon.nordapi import FetchError
from nordvpn_linux.daemon.tunnel import Launcher

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


FAKE_OPENVPN = Path(__file__).with_name("fake_openvpn.py")


def fake_launcher(
    scenario: str = "ok",
    *,
    log: Path | None = None,
    user: str = "user",
    password: str = "secret",
) -> Launcher:
    """A Launcher that runs fake_openvpn.py (with this interpreter) instead of openvpn."""

    async def launch(argv: list[str]) -> asyncio.subprocess.Process:
        env = {
            **os.environ,
            "FAKE_OPENVPN_SCENARIO": scenario,
            "FAKE_OPENVPN_USER": user,
            "FAKE_OPENVPN_PASS": password,
        }
        if log is not None:
            env["FAKE_OPENVPN_LOG"] = str(log)
        return await asyncio.create_subprocess_exec(
            sys.executable, str(FAKE_OPENVPN), *argv[1:], env=env
        )

    return launch


def launches(log: Path) -> list[dict[str, Any]]:
    """Every fake OpenVPN start recorded in *log*: ``{"pid": int, "argv": [...]}``."""
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def eventually(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    """Poll *predicate* until it is true, failing the test after *timeout* seconds."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError(f"condition not met within {timeout}s")
        await asyncio.sleep(0.02)
