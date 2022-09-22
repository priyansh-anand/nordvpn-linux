# SPDX-License-Identifier: GPL-3.0-only
"""Helpers for driving the e2e Docker stack."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

E2E = Path(__file__).parent
ROOT = E2E.parents[1]
COMPOSE = ["docker", "compose", "-f", str(E2E / "compose.yaml")]
SOCKET = "/run/nordvpn/nordvpnd.sock"
Result = subprocess.CompletedProcess[str]


class Stack:
    def exec(
        self,
        *argv: str,
        user: str | None = None,
        check: bool = True,
        input: str | None = None,
        timeout: float = 120,
    ) -> Result:
        """Run *argv* in the client container, as root or (with runuser) as *user*."""
        command = [*COMPOSE, "exec", "-T", "client"]
        if user is not None:
            command += ["runuser", "-u", user, "--"]
        result = subprocess.run(
            [*command, *argv], input=input, capture_output=True, text=True, timeout=timeout
        )
        if check and result.returncode != 0:
            raise AssertionError(
                f"{list(argv)} exited {result.returncode}\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        return result

    def sh(self, script: str, *, user: str | None = None, check: bool = True) -> Result:
        return self.exec("sh", "-c", script, user=user, check=check)

    def nordvpn(self, *args: str, user: str = "alice", input: str | None = None) -> Result:
        return self.exec("nordvpn", *args, user=user, check=False, input=input)

    def status(self) -> dict[str, Any]:
        result = self.nordvpn("status", "--json")
        assert result.returncode == 0, result.stderr
        status: dict[str, Any] = json.loads(result.stdout)
        return status

    def connect(self, *target: str) -> dict[str, Any]:
        result = self.nordvpn("connect", *target)
        assert result.returncode == 0, result.stderr
        return self.status()

    def wait_for(
        self, predicate: Callable[[], bool], timeout: float = 30, message: str = "condition"
    ) -> None:
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError(f"timed out waiting for {message}")
            time.sleep(0.5)

    def wait_for_daemon(self) -> None:
        self.wait_for(
            lambda: self.exec("test", "-S", SOCKET, check=False).returncode == 0,
            message="the nordvpnd socket",
        )
