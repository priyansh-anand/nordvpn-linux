# SPDX-License-Identifier: GPL-3.0-only
"""Tunnel state machine, driven by a fake OpenVPN over a real management socket."""

from __future__ import annotations

import asyncio
import socket
import time
from pathlib import Path

import pytest
from fakes import eventually, fake_launcher, launches, pid_alive

from nordvpn_linux.daemon.store import Credentials
from nordvpn_linux.daemon.tunnel import Tunnel, TunnelState, build_argv
from nordvpn_linux.errors import ErrorCode, NordVPNError

CREDS = Credentials("user", "secret")
Events = list[tuple[TunnelState, str]]


def make_tunnel(
    root: Path, scenario: str = "ok", *, user: str = "user", password: str = "secret"
) -> tuple[Tunnel, Path, Events]:
    log = root / "launches.jsonl"
    tunnel = Tunnel(
        openvpn="/usr/sbin/openvpn",
        management_socket=root / "mgmt.sock",
        launcher=fake_launcher(scenario, log=log, user=user, password=password),
    )
    events: Events = []
    tunnel.add_listener(lambda state, detail: events.append((state, detail)))
    return tunnel, log, events


async def connect(
    tunnel: Tunnel, root: Path, *, timeout: float = 5.0, credentials: Credentials = CREDS
) -> None:
    await tunnel.connect(
        config=root / "us1.udp.ovpn",
        server="us1",
        country="United States",
        protocol="udp",
        credentials=credentials,
        timeout=timeout,
    )


async def expect_failure(
    tunnel: Tunnel, root: Path, code: ErrorCode, *, timeout: float = 5.0
) -> str:
    with pytest.raises(NordVPNError) as excinfo:
        await connect(tunnel, root, timeout=timeout)
    assert excinfo.value.code is code
    assert tunnel.state is TunnelState.DISCONNECTED
    assert not tunnel.active
    last_error = tunnel.snapshot().last_error
    assert last_error is not None
    assert last_error.code is code
    return excinfo.value.message


def all_exited(log: Path) -> bool:
    return all(not pid_alive(launch["pid"]) for launch in launches(log))


def test_argv_is_fixed_and_overrides_the_config() -> None:
    argv = build_argv("/usr/sbin/openvpn", Path("/c/us1.ovpn"), Path("/run/m.sock"))
    assert argv[:3] == ["/usr/sbin/openvpn", "--config", "/c/us1.ovpn"]
    joined = " ".join(argv)
    for option in (
        "--script-security 1",
        "--dev nordtun",
        "--dev-type tun",
        "--auth-nocache",
        "--auth-retry none",
        "--management /run/m.sock unix",
        "--management-hold",
        "--management-query-passwords",
    ):
        assert option in joined
    assert argv.index("--script-security") > argv.index("--config")


async def test_connect_and_stop(short_tmp: Path) -> None:
    tunnel, log, events = make_tunnel(short_tmp)
    await connect(tunnel, short_tmp)
    info = tunnel.snapshot()
    assert info.state is TunnelState.CONNECTED
    assert (info.server, info.country, info.protocol) == ("us1", "United States", "udp")
    assert info.remote_ip == "203.0.113.7"
    assert info.connected_since is not None
    assert events[0][0] is TunnelState.CONNECTING
    assert (TunnelState.CONNECTING, "authenticating") in events
    assert events[-1] == (TunnelState.CONNECTED, "connected to us1")
    (launch,) = launches(log)
    argv = launch["argv"]
    assert argv[argv.index("--management") + 1] == str(short_tmp / "mgmt.sock")
    await eventually(lambda: tunnel.snapshot().rx_bytes == 1024)
    assert tunnel.snapshot().tx_bytes == 2048

    await tunnel.stop()
    assert tunnel.state is TunnelState.DISCONNECTED
    assert tunnel.snapshot().last_error is None
    assert not tunnel.active
    assert not pid_alive(launch["pid"])
    assert not (short_tmp / "mgmt.sock").exists()
    assert events[-1] == (TunnelState.DISCONNECTED, "disconnected")


async def test_credentials_are_quoted_safely(short_tmp: Path) -> None:
    tunnel, _, _ = make_tunnel(short_tmp, user='us"er', password="pa\\ss word")
    await connect(tunnel, short_tmp, credentials=Credentials('us"er', "pa\\ss word"))
    assert tunnel.state is TunnelState.CONNECTED
    await tunnel.stop()


async def test_rejected_credentials(short_tmp: Path) -> None:
    tunnel, log, events = make_tunnel(short_tmp, password="something-else")
    await expect_failure(tunnel, short_tmp, ErrorCode.AUTH_FAILED)
    assert [state for state, _ in events][-2:] == [TunnelState.FAILED, TunnelState.DISCONNECTED]
    await eventually(lambda: all_exited(log))


