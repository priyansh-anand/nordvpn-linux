# SPDX-License-Identifier: GPL-3.0-only
"""OpenVPN management protocol parsing and client."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from nordvpn_linux.daemon.management import (
    ByteCount,
    CommandReply,
    Fatal,
    HoldRequest,
    ManagementClient,
    Message,
    PasswordFailure,
    PasswordRequest,
    StateChange,
    Unrecognized,
    parse_line,
    quote,
)

INFO = ">INFO:OpenVPN Management Interface Version 5"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            ">STATE:1695500000,CONNECTED,SUCCESS,10.8.0.2,203.0.113.7,1194,,\r\n",
            StateChange("CONNECTED", "SUCCESS", "10.8.0.2", "203.0.113.7"),
        ),
        (">STATE:1695500000,WAIT,,,,,,", StateChange("WAIT")),
        (">STATE:1695500000", StateChange("")),
        (">BYTECOUNT:1024,2048", ByteCount(1024, 2048)),
        (">BYTECOUNT:x,y", Unrecognized(">BYTECOUNT:x,y")),
        (">PASSWORD:Need 'Auth' username/password", PasswordRequest("Auth")),
        (">PASSWORD:Need 'Private Key' password", PasswordRequest("Private Key")),
        (">PASSWORD:Verification Failed: 'Auth'", PasswordFailure("Auth")),
        (">PASSWORD:something new", Unrecognized(">PASSWORD:something new")),
        (">HOLD:Waiting for hold release:0", HoldRequest()),
        (">FATAL:Cannot open TUN/TAP dev", Fatal("Cannot open TUN/TAP dev")),
        ("SUCCESS: hold release succeeded", CommandReply(True, "hold release succeeded")),
        ("ERROR: unknown command", CommandReply(False, "unknown command")),
        (INFO, Unrecognized(INFO)),
        ("END", Unrecognized("END")),
    ],
)
def test_parse_line(line: str, expected: Message) -> None:
    assert parse_line(line) == expected


def test_quote_escapes_backslashes_and_quotes() -> None:
    assert quote('a"b\\c') == '"a\\"b\\\\c"'
    assert quote("plain") == '"plain"'


@pytest.mark.parametrize("bad", ["a\nb", "a\rb", "a\x00b"])
def test_quote_rejects_line_breaks(bad: str) -> None:
    with pytest.raises(ValueError, match="line breaks"):
        quote(bad)


async def test_client_waits_for_the_socket_and_sends_commands(short_tmp: Path) -> None:
    path = short_tmp / "mgmt.sock"
    received: list[str] = []
    done = asyncio.Event()

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b">HOLD:Waiting for hold release:0\r\n")
        await writer.drain()
        while line := await reader.readline():
            received.append(line.decode().rstrip("\n"))
        writer.close()
        done.set()

    async def start_later() -> asyncio.Server:
        await asyncio.sleep(0.2)
        return await asyncio.start_unix_server(serve, path)

    server_task = asyncio.create_task(start_later())
    client = await ManagementClient.connect(path, timeout=5)
    assert await client.read() == HoldRequest()
    await client.send("hold release")
    await client.send_credentials("Auth", 'us"er', "pa\\ss")
    await client.close()
    await asyncio.wait_for(done.wait(), 5)
    server = await server_task
    server.close()
    await server.wait_closed()
    assert received == [
        "hold release",
        'username "Auth" "us\\"er"',
        'password "Auth" "pa\\\\ss"',
    ]


async def test_read_returns_none_at_eof(short_tmp: Path) -> None:
    path = short_tmp / "mgmt.sock"

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b">BYTECOUNT:1,2\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_unix_server(serve, path)
    client = await ManagementClient.connect(path)
    assert await client.read() == ByteCount(1, 2)
    assert await client.read() is None
    await client.close()
    server.close()
    await server.wait_closed()


async def test_connect_times_out(short_tmp: Path) -> None:
    with pytest.raises(TimeoutError):
        await ManagementClient.connect(short_tmp / "never.sock", timeout=0.2)
