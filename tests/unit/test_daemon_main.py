# SPDX-License-Identifier: GPL-3.0-only
"""nordvpnd's command-line entry point."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from nordvpn_linux.daemon.main import EX_CONFIG, main, prepare_directories
from nordvpn_linux.paths import Paths


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "nordvpnd 2.0.0" in capsys.readouterr().out


def test_invalid_config_exits_with_ex_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "nordvpnd.toml"
    config.write_text("colour = 'red'\n")
    assert main(["--config", str(config)]) == EX_CONFIG
    assert "unknown option" in capsys.readouterr().err


def test_refuses_to_run_without_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    assert main(["--config", str(tmp_path / "absent.toml")]) == 1


def test_prepare_directories(tmp_path: Path) -> None:
    paths = Paths.under(tmp_path)
    prepare_directories(paths)
    assert stat.S_IMODE(paths.private_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(paths.state_dir.stat().st_mode) == 0o700
    assert paths.configs_dir.is_dir()
