# SPDX-License-Identifier: GPL-3.0-only
"""Client for NordVPN's public server API and config CDN.

Everything here is blocking; the daemon calls it through ``asyncio.to_thread``.
Network access goes through an injectable ``fetch`` so tests never touch the
network. Responses are cached under ``/var/cache/nordvpn``.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPMessage
from pathlib import Path
from typing import IO, Any

from nordvpn_linux import __version__
from nordvpn_linux.daemon.ovpn import InvalidConfigError, validate_config
from nordvpn_linux.daemon.store import VpnProtocol, atomic_write
from nordvpn_linux.errors import ErrorCode, NordVPNError
from nordvpn_linux.paths import Paths
from nordvpn_linux.targets import COUNTRY_ALIASES, normalize_country_name, require_hostname

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10.0
MAX_BODY_BYTES = 5 * 1024 * 1024
COUNTRIES_TTL = 24 * 3600
CONFIG_TTL = 7 * 24 * 3600
HTTP_NOT_FOUND = 404

Fetch = Callable[[str], bytes]


class FetchError(Exception):
    def __init__(self, url: str, status: int | None, reason: str) -> None:
        super().__init__(f"{url}: {reason}")
        self.url = url
        self.status = status
        self.reason = reason


class _HTTPSOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to https:// URLs. A downgrade is an error, not a detour."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        if not newurl.startswith("https://"):
            raise urllib.error.HTTPError(
                newurl, code, "refusing to follow a redirect to a non-HTTPS URL", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HTTPSOnlyRedirects())


def urllib_fetch(url: str) -> bytes:
    """GET *url* over HTTPS with certificate verification, a timeout and a size cap."""
    if not url.startswith("https://"):
        raise FetchError(url, None, "refusing to fetch a non-HTTPS URL")
    headers = {"User-Agent": f"nordvpn-linux/{__version__}"}
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 - scheme checked above
    try:
        with _OPENER.open(request, timeout=REQUEST_TIMEOUT) as response:
            body: bytes = response.read(MAX_BODY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise FetchError(url, exc.code, f"HTTP {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(url, None, str(exc.reason)) from exc
    except OSError as exc:
        raise FetchError(url, None, str(exc)) from exc
    if len(body) > MAX_BODY_BYTES:
        raise FetchError(url, None, "response is too large")
    return body


@dataclass(frozen=True)
class CountryInfo:
    id: int
    code: str  # lower-case ISO 3166-1 alpha-2, e.g. "gb"
    name: str


@dataclass(frozen=True)
class ServerInfo:
    hostname: str  # short form, e.g. "us12941"
    country: str  # display name, or "" when unknown


class NordAPI:
    def __init__(
        self,
        *,
        api_base: str,
        configs_base: str,
        paths: Paths,
        fetch: Fetch = urllib_fetch,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._api_base = api_base
        self._configs_base = configs_base
        self._paths = paths
        self._fetch = fetch
        self._clock = clock

    def countries(self) -> list[CountryInfo]:
        cached = self._read_countries_cache()
        if cached is not None and self._clock() - cached[0] < COUNTRIES_TTL:
            return cached[1]
        try:
            countries = _parse_countries(self._get_json(f"{self._api_base}/v1/servers/countries"))
        except NordVPNError:
            if cached is None:
                raise
            log.warning("NordVPN API unavailable; using the cached country list")
            return cached[1]
        payload = {
            "fetched_at": self._clock(),
            "countries": [{"id": c.id, "code": c.code, "name": c.name} for c in countries],
        }
        atomic_write(self._paths.countries_cache, json.dumps(payload).encode(), 0o644)
        return countries

    def find_country(self, query: str) -> CountryInfo:
        wanted = COUNTRY_ALIASES.get(query, query)
        for country in self.countries():
            if wanted in (country.code, normalize_country_name(country.name)):
                return country
        raise NordVPNError(
            ErrorCode.INVALID_TARGET, f"unknown country {query!r}; see: nordvpn countries"
        )

    def country_name_for_host(self, hostname: str) -> str:
        prefix = hostname[:2]
        code = COUNTRY_ALIASES.get(prefix, prefix)
        try:
            countries = self.countries()
        except NordVPNError:
            return ""
        return next((c.name for c in countries if c.code == code), "")

    def recommend(self, country: CountryInfo | None, protocol: VpnProtocol) -> ServerInfo:
        params = [
            ("filters[servers_technologies][identifier]", f"openvpn_{protocol.value}"),
            ("limit", "1"),
        ]
        if country is not None:
            params.append(("filters[country_id]", str(country.id)))
        query = urllib.parse.urlencode(params)
        data = self._get_json(f"{self._api_base}/v1/servers/recommendations?{query}")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            where = country.name if country is not None else "your location"
            raise NordVPNError(
                ErrorCode.API_ERROR,
                f"NordVPN has no OpenVPN {protocol.value.upper()} server available for {where}",
            )
        server = data[0]
        fallback = country.name if country is not None else ""
        return ServerInfo(
            hostname=require_hostname(server.get("hostname")),
            country=_server_country(server) or fallback,
        )

    def config(self, hostname: str, protocol: VpnProtocol) -> Path:
        """Return the path of a validated config for *hostname*, downloading it if needed."""
        path = self._paths.configs_dir / f"{hostname}.{protocol.value}.ovpn"
        age = self._cached_config_age(path, hostname)
        if age is not None and age < CONFIG_TTL:
            return path
        proto = protocol.value
        url = (
            f"{self._configs_base}/configs/files/ovpn_{proto}/servers/"
            f"{hostname}.nordvpn.com.{proto}.ovpn"
        )
        try:
            body = self._fetch(url)
        except FetchError as exc:
            if exc.status == HTTP_NOT_FOUND:
                raise NordVPNError(
                    ErrorCode.UNKNOWN_SERVER,
                    f"NordVPN has no OpenVPN {proto.upper()} server named {hostname}",
                ) from exc
            if age is not None:
                log.warning("using cached config for %s: refresh failed (%s)", hostname, exc.reason)
                return path
            raise NordVPNError(
                ErrorCode.API_ERROR, f"could not download the config for {hostname}: {exc.reason}"
            ) from exc
        try:
            validate_config(body.decode("utf-8"), hostname)
        except (UnicodeDecodeError, InvalidConfigError) as exc:
            log.error("rejected the config NordVPN served for %s: %s", hostname, exc)
            raise NordVPNError(
                ErrorCode.INVALID_CONFIG, f"the config for {hostname} failed validation ({exc})"
            ) from exc
        atomic_write(path, body, 0o644)
        return path

    def _cached_config_age(self, path: Path, hostname: str) -> float | None:
        try:
            text = path.read_text("utf-8")
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError):
            path.unlink(missing_ok=True)
            return None
        try:
            validate_config(text, hostname)
        except InvalidConfigError:
            log.warning("discarding cached config %s: it no longer validates", path)
            path.unlink(missing_ok=True)
            return None
        return self._clock() - mtime

    def _read_countries_cache(self) -> tuple[float, list[CountryInfo]] | None:
        try:
            obj = json.loads(self._paths.countries_cache.read_bytes())
        except (OSError, ValueError):
            return None
        if not isinstance(obj, dict):
            return None
        fetched_at = obj.get("fetched_at")
        if isinstance(fetched_at, bool) or not isinstance(fetched_at, int | float):
            return None
        try:
            return float(fetched_at), _parse_countries(obj.get("countries"))
        except NordVPNError:
            return None

    def _get_json(self, url: str) -> Any:
        try:
            body = self._fetch(url)
        except FetchError as exc:
            raise NordVPNError(
                ErrorCode.API_ERROR, f"NordVPN API request failed: {exc.reason}"
            ) from exc
        try:
            return json.loads(body)
        except ValueError as exc:
            raise NordVPNError(ErrorCode.API_ERROR, "NordVPN API returned invalid JSON") from exc


def _parse_countries(data: object) -> list[CountryInfo]:
    countries: list[CountryInfo] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            cid, code, name = item.get("id"), item.get("code"), item.get("name")
            if (
                isinstance(cid, int)
                and not isinstance(cid, bool)
                and isinstance(code, str)
                and len(code) == 2
                and code.isascii()
                and code.isalpha()
                and isinstance(name, str)
                and name
            ):
                countries.append(CountryInfo(cid, code.lower(), name))
    if not countries:
        raise NordVPNError(ErrorCode.API_ERROR, "NordVPN API returned no countries")
    return sorted(countries, key=lambda c: c.name)


def _server_country(server: dict[str, Any]) -> str:
    try:
        name = server["locations"][0]["country"]["name"]
    except (KeyError, IndexError, TypeError):
        return ""
    return name if isinstance(name, str) else ""
