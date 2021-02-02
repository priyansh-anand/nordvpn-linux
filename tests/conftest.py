# SPDX-License-Identifier: GPL-3.0-only
"""Shared pytest fixtures."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def short_tmp() -> Iterator[Path]:
    """A temporary directory with a short path.

    AF_UNIX socket paths are limited to 104 bytes on macOS (108 on Linux), and
    pytest's ``tmp_path`` is longer than that on macOS.
    """
    path = Path(tempfile.mkdtemp(prefix="nv", dir="/tmp"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
