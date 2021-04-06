# SPDX-License-Identifier: GPL-3.0-only
"""Connect-target parsing: the only things a client may ask the daemon to connect to."""

from __future__ import annotations

import pytest

from nordvpn_linux.errors import ErrorCode, NordVPNError
from nordvpn_linux.targets import (
    Country,
    Host,
    Nearest,
    normalize_country_name,
    normalize_hostname,
    parse_target,
    require_hostname,
)


def test_none_means_nearest() -> None:
    assert parse_target(None) == Nearest()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("us", Country("us")),
        ("US", Country("us")),
        (" de ", Country("de")),
        ("united states", Country("united states")),
        ("United_States", Country("united states")),
        ("Bosnia and Herzegovina", Country("bosnia and herzegovina")),
        ("us1234", Host("us1234")),
        ("US1234.NordVPN.com", Host("us1234")),
        ("uk-nl1", Host("uk-nl1")),
        ("us1234.nordvpn.com\n", Host("us1234")),
    ],
)
def test_valid_targets(raw: str, expected: object) -> None:
    assert parse_target(raw) == expected


def test_uk_is_an_alias_for_gb() -> None:
    # NordVPN hostnames use "uk" but the API's ISO code for the United Kingdom is "GB".
    assert parse_target("uk") == Country("gb")
    assert parse_target("uk1234") == Host("uk1234")


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "/tmp/evil.ovpn",
        "../../etc/passwd",
        "us1234.ovpn",
        "us1234.nordvpn.com.evil.com",
        "-us",
        "--config",
        "us 1234",
        "us\x001234",
        "us1\nplugin /x.so",
        "us123456",
        "u",
        "x" * 65,
        "a/b",
        "us;reboot",
        123,
        ["us"],
    ],
)
def test_invalid_targets(raw: object) -> None:
    with pytest.raises(NordVPNError) as excinfo:
        parse_target(raw)
    assert excinfo.value.code is ErrorCode.INVALID_TARGET


def test_trailing_newline_cannot_smuggle_text() -> None:
    # re.match(r"...$") would accept "us1\n"; the parser must use full matches only.
    assert normalize_hostname("us1\n") == "us1"
    assert normalize_hostname("us1\nx") is None
    assert normalize_hostname("us1\n\n") == "us1"


def test_normalize_country_name() -> None:
    assert normalize_country_name("  South_Korea ") == "south korea"
    assert normalize_country_name("Czech   Republic") == "czech republic"


def test_require_hostname() -> None:
    assert require_hostname("us12941.nordvpn.com") == "us12941"
    for bad in ("../x", "", None, 5, "us12941.example.com"):
        with pytest.raises(NordVPNError) as excinfo:
            require_hostname(bad)
        assert excinfo.value.code is ErrorCode.API_ERROR
