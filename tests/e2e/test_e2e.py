# SPDX-License-Identifier: GPL-3.0-only
"""End to end: the real .deb under systemd, real OpenVPN, a fake NordVPN.

Run with `make e2e`. The tests share one stack and run in file order.
"""

from __future__ import annotations

import json
import os
import re
import time

import pytest
from e2e.stack import SOCKET, Stack

pytestmark = pytest.mark.e2e

LOGIN = ("login", "--username", "e2e-user", "--password-stdin")
SOAK_SECONDS = int(os.environ.get("E2E_SOAK_SECONDS", "120"))
RAW_CLIENT = (
    "import socket, sys\n"
    "s = socket.socket(socket.AF_UNIX)\n"
    f"s.connect({SOCKET!r})\n"
    "s.sendall(sys.argv[1].encode() + b'\\n')\n"
    "print(s.makefile().readline(), end='')\n"
)


def mode_owner(stack: Stack, path: str) -> str:
    return stack.exec("stat", "-c", "%a %U:%G", path).stdout.strip()


def link_gone(stack: Stack) -> bool:
    return stack.exec("ip", "link", "show", "nordtun", check=False).returncode != 0


def test_install_layout(stack: Stack) -> None:
    stack.exec("getent", "group", "nordvpn")
    stack.exec("systemctl", "is-active", "--quiet", "nordvpnd")
    assert mode_owner(stack, "/run/nordvpn") == "750 root:nordvpn"
    assert mode_owner(stack, SOCKET) == "660 root:nordvpn"
    assert mode_owner(stack, "/run/nordvpn/private").startswith("700 root:")
    assert mode_owner(stack, "/var/lib/nordvpn").startswith("700 root:")


def test_systemd_hardening_score(stack: Stack) -> None:
    out = stack.exec("systemd-analyze", "security", "--no-pager", "nordvpnd.service", check=False)
    match = re.search(r"Overall exposure level for nordvpnd\.service: (\d+\.\d+)", out.stdout)
    assert match, out.stdout
    assert float(match.group(1)) <= 4.0, out.stdout


def test_wrong_credentials_are_rejected(stack: Stack) -> None:
    assert stack.nordvpn(*LOGIN, input="wrong\n").returncode == 0
    result = stack.nordvpn("connect", "xx1")
    assert result.returncode == 4, result.stderr
    assert stack.status()["state"] == "DISCONNECTED"


def test_credentials_are_root_only(stack: Stack) -> None:
    assert stack.nordvpn(*LOGIN, input="e2e-pass\n").returncode == 0
    assert mode_owner(stack, "/var/lib/nordvpn/credentials").startswith("600 root:")
    cat = stack.exec("cat", "/var/lib/nordvpn/credentials", user="alice", check=False)
    assert cat.returncode != 0


@pytest.mark.parametrize(
    "target", [(), ("xx",), ("testland",), ("xx1",)], ids=["nearest", "code", "name", "host"]
)
def test_connect_targets(stack: Stack, target: tuple[str, ...]) -> None:
    status = stack.connect(*target)
    assert (status["state"], status["server"], status["country"]) == (
        "CONNECTED",
        "xx1",
        "Testland",
    )


def test_traffic_and_dns_go_through_the_tunnel(stack: Stack) -> None:
    stack.connect("xx1")
    stack.exec("ip", "link", "show", "nordtun")
    page = stack.exec("curl", "-fsS", "--max-time", "5", "http://10.8.0.1/").stdout
    assert "hello from inside the tunnel" in page
    assert "10.8.0.1" in stack.exec("resolvectl", "dns", "nordtun").stdout
    stack.wait_for(lambda: stack.status()["rx_bytes"] > 0, message="byte counters")
    assert stack.status()["dns"] == "applied"


def test_disconnect_removes_the_tunnel(stack: Stack) -> None:
    stack.connect("xx1")
    assert stack.nordvpn("disconnect").returncode == 0
    assert link_gone(stack)
    curl = stack.exec("curl", "-fsS", "--max-time", "3", "http://10.8.0.1/", check=False)
    assert curl.returncode != 0


