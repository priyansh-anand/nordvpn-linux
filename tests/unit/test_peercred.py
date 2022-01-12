# SPDX-License-Identifier: GPL-3.0-only
"""Peer credentials and group-based authorization."""

from __future__ import annotations

import grp
import os
import socket

import pytest

from nordvpn_linux.daemon.peercred import get_peer_uid, group_authorizer

MISSING_GROUP = "nordvpn-test-no-such-group"


def test_peer_uid_of_a_socketpair_is_our_uid() -> None:
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with a, b:
        assert get_peer_uid(b) == os.getuid()


def test_root_is_always_allowed() -> None:
    assert group_authorizer(MISSING_GROUP)(0)


@pytest.mark.skipif(os.getuid() == 0, reason="root is always allowed")
def test_missing_group_denies_everyone_else() -> None:
    assert not group_authorizer(MISSING_GROUP)(os.getuid())


def test_members_are_allowed() -> None:
    our_group = grp.getgrgid(os.getgid()).gr_name
    assert group_authorizer(our_group)(os.getuid())


def test_unknown_uid_is_denied() -> None:
    our_group = grp.getgrgid(os.getgid()).gr_name
    assert not group_authorizer(our_group)(2_000_000_000)
