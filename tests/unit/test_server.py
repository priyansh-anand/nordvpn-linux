# SPDX-License-Identifier: GPL-3.0-only
"""Unix-socket server: framing, authorization, cancellation and lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
import grp
import json
import os
import socket
import stat
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from nordvpn_linux.daemon.server import EventSink, Server
from nordvpn_linux.errors import ErrorCode, NordVPNError
from nordvpn_linux.protocol import JSONObject, Request


class Recorder:
    """A Dispatcher whose behaviour is picked by the request's ``do`` argument."""

    def __init__(self) -> None:
        self.cancelled = asyncio.Event()
        self.finished = asyncio.Event()
        self.requests: list[Request] = []

    async def handle(self, request: Request, emit: EventSink) -> JSONObject:
        self.requests.append(request)
        match request.args.get("do"):
            case "events":
                emit("CONNECTING", "one")
                emit("CONNECTING", "two")
                return {"done": True}
            case "fail":
                raise NordVPNError(ErrorCode.AUTH_FAILED, "bad credentials")
            case "crash":
                raise RuntimeError("bug")
            case "huge":
                return {"blob": "x" * 70_000}
            case "slow":
                await asyncio.sleep(0.3)
                self.finished.set()
                return {}
            case "hang":
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise
        return {"echo": request.args}


@contextlib.asynccontextmanager
async def serving(
    root: Path, *, authorized: bool = True, **options: Any
) -> AsyncIterator[tuple[Server, Recorder, Path]]:
    path = root / "run" / "d.sock"
    recorder = Recorder()
    options.setdefault("mode", 0o600)
    server = Server(path=path, dispatcher=recorder, authorizer=lambda uid: authorized, **options)
    await server.start()
    try:
        yield server, recorder, path
    finally:
        await server.close()


def req(cmd: str = "status", rid: int = 1, **args: Any) -> bytes:
    return json.dumps({"v": 1, "id": rid, "cmd": cmd, "args": args}).encode() + b"\n"


async def call(path: Path, line: bytes) -> list[dict[str, Any]]:
    """Send one line; return every reply up to and including the final response."""
    reader, writer = await asyncio.open_unix_connection(path)
    try:
        writer.write(line)
        await writer.drain()
        replies: list[dict[str, Any]] = []
        while raw := await asyncio.wait_for(reader.readline(), 5):
            replies.append(json.loads(raw))
            if "ok" in replies[-1]:
                break
        return replies
    finally:
        writer.close()


def error_of(replies: list[dict[str, Any]]) -> str:
    assert replies[-1]["ok"] is False, replies
    return str(replies[-1]["error"]["code"])


async def test_request_and_response(short_tmp: Path) -> None:
    async with serving(short_tmp) as (_, recorder, path):
        assert await call(path, req(x=1)) == [
            {"v": 1, "id": 1, "ok": True, "result": {"echo": {"x": 1}}}
        ]
        assert recorder.requests[0].args == {"x": 1}


async def test_events_precede_the_response(short_tmp: Path) -> None:
    async with serving(short_tmp) as (_, _, path):
        replies = await call(path, req("connect", rid=4, do="events"))
    assert [r.get("detail") for r in replies] == ["one", "two", None]
    assert all(r["id"] == 4 for r in replies)
    assert replies[-1]["result"] == {"done": True}


async def test_errors_become_failure_responses(short_tmp: Path) -> None:
    async with serving(short_tmp) as (_, _, path):
        failed = await call(path, req(do="fail"))
        crashed = await call(path, req(do="crash"))
        huge = await call(path, req(do="huge"))
    assert error_of(failed) == "AUTH_FAILED"
    assert failed[-1]["error"]["message"] == "bad credentials"
    assert error_of(crashed) == "INTERNAL"
    assert "journalctl" in crashed[-1]["error"]["message"]
    assert error_of(huge) == "INTERNAL"


@pytest.mark.parametrize("mode", [0o600, 0o660])
async def test_socket_mode(short_tmp: Path, mode: int) -> None:
    async with serving(short_tmp, mode=mode) as (_, _, path):
        assert stat.S_IMODE(path.stat().st_mode) == mode


async def test_socket_group(short_tmp: Path) -> None:
    our_group = grp.getgrgid(os.getgid()).gr_name
    async with serving(short_tmp, group=our_group) as (_, _, path):
        assert path.stat().st_gid == os.getgid()


async def test_missing_group_is_a_clear_error(short_tmp: Path) -> None:
    with pytest.raises(RuntimeError, match="does not exist"):
        async with serving(short_tmp, group="nordvpn-test-no-such-group"):
            pass


