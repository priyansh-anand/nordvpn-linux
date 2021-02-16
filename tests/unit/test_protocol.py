# SPDX-License-Identifier: GPL-3.0-only
"""JSON-lines protocol codec."""

from __future__ import annotations

import json

import pytest

from nordvpn_linux.errors import ErrorCode, NordVPNError
from nordvpn_linux.protocol import (
    MAX_MESSAGE_BYTES,
    Command,
    Event,
    Request,
    Response,
    decode_reply,
    decode_request,
    encode,
)


def line(obj: object) -> bytes:
    return json.dumps(obj).encode() + b"\n"


def test_request_round_trip() -> None:
    request = Request(id=7, cmd=Command.CONNECT, args={"target": "us"})
    data = encode(request)
    assert data.endswith(b"\n")
    assert data.count(b"\n") == 1
    assert decode_request(data) == request


def test_success_and_failure_round_trip() -> None:
    ok = Response.success(3, {"state": "CONNECTED"})
    assert decode_reply(encode(ok)) == ok
    bad = Response.failure(3, ErrorCode.AUTH_FAILED, "nope")
    assert decode_reply(encode(bad)) == bad


def test_event_round_trip() -> None:
    event = Event(id=1, state="CONNECTING", detail="authenticating")
    assert decode_reply(encode(event)) == event


def test_unwrap_raises_error() -> None:
    with pytest.raises(NordVPNError) as excinfo:
        Response.failure(1, ErrorCode.NOT_LOGGED_IN, "log in first").unwrap()
    assert excinfo.value.code is ErrorCode.NOT_LOGGED_IN
    assert excinfo.value.message == "log in first"
    assert Response.success(1, {"a": 1}).unwrap() == {"a": 1}


def test_encode_rejects_oversized_message() -> None:
    with pytest.raises(ValueError, match="limit"):
        encode(Response.success(1, {"blob": "x" * MAX_MESSAGE_BYTES}))


def test_non_ascii_is_preserved() -> None:
    event = Event(id=1, state="CONNECTED", detail="Côte d'Ivoire")
    assert decode_reply(encode(event)) == event


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"not json\n", ErrorCode.BAD_REQUEST),
        (b"\xc3\x28\n", ErrorCode.BAD_REQUEST),
        (line([1, 2]), ErrorCode.BAD_REQUEST),
        (line({"v": 2, "id": 1, "cmd": "status"}), ErrorCode.UNSUPPORTED_VERSION),
        (line({"id": 1, "cmd": "status"}), ErrorCode.UNSUPPORTED_VERSION),
        (line({"v": 1, "id": True, "cmd": "status"}), ErrorCode.BAD_REQUEST),
        (line({"v": 1, "id": "1", "cmd": "status"}), ErrorCode.BAD_REQUEST),
        (line({"v": 1, "id": 1, "cmd": "rm -rf"}), ErrorCode.BAD_REQUEST),
        (line({"v": 1, "id": 1, "cmd": "status", "args": []}), ErrorCode.BAD_REQUEST),
        (b"{" + b" " * MAX_MESSAGE_BYTES + b"}\n", ErrorCode.BAD_REQUEST),
    ],
)
def test_decode_request_rejects(raw: bytes, code: ErrorCode) -> None:
    with pytest.raises(NordVPNError) as excinfo:
        decode_request(raw)
    assert excinfo.value.code is code


def test_decode_request_defaults_args() -> None:
    assert decode_request(line({"v": 1, "id": 1, "cmd": "status"})).args == {}


def test_decode_reply_maps_unknown_error_code_to_internal() -> None:
    reply = decode_reply(
        line({"v": 1, "id": 1, "ok": False, "error": {"code": "NEW_THING", "message": "x"}})
    )
    assert isinstance(reply, Response)
    assert reply.error_code is ErrorCode.INTERNAL


def test_decode_reply_rejects_garbage() -> None:
    with pytest.raises(NordVPNError):
        decode_reply(line({"v": 1, "id": 1}))
    with pytest.raises(NordVPNError):
        decode_reply(line({"v": 1, "id": 1, "ok": True, "result": [1]}))
    with pytest.raises(NordVPNError):
        decode_reply(line({"v": 1, "id": 1, "ok": False, "error": "boom"}))
