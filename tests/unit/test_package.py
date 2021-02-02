# SPDX-License-Identifier: GPL-3.0-only
"""Package metadata."""

from __future__ import annotations

import re

import nordvpn_linux


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", nordvpn_linux.__version__)
