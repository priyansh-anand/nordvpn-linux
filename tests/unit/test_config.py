# SPDX-License-Identifier: GPL-3.0-only
"""nordvpnd.toml loading and validation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from nordvpn_linux.daemon.config import ConfigError, DaemonConfig, load_config, parse_config


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path / "absent.toml") == DaemonConfig()


def test_full_file(tmp_path: Path) -> None:
    path = tmp_path / "nordvpnd.toml"
    path.write_text(
        'log_level = "DEBUG"\n'
        "connect_timeout = 45\n"
        'api_base = "https://api.example.test/"\n'
        'configs_base = "https://cdn.example.test"\n'
        'dns_servers = ["10.8.0.1", "2001:db8::1"]\n'
        'openvpn = "/opt/openvpn/sbin/openvpn"\n'
    )
    config = load_config(path)
    assert config == DaemonConfig(
        log_level="debug",
        connect_timeout=45.0,
        api_base="https://api.example.test",
        configs_base="https://cdn.example.test",
        dns_servers=("10.8.0.1", "2001:db8::1"),
        openvpn="/opt/openvpn/sbin/openvpn",
    )
    assert isinstance(config.connect_timeout, float)


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        ({"colour": "red"}, "unknown option"),
        ({"log_level": "loud"}, "log_level"),
        ({"log_level": 3}, "log_level"),
        ({"connect_timeout": 0}, "connect_timeout"),
        ({"connect_timeout": 301}, "connect_timeout"),
        ({"connect_timeout": True}, "connect_timeout"),
        ({"connect_timeout": "30"}, "connect_timeout"),
        ({"api_base": "http://api.nordvpn.com"}, "api_base"),
        ({"api_base": "https://api.nordvpn.com?x=1"}, "api_base"),
        ({"configs_base": "https://"}, "configs_base"),
        ({"configs_base": 5}, "configs_base"),
        ({"dns_servers": []}, "dns_servers"),
        ({"dns_servers": ["1.1.1.1"] * 5}, "dns_servers"),
        ({"dns_servers": "1.1.1.1"}, "dns_servers"),
        ({"dns_servers": ["dns.google"]}, "not an IP address"),
        ({"dns_servers": [1]}, "dns_servers"),
        ({"openvpn": "openvpn"}, "absolute path"),
    ],
)
def test_invalid_values(data: dict[str, Any], fragment: str) -> None:
    with pytest.raises(ConfigError, match=fragment):
        parse_config(data)


def test_toml_syntax_error_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "nordvpnd.toml"
    path.write_text("log_level = [\n")
    with pytest.raises(ConfigError, match=re.escape(str(path))):
        load_config(path)


def test_validation_error_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "nordvpnd.toml"
    path.write_text('api_base = "http://plain.example"\n')
    with pytest.raises(ConfigError, match=re.escape(str(path)) + ".*api_base"):
        load_config(path)
