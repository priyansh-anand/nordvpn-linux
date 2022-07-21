# SPDX-License-Identifier: GPL-3.0-only
"""Build artefacts: the zipapp, generated launchers and unit, and the static packaging files."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from nordvpn_linux.cli.main import build_parser
from nordvpn_linux.daemon.config import DaemonConfig, load_config

ROOT = Path(__file__).parents[2]
PACKAGING = ROOT / "packaging"


@pytest.fixture(scope="module")
def pyz(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build = tmp_path_factory.mktemp("build")
    dist = tmp_path_factory.mktemp("dist")
    subprocess.run(
        ["make", "-s", "pyz", f"BUILD={build}", f"DIST={dist}", f"BUILD_PYTHON={sys.executable}"],
        cwd=ROOT,
        check=True,
    )
    return dist / "nordvpn.pyz"


def run_pyz(pyz: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-I", str(pyz), *args], capture_output=True, text=True)


def test_pyz_runs_isolated(pyz: Path) -> None:
    assert run_pyz(pyz, "cli", "--version").stdout.strip() == "nordvpn 2.0.0"
    assert run_pyz(pyz, "daemon", "--version").stdout.strip() == "nordvpnd 2.0.0"


def test_pyz_propagates_exit_codes(pyz: Path, short_tmp: Path) -> None:
    # zipapp's generated __main__ would discard main()'s return value; ours must not.
    result = run_pyz(pyz, "cli", "--socket", str(short_tmp / "none.sock"), "status")
    assert result.returncode == 3, result.stderr


def test_pyz_contains_only_the_package(pyz: Path) -> None:
    with zipfile.ZipFile(pyz) as archive:
        names = archive.namelist()
    assert "__main__.py" in names
    assert all(name == "__main__.py" or name.startswith("nordvpn_linux/") for name in names)
    assert not any(name.endswith(".pyc") or "__pycache__" in name for name in names)


def test_generated_files_honour_prefix(tmp_path: Path) -> None:
    subprocess.run(
        [
            "make",
            "-s",
            "generated",
            f"BUILD={tmp_path}",
            "PREFIX=/opt/nv",
            "PYTHON=/opt/py/bin/python3",
        ],
        cwd=ROOT,
        check=True,
    )
    gen = tmp_path / "gen"
    launcher = (gen / "nordvpn").read_text()
    daemon = (gen / "nordvpnd").read_text()
    assert 'exec /opt/py/bin/python3 -I /opt/nv/lib/nordvpn/nordvpn.pyz cli "$@"' in launcher
    assert 'exec /opt/py/bin/python3 -I /opt/nv/lib/nordvpn/nordvpn.pyz daemon "$@"' in daemon
    assert "ExecStart=/opt/nv/bin/nordvpnd" in (gen / "nordvpnd.service").read_text().splitlines()


def test_unit_is_hardened() -> None:
    lines = (PACKAGING / "systemd" / "nordvpnd.service.in").read_text().splitlines()
    for expected in (
        "Group=nordvpn",
        "CapabilityBoundingSet=CAP_NET_ADMIN",
        "NoNewPrivileges=yes",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        "PrivateTmp=yes",
        "DevicePolicy=closed",
        "DeviceAllow=/dev/net/tun rw",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK",
        "RuntimeDirectory=nordvpn",
        "RuntimeDirectoryMode=0750",
        "StateDirectoryMode=0700",
    ):
        assert expected in lines, expected


def test_shipped_daemon_config_is_the_default() -> None:
    shipped = PACKAGING / "nordvpnd.toml"
    assert shipped.is_file()  # load_config() of a missing file would also return the defaults
    assert load_config(shipped) == DaemonConfig()


def test_sysusers_declares_the_group() -> None:
    lines = (PACKAGING / "sysusers.d" / "nordvpn.conf").read_text().splitlines()
    assert any(re.fullmatch(r"g\s+nordvpn\s+-.*", line) for line in lines)


def test_completions_cover_every_command() -> None:
    subparsers = next(
        a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction)
    )
    for name in ("nordvpn.bash", "_nordvpn", "nordvpn.fish"):
        text = (PACKAGING / "completions" / name).read_text()
        for command in subparsers.choices:
            assert re.search(rf"(?<![\w-]){re.escape(command)}(?![\w-])", text), (name, command)
