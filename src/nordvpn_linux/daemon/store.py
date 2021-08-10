# SPDX-License-Identifier: GPL-3.0-only
"""Persistent daemon state: NordVPN service credentials and user settings."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from nordvpn_linux.errors import ErrorCode, NordVPNError

log = logging.getLogger(__name__)

MAX_CREDENTIAL_LENGTH = 256
_FORBIDDEN_CHARACTERS = frozenset("\r\n\x00")


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    """Replace *path* with *data* so readers see the old file or the new one, never a mix.

    The temporary file gets *mode* before any data is written, so a secret is
    never briefly readable by others.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            os.fchmod(fh.fileno(), mode)
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        with contextlib.suppress(OSError):
            os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str = field(repr=False)

    @classmethod
    def from_untrusted(cls, username: object, password: object) -> Credentials:
        return cls(_credential("username", username), _credential("password", password))


def _credential(label: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise NordVPNError(ErrorCode.BAD_REQUEST, f"{label} must be a non-empty string")
    if len(value) > MAX_CREDENTIAL_LENGTH:
        raise NordVPNError(ErrorCode.BAD_REQUEST, f"{label} is too long")
    if _FORBIDDEN_CHARACTERS.intersection(value):
        raise NordVPNError(ErrorCode.BAD_REQUEST, f"{label} contains line breaks or NUL bytes")
    return value


class CredentialStore:
    """Root-only (0600) storage for the NordVPN service credentials."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> Credentials | None:
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return None
        try:
            obj = json.loads(raw)
            return Credentials.from_untrusted(obj["username"], obj["password"])
        except (ValueError, KeyError, TypeError, NordVPNError):
            log.warning("ignoring unreadable credentials file %s", self._path)
            return None

    def save(self, credentials: Credentials) -> None:
        data = json.dumps({"username": credentials.username, "password": credentials.password})
        atomic_write(self._path, data.encode(), 0o600)

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)


class VpnProtocol(StrEnum):
    UDP = "udp"
    TCP = "tcp"


@dataclass(frozen=True)
class Settings:
    protocol: VpnProtocol = VpnProtocol.UDP
    dns: bool = True

    def to_json(self) -> dict[str, Any]:
        return {"protocol": self.protocol.value, "dns": self.dns}


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> Settings:
        try:
            obj = json.loads(self._path.read_bytes())
        except FileNotFoundError:
            return Settings()
        except ValueError:
            log.warning("ignoring unreadable settings file %s", self._path)
            return Settings()
        if not isinstance(obj, dict):
            log.warning("ignoring malformed settings file %s", self._path)
            return Settings()
        settings = Settings()
        for key, value in obj.items():
            try:
                settings = _apply(settings, key, value)
            except NordVPNError:
                log.warning("ignoring invalid setting %s=%r", key, value)
        return settings

    def save(self, settings: Settings) -> None:
        data = json.dumps(settings.to_json(), indent=2) + "\n"
        atomic_write(self._path, data.encode(), 0o644)

    def update(self, key: object, value: object) -> Settings:
        settings = _apply(self.load(), key, value)
        self.save(settings)
        return settings


def _apply(settings: Settings, key: object, value: object) -> Settings:
    if key == "protocol":
        if not isinstance(value, str) or value not in tuple(VpnProtocol):
            raise NordVPNError(ErrorCode.BAD_REQUEST, "protocol must be 'udp' or 'tcp'")
        return replace(settings, protocol=VpnProtocol(value))
    if key == "dns":
        if not isinstance(value, bool):
            raise NordVPNError(ErrorCode.BAD_REQUEST, "dns must be true or false")
        return replace(settings, dns=value)
    raise NordVPNError(ErrorCode.BAD_REQUEST, f"unknown setting {key!r}")
