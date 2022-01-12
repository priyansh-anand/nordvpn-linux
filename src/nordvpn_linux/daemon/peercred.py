# SPDX-License-Identifier: GPL-3.0-only
"""Who is on the other end of a Unix socket, and may they use the daemon?"""

from __future__ import annotations

import grp
import os
import pwd
import socket
import struct
import sys
from collections.abc import Callable
from typing import Protocol

Authorizer = Callable[[int], bool]

# Linux: struct ucred { pid_t pid; uid_t uid; gid_t gid; }
_UCRED = struct.Struct("3i")
# macOS: struct xucred { u_int cr_version; uid_t cr_uid; short cr_ngroups; gid_t cr_groups[16]; }
_XUCRED = struct.Struct("IIh16I")
_SOL_LOCAL = 0  # macOS <sys/un.h>
_LOCAL_PEERCRED = 0x001


class SupportsGetsockopt(Protocol):
    def getsockopt(self, level: int, optname: int, buflen: int, /) -> bytes: ...


def get_peer_uid(sock: SupportsGetsockopt) -> int:
    """The uid of the process that connected to *sock*, as vouched for by the kernel."""
    if sys.platform == "linux":
        data = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _UCRED.size)
        _pid, uid, _gid = _UCRED.unpack_from(data)
        return int(uid)
    if sys.platform == "darwin":
        data = sock.getsockopt(_SOL_LOCAL, _LOCAL_PEERCRED, _XUCRED.size)
        return int(_XUCRED.unpack_from(data)[1])
    raise OSError(f"peer credentials are not supported on {sys.platform}")


def group_authorizer(group: str) -> Authorizer:
    """Allow root and members of *group*. Membership is looked up on every call."""

    def authorize(uid: int) -> bool:
        if uid == 0:
            return True
        try:
            gid = grp.getgrnam(group).gr_gid
            user = pwd.getpwuid(uid)
        except KeyError:
            return False
        return gid in os.getgrouplist(user.pw_name, user.pw_gid)

    return authorize