async def test_auth_fail_scenario(short_tmp: Path) -> None:
    tunnel, _, _ = make_tunnel(short_tmp, "auth_fail")
    await expect_failure(tunnel, short_tmp, ErrorCode.AUTH_FAILED)


async def test_timeout_kills_openvpn(short_tmp: Path) -> None:
    tunnel, log, _ = make_tunnel(short_tmp, "hang")
    await expect_failure(tunnel, short_tmp, ErrorCode.TIMEOUT, timeout=1.0)
    assert all_exited(log)


async def test_fatal_error(short_tmp: Path) -> None:
    tunnel, _, _ = make_tunnel(short_tmp, "fatal")
    message = await expect_failure(tunnel, short_tmp, ErrorCode.TUNNEL_FAILED)
    assert "Cannot open TUN/TAP" in message


async def test_early_exit_is_reported_promptly(short_tmp: Path) -> None:
    tunnel, _, _ = make_tunnel(short_tmp, "exit_early")
    started = time.monotonic()
    message = await expect_failure(tunnel, short_tmp, ErrorCode.TUNNEL_FAILED, timeout=10.0)
    assert "exited" in message
    assert time.monotonic() - started < 3


async def test_crash_after_connect_is_detected(short_tmp: Path) -> None:
    tunnel, log, events = make_tunnel(short_tmp, "crash_after_connect")
    await connect(tunnel, short_tmp)
    await eventually(lambda: tunnel.state is TunnelState.DISCONNECTED)
    last_error = tunnel.snapshot().last_error
    assert last_error is not None
    assert last_error.code is ErrorCode.TUNNEL_FAILED
    assert TunnelState.FAILED in [state for state, _ in events]
    assert not tunnel.active
    assert all_exited(log)


async def test_reconnect_events(short_tmp: Path) -> None:
    tunnel, _, events = make_tunnel(short_tmp, "reconnect")
    await connect(tunnel, short_tmp)
    await eventually(lambda: TunnelState.RECONNECTING in [s for s, _ in events])
    await eventually(lambda: events[-1][0] is TunnelState.CONNECTED)
    assert tunnel.state is TunnelState.CONNECTED
    await tunnel.stop()


async def test_cancel_mid_connect(short_tmp: Path) -> None:
    tunnel, log, _ = make_tunnel(short_tmp, "hang")
    task = asyncio.create_task(connect(tunnel, short_tmp, timeout=10.0))
    await eventually(lambda: bool(launches(log)))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    last_error = tunnel.snapshot().last_error
    assert last_error is not None
    assert last_error.code is ErrorCode.CANCELLED
    assert tunnel.state is TunnelState.DISCONNECTED
    await eventually(lambda: all_exited(log))


async def test_connect_while_active_is_a_bug(short_tmp: Path) -> None:
    tunnel, _, _ = make_tunnel(short_tmp)
    await connect(tunnel, short_tmp)
    with pytest.raises(RuntimeError):
        await connect(tunnel, short_tmp)
    await tunnel.stop()


async def test_missing_openvpn_binary(short_tmp: Path) -> None:
    async def missing(argv: list[str]) -> asyncio.subprocess.Process:
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    tunnel = Tunnel(
        openvpn="/nope/openvpn", management_socket=short_tmp / "m.sock", launcher=missing
    )
    message = await expect_failure(tunnel, short_tmp, ErrorCode.TUNNEL_FAILED)
    assert "cannot start OpenVPN" in message


async def test_stale_management_socket_is_removed(short_tmp: Path) -> None:
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(short_tmp / "mgmt.sock"))
    stale.close()  # the file stays behind, as after a crash
    tunnel, _, _ = make_tunnel(short_tmp)
    await connect(tunnel, short_tmp)
    assert tunnel.state is TunnelState.CONNECTED
    await tunnel.stop()


async def test_stop_when_idle_is_a_no_op(short_tmp: Path) -> None:
    tunnel, _, events = make_tunnel(short_tmp)
    await tunnel.stop()
    assert events == []


async def test_a_broken_listener_does_not_break_the_tunnel(short_tmp: Path) -> None:
    tunnel, _, _ = make_tunnel(short_tmp)

    def broken(state: TunnelState, detail: str) -> None:
        raise RuntimeError("listener bug")

    remove = tunnel.add_listener(broken)
    await connect(tunnel, short_tmp)
    remove()
    remove()  # removing twice is harmless
    assert tunnel.state is TunnelState.CONNECTED
    await tunnel.stop()
