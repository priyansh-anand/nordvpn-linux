# SPDX-License-Identifier: GPL-3.0-only
"""Session fixture that builds, starts and tears down the e2e Docker stack."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Generator, Iterator
from pathlib import Path

import pytest
from e2e.stack import COMPOSE, ROOT, Stack

import nordvpn_linux

DAEMON_CONFIG = """\
log_level = "debug"
connect_timeout = 20
api_base = "https://api.fakenord.test"
configs_base = "https://cdn.fakenord.test"
dns_servers = ["10.8.0.1"]
"""


def _deb() -> Path:
    debs = sorted((ROOT / "dist").glob(f"nordvpn-linux_{nordvpn_linux.__version__}*_all.deb"))
    if not debs:
        pytest.fail("no .deb for this version in dist/; run the e2e tests with: make e2e")
    return debs[-1]


@pytest.fixture(scope="session")
def stack() -> Iterator[Stack]:
    deb = _deb()
    subprocess.run(
        [*COMPOSE, "up", "--detach", "--build", "--wait", "--wait-timeout", "300"], check=True
    )
    s = Stack()
    try:
        s.exec("apt-get", "install", "-y", "--no-install-recommends", f"/dist/{deb.name}")
        s.exec("usermod", "-aG", "nordvpn", "alice")
        s.exec("tee", "/etc/nordvpn/nordvpnd.toml", input=DAEMON_CONFIG)
        s.exec("systemctl", "restart", "nordvpnd")
        s.wait_for_daemon()
        yield s
    finally:
        if os.environ.get("E2E_KEEP") == "1":
            print("\nE2E_KEEP=1: stack left running. Remove it with:")
            print("  docker compose -f tests/e2e/compose.yaml down --volumes")
        else:
            subprocess.run([*COMPOSE, "down", "--volumes", "--remove-orphans"], check=False)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Attach the daemon's journal to every failing e2e test."""
    report = yield
    stack = getattr(item, "funcargs", {}).get("stack")
    if report.when == "call" and report.failed and isinstance(stack, Stack):
        journal = stack.exec("journalctl", "-u", "nordvpnd", "-n", "80", "--no-pager", check=False)
        report.sections.append(("nordvpnd journal", journal.stdout))
    return report
