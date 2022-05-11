# SPDX-License-Identifier: GPL-3.0-only
"""Blocking client for the daemon's Unix socket."""

from __future__ import annotations

import itertools
import socket
from collections.abc import Callable
from pathlib import Path

from nordvpn_linux.errors import ErrorCode, NordVPNError
from nordvpn_linux.paths import DEFAULT_SOCKET
from nordvpn_linux.protocol import (
    MAX_MESSAGE_BYTES,
    Command,
    Event,
    JSONObject,
    Request,
    decode_reply,
    encode,
)

DEFAULT_TIMEOUT = 15.0


class DaemonUnavailableError(Exception):
    """The daemon's socket is missing, refusing connections, or closed early."""


class Client:
    def __init__(self, socket_path: Path = DEFAULT_SOCKET) -> None:
        self._path = socket_path
        self._ids = itertools.count(1)

    def call(
        self,
        cmd: Command,
        args: JSONObject | None = None,
        *,
        on_event: Callable[[Event], None] | None = None,
        timeout: float | None = DEFAULT_TIMEOUT,
    ) -> JSONObject:
        """Send one request and return its result, passing progress events to *on_event*.

        ``timeout=None`` waits as long as the daemon takes; ``connect`` uses that,
        because the daemon enforces its own connection timeout.
        """
        request = Request(id=next(self._ids), cmd=cmd, args=args or {})
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            self._connect(sock)
            try:
                sock.sendall(encode(request))
                with sock.makefile("rb") as stream:
                    while line := stream.readline(MAX_MESSAGE_BYTES + 1):
                        reply = decode_reply(line)
                        if isinstance(reply, Event):
                            if on_event is not None:
                                on_event(reply)
                            continue
                        return reply.unwrap()
            except TimeoutError:
                raise NordVPNError(ErrorCode.TIMEOUT, "timed out waiting for the daemon") from None
            except (ConnectionResetError, BrokenPipeError) as exc:
                raise DaemonUnavailableError("the daemon closed the connection") from exc
        raise DaemonUnavailableError("the daemon closed the connection without answering")

    def _connect(self, sock: socket.socket) -> None:
        try:
            sock.connect(str(self._path))
        except PermissionError:
            raise NordVPNError(
                ErrorCode.PERMISSION_DENIED, f"permission denied opening {self._path}"
            ) from None
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            raise DaemonUnavailableError(f"{self._path}: {exc.strerror}") from None
