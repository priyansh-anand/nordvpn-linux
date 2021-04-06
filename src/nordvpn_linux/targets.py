# SPDX-License-Identifier: GPL-3.0-only
"""Parsing and validation of ``connect`` targets.

This is the security boundary for ``connect``: all an unprivileged client can ask
for is "nearest", a country, or a NordVPN server hostname. Paths and anything else
are rejected here, before the daemon does any work. Only full-string matches are
used, because ``re.match(r"...$")`` would also accept a trailing newline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from nordvpn_linux.errors import ErrorCode, NordVPNError

HOSTNAME_RE = re.compile(r"[a-z]{2}(?:-[a-z]{2})?[0-9]{1,5}")
NORDVPN_DOMAIN = ".nordvpn.com"
MAX_TARGET_LENGTH = 64
MIN_COUNTRY_NAME_LENGTH = 3  # the shortest NordVPN country name is "Chad"
_NAME_PUNCTUATION = frozenset(" .'-")

# NordVPN names its UK servers "uk1234", but the API uses the ISO code "GB".
COUNTRY_ALIASES: dict[str, str] = {"uk": "gb"}


@dataclass(frozen=True)
class Nearest:
    """Let NordVPN pick the closest server."""


@dataclass(frozen=True)
class Country:
    query: str  # lower-case ISO code ("us") or normalised name ("united states")


@dataclass(frozen=True)
class Host:
    name: str  # short hostname, e.g. "us1234"


Target = Nearest | Country | Host


def normalize_hostname(value: str) -> str | None:
    """``"US1234.nordvpn.com"`` -> ``"us1234"``; ``None`` if it is not a NordVPN hostname."""
    name = value.strip().lower().removesuffix(NORDVPN_DOMAIN)
    return name if HOSTNAME_RE.fullmatch(name) else None


def normalize_country_name(value: str) -> str:
    """Lower-case, treat underscores as spaces, and collapse whitespace."""
    return " ".join(value.replace("_", " ").lower().split())


def parse_target(raw: object) -> Target:
    if raw is None:
        return Nearest()
    if not isinstance(raw, str):
        raise _invalid("target must be a string")
    value = raw.strip().lower()
    if not value:
        raise _invalid("target must not be empty")
    if len(value) > MAX_TARGET_LENGTH:
        raise _invalid("target is too long")
    if len(value) == 2 and value.isascii() and value.isalpha():
        return Country(COUNTRY_ALIASES.get(value, value))
    host = normalize_hostname(value)
    if host is not None:
        return Host(host)
    name = normalize_country_name(value)
    if (
        len(name) >= MIN_COUNTRY_NAME_LENGTH
        and name[0].isalpha()
        and all(ch.isalpha() or ch in _NAME_PUNCTUATION for ch in name)
    ):
        return Country(name)
    raise _invalid(f"{raw!r} is not a country or a NordVPN server name")


def require_hostname(value: object) -> str:
    """Validate a hostname returned by the NordVPN API before using it."""
    if isinstance(value, str) and (name := normalize_hostname(value)) is not None:
        return name
    raise NordVPNError(ErrorCode.API_ERROR, f"NordVPN API returned an invalid hostname: {value!r}")


def _invalid(message: str) -> NordVPNError:
    return NordVPNError(ErrorCode.INVALID_TARGET, message)
