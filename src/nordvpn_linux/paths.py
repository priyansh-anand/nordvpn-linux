# SPDX-License-Identifier: GPL-3.0-only
"""Filesystem locations used by the daemon and the CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_FILE = Path("/etc/nordvpn/nordvpnd.toml")
DEFAULT_SOCKET = Path("/run/nordvpn/nordvpnd.sock")
GROUP = "nordvpn"


@dataclass(frozen=True)
class Paths:
    """Where the daemon keeps its state. Tests point this at a temporary directory."""

    state_dir: Path = Path("/var/lib/nordvpn")
    cache_dir: Path = Path("/var/cache/nordvpn")
    runtime_dir: Path = Path("/run/nordvpn")

    @classmethod
    def under(cls, root: Path) -> Paths:
        return cls(state_dir=root / "state", cache_dir=root / "cache", runtime_dir=root / "run")

    @property
    def credentials_file(self) -> Path:
        return self.state_dir / "credentials"

    @property
    def settings_file(self) -> Path:
        return self.state_dir / "settings.json"

    @property
    def countries_cache(self) -> Path:
        return self.cache_dir / "countries.json"

    @property
    def configs_dir(self) -> Path:
        return self.cache_dir / "configs"

    @property
    def socket(self) -> Path:
        return self.runtime_dir / "nordvpnd.sock"

    @property
    def private_dir(self) -> Path:
        return self.runtime_dir / "private"

    @property
    def management_socket(self) -> Path:
        return self.private_dir / "mgmt.sock"
