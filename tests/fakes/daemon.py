# SPDX-License-Identifier: GPL-3.0-only
"""Run the real daemon (server + service) in-process, against fakes."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fakes import API, CDN, FakeFetch, FakeRunner, fake_launcher, nord_routes
from nordvpn_linux.daemon.config import DaemonConfig
from nordvpn_linux.daemon.dns import DnsConfigurator
from nordvpn_linux.daemon.main import build_service, run
from nordvpn_linux.daemon.nordapi import NordAPI
from nordvpn_linux.daemon.service import Service
from nordvpn_linux.daemon.tunnel import Tunnel
from nordvpn_linux.paths import Paths

LOGIN = {"username": "user", "password": "secret"}


@dataclass
class Harness:
    paths: Paths
    service: Service
    fetch: FakeFetch
    runner: FakeRunner
    log: Path

    async def call(
        self, cmd: str, args: dict[str, Any] | None = None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Send one request; return (events, final response)."""
        reader, writer = await asyncio.open_unix_connection(self.paths.socket)
        try:
            request = {"v": 1, "id": 1, "cmd": cmd, "args": args or {}}
            writer.write(json.dumps(request).encode() + b"\n")
            await writer.drain()
            events: list[dict[str, Any]] = []
            while True:
                line = await asyncio.wait_for(reader.readline(), 30)
                assert line, "daemon closed the connection without a response"
                message: dict[str, Any] = json.loads(line)
                if "event" not in message:
                    return events, message
                events.append(message)
        finally:
            writer.close()

    async def result(self, cmd: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        _, response = await self.call(cmd, args)
        assert response["ok"], response
        result: dict[str, Any] = response["result"]
        return result

    async def error(self, cmd: str, args: dict[str, Any] | None = None) -> str:
        _, response = await self.call(cmd, args)
        assert not response["ok"], response
        return str(response["error"]["code"])


@contextlib.asynccontextmanager
async def running_daemon(
    root: Path,
    *,
    scenario: str = "ok",
    authorized: bool = True,
    openvpn_password: str = "secret",
) -> AsyncIterator[Harness]:
    paths = Paths.under(root)
    config = DaemonConfig(connect_timeout=5, api_base=API, configs_base=CDN)
    fetch = FakeFetch(nord_routes())
    runner = FakeRunner()
    log = root / "launches.jsonl"
    service = build_service(
        config,
        paths,
        api=NordAPI(api_base=API, configs_base=CDN, paths=paths, fetch=fetch),
        tunnel=Tunnel(
            openvpn="/usr/sbin/openvpn",
            management_socket=paths.management_socket,
            launcher=fake_launcher(scenario, log=log, password=openvpn_password),
        ),
        dns=DnsConfigurator(config.dns_servers, runner=runner),
    )
    stop = asyncio.Event()
    task = asyncio.create_task(
        run(
            config,
            paths,
            authorizer=lambda uid: authorized,
            group=None,
            service=service,
            stop=stop,
            install_signal_handlers=False,
        )
    )
    for _ in range(500):
        if paths.socket.exists():
            break
        if task.done():
            task.result()  # re-raise a startup failure
        await asyncio.sleep(0.01)
    try:
        yield Harness(paths, service, fetch, runner, log)
    finally:
        stop.set()
        await asyncio.wait_for(task, 15)
