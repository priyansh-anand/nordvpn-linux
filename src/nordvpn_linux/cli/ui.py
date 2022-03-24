# SPDX-License-Identifier: GPL-3.0-only
"""Terminal output: colour, a spinner and human-readable status."""

from __future__ import annotations

import itertools
import os
import sys
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, TextIO

UNICODE_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
ASCII_FRAMES = "|/-\\"
LABEL_WIDTH = 12
_UNITS = ("B", "KiB", "MiB", "GiB", "TiB")


class Style:
    """ANSI colour, only on terminals and never when NO_COLOR is set (https://no-color.org)."""

    def __init__(self, stream: TextIO, env: Mapping[str, str] = os.environ) -> None:
        self.enabled = stream.isatty() and "NO_COLOR" not in env and env.get("TERM") != "dumb"

    def _paint(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._paint("1", text)

    def dim(self, text: str) -> str:
        return self._paint("2", text)

    def red(self, text: str) -> str:
        return self._paint("31", text)

    def green(self, text: str) -> str:
        return self._paint("32", text)

    def yellow(self, text: str) -> str:
        return self._paint("33", text)


class Spinner:
    """A one-line progress indicator on a terminal; silent when not writing to a TTY."""

    def __init__(self, text: str, stream: TextIO = sys.stderr, interval: float = 0.08) -> None:
        self._text = text
        self._stream = stream
        self._interval = interval
        self._enabled = stream.isatty()
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        self.frames = UNICODE_FRAMES if encoding.startswith("utf") else ASCII_FRAMES
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def update(self, text: str) -> None:
        with self._lock:
            self._text = text

    def __enter__(self) -> Spinner:
        if self._enabled:
            self._thread = threading.Thread(target=self._spin, name="spinner", daemon=True)
            self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._stream.write("\r\x1b[2K")
            self._stream.flush()

    def _spin(self) -> None:
        for frame in itertools.cycle(self.frames):
            with self._lock:
                text = self._text
            self._stream.write(f"\r\x1b[2K{frame} {text}")
            self._stream.flush()
            if self._stop.wait(self._interval):
                return


def format_bytes(n: int) -> str:
    value = float(n)
    for unit in _UNITS:
        if value < 1024 or unit == _UNITS[-1]:
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def render_status(status: Mapping[str, Any], style: Style, now: datetime | None = None) -> str:
    state = str(status.get("state", "UNKNOWN"))
    paint = {
        "CONNECTED": style.green,
        "CONNECTING": style.yellow,
        "RECONNECTING": style.yellow,
    }.get(state, style.dim)
    rows = [("Status", paint(state.capitalize()))]
    if state != "DISCONNECTED" and status.get("server"):
        server = str(status["server"])
        country = status.get("country")
        rows.append(("Server", f"{server} ({country})" if country else server))
        if status.get("protocol"):
            rows.append(("Protocol", str(status["protocol"]).upper()))
        if status.get("remote_ip"):
            rows.append(("Remote IP", str(status["remote_ip"])))
        if status.get("connected_since"):
            started = datetime.fromisoformat(str(status["connected_since"]))
            elapsed = ((now or datetime.now(UTC)) - started).total_seconds()
            rows.append(("Uptime", format_duration(elapsed)))
        rx = format_bytes(int(status.get("rx_bytes") or 0))
        tx = format_bytes(int(status.get("tx_bytes") or 0))
        rows.append(("Traffic", f"{rx} received, {tx} sent"))
        rows.append(("DNS", _describe_dns(str(status.get("dns", "")), style)))
    error = status.get("last_error")
    if state == "DISCONNECTED" and isinstance(error, Mapping):
        rows.append(("Last error", style.red(str(error.get("message", "")))))
    return _table(rows)


def render_countries(countries: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join(f"{c['code']:<4}{c['name']}" for c in countries)


def render_settings(settings: Mapping[str, Any]) -> str:
    return _table(
        [
            ("Protocol", str(settings.get("protocol", "")).upper()),
            ("DNS", "on" if settings.get("dns") else "off"),
        ]
    )


def _describe_dns(dns: str, style: Style) -> str:
    return {
        "applied": "NordVPN DNS (systemd-resolved)",
        "disabled": "system resolver (to change: nordvpn set dns on)",
        "unavailable": style.yellow("not protected: systemd-resolved is not running"),
        "failed": style.red("not protected: DNS setup failed and may leak"),
    }.get(dns, dns)


def _table(rows: Sequence[tuple[str, str]]) -> str:
    return "\n".join(f"{label + ':':<{LABEL_WIDTH}}{value}" for label, value in rows)
