# SPDX-License-Identifier: GPL-3.0-only
"""Credentials and settings persistence."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from nordvpn_linux.daemon.store import (
    Credentials,
    CredentialStore,
    Settings,
    SettingsStore,
    VpnProtocol,
    atomic_write,
)
from nordvpn_linux.errors import ErrorCode, NordVPNError


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_atomic_write_sets_mode_and_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "file"
    atomic_write(target, b"one", 0o600)
    atomic_write(target, b"two", 0o644)
    assert target.read_bytes() == b"two"
    assert mode(target) == 0o644
    assert sorted(p.name for p in target.parent.iterdir()) == ["file"]


def test_atomic_write_cleans_up_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "file"
    target.write_bytes(b"old")

    def boom(self: Path, other: Path) -> Path:
        raise OSError("disk on fire")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError, match="disk on fire"):
        atomic_write(target, b"new", 0o600)
    assert target.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["file"]


def test_credentials_round_trip_with_private_mode(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path / "credentials")
    assert store.load() is None
    store.save(Credentials("svc-user", 'p"a\\ss'))
    assert store.load() == Credentials("svc-user", 'p"a\\ss')
    assert mode(tmp_path / "credentials") == 0o600


def test_clear_is_idempotent(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path / "credentials")
    store.save(Credentials("u", "p"))
    store.clear()
    store.clear()
    assert store.load() is None


@pytest.mark.parametrize("content", [b"", b"not json", b"[1]", b'{"username": "u"}', b'"x"'])
def test_corrupt_credentials_are_ignored(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "credentials"
    path.write_bytes(content)
    assert CredentialStore(path).load() is None


def test_repr_hides_password() -> None:
    text = repr(Credentials("svc-user", "hunter2"))
    assert "svc-user" in text
    assert "hunter2" not in text


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("", "p"),
        ("u", ""),
        (None, "p"),
        ("u", 5),
        ("u\n", "p"),
        ("u", "p\r"),
        ("u", "p\x00"),
        ("u" * 257, "p"),
    ],
)
def test_untrusted_credentials_are_validated(username: object, password: object) -> None:
    with pytest.raises(NordVPNError) as excinfo:
        Credentials.from_untrusted(username, password)
    assert excinfo.value.code is ErrorCode.BAD_REQUEST


def test_settings_defaults_and_updates(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    assert store.load() == Settings(VpnProtocol.UDP, dns=True)
    assert store.update("protocol", "tcp") == Settings(VpnProtocol.TCP, dns=True)
    assert store.update("dns", False) == Settings(VpnProtocol.TCP, dns=False)
    assert store.load().to_json() == {"protocol": "tcp", "dns": False}
    assert mode(tmp_path / "settings.json") == 0o644


@pytest.mark.parametrize(
    ("key", "value"),
    [("protocol", "icmp"), ("protocol", 1), ("protocol", ["udp"]), ("dns", "yes"), ("colour", 1)],
)
def test_invalid_setting_updates(tmp_path: Path, key: object, value: object) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    with pytest.raises(NordVPNError) as excinfo:
        store.update(key, value)
    assert excinfo.value.code is ErrorCode.BAD_REQUEST
    assert not (tmp_path / "settings.json").exists()


def test_settings_file_with_bad_entries_falls_back_per_key(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"protocol": "tcp", "dns": "maybe", "old_key": 1}')
    assert SettingsStore(path).load() == Settings(VpnProtocol.TCP, dns=True)
    path.write_text("[not an object]")
    assert SettingsStore(path).load() == Settings()