async def test_stale_socket_file_is_replaced(short_tmp: Path) -> None:
    path = short_tmp / "run" / "d.sock"
    path.parent.mkdir()
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(path))
    stale.close()  # the file stays behind, as after a crash
    async with serving(short_tmp) as (_, _, served):
        assert (await call(served, req()))[-1]["ok"]


async def test_refuses_to_replace_a_regular_file(short_tmp: Path) -> None:
    path = short_tmp / "run" / "d.sock"
    path.parent.mkdir()
    path.write_text("precious")
    with pytest.raises(RuntimeError, match="not a socket"):
        async with serving(short_tmp):
            pass
    assert path.read_text() == "precious"


async def test_unauthorized_peer_is_refused(short_tmp: Path) -> None:
    async with serving(short_tmp, authorized=False) as (_, recorder, path):
        replies = await call(path, req())
    assert error_of(replies) == "PERMISSION_DENIED"
    assert replies[-1]["id"] == 0
    assert recorder.requests == []


@pytest.mark.parametrize(
    ("line", "code"),
    [
        (b"nope\n", "BAD_REQUEST"),
        (json.dumps({"v": 2, "id": 1, "cmd": "status"}).encode() + b"\n", "UNSUPPORTED_VERSION"),
        (b"{" + b" " * 70_000 + b"}\n", "BAD_REQUEST"),
    ],
)
async def test_bad_requests(short_tmp: Path, line: bytes, code: str) -> None:
    async with serving(short_tmp) as (_, recorder, path):
        assert error_of(await call(path, line)) == code
        assert recorder.requests == []


async def test_incomplete_message_at_eof(short_tmp: Path) -> None:
    async with serving(short_tmp) as (_, _, path):
        reader, writer = await asyncio.open_unix_connection(path)
        writer.write(b'{"v": 1')
        writer.write_eof()
        reply = json.loads(await asyncio.wait_for(reader.readline(), 5))
        writer.close()
    assert reply["error"]["code"] == "BAD_REQUEST"


async def test_sequential_requests_on_one_connection(short_tmp: Path) -> None:
    async with serving(short_tmp) as (_, _, path):
        reader, writer = await asyncio.open_unix_connection(path)
        for rid in (1, 2, 3):
            writer.write(req(rid=rid))
            await writer.drain()
            assert json.loads(await asyncio.wait_for(reader.readline(), 5))["id"] == rid
        writer.close()


async def test_hangup_cancels_a_connect(short_tmp: Path) -> None:
    async with serving(short_tmp) as (_, recorder, path):
        _, writer = await asyncio.open_unix_connection(path)
        writer.write(req("connect", do="hang"))
        await writer.drain()
        await asyncio.sleep(0.1)
        writer.close()
        await asyncio.wait_for(recorder.cancelled.wait(), 2)


async def test_idle_client_is_disconnected(short_tmp: Path) -> None:
    async with serving(short_tmp, read_timeout=0.2) as (_, _, path):
        reader, writer = await asyncio.open_unix_connection(path)
        assert await asyncio.wait_for(reader.read(), 2) == b""
        writer.close()


async def test_too_many_clients(short_tmp: Path) -> None:
    async with serving(short_tmp, max_clients=1) as (_, _, path):
        _, first = await asyncio.open_unix_connection(path)
        await asyncio.sleep(0.05)
        replies = await call(path, req())
        first.close()
    assert error_of(replies) == "INTERNAL"
    assert "busy" in replies[-1]["error"]["message"]


async def test_close_cancels_requests_and_removes_the_socket(short_tmp: Path) -> None:
    async with serving(short_tmp) as (server, recorder, path):
        _, writer = await asyncio.open_unix_connection(path)
        writer.write(req(do="hang"))
        await writer.drain()
        await asyncio.sleep(0.1)
        await asyncio.wait_for(server.close(), 5)
        assert recorder.cancelled.is_set()
        assert not path.exists()
        writer.close()


@pytest.mark.parametrize("cmd", ["disconnect", "logout", "login", "settings.set"])
async def test_hangup_does_not_cancel_other_requests(short_tmp: Path, cmd: str) -> None:
    # An interrupted `nordvpn logout` must still forget the credentials, and an
    # interrupted disconnect must still disconnect.
    async with serving(short_tmp) as (_, recorder, path):
        _, writer = await asyncio.open_unix_connection(path)
        writer.write(req(cmd, do="slow"))
        await writer.drain()
        writer.close()
        await asyncio.wait_for(recorder.finished.wait(), 2)
        assert not recorder.cancelled.is_set()
