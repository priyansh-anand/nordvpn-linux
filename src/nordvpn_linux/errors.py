# SPDX-License-Identifier: GPL-3.0-only
"""Error codes shared by the CLI and the daemon, and the CLI exit codes they map to."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    BAD_REQUEST = "BAD_REQUEST"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_LOGGED_IN = "NOT_LOGGED_IN"
    AUTH_FAILED = "AUTH_FAILED"
    INVALID_TARGET = "INVALID_TARGET"
    UNKNOWN_SERVER = "UNKNOWN_SERVER"
    API_ERROR = "API_ERROR"
    INVALID_CONFIG = "INVALID_CONFIG"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    TUNNEL_FAILED = "TUNNEL_FAILED"
    INTERNAL = "INTERNAL"


EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_DAEMON_UNREACHABLE = 3
EXIT_AUTH = 4
EXIT_PERMISSION = 5
EXIT_CANCELLED = 130

_EXIT_CODES: dict[ErrorCode, int] = {
    ErrorCode.BAD_REQUEST: EXIT_USAGE,
    ErrorCode.INVALID_TARGET: EXIT_USAGE,
    ErrorCode.UNKNOWN_SERVER: EXIT_USAGE,
    ErrorCode.NOT_LOGGED_IN: EXIT_AUTH,
    ErrorCode.AUTH_FAILED: EXIT_AUTH,
    ErrorCode.PERMISSION_DENIED: EXIT_PERMISSION,
    ErrorCode.CANCELLED: EXIT_CANCELLED,
}


def exit_code_for(code: ErrorCode) -> int:
    """The ``nordvpn`` exit status for an error code."""
    return _EXIT_CODES.get(code, EXIT_ERROR)


class NordVPNError(Exception):
    """An error with a stable code, safe to send across the IPC boundary."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __repr__(self) -> str:
        return f"NordVPNError({self.code.value}, {self.message!r})"
