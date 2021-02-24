# SPDX-License-Identifier: GPL-3.0-only
"""Wire protocol between ``nordvpn`` and ``nordvpnd``: newline-delimited JSON.

Every message is one UTF-8 JSON object on one line. A client sends a Request; the
daemon answers with zero or more Events followed by exactly one Response.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from nordvpn_linux.errors import ErrorCode, NordVPNError

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 64 * 1024

JSONObject = dict[str, Any]


class Command(StrEnum):
    STATUS = "status"
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    LOGIN = "login"
    LOGOUT = "logout"
    COUNTRIES = "countries"
    SETTINGS_GET = "settings.get"
    SETTINGS_SET = "settings.set"


@dataclass(frozen=True)
class Request:
    id: int
    cmd: Command
    args: JSONObject = field(default_factory=dict)


@dataclass(frozen=True)
class Response:
    id: int
    ok: bool
    result: JSONObject | None = None
    error_code: ErrorCode | None = None
    error_message: str = ""

    @classmethod
    def success(cls, request_id: int, result: JSONObject) -> Response:
        return cls(id=request_id, ok=True, result=result)

    @classmethod
    def failure(cls, request_id: int, code: ErrorCode, message: str) -> Response:
        return cls(id=request_id, ok=False, error_code=code, error_message=message)

    def unwrap(self) -> JSONObject:
        """Return the result, or raise the error as a NordVPNError."""
        if self.ok:
            return self.result or {}
        raise NordVPNError(self.error_code or ErrorCode.INTERNAL, self.error_message)


@dataclass(frozen=True)
class Event:
    """A progress notification sent while a request (``connect``) is running."""

    id: int
    state: str
    detail: str = ""


def encode(message: Request | Response | Event) -> bytes:
    """Serialise one message as a single line, enforcing the size limit."""
    payload: JSONObject = {"v": PROTOCOL_VERSION, "id": message.id}
    if isinstance(message, Request):
        payload |= {"cmd": message.cmd.value, "args": message.args}
    elif isinstance(message, Event):
        payload |= {"event": "state", "state": message.state, "detail": message.detail}
    elif message.ok:
        payload |= {"ok": True, "result": message.result or {}}
    else:
        code = message.error_code or ErrorCode.INTERNAL
        payload |= {"ok": False, "error": {"code": code.value, "message": message.error_message}}
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
    if len(data) > MAX_MESSAGE_BYTES:
        raise ValueError(f"message is {len(data)} bytes; the limit is {MAX_MESSAGE_BYTES}")
    return data


def _bad(message: str) -> NordVPNError:
    return NordVPNError(ErrorCode.BAD_REQUEST, message)


def _load(line: bytes) -> JSONObject:
    if len(line) > MAX_MESSAGE_BYTES:
        raise _bad("message too large")
    try:
        obj = json.loads(line)
    except ValueError as exc:
        raise _bad("message is not valid UTF-8 JSON") from exc
    if not isinstance(obj, dict):
        raise _bad("message must be a JSON object")
    version = obj.get("v")
    if version != PROTOCOL_VERSION:
        raise NordVPNError(
            ErrorCode.UNSUPPORTED_VERSION,
            f"protocol version {version!r} is not supported (expected {PROTOCOL_VERSION})",
        )
    return obj


def _message_id(obj: JSONObject) -> int:
    value = obj.get("id")
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad("'id' must be an integer")
    return value


def decode_request(line: bytes) -> Request:
    obj = _load(line)
    request_id = _message_id(obj)
    try:
        cmd = Command(obj.get("cmd", ""))
    except ValueError:
        raise _bad(f"unknown command {obj.get('cmd')!r}") from None
    args = obj.get("args", {})
    if not isinstance(args, dict):
        raise _bad("'args' must be an object")
    return Request(id=request_id, cmd=cmd, args=args)


def decode_reply(line: bytes) -> Response | Event:
    obj = _load(line)
    reply_id = _message_id(obj)
    if obj.get("event") == "state":
        return Event(
            id=reply_id, state=str(obj.get("state", "")), detail=str(obj.get("detail", ""))
        )
    if obj.get("ok") is True:
        result = obj.get("result", {})
        if not isinstance(result, dict):
            raise _bad("'result' must be an object")
        return Response.success(reply_id, result)
    if obj.get("ok") is False:
        error = obj.get("error")
        if not isinstance(error, dict):
            raise _bad("'error' must be an object")
        try:
            code = ErrorCode(error.get("code", ""))
        except ValueError:
            code = ErrorCode.INTERNAL
        return Response.failure(reply_id, code, str(error.get("message", "")))
    raise _bad("reply is neither an event nor a response")
