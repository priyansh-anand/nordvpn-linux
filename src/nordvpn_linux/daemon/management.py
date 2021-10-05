# SPDX-License-Identifier: GPL-3.0-only
"""OpenVPN management-interface protocol: a line parser and a small asyncio client.

Reference: https://openvpn.net/community-resources/management-interface/
Real-time notifications start with ``>``; replies to commands start with
``SUCCESS:`` or ``ERROR:``.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StateChange:
    name: str
    description: str = ""
    local_ip: str = ""
    remote_ip: str = ""


@dataclass(frozen=True)
class ByteCount:
    rx: int
    tx: int


@dataclass(frozen=True)
class PasswordRequest:
    kind: str


@dataclass(frozen=True)
class PasswordFailure:
    kind: str


@dataclass(frozen=True)
class HoldRequest:
    pass


@dataclass(frozen=True)
class Fatal:
    message: str


@dataclass(frozen=True)
class CommandReply:
    ok: bool
    message: str


@dataclass(frozen=True)
class Unrecognized:
    line: str


Message = (
    StateChange
    | ByteCount
    | PasswordRequest
    | PasswordFailure
    | HoldRequest
    | Fatal
    | CommandReply
    | Unrecognized
)

_NEED_PASSWORD = re.compile(r"Need '([^']+)' (?:username/password|password)")
_PASSWORD_FAILED = re.compile(r"Verification Failed: '([^']+)'")
_STATE_FIELDS = 5  # timestamp, name, description, local IP, remote IP


def parse_line(line: str) -> Message:
    line = line.rstrip("\r\n")
    if line.startswith("SUCCESS:"):
        return CommandReply(ok=True, message=line.removeprefix("SUCCESS:").strip())
    if line.startswith("ERROR:"):
        return CommandReply(ok=False, message=line.removeprefix("ERROR:").strip())
    if not line.startswith(">") or ":" not in line:
        return Unrecognized(line)
    kind, _, body = line[1:].partition(":")
    if kind == "STATE":
        fields = [*body.split(","), *([""] * _STATE_FIELDS)]
        return StateChange(fields[1], fields[2], fields[3], fields[4])
    if kind == "BYTECOUNT":
        rx, _, tx = body.partition(",")
        try:
            return ByteCount(int(rx), int(tx))
        except ValueError:
            return Unrecognized(line)
    if kind == "PASSWORD":
        if match := _PASSWORD_FAILED.search(body):
            return PasswordFailure(match.group(1))
        if match := _NEED_PASSWORD.search(body):
            return PasswordRequest(match.group(1))
        return Unrecognized(line)
    if kind == "HOLD":
        return HoldRequest()
    if kind == "FATAL":
        return Fatal(body)
    return Unrecognized(line)


def quote(value: str) -> str:
    """Quote a command argument: backslash-escape ``\\`` and ``"``, then wrap in quotes."""
    if any(ch in value for ch in "\r\n\x00"):
        raise ValueError("management arguments cannot contain line breaks or NUL bytes")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class ManagementClient:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer

    @classmethod
    async def connect(
        cls, path: Path, *, timeout: float = 5.0, interval: float = 0.05
    ) -> ManagementClient:
        """Connect to OpenVPN's management socket, waiting for OpenVPN to create it."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            try:
                reader, writer = await asyncio.open_unix_connection(path)
            except (FileNotFoundError, ConnectionRefusedError):
                if loop.time() >= deadline:
                    raise TimeoutError(
                        f"OpenVPN management socket {path} did not appear within {timeout:g}s"
                    ) from None
                await asyncio.sleep(interval)
            else:
                return cls(reader, writer)

    async def read(self) -> Message | None:
        line = await self._reader.readline()
        if not line:
            return None
        return parse_line(line.decode("utf-8", errors="replace"))

    async def send(self, command: str) -> None:
        self._writer.write(command.encode() + b"\n")
        await self._writer.drain()

    async def send_credentials(self, kind: str, username: str, password: str) -> None:
        await self.send(f"username {quote(kind)} {quote(username)}")
        await self.send(f"password {quote(kind)} {quote(password)}")

    async def close(self) -> None:
        self._writer.close()
        with contextlib.suppress(OSError):
            await self._writer.wait_closed()
