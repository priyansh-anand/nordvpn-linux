# SPDX-License-Identifier: GPL-3.0-only
"""The nordvpn command line, against a fake client."""

from __future__ import annotations

import builtins
import getpass
import io
import json
import sys
from collections.abc import Callable
from typing import Any

import pytest

from nordvpn_linux.__main__ import main as entry_point
from nordvpn_linux.cli import main as cli
from nordvpn_linux.cli.client import DaemonUnavailableError
from nordvpn_linux.errors import ErrorCode, NordVPNError
from nordvpn_linux.protocol import Command, Event, JSONObject

CONNECTED: JSONObject = {
    "state": "CONNECTED",
    "server": "us12941",
    "country": "United States",
    "protocol": "udp",
    "remote_ip": "203.0.113.7",
    "connected_since": None,
    "rx_bytes": 0,
    "tx_bytes": 0,
    "dns": "applied",
    "last_error": None,
}


class FakeClient:
    def __init__(
        self,
        replies: dict[Command, JSONObject | BaseException] | None = None,
        events: list[Event] | None = None,
    ) -> None:
        self.replies = replies or {}
        self.events = events or []
        self.calls: list[tuple[Command, JSONObject | None, float | None]] = []

    def call(
        self,
        cmd: Command,
        args: JSONObject | None = None,
        *,
        on_event: Callable[[Event], None] | None = None,
        timeout: float | None = 15.0,
    ) -> JSONObject:
        self.calls.append((cmd, args, timeout))
        for event in self.events:
            if on_event is not None:
                on_event(event)
        reply = self.replies.get(cmd, {})
        if isinstance(reply, BaseException):
            raise reply
        return reply


def install(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> FakeClient:
    monkeypatch.setattr(cli, "Client", lambda socket_path: client)
    return client


def test_connect(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    client = install(
        monkeypatch,
        FakeClient({Command.CONNECT: CONNECTED}, [Event(1, "CONNECTING", "authenticating")]),
    )
    assert cli.main(["c", "us"]) == 0
    assert capsys.readouterr().out == "Connected to us12941 (United States).\n"
    assert client.calls == [(Command.CONNECT, {"target": "us"}, None)]


def test_connect_nearest_sends_a_null_target(monkeypatch: pytest.MonkeyPatch) -> None:
    client = install(monkeypatch, FakeClient({Command.CONNECT: CONNECTED}))
    assert cli.main(["connect"]) == 0
    assert client.calls[0][1] == {"target": None}


@pytest.mark.parametrize(
    ("dns", "fragment"),
    [("unavailable", "systemd-resolved is not running"), ("failed", "may leak")],
)
def test_connect_warns_about_dns(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], dns: str, fragment: str
) -> None:
    install(monkeypatch, FakeClient({Command.CONNECT: CONNECTED | {"dns": dns}}))
    assert cli.main(["connect", "us"]) == 0
    assert fragment in capsys.readouterr().err


@pytest.mark.parametrize(
    ("code", "exit_code", "hint"),
    [
        (ErrorCode.PERMISSION_DENIED, 5, "usermod -aG nordvpn"),
        (ErrorCode.NOT_LOGGED_IN, 4, "nordvpn login"),
        (ErrorCode.AUTH_FAILED, 4, "service credentials"),
        (ErrorCode.INVALID_TARGET, 2, "nordvpn countries"),
        (ErrorCode.UNKNOWN_SERVER, 2, "nordvpn countries"),
        (ErrorCode.TUNNEL_FAILED, 1, "journalctl -u nordvpnd"),
        (ErrorCode.CANCELLED, 130, ""),
    ],
)
def test_errors_map_to_exit_codes_and_hints(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    code: ErrorCode,
    exit_code: int,
    hint: str,
) -> None:
    install(monkeypatch, FakeClient({Command.STATUS: NordVPNError(code, "it broke")}))
    assert cli.main(["status"]) == exit_code
    err = capsys.readouterr().err
    assert err.startswith("nordvpn: it broke\n")
    assert hint in err


def test_daemon_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, FakeClient({Command.STATUS: DaemonUnavailableError("no socket")}))
    assert cli.main(["status"]) == 3
    assert "systemctl status nordvpnd" in capsys.readouterr().err


