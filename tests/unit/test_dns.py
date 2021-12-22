# SPDX-License-Identifier: GPL-3.0-only
"""DNS configuration through resolvectl."""

from __future__ import annotations

import sys

from fakes import FakeRunner

from nordvpn_linux.daemon.dns import DnsConfigurator, DnsStatus, run_command


async def test_apply_points_the_tunnel_link_at_the_vpn_resolvers() -> None:
    runner = FakeRunner()
    dns = DnsConfigurator(["10.0.0.1", "10.0.0.2"], runner=runner)
    assert await dns.apply("nordtun") is DnsStatus.APPLIED
    assert runner.calls == [
        ["resolvectl", "status"],
        ["resolvectl", "dns", "nordtun", "10.0.0.1", "10.0.0.2"],
        ["resolvectl", "domain", "nordtun", "~."],
        ["resolvectl", "default-route", "nordtun", "true"],
    ]


async def test_unavailable_when_resolved_is_not_running() -> None:
    runner = FakeRunner({"status": 1})
    dns = DnsConfigurator(["10.0.0.1"], runner=runner)
    assert await dns.apply("nordtun") is DnsStatus.UNAVAILABLE
    assert len(runner.calls) == 1


async def test_unavailable_when_resolvectl_is_missing() -> None:
    dns = DnsConfigurator(["10.0.0.1"], runner=FakeRunner({"status": 127}))
    assert await dns.apply("nordtun") is DnsStatus.UNAVAILABLE


async def test_failed_when_a_command_fails() -> None:
    runner = FakeRunner({"domain": 1})
    assert await DnsConfigurator(["10.0.0.1"], runner=runner).apply("nordtun") is DnsStatus.FAILED
    assert ["resolvectl", "default-route", "nordtun", "true"] not in runner.calls


async def test_revert_is_best_effort() -> None:
    runner = FakeRunner({"revert": 1})
    await DnsConfigurator(["10.0.0.1"], runner=runner).revert("nordtun")
    assert runner.calls == [["resolvectl", "revert", "nordtun"]]


async def test_run_command_reports_exit_status() -> None:
    assert await run_command([sys.executable, "-c", "raise SystemExit(3)"]) == 3


async def test_run_command_reports_a_missing_binary() -> None:
    assert await run_command(["/nonexistent/resolvectl", "status"]) == 127
