# SPDX-License-Identifier: GPL-3.0-only
"""The .ovpn allowlist: real NordVPN configs pass, anything that can run code fails."""

from __future__ import annotations

from pathlib import Path

import pytest

from nordvpn_linux.daemon.ovpn import InvalidConfigError, validate_config

OVPN = Path(__file__).parents[1] / "fixtures" / "ovpn"
REAL_UDP = (OVPN / "us12941.udp.ovpn").read_text()
REAL_TCP = (OVPN / "us12941.tcp.ovpn").read_text()


@pytest.mark.parametrize("text", [REAL_UDP, REAL_TCP])
def test_real_nordvpn_configs_pass(text: str) -> None:
    assert validate_config(text, "us12941") == text


def test_crlf_and_comments_are_fine() -> None:
    text = "# comment\r\n; another\r\n\r\n" + REAL_UDP.replace("\n", "\r\n")
    assert validate_config(text, "us12941") == text


def test_config_for_a_different_server_is_rejected() -> None:
    with pytest.raises(InvalidConfigError, match="verify-x509-name"):
        validate_config(REAL_UDP, "us1")


@pytest.mark.parametrize(
    "line",
    [
        "up /tmp/x.sh",
        "down /tmp/x.sh",
        "route-up /tmp/x.sh",
        "ipchange /tmp/x.sh",
        "tls-verify /tmp/x.sh",
        "auth-user-pass-verify /tmp/x.sh via-env",
        "plugin /tmp/x.so",
        "script-security 2",
        "setenv FOO bar",
        "config /etc/other.conf",
        "log /etc/passwd",
        "status /etc/passwd",
        "writepid /etc/passwd",
        "management 0.0.0.0 7505",
        "auth-user-pass /etc/shadow",
        "--up /tmp/x.sh",
        "UP /tmp/x.sh",
        "dev tap",
        "remote evil.example.com 1194",
        "remote 1.2.3.4 99999",
        "remote 1.2.3.4 1194 icmp",
        "remote 1.2.3.4 1194 udp extra",
        "remote",
        "verify-x509-name CN=evil.example.com",
        "totally-new-directive 1",
        "<connection>",
    ],
)
def test_dangerous_or_unknown_lines_are_rejected(line: str) -> None:
    # Guard: if the fixture lost its final newline, the line would glue onto "</tls-auth>"
    # and the test would pass for the wrong reason.
    assert REAL_UDP.endswith("\n")
    with pytest.raises(InvalidConfigError):
        validate_config(REAL_UDP + line + "\n", "us12941")


def test_error_reports_line_number() -> None:
    text = "client\nremote 1.2.3.4 1194\nup /tmp/x.sh\n"
    with pytest.raises(InvalidConfigError) as excinfo:
        validate_config(text, "us1")
    assert excinfo.value.line_no == 3
    assert "'up'" in str(excinfo.value)


def test_unterminated_block_is_rejected() -> None:
    with pytest.raises(InvalidConfigError, match="unterminated"):
        validate_config("client\nremote 1.2.3.4 1194\n<ca>\nAAAA\n", "us1")


def test_tag_inside_block_is_rejected() -> None:
    with pytest.raises(InvalidConfigError, match="inside"):
        validate_config("client\nremote 1.2.3.4\n<ca>\n<connection>\n</ca>\n", "us1")


def test_config_without_remote_is_rejected() -> None:
    with pytest.raises(InvalidConfigError, match="remote"):
        validate_config("client\ndev tun\n", "us1")


def test_nul_byte_is_rejected() -> None:
    with pytest.raises(InvalidConfigError, match="NUL"):
        validate_config("client\nremote 1.2.3.4 1194\x00\n", "us1")


def test_remote_by_hostname_is_allowed() -> None:
    text = "client\nremote us1.nordvpn.com 443 tcp\n"
    assert validate_config(text, "us1") == text
