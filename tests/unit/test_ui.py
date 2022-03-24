# SPDX-License-Identifier: GPL-3.0-only
"""Terminal rendering helpers."""

from __future__ import annotations

import io
import time
from datetime import UTC, datetime

import pytest

from nordvpn_linux.cli.ui import (
    ASCII_FRAMES,
    UNICODE_FRAMES,
    Spinner,
    Style,
    format_bytes,
    format_duration,
    render_countries,
    render_settings,
    render_status,
)

CONNECTED = {
    "state": "CONNECTED",
    "server": "us12941",
    "country": "United States",
    "protocol": "udp",
    "remote_ip": "203.0.113.7",
    "connected_since": "2026-09-24T10:00:00+00:00",
    "rx_bytes": 1536,
    "tx_bytes": 512,
    "dns": "applied",
    "last_error": None,
}


class FakeTerminal(io.TextIOWrapper):
    def isatty(self) -> bool:
        return True


def plain() -> Style:
    return Style(io.StringIO(), env={})


@pytest.mark.parametrize(
    ("n", "text"),
    [
        (0, "0 B"),
        (512, "512 B"),
        (1536, "1.5 KiB"),
        (5 * 1024**2, "5.0 MiB"),
        (3 * 1024**4, "3.0 TiB"),
    ],
)
def test_format_bytes(n: int, text: str) -> None:
    assert format_bytes(n) == text


@pytest.mark.parametrize(
    ("seconds", "text"), [(5, "5s"), (65, "1m 05s"), (3723, "1h 02m 03s"), (-3, "0s")]
)
def test_format_duration(seconds: float, text: str) -> None:
    assert format_duration(seconds) == text


def test_render_connected_status() -> None:
    now = datetime(2026, 9, 24, 11, 2, 3, tzinfo=UTC)
    assert render_status(CONNECTED, plain(), now=now).splitlines() == [
        "Status:     Connected",
        "Server:     us12941 (United States)",
        "Protocol:   UDP",
        "Remote IP:  203.0.113.7",
        "Uptime:     1h 02m 03s",
        "Traffic:    1.5 KiB received, 512 B sent",
        "DNS:        NordVPN DNS (systemd-resolved)",
    ]


def test_render_disconnected_status_with_error() -> None:
    status = {"state": "DISCONNECTED", "last_error": {"code": "TUNNEL_FAILED", "message": "boom"}}
    assert render_status(status, plain()) == "Status:     Disconnected\nLast error: boom"


@pytest.mark.parametrize(
    ("dns", "fragment"),
    [("unavailable", "not protected"), ("failed", "may leak"), ("disabled", "nordvpn set dns on")],
)
def test_render_dns_states(dns: str, fragment: str) -> None:
    assert fragment in render_status(CONNECTED | {"dns": dns}, plain())


def test_render_countries_and_settings() -> None:
    countries = [{"code": "de", "name": "Germany"}, {"code": "us", "name": "United States"}]
    assert render_countries(countries) == "de  Germany\nus  United States"
    assert render_settings({"protocol": "tcp", "dns": False}) == "Protocol:   TCP\nDNS:        off"


def test_style_only_colours_terminals_without_no_color() -> None:
    terminal = FakeTerminal(io.BytesIO(), encoding="utf-8")
    assert Style(terminal, env={}).enabled
    assert Style(terminal, env={}).green("x") == "\x1b[32mx\x1b[0m"
    assert not Style(terminal, env={"NO_COLOR": "1"}).enabled
    assert not Style(terminal, env={"TERM": "dumb"}).enabled
    assert not Style(io.StringIO(), env={}).enabled
    assert Style(io.StringIO(), env={}).green("x") == "x"


def test_spinner_is_silent_off_a_terminal() -> None:
    stream = io.StringIO()
    with Spinner("Connecting", stream=stream) as spinner:
        spinner.update("still connecting")
    assert stream.getvalue() == ""


def test_spinner_uses_ascii_frames_without_utf8() -> None:
    raw = io.BytesIO()
    terminal = FakeTerminal(raw, encoding="ascii")
    with Spinner("Connecting", stream=terminal, interval=0.01) as spinner:
        assert spinner.frames == ASCII_FRAMES
        time.sleep(0.05)
    terminal.flush()
    output = raw.getvalue().decode("ascii")
    assert "Connecting" in output
    assert output.endswith("\r\x1b[2K")


def test_spinner_uses_braille_frames_on_utf8() -> None:
    terminal = FakeTerminal(io.BytesIO(), encoding="utf-8")
    assert Spinner("x", stream=terminal).frames == UNICODE_FRAMES