def test_ctrl_c(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeClient({Command.CONNECT: KeyboardInterrupt()}))
    assert cli.main(["connect", "us"]) == 130


def test_login_non_interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    client = install(monkeypatch, FakeClient())
    monkeypatch.setattr(sys, "stdin", io.StringIO("s3cret\n"))
    assert cli.main(["login", "--username", "svc", "--password-stdin"]) == 0
    assert client.calls[0][:2] == (Command.LOGIN, {"username": "svc", "password": "s3cret"})


def test_login_interactive(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = install(monkeypatch, FakeClient())
    monkeypatch.setattr(builtins, "input", lambda prompt: " svc ")
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "pw")
    assert cli.main(["login"]) == 0
    assert client.calls[0][:2] == (Command.LOGIN, {"username": "svc", "password": "pw"})
    assert "service credentials" in capsys.readouterr().err


def test_password_stdin_requires_a_username(monkeypatch: pytest.MonkeyPatch) -> None:
    client = install(monkeypatch, FakeClient())
    assert cli.main(["login", "--password-stdin"]) == 2
    assert client.calls == []


def test_login_rejects_an_empty_password(monkeypatch: pytest.MonkeyPatch) -> None:
    client = install(monkeypatch, FakeClient())
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert cli.main(["login", "--username", "svc", "--password-stdin"]) == 2
    assert client.calls == []


def test_status_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    install(monkeypatch, FakeClient({Command.STATUS: CONNECTED}))
    assert cli.main(["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == CONNECTED


def test_status_human(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    install(monkeypatch, FakeClient({Command.STATUS: CONNECTED}))
    assert cli.main(["s"]) == 0
    assert "Server:     us12941 (United States)" in capsys.readouterr().out


def test_countries(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    countries = [{"code": "de", "name": "Germany"}, {"code": "us", "name": "United States"}]
    install(monkeypatch, FakeClient({Command.COUNTRIES: {"countries": countries}}))
    assert cli.main(["countries", "--plain"]) == 0
    assert capsys.readouterr().out == "de\nus\n"
    assert cli.main(["countries"]) == 0
    assert capsys.readouterr().out == "de  Germany\nus  United States\n"
    assert cli.main(["countries", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == countries


def test_settings(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    install(monkeypatch, FakeClient({Command.SETTINGS_GET: {"protocol": "tcp", "dns": False}}))
    assert cli.main(["settings"]) == 0
    assert capsys.readouterr().out == "Protocol:   TCP\nDNS:        off\n"


@pytest.mark.parametrize(
    ("argv", "key", "value"),
    [
        (["set", "dns", "off"], "dns", False),
        (["set", "dns", "on"], "dns", True),
        (["set", "protocol", "tcp"], "protocol", "tcp"),
    ],
)
def test_set(monkeypatch: pytest.MonkeyPatch, argv: list[str], key: str, value: Any) -> None:
    client = install(monkeypatch, FakeClient())
    assert cli.main(argv) == 0
    assert client.calls[0][:2] == (Command.SETTINGS_SET, {"key": key, "value": value})


@pytest.mark.parametrize(
    "argv",
    [[], ["bogus"], ["set"], ["set", "protocol", "icmp"], ["countries", "--json", "--plain"]],
)
def test_usage_errors_exit_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(argv)
    assert excinfo.value.code == 2


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--version"], "nordvpn 2.0.0"),
        (["cli", "--version"], "nordvpn 2.0.0"),
        (["daemon", "--version"], "nordvpnd 2.0.0"),
    ],
)
def test_entry_point_dispatch(
    capsys: pytest.CaptureFixture[str], argv: list[str], expected: str
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        entry_point(argv)
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == expected
