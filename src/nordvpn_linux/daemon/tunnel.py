# SPDX-License-Identifier: GPL-3.0-only
"""The OpenVPN child process and the state machine that tracks it.

OpenVPN is started with a fixed argv (no shell) and controlled only through its
management interface, which reports state changes, byte counts and password
prompts. OpenVPN's stdout and stderr are inherited, so its log goes to the journal
and no pipe can fill up and stall the tunnel.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

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
)
from nordvpn_linux.daemon.store import Credentials
from nordvpn_linux.errors import ErrorCode, NordVPNError

log = logging.getLogger(__name__)

DEVICE = "nordtun"
# NordVPN configs still say "cipher AES-256-CBC"; OpenVPN 2.6 negotiates from this list.
DATA_CIPHERS = "AES-256-GCM:AES-128-GCM:CHACHA20-POLY1305:AES-256-CBC"
STOP_GRACE_SECONDS = 5.0
BYTECOUNT_INTERVAL = 5

_PROGRESS = {
    "RESOLVE": "resolving the server address",
    "TCP_CONNECT": "opening a TCP connection",
    "WAIT": "waiting for the server",
    "AUTH": "authenticating",
    "GET_CONFIG": "receiving the configuration",
    "ASSIGN_IP": "assigning an IP address",
    "ADD_ROUTES": "adding routes",
}


class TunnelState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"


_UP = frozenset({TunnelState.CONNECTED, TunnelState.RECONNECTING})

Launcher = Callable[[list[str]], Awaitable[asyncio.subprocess.Process]]
StateListener = Callable[[TunnelState, str], None]


async def launch_openvpn(argv: list[str]) -> asyncio.subprocess.Process:
    """Start OpenVPN with no stdin; stdout/stderr are inherited (the journal)."""
    return await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.DEVNULL)


def build_argv(openvpn: str, config: Path, management_socket: Path) -> list[str]:
    """The complete OpenVPN command line.

    Options after ``--config`` override the file, so these always win over
    anything a downloaded config says.
    """
    # fmt: off
    return [
        openvpn,
        "--config", str(config),
        "--dev", DEVICE,
        "--dev-type", "tun",
        "--script-security", "1",
        "--auth-nocache",
        "--auth-retry", "none",
        "--data-ciphers", DATA_CIPHERS,
        "--management", str(management_socket), "unix",
        "--management-hold",
        "--management-query-passwords",
        "--suppress-timestamps",
        "--verb", "3",
    ]
    # fmt: on


@dataclass(frozen=True)
class TunnelInfo:
    state: TunnelState = TunnelState.DISCONNECTED
    server: str = ""
    country: str = ""
    protocol: str = ""
    remote_ip: str = ""
    connected_since: datetime | None = None
    rx_bytes: int = 0
    tx_bytes: int = 0
    last_error: NordVPNError | None = None


class Tunnel:
    """At most one OpenVPN tunnel. Callers must serialise connect() and stop()."""

    def __init__(
        self, *, openvpn: str, management_socket: Path, launcher: Launcher = launch_openvpn
    ) -> None:
        self._openvpn = openvpn
        self._management_socket = management_socket
        self._launcher = launcher
        self._info = TunnelInfo()
        self._listeners: list[StateListener] = []
        self._proc: asyncio.subprocess.Process | None = None
        self._mgmt: ManagementClient | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._credentials: Credentials | None = None
        self._outcome: asyncio.Future[None] | None = None
        self._stopping = False
        self._teardown_task: asyncio.Task[None] | None = None

    @property
    def state(self) -> TunnelState:
        return self._info.state

    @property
    def active(self) -> bool:
        return self._proc is not None or self._info.state is not TunnelState.DISCONNECTED

    def snapshot(self) -> TunnelInfo:
        return self._info

    def add_listener(self, listener: StateListener) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            with contextlib.suppress(ValueError):
                self._listeners.remove(listener)

        return remove

    async def connect(
        self,
        *,
        config: Path,
        server: str,
        country: str,
        protocol: str,
        credentials: Credentials,
        timeout: float,
    ) -> None:
        """Start OpenVPN and wait until the tunnel is up.

        On any failure, including timeout and cancellation, OpenVPN is stopped, the
        state returns to DISCONNECTED with ``last_error`` set, and the error is raised.
        """
        if self.active:
            raise RuntimeError("the tunnel is already active; stop() it first")
        self._info = TunnelInfo(server=server, country=country, protocol=protocol)
        self._credentials = credentials
        self._stopping = False
        outcome: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._outcome = outcome
        self._set_state(TunnelState.CONNECTING, f"starting OpenVPN for {server}")
        try:
            async with asyncio.timeout(timeout):
                await self._start(config, outcome)
                await outcome
        except TimeoutError:
            timed_out = NordVPNError(
                ErrorCode.TIMEOUT, f"no connection to {server} after {timeout:g}s"
            )
            await self._teardown(timed_out)
            raise timed_out from None
        except asyncio.CancelledError:
            await self._teardown(
                NordVPNError(ErrorCode.CANCELLED, "the connection attempt was cancelled")
            )
            raise
        except NordVPNError as error:
            await self._teardown(error)
            raise
        except OSError as exc:
            not_started = NordVPNError(ErrorCode.TUNNEL_FAILED, f"cannot start OpenVPN: {exc}")
            await self._teardown(not_started)
            raise not_started from exc

    async def stop(self) -> None:
        """Stop OpenVPN if it is running and return to DISCONNECTED.

        If a teardown is already under way (for example after OpenVPN reported a
        fatal error), this waits for it instead of starting another.
        """
        await self._teardown(None)

    async def _start(self, config: Path, outcome: asyncio.Future[None]) -> None:
        self._management_socket.unlink(missing_ok=True)  # left behind by a crash
        proc = await self._launcher(build_argv(self._openvpn, config, self._management_socket))
        self._proc = proc
        log.info("started openvpn pid=%s server=%s", proc.pid, self._info.server)
        self._spawn(self._watch(proc))

        connecting = asyncio.ensure_future(ManagementClient.connect(self._management_socket))
        waiters: set[asyncio.Future[Any]] = {connecting, outcome}
        try:
            done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        except BaseException:
            connecting.cancel()
            raise
        if connecting not in done:
            # OpenVPN failed (usually it exited) before opening its management socket.
            connecting.cancel()
            (late,) = await asyncio.gather(connecting, return_exceptions=True)
            if isinstance(late, ManagementClient):
                await late.close()
            await outcome
            raise NordVPNError(
                ErrorCode.TUNNEL_FAILED, "OpenVPN stopped before it could be controlled"
            )
        try:
            mgmt = connecting.result()
        except TimeoutError:
            raise NordVPNError(
                ErrorCode.TUNNEL_FAILED, "OpenVPN did not open its management socket"
            ) from None
        self._mgmt = mgmt
        self._spawn(self._read(mgmt))
        for command in ("state on", f"bytecount {BYTECOUNT_INTERVAL}", "hold release"):
            await mgmt.send(command)

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _watch(self, proc: asyncio.subprocess.Process) -> None:
        code = await proc.wait()
        if not self._stopping:
            log.warning("openvpn exited unexpectedly with code %s", code)
            self._failure(
                NordVPNError(ErrorCode.TUNNEL_FAILED, f"OpenVPN exited unexpectedly (code {code})")
            )

    async def _read(self, mgmt: ManagementClient) -> None:
        with contextlib.suppress(ConnectionError):
            while (message := await mgmt.read()) is not None:
                await self._handle(mgmt, message)

    async def _handle(self, mgmt: ManagementClient, message: Message) -> None:
        match message:
            case HoldRequest():
                await mgmt.send("hold release")
            case PasswordRequest(kind=kind) if self._credentials is not None:
                creds = self._credentials
                await mgmt.send_credentials(kind, creds.username, creds.password)
            case PasswordFailure():
                self._failure(
                    NordVPNError(ErrorCode.AUTH_FAILED, "NordVPN rejected the service credentials")
                )
            case Fatal(message=text):
                self._failure(NordVPNError(ErrorCode.TUNNEL_FAILED, f"OpenVPN error: {text}"))
            case StateChange():
                self._on_state(message)
            case ByteCount(rx=rx, tx=tx):
                self._info = replace(self._info, rx_bytes=rx, tx_bytes=tx)
            case CommandReply(ok=False, message=text):
                log.debug("openvpn rejected a management command: %s", text)
            case _:
                pass

    def _on_state(self, change: StateChange) -> None:
        if change.name == "CONNECTED":
            self._info = replace(
                self._info,
                remote_ip=change.remote_ip or self._info.remote_ip,
                connected_since=self._info.connected_since or datetime.now(UTC),
            )
            self._set_state(TunnelState.CONNECTED, f"connected to {self._info.server}")
            if self._outcome is not None and not self._outcome.done():
                self._outcome.set_result(None)
        elif change.name == "RECONNECTING" and self.state in _UP:
            self._set_state(TunnelState.RECONNECTING, change.description or "reconnecting")
        elif self.state is TunnelState.CONNECTING and change.name in _PROGRESS:
            self._set_state(TunnelState.CONNECTING, _PROGRESS[change.name])

    def _failure(self, error: NordVPNError) -> None:
        """Handle a failure OpenVPN reported: bad credentials, a fatal error or an exit."""
        if self._stopping:
            return
        if self._outcome is not None and not self._outcome.done():
            self._outcome.set_exception(error)  # connect() is waiting and will clean up
        elif self.state in _UP and self._teardown_task is None:
            self._stopping = True
            # Nobody is waiting on this tunnel: tear it down in the background.
            self._teardown_task = asyncio.create_task(self._run_teardown(error))

    async def _teardown(self, error: NordVPNError | None) -> None:
        """Stop OpenVPN and settle the state, even if the caller is cancelled meanwhile.

        The work runs in its own task and callers await it through a shield, so
        a cancelled caller (a client pressing Ctrl-C) cannot leave the tunnel
        half torn down with a state that claims it is still connected.
        """
        if self._teardown_task is None:
            if not self.active:
                return
            self._teardown_task = asyncio.create_task(self._run_teardown(error))
        await asyncio.shield(self._teardown_task)

    async def _run_teardown(self, error: NordVPNError | None) -> None:
        try:
            if error is not None:
                log.warning("tunnel failed: %s", error.message)
            await self._cleanup()
            if error is None:
                self._info = TunnelInfo()
                self._emit(TunnelState.DISCONNECTED, "disconnected")
            else:
                self._info = replace(self._info, state=TunnelState.FAILED, last_error=error)
                self._emit(TunnelState.FAILED, error.message)
                self._info = TunnelInfo(last_error=error)
                self._emit(TunnelState.DISCONNECTED, error.message)
        finally:
            self._teardown_task = None

    async def _cleanup(self) -> None:
        self._stopping = True
        proc, mgmt = self._proc, self._mgmt
        self._proc = None
        self._mgmt = None
        self._credentials = None
        if self._outcome is not None and not self._outcome.done():
            self._outcome.cancel()
        self._outcome = None
        if proc is not None and proc.returncode is None:
            await _terminate(proc, mgmt)
        tasks = list(self._tasks)  # the process watcher and management reader
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if mgmt is not None:
            await mgmt.close()
        self._management_socket.unlink(missing_ok=True)

    def _set_state(self, state: TunnelState, detail: str) -> None:
        self._info = replace(self._info, state=state)
        self._emit(state, detail)

    def _emit(self, state: TunnelState, detail: str) -> None:
        for listener in list(self._listeners):
            try:
                listener(state, detail)
            except Exception:
                log.exception("tunnel state listener failed")


async def _terminate(proc: asyncio.subprocess.Process, mgmt: ManagementClient | None) -> None:
    """Ask OpenVPN to exit cleanly; kill it if it is still running after the grace period."""
    asked = False
    if mgmt is not None:
        with contextlib.suppress(OSError):
            await mgmt.send("signal SIGTERM")
            asked = True
    if not asked:
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), STOP_GRACE_SECONDS)
    except TimeoutError:
        log.warning("openvpn did not exit within %gs; killing it", STOP_GRACE_SECONDS)
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
