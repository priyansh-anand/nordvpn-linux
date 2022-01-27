# SPDX-License-Identifier: GPL-3.0-only
"""The daemon's Unix-socket server: framing, peer authorization and dispatch.

A connection carries sequential requests. While a request runs, the server
watches the connection: if the client hangs up (for example on Ctrl-C), the
request is cancelled. Clients must not send anything else before the response.
"""

from __future__ import annotations

import asyncio
import contextlib
import grp
import logging
import os
import socket
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from nordvpn_linux.daemon.peercred import Authorizer, get_peer_uid
from nordvpn_linux.errors import ErrorCode, NordVPNError
from nordvpn_linux.protocol import (
    MAX_MESSAGE_BYTES,
    Event,
    JSONObject,
    Request,
    Response,
    decode_request,
    encode,
)

log = logging.getLogger(__name__)

EventSink = Callable[[str, str], None]  # (state, detail)


class Dispatcher(Protocol):
    async def handle(self, request: Request, emit: EventSink) -> JSONObject: ...


class Server:
    def __init__(
        self,
        *,
        path: Path,
        dispatcher: Dispatcher,
        authorizer: Authorizer,
        group: str | None = None,
        mode: int = 0o660,
        max_clients: int = 32,
        read_timeout: float = 10.0,
    ) -> None:
        self._path = path
        self._dispatcher = dispatcher
        self._authorizer = authorizer
        self._group = group
        self._mode = mode
        self._max_clients = max_clients
        self._read_timeout = read_timeout
        self._server: asyncio.Server | None = None
        self._connections: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        sock = self._bind()
        try:
            self._server = await asyncio.start_unix_server(
                self._on_connect, sock=sock, limit=MAX_MESSAGE_BYTES + 1
            )
        except BaseException:
            sock.close()
            raise
        log.info("listening on %s", self._path)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
        tasks = list(self._connections)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._server is not None:
            await self._server.wait_closed()
        self._path.unlink(missing_ok=True)

    def _bind(self) -> socket.socket:
        """Bind the socket with its final owner and mode before anyone can connect."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = self._path.lstat()
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISSOCK(existing.st_mode):
                raise RuntimeError(
                    f"{self._path} exists and is not a socket; refusing to remove it"
                )
            self._path.unlink()  # left behind by a previous run
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            old_umask = os.umask(0o177)  # created 0600; widened below once the group is right
            try:
                sock.bind(str(self._path))
            finally:
                os.umask(old_umask)
            if self._group is not None:
                gid = _group_id(self._group)
                if self._path.stat().st_gid != gid:
                    os.chown(self._path, -1, gid)
            self._path.chmod(self._mode)
        except BaseException:
            sock.close()
            raise
        return sock

    async def _on_connect(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._connections.add(task)
        try:
            await self._serve(reader, writer)
        except Exception:
            log.exception("unexpected error while serving a client")
        finally:
            if task is not None:
                self._connections.discard(task)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if len(self._connections) > self._max_clients:
            busy = Response.failure(0, ErrorCode.INTERNAL, "the daemon is busy; retry")
            await _reply(writer, busy)
            return
        uid = self._peer_uid(writer)
        if uid is None or not self._authorizer(uid):
            log.warning("refused a client with uid=%s", uid)
            await _reply(
                writer,
                Response.failure(
                    0, ErrorCode.PERMISSION_DENIED, "you are not allowed to control nordvpnd"
                ),
            )
            return
        while True:
            try:
                line = await asyncio.wait_for(reader.readline(), self._read_timeout)
            except TimeoutError:
                return
            except ValueError:  # the line is longer than the stream limit
                too_large = Response.failure(0, ErrorCode.BAD_REQUEST, "message too large")
                await _reply(writer, too_large)
                return
            except ConnectionError:
                return
            if not line:
                return
            try:
                if not line.endswith(b"\n"):
                    raise NordVPNError(ErrorCode.BAD_REQUEST, "incomplete message")
                request = decode_request(line)
            except NordVPNError as error:
                await _reply(writer, Response.failure(0, error.code, error.message))
                return
            log.info("uid=%s %s", uid, request.cmd.value)
            response = await self._dispatch(request, reader, writer)
            if response is None:
                log.info("uid=%s hung up during %s; cancelled it", uid, request.cmd.value)
                return
            await _reply(writer, response)

    async def _dispatch(
        self, request: Request, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> Response | None:
        """Run the request; return None if the client hung up and it was cancelled."""

        def emit(state: str, detail: str) -> None:
            if writer.is_closing():
                return
            with contextlib.suppress(OSError, RuntimeError, ValueError):
                writer.write(encode(Event(request.id, state, detail)))

        handler = asyncio.create_task(self._dispatcher.handle(request, emit))
        hangup = asyncio.create_task(reader.read(1))
        both: set[asyncio.Task[Any]] = {handler, hangup}
        try:
            await asyncio.wait(both, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (handler, hangup):
                if not task.done():
                    task.cancel()
            await asyncio.gather(handler, hangup, return_exceptions=True)
        if handler.cancelled():
            return None
        error = handler.exception()
        if error is None:
            return Response.success(request.id, handler.result())
        if isinstance(error, NordVPNError):
            return Response.failure(request.id, error.code, error.message)
        log.error("error while handling %s", request.cmd.value, exc_info=error)
        return Response.failure(
            request.id, ErrorCode.INTERNAL, "internal daemon error; see: journalctl -u nordvpnd"
        )

    def _peer_uid(self, writer: asyncio.StreamWriter) -> int | None:
        try:
            return get_peer_uid(writer.get_extra_info("socket"))
        except OSError:
            log.exception("could not read the peer's credentials")
            return None


def _group_id(group: str) -> int:
    try:
        return grp.getgrnam(group).gr_gid
    except KeyError:
        raise RuntimeError(
            f"group {group!r} does not exist; create it with: systemd-sysusers"
        ) from None


async def _reply(writer: asyncio.StreamWriter, response: Response) -> None:
    try:
        data = encode(response)
    except ValueError:
        data = encode(Response.failure(response.id, ErrorCode.INTERNAL, "response too large"))
    with contextlib.suppress(ConnectionError):
        writer.write(data)
        await writer.drain()
