# SPDX-License-Identifier: GPL-3.0-only
"""Loading and validation of ``/etc/nordvpn/nordvpnd.toml``.

The file is root-owned, and it is the only place the API endpoints can be changed:
clients never influence where the daemon downloads configs from.
"""

from __future__ import annotations

import ipaddress
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

LOG_LEVELS = ("debug", "info", "warning", "error")
MAX_DNS_SERVERS = 4
MIN_TIMEOUT, MAX_TIMEOUT = 1, 300


class ConfigError(Exception):
    """The daemon configuration is unreadable or invalid."""


@dataclass(frozen=True)
class DaemonConfig:
    log_level: str = "info"
    connect_timeout: float = 30.0
    api_base: str = "https://api.nordvpn.com"
    configs_base: str = "https://downloads.nordcdn.com"
    dns_servers: tuple[str, ...] = ("103.86.96.100", "103.86.99.100")
    openvpn: str = "/usr/sbin/openvpn"


def load_config(path: Path) -> DaemonConfig:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return DaemonConfig()
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{path}: {exc.strerror}") from exc
    try:
        return parse_config(data)
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def parse_config(data: dict[str, Any]) -> DaemonConfig:
    known = {f.name for f in fields(DaemonConfig)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ConfigError(f"unknown option(s): {', '.join(unknown)}")
    defaults = DaemonConfig()
    return DaemonConfig(
        log_level=_log_level(data.get("log_level", defaults.log_level)),
        connect_timeout=_timeout(data.get("connect_timeout", defaults.connect_timeout)),
        api_base=_https_url("api_base", data.get("api_base", defaults.api_base)),
        configs_base=_https_url("configs_base", data.get("configs_base", defaults.configs_base)),
        dns_servers=_dns_servers(data.get("dns_servers", list(defaults.dns_servers))),
        openvpn=_absolute_path("openvpn", data.get("openvpn", defaults.openvpn)),
    )


def _log_level(value: object) -> str:
    if not isinstance(value, str) or value.lower() not in LOG_LEVELS:
        raise ConfigError(f"log_level must be one of: {', '.join(LOG_LEVELS)}")
    return value.lower()


def _timeout(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not MIN_TIMEOUT <= value <= MAX_TIMEOUT
    ):
        raise ConfigError(
            f"connect_timeout must be a number of seconds between {MIN_TIMEOUT} and {MAX_TIMEOUT}"
        )
    return float(value)


def _https_url(name: str, value: object) -> str:
    if isinstance(value, str):
        parts = urlsplit(value)
        if parts.scheme == "https" and parts.hostname and not parts.query and not parts.fragment:
            return value.rstrip("/")
    raise ConfigError(f"{name} must be an https:// URL without a query string")


def _dns_servers(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_DNS_SERVERS:
        raise ConfigError(f"dns_servers must be a list of 1 to {MAX_DNS_SERVERS} IP addresses")
    servers: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ConfigError("dns_servers entries must be strings")
        try:
            ipaddress.ip_address(item)
        except ValueError:
            raise ConfigError(f"dns_servers: {item!r} is not an IP address") from None
        servers.append(item)
    return tuple(servers)


def _absolute_path(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ConfigError(f"{name} must be an absolute path")
    return value
