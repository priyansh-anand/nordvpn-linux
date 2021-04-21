# SPDX-License-Identifier: GPL-3.0-only
"""Filesystem layout."""

from __future__ import annotations

from pathlib import Path

from nordvpn_linux.paths import DEFAULT_SOCKET, Paths


def test_default_layout() -> None:
    paths = Paths()
    assert paths.socket == DEFAULT_SOCKET == Path("/run/nordvpn/nordvpnd.sock")
    assert paths.credentials_file == Path("/var/lib/nordvpn/credentials")
    assert paths.settings_file == Path("/var/lib/nordvpn/settings.json")
    assert paths.countries_cache == Path("/var/cache/nordvpn/countries.json")
    assert paths.configs_dir == Path("/var/cache/nordvpn/configs")
    assert paths.private_dir == Path("/run/nordvpn/private")
    assert paths.management_socket == Path("/run/nordvpn/private/mgmt.sock")


def test_under_root_keeps_everything_inside(tmp_path: Path) -> None:
    paths = Paths.under(tmp_path)
    for path in (
        paths.socket,
        paths.credentials_file,
        paths.settings_file,
        paths.countries_cache,
        paths.configs_dir,
        paths.management_socket,
    ):
        assert path.is_relative_to(tmp_path)
    assert paths.socket == tmp_path / "run" / "nordvpnd.sock"