def test_tcp(stack: Stack) -> None:
    assert stack.nordvpn("set", "protocol", "tcp").returncode == 0
    try:
        assert stack.connect("xx1")["protocol"] == "tcp"
        assert "hello" in stack.exec("curl", "-fsS", "--max-time", "5", "http://10.9.0.1/").stdout
    finally:
        stack.nordvpn("set", "protocol", "udp")
        stack.nordvpn("disconnect")


def test_outsiders_are_locked_out(stack: Stack) -> None:
    for args in (["status"], ["connect", "xx"], ["countries"], ["logout"]):
        result = stack.nordvpn(*args, user="mallory")
        assert result.returncode == 5, (args, result.stderr)
        assert "usermod -aG nordvpn" in result.stderr
    request = json.dumps({"v": 1, "id": 1, "cmd": "status"})
    raw = stack.exec("python3", "-c", RAW_CLIENT, request, user="mallory", check=False)
    assert "PermissionError" in raw.stderr


def test_privilege_escalation_regressions(stack: Stack) -> None:
    request = json.dumps({"v": 1, "id": 1, "cmd": "connect", "args": {"target": "/tmp/evil.ovpn"}})
    reply = json.loads(stack.exec("python3", "-c", RAW_CLIENT, request, user="alice").stdout)
    assert reply["error"]["code"] == "INVALID_TARGET"

    result = stack.nordvpn("connect", "xx666")
    assert result.returncode == 1, result.stderr
    assert "failed validation" in result.stderr
    assert stack.exec("test", "-e", "/var/lib/nordvpn/pwn-ran", check=False).returncode != 0
    journal = stack.exec("journalctl", "-u", "nordvpnd", "--no-pager").stdout
    assert "rejected the config NordVPN served for xx666" in journal
    assert "server=xx666" not in journal  # OpenVPN was never started for it


def test_openvpn_crash_is_detected(stack: Stack) -> None:
    stack.connect("xx1")
    stack.exec("pkill", "-KILL", "-x", "openvpn")
    stack.wait_for(lambda: stack.status()["state"] == "DISCONNECTED", message="crash detection")
    assert stack.status()["last_error"]["code"] == "TUNNEL_FAILED"
    stack.wait_for(lambda: link_gone(stack), message="nordtun to disappear")


def test_daemon_restart_while_connected(stack: Stack) -> None:
    stack.connect("xx1")
    stack.exec("systemctl", "restart", "nordvpnd")
    stack.wait_for_daemon()
    assert stack.status()["state"] == "DISCONNECTED"
    assert stack.exec("pgrep", "-x", "openvpn", check=False).returncode != 0
    assert link_gone(stack)


def test_long_session_stays_healthy(stack: Stack) -> None:
    # v1 stopped reading OpenVPN's stdout after connecting, so its pipe filled and the
    # tunnel froze. Keep traffic flowing for a while and make sure nothing stalls.
    stack.connect("xx1")
    deadline = time.monotonic() + SOAK_SECONDS
    while time.monotonic() < deadline:
        stack.exec("curl", "-fsS", "--max-time", "10", "-o", "/dev/null", "http://10.8.0.1/blob")
        time.sleep(1)
    status = stack.status()
    assert status["state"] == "CONNECTED"
    assert status["rx_bytes"] > 1024 * 1024
    stack.nordvpn("disconnect")


def test_package_removal(stack: Stack) -> None:  # keep this test last
    stack.exec("apt-get", "remove", "-y", "nordvpn-linux")
    assert stack.exec("systemctl", "is-active", "--quiet", "nordvpnd", check=False).returncode != 0
    assert stack.exec("test", "-e", "/usr/bin/nordvpn", check=False).returncode != 0
    stack.exec("getent", "group", "nordvpn")  # the group is kept, as is conventional
