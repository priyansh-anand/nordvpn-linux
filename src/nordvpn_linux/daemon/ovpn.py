# SPDX-License-Identifier: GPL-3.0-only
"""Validation of OpenVPN client configs downloaded from NordVPN.

The daemon runs OpenVPN as root, and an OpenVPN config can run arbitrary commands
(``up``, ``plugin``, ``tls-verify`` ...). Instead of trying to list every dangerous
directive in every OpenVPN version, we accept only the directives NordVPN's configs
actually use. Anything unknown fails closed.

Lines are split the way OpenVPN splits them (on ``\n`` only), and any other
control character or non-ASCII character is rejected, so the validator can never
see different lines from the ones OpenVPN will run.
"""

from __future__ import annotations

import ipaddress
import re

ALLOWED_DIRECTIVES = frozenset(
    {
        "auth",
        "auth-user-pass",
        "cipher",
        "client",
        "comp-lzo",
        "compress",
        "data-ciphers",
        "data-ciphers-fallback",
        "dev",
        "explicit-exit-notify",
        "fast-io",
        "fragment",
        "key-direction",
        "mssfix",
        "mute",
        "nobind",
        "persist-key",
        "persist-tun",
        "ping",
        "ping-restart",
        "ping-timer-rem",
        "proto",
        "pull",
        "remote",
        "remote-cert-tls",
        "remote-random",
        "reneg-sec",
        "resolv-retry",
        "tls-client",
        "tls-version-min",
        "tun-mtu",
        "tun-mtu-extra",
        "verb",
        "verify-x509-name",
    }
)
ALLOWED_BLOCKS = frozenset({"ca", "cert", "key", "tls-auth", "tls-crypt"})
REMOTE_PROTOCOLS = frozenset({"udp", "udp4", "tcp", "tcp4", "tcp-client", "tcp4-client"})
MAX_REMOTE_ARGS = 3  # host [port [proto]]
MAX_PORT = 65535

_DIRECTIVE_RE = re.compile(r"[a-z][a-z0-9-]*")
_BLOCK_RE = re.compile(r"<([a-z][a-z-]*)>")
_PORT_RE = re.compile(r"[0-9]{1,5}")


class InvalidConfigError(ValueError):
    def __init__(self, line_no: int, reason: str) -> None:
        super().__init__(f"line {line_no}: {reason}")
        self.line_no = line_no
        self.reason = reason


def validate_config(text: str, hostname: str) -> str:
    """Return *text* unchanged if it is a safe config for *hostname*, else raise."""
    fqdn = f"{hostname}.nordvpn.com"
    block: str | None = None
    remotes = 0
    line_no = 0
    for line_no, raw in enumerate(text.split("\n"), start=1):
        raw = raw.removesuffix("\r")  # CRLF line endings
        _check_characters(line_no, raw)
        line = raw.strip()
        if block is not None:
            if line == f"</{block}>":
                block = None
            elif line.startswith("<"):
                raise InvalidConfigError(line_no, f"unexpected tag {line!r} inside <{block}>")
            continue
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("<"):
            match = _BLOCK_RE.fullmatch(line)
            if match is None or match.group(1) not in ALLOWED_BLOCKS:
                raise InvalidConfigError(line_no, f"block {line!r} is not allowed")
            block = match.group(1)
            continue
        directive, *args = line.split()
        if not _DIRECTIVE_RE.fullmatch(directive) or directive not in ALLOWED_DIRECTIVES:
            raise InvalidConfigError(line_no, f"directive {directive!r} is not allowed")
        _check_arguments(line_no, directive, args, fqdn)
        if directive == "remote":
            remotes += 1
    if block is not None:
        raise InvalidConfigError(line_no, f"unterminated <{block}> block")
    if remotes == 0:
        raise InvalidConfigError(line_no, "config has no 'remote' directive")
    return text


def _check_characters(line_no: int, raw: str) -> None:
    for ch in raw:
        if ch == "\x00":
            raise InvalidConfigError(line_no, "NUL byte")
        if not ch.isascii():
            raise InvalidConfigError(line_no, f"non-ASCII character {ch!r}")
        if (ch < " " and ch != "\t") or ch == "\x7f":
            raise InvalidConfigError(line_no, f"control character {ch!r}")


def _check_arguments(line_no: int, directive: str, args: list[str], fqdn: str) -> None:
    if directive == "auth-user-pass" and args:
        raise InvalidConfigError(line_no, "auth-user-pass must not name a file")
    if directive == "dev" and args != ["tun"]:
        raise InvalidConfigError(line_no, "dev must be 'tun'")
    if directive == "verify-x509-name" and (not args or args[0] != f"CN={fqdn}"):
        raise InvalidConfigError(line_no, f"verify-x509-name does not match {fqdn}")
    if directive == "remote":
        _check_remote(line_no, args, fqdn)


def _check_remote(line_no: int, args: list[str], fqdn: str) -> None:
    if not 1 <= len(args) <= MAX_REMOTE_ARGS:
        raise InvalidConfigError(line_no, "remote must be: remote HOST [PORT [PROTO]]")
    host, *rest = args
    if host != fqdn and not _is_ipv4(host):
        raise InvalidConfigError(line_no, f"remote {host!r} is neither {fqdn} nor an IPv4 address")
    if rest and not (_PORT_RE.fullmatch(rest[0]) and 1 <= int(rest[0]) <= MAX_PORT):
        raise InvalidConfigError(line_no, f"invalid remote port {rest[0]!r}")
    if len(rest) == 2 and rest[1] not in REMOTE_PROTOCOLS:
        raise InvalidConfigError(line_no, f"invalid remote protocol {rest[1]!r}")


def _is_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return True
