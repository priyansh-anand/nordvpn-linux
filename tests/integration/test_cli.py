# SPDX-License-Identifier: GPL-3.0-only
"""The real CLI and client against the real (in-process) daemon."""

from __future__ import annotations

import asyncio
import io
import json
import os
import socket
import sys
from pathlib import Path

import pytest
from fakes.daemon import running_daemon

from nordvpn_linux.cli.client import Client
from nordvpn_linux.cli.main import main as cli_main
from nordvpn_linux.errors import ErrorCode, NordVPNError
from nordvpn_linux.protocol import Command


async def run_cli(*argv: str) -> int:
    return await asyncio.to_thread(cli_main, list(argv))


async def test_cli_against_the_daemon(
    short_tmp: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with running_daemon(short_tmp) as h:
        sock = str(h.paths.socket)
        monkeypatch.setattr(sys, "stdin", io.StringIO("secret\n"))
        login = ("login", "--username", "user", "--password-stdin")
        assert await run_cli("--socket", sock, *login) == 0
        assert await run_cli("--socket", sock, "connect", "us") == 0
        assert "Connected to us12941 (United States)." in capsys.readouterr().out
        assert await run_cli("--socket", sock, "status", "--json") == 0
        assert json.loads(capsys.readouterr().out)["state"] == "CONNECTED"
        assert await run_cli("--socket", sock, "disconnect") == 0
        assert capsys.readouterr().out == "Disconnected.\n"


async def test_cli_reports_permission_denied(
    short_tmp: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    async with running_daemon(short_tmp, authorized=False) as h:
        assert await run_cli("--socket", str(h.paths.socket), "status") == 5
    assert "usermod -aG nordvpn" in capsys.readouterr().err


def test_cli_without_a_daemon(short_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["--socket", str(short_tmp / "none.sock"), "status"]) == 3
    assert "cannot reach the NordVPN daemon" in capsys.readouterr().err


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_socket_permission_error_is_permission_denied(short_tmp: Path) -> None:
    path = short_tmp / "locked.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(1)
    path.chmod(0)
    try:
        with pytest.raises(NordVPNError) as excinfo:
            Client(path).call(Command.STATUS)
        assert excinfo.value.code is ErrorCode.PERMISSION_DENIED
    finally:
        listener.close()


async def test_client_times_out(short_tmp: Path) -> None:
    path = short_tmp / "silent.sock"

    async def never_answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await asyncio.sleep(5)
        writer.close()

    server = await asyncio.start_unix_server(never_answer, path)
    try:
        with pytest.raises(NordVPNError) as excinfo:
            await asyncio.to_thread(Client(path).call, Command.STATUS, timeout=0.2)
        assert excinfo.value.code is ErrorCode.TIMEOUT
    finally:
        server.close()
