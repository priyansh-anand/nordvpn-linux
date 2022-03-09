# SPDX-License-Identifier: GPL-3.0-only
"""The whole daemon in-process: IPC -> service -> NordAPI (fake) -> tunnel (fake OpenVPN)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fakes import TCP_CONFIG_URL, eventually, launches, pid_alive
from fakes.daemon import LOGIN, Harness, running_daemon


def all_exited(h: Harness) -> bool:
    return all(not pid_alive(launch["pid"]) for launch in launches(h.log))


async def test_connect_status_disconnect(short_tmp: Path) -> None:
    async with running_daemon(short_tmp) as h:
        await h.result("login", LOGIN)
        events, reply = await h.call("connect", {"target": "us"})
        assert reply["ok"], reply
        status = reply["result"]
        assert status["state"] == "CONNECTED"
        assert status["server"] == "us12941"
        assert status["country"] == "United States"
        assert status["protocol"] == "udp"
        assert status["remote_ip"] == "203.0.113.7"
        assert status["dns"] == "applied"
        assert status["last_error"] is None
        details = [event["detail"] for event in events]
        assert details[0] == "finding a server"
        assert "authenticating" in details
        assert ["resolvectl", "dns", "nordtun", "103.86.96.100", "103.86.99.100"] in h.runner.calls
        assert (await h.result("status"))["state"] == "CONNECTED"

        status = await h.result("disconnect")
        assert status["state"] == "DISCONNECTED"
        assert ["resolvectl", "revert", "nordtun"] in h.runner.calls
        assert all_exited(h)


async def test_connect_requires_login(short_tmp: Path) -> None:
    async with running_daemon(short_tmp) as h:
        assert await h.error("connect", {"target": "us"}) == "NOT_LOGGED_IN"
        assert launches(h.log) == []


async def test_rejected_credentials(short_tmp: Path) -> None:
    async with running_daemon(short_tmp, openvpn_password="something-else") as h:
        await h.result("login", LOGIN)
        assert await h.error("connect", {"target": "us"}) == "AUTH_FAILED"
        status = await h.result("status")
        assert status["state"] == "DISCONNECTED"
        assert status["last_error"]["code"] == "AUTH_FAILED"


async def test_path_targets_never_reach_openvpn(short_tmp: Path) -> None:
    async with running_daemon(short_tmp) as h:
        await h.result("login", LOGIN)
        for target in ("/tmp/evil.ovpn", "../../etc/passwd", "us1 --up /x"):
            assert await h.error("connect", {"target": target}) == "INVALID_TARGET"
        assert launches(h.log) == []
        assert h.fetch.calls == []


async def test_unknown_server_never_reaches_openvpn(short_tmp: Path) -> None:
    async with running_daemon(short_tmp) as h:
        await h.result("login", LOGIN)
        assert await h.error("connect", {"target": "zz99999"}) == "UNKNOWN_SERVER"
        assert launches(h.log) == []


async def test_switching_servers_replaces_the_tunnel(short_tmp: Path) -> None:
    async with running_daemon(short_tmp) as h:
        await h.result("login", LOGIN)
        await h.result("connect", {"target": "us12941"})
        await h.result("connect", {"target": "us"})
        first, second = launches(h.log)
        assert not pid_alive(first["pid"])
        assert pid_alive(second["pid"])
        assert (await h.result("status"))["state"] == "CONNECTED"


async def test_failed_switch_keeps_the_working_tunnel(short_tmp: Path) -> None:
    async with running_daemon(short_tmp) as h:
        await h.result("login", LOGIN)
        await h.result("connect", {"target": "us12941"})
        assert await h.error("connect", {"target": "zz99999"}) == "UNKNOWN_SERVER"
        status = await h.result("status")
        assert (status["state"], status["server"]) == ("CONNECTED", "us12941")


async def test_nearest_disconnects_before_asking_for_a_server(short_tmp: Path) -> None:
    async with running_daemon(short_tmp) as h:
        await h.result("login", LOGIN)
        await h.result("connect", {"target": "us"})
        events, reply = await h.call("connect", {"target": None})
        assert reply["ok"], reply
        assert [(e["state"], e["detail"]) for e in events[:2]] == [
            ("DISCONNECTED", "disconnected"),
            ("CONNECTING", "finding a server"),
        ]


async def test_hangup_cancels_the_connection(short_tmp: Path) -> None:
    async with running_daemon(short_tmp, scenario="hang") as h:
        await h.result("login", LOGIN)
        reader, writer = await asyncio.open_unix_connection(h.paths.socket)
        request = {"v": 1, "id": 1, "cmd": "connect", "args": {"target": "us"}}
        writer.write(json.dumps(request).encode() + b"\n")
        await writer.drain()
        while True:  # wait until OpenVPN has actually been started
            event = json.loads(await asyncio.wait_for(reader.readline(), 5))
            if event["detail"].startswith("starting OpenVPN"):
                break
        writer.close()
        await eventually(lambda: h.service.status()["state"] == "DISCONNECTED")
        assert h.service.status()["last_error"]["code"] == "CANCELLED"
        await eventually(lambda: all_exited(h))


async def test_status_is_answered_while_connecting(short_tmp: Path) -> None:
    async with running_daemon(short_tmp, scenario="hang") as h:
        await h.result("login", LOGIN)
        pending = asyncio.create_task(h.call("connect", {"target": "us"}))
        await eventually(lambda: bool(launches(h.log)))
        assert (await h.result("status"))["state"] == "CONNECTING"
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


async def test_logout_disconnects_and_forgets_credentials(short_tmp: Path) -> None:
    async with running_daemon(short_tmp) as h:
        await h.result("login", LOGIN)
        await h.result("connect", {"target": "us"})
        await h.result("logout")
        assert (await h.result("status"))["state"] == "DISCONNECTED"
        assert not h.paths.credentials_file.exists()
        assert await h.error("connect", {"target": "us"}) == "NOT_LOGGED_IN"


async def test_tcp_setting_is_used_on_the_next_connection(short_tmp: Path) -> None:
    async with running_daemon(short_tmp) as h:
        await h.result("login", LOGIN)
        assert await h.result("settings.set", {"key": "protocol", "value": "tcp"}) == {
            "protocol": "tcp",
            "dns": True,
        }
        status = await h.result("connect", {"target": "us"})
        assert status["protocol"] == "tcp"
        assert TCP_CONFIG_URL in h.fetch.calls
        argv = launches(h.log)[-1]["argv"]
        assert argv[argv.index("--config") + 1].endswith("us12941.tcp.ovpn")


async def test_dns_can_be_disabled(short_tmp: Path) -> None:
    async with running_daemon(short_tmp) as h:
        await h.result("login", LOGIN)
        await h.result("settings.set", {"key": "dns", "value": False})
        assert (await h.result("settings.get"))["dns"] is False
        status = await h.result("connect", {"target": "us"})
        assert status["dns"] == "disabled"
        assert h.runner.calls == []


async def test_invalid_settings_and_login(short_tmp: Path) -> None:
    async with running_daemon(short_tmp) as h:
        assert await h.error("settings.set", {"key": "protocol", "value": "icmp"}) == "BAD_REQUEST"
        assert await h.error("login", {"username": "", "password": "x"}) == "BAD_REQUEST"


async def test_crash_shows_up_in_status(short_tmp: Path) -> None:
    async with running_daemon(short_tmp, scenario="crash_after_connect") as h:
        await h.result("login", LOGIN)
        await h.result("connect", {"target": "us"})
        await eventually(lambda: h.service.status()["state"] == "DISCONNECTED")
        status = await h.result("status")
        assert status["last_error"]["code"] == "TUNNEL_FAILED"
        assert status["dns"] == "disabled"


async def test_countries(short_tmp: Path) -> None:
    async with running_daemon(short_tmp) as h:
        countries = (await h.result("countries"))["countries"]
        assert countries[0] == {"code": "ba", "name": "Bosnia and Herzegovina"}
        assert {"code": "gb", "name": "United Kingdom"} in countries


async def test_unauthorized_client(short_tmp: Path) -> None:
    async with running_daemon(short_tmp, authorized=False) as h:
        assert await h.error("status") == "PERMISSION_DENIED"


async def test_shutdown_stops_the_tunnel(short_tmp: Path) -> None:
    async with running_daemon(short_tmp) as h:
        await h.result("login", LOGIN)
        await h.result("connect", {"target": "us"})
        (launch,) = launches(h.log)
    assert not pid_alive(launch["pid"])
    assert not h.paths.socket.exists()
