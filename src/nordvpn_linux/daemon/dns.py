# SPDX-License-Identifier: GPL-3.0-only
"""Send DNS through the tunnel with systemd-resolved while connected.

OpenVPN runs with ``--script-security 1``, so no ``up`` script applies the DNS
servers the VPN pushes. The daemon configures the tunnel link itself instead.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from enum import StrEnum

log = logging.getLogger(__name__)

Runner = Callable[[list[str]], Awaitable[int]]
COMMAND_NOT_FOUND = 127


class DnsStatus(StrEnum):
    APPLIED = "applied"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


async def run_command(argv: list[str]) -> int:
    """Run *argv* without a shell; stdout is discarded and stderr goes to the journal."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL
        )
    except FileNotFoundError:
        return COMMAND_NOT_FOUND
    return await proc.wait()


class DnsConfigurator:
    def __init__(
        self,
        servers: Sequence[str],
        *,
        resolvectl: str = "resolvectl",
        runner: Runner = run_command,
    ) -> None:
        self._servers = list(servers)
        self._resolvectl = resolvectl
        self._runner = runner

    async def apply(self, device: str) -> DnsStatus:
        if await self._run("status") != 0:
            log.warning("systemd-resolved is not running; DNS will not go through the VPN tunnel")
            return DnsStatus.UNAVAILABLE
        for args in (
            ["dns", device, *self._servers],
            ["domain", device, "~."],
            ["default-route", device, "true"],
        ):
            if await self._run(*args) != 0:
                log.error("resolvectl %s failed; DNS may leak outside the tunnel", " ".join(args))
                return DnsStatus.FAILED
        log.info("DNS for %s set to %s", device, ", ".join(self._servers))
        return DnsStatus.APPLIED

    async def revert(self, device: str) -> None:
        if await self._run("revert", device) != 0:
            log.debug("resolvectl revert %s failed (the link is probably gone)", device)

    async def _run(self, *args: str) -> int:
        return await self._runner([self._resolvectl, *args])
