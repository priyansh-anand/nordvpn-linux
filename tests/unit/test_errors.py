# SPDX-License-Identifier: GPL-3.0-only
"""Exit-code mapping."""

from __future__ import annotations

import pytest

from nordvpn_linux.errors import ErrorCode, NordVPNError, exit_code_for


@pytest.mark.parametrize(
    ("code", "exit_code"),
    [
        (ErrorCode.BAD_REQUEST, 2),
        (ErrorCode.INVALID_TARGET, 2),
        (ErrorCode.UNKNOWN_SERVER, 2),
        (ErrorCode.NOT_LOGGED_IN, 4),
        (ErrorCode.AUTH_FAILED, 4),
        (ErrorCode.PERMISSION_DENIED, 5),
        (ErrorCode.CANCELLED, 130),
        (ErrorCode.API_ERROR, 1),
        (ErrorCode.TUNNEL_FAILED, 1),
        (ErrorCode.INTERNAL, 1),
    ],
)
def test_exit_codes(code: ErrorCode, exit_code: int) -> None:
    assert exit_code_for(code) == exit_code


def test_error_carries_code_and_message() -> None:
    error = NordVPNError(ErrorCode.TIMEOUT, "too slow")
    assert error.code is ErrorCode.TIMEOUT
    assert error.message == "too slow"
    assert str(error) == "too slow"
