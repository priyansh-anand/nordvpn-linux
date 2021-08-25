# SPDX-License-Identifier: GPL-3.0-only
"""NordVPN API client: parsing, caching, fallbacks and HTTPS enforcement."""

from __future__ import annotations

import io
import stat
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from http.client import HTTPMessage
from pathlib import Path

import pytest
from fakes import API, CDN, FIXTURES, UDP_CONFIG_URL, FakeFetch, Route, nord_routes

from nordvpn_linux.daemon.nordapi import (
    CONFIG_TTL,
    COUNTRIES_TTL,
    CountryInfo,
    FetchError,
    NordAPI,
    ServerInfo,
    _HTTPSOnlyRedirects,
    urllib_fetch,
)
from nordvpn_linux.daemon.store import VpnProtocol
from nordvpn_linux.errors import ErrorCode, NordVPNError
from nordvpn_linux.paths import Paths

COUNTRIES_URL = f"{API}/v1/servers/countries"
REAL_UDP = (FIXTURES / "ovpn" / "us12941.udp.ovpn").read_bytes()


def make_api(
    root: Path,
    routes: Mapping[str, Route] | None = None,
    clock: Callable[[], float] = time.time,
) -> tuple[NordAPI, FakeFetch]:
    fetch = FakeFetch(nord_routes() if routes is None else routes)
    api = NordAPI(api_base=API, configs_base=CDN, paths=Paths.under(root), fetch=fetch, clock=clock)
    return api, fetch


def error_code(call: Callable[[], object]) -> ErrorCode:
    with pytest.raises(NordVPNError) as excinfo:
        call()
    return excinfo.value.code


def test_countries_are_parsed_and_sorted(tmp_path: Path) -> None:
    countries = make_api(tmp_path)[0].countries()
    assert [c.code for c in countries] == ["ba", "de", "kr", "gb", "us"]
    assert countries[-1] == CountryInfo(228, "us", "United States")


def test_countries_are_cached_on_disk(tmp_path: Path) -> None:
    api, fetch = make_api(tmp_path)
    first = api.countries()
    assert api.countries() == first
    assert fetch.calls.count(COUNTRIES_URL) == 1
    offline, _ = make_api(tmp_path, routes={})
    assert offline.countries() == first


def test_stale_countries_are_refreshed(tmp_path: Path) -> None:
    now = [1_000_000.0]
    api, fetch = make_api(tmp_path, clock=lambda: now[0])
    api.countries()
    now[0] += COUNTRIES_TTL + 1
    api.countries()
    assert fetch.calls.count(COUNTRIES_URL) == 2


def test_stale_countries_are_used_when_the_api_is_down(tmp_path: Path) -> None:
    online, _ = make_api(tmp_path)
    expected = online.countries()
    down = {COUNTRIES_URL: FetchError(COUNTRIES_URL, None, "timed out")}
    offline, _ = make_api(tmp_path, routes=down, clock=lambda: time.time() + COUNTRIES_TTL * 2)
    assert offline.countries() == expected


@pytest.mark.parametrize("body", [None, b"[]", b"{", b'{"a": 1}', b'[{"id": "x"}]'])
def test_unusable_countries_response_is_an_api_error(tmp_path: Path, body: bytes | None) -> None:
    routes: dict[str, Route] = {} if body is None else {COUNTRIES_URL: body}
    api, _ = make_api(tmp_path, routes=routes)
    assert error_code(api.countries) is ErrorCode.API_ERROR


@pytest.mark.parametrize(
    ("query", "code"),
    [
        ("us", "us"),
        ("united states", "us"),
        ("south korea", "kr"),
        ("bosnia and herzegovina", "ba"),
    ],
)
def test_find_country(tmp_path: Path, query: str, code: str) -> None:
    assert make_api(tmp_path)[0].find_country(query).code == code


def test_find_country_accepts_uk_alias(tmp_path: Path) -> None:
    assert make_api(tmp_path)[0].find_country("uk").name == "United Kingdom"


def test_unknown_country_is_an_invalid_target(tmp_path: Path) -> None:
    api, _ = make_api(tmp_path)
    assert error_code(lambda: api.find_country("atlantis")) is ErrorCode.INVALID_TARGET


def test_country_name_for_host(tmp_path: Path) -> None:
    api, _ = make_api(tmp_path)
    assert api.country_name_for_host("uk2612") == "United Kingdom"
    assert api.country_name_for_host("us1") == "United States"
    assert api.country_name_for_host("zz1") == ""
    assert make_api(tmp_path / "empty", routes={})[0].country_name_for_host("us1") == ""


def test_recommend_builds_the_documented_query(tmp_path: Path) -> None:
    api, fetch = make_api(tmp_path)
    server = api.recommend(api.find_country("us"), VpnProtocol.TCP)
    assert server == ServerInfo("us12941", "United States")
    assert fetch.calls[-1] == (
        f"{API}/v1/servers/recommendations?"
        "filters%5Bservers_technologies%5D%5Bidentifier%5D=openvpn_tcp"
        "&limit=1&filters%5Bcountry_id%5D=228"
    )


def test_recommend_nearest_has_no_country_filter(tmp_path: Path) -> None:
    api, fetch = make_api(tmp_path)
    assert api.recommend(None, VpnProtocol.UDP).hostname == "us12941"
    assert "country_id" not in fetch.calls[-1]
    assert "openvpn_udp" in fetch.calls[-1]


def test_recommend_with_no_servers(tmp_path: Path) -> None:
    routes = nord_routes() | {f"{API}/v1/servers/recommendations?*": b"[]"}
    api, _ = make_api(tmp_path, routes=routes)
    with pytest.raises(NordVPNError, match="United States") as excinfo:
        api.recommend(api.find_country("us"), VpnProtocol.UDP)
    assert excinfo.value.code is ErrorCode.API_ERROR


def test_recommend_rejects_a_hostile_hostname(tmp_path: Path) -> None:
    routes = nord_routes() | {f"{API}/v1/servers/recommendations?*": b'[{"hostname": "../x"}]'}
    api, _ = make_api(tmp_path, routes=routes)
    assert error_code(lambda: api.recommend(None, VpnProtocol.UDP)) is ErrorCode.API_ERROR


def test_config_is_downloaded_validated_and_cached(tmp_path: Path) -> None:
    api, fetch = make_api(tmp_path)
    path = api.config("us12941", VpnProtocol.UDP)
    assert path == Paths.under(tmp_path).configs_dir / "us12941.udp.ovpn"
    assert path.read_bytes() == REAL_UDP
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    assert api.config("us12941", VpnProtocol.UDP) == path
    assert fetch.calls.count(UDP_CONFIG_URL) == 1


def test_stale_config_is_refetched(tmp_path: Path) -> None:
    make_api(tmp_path)[0].config("us12941", VpnProtocol.UDP)
    later, fetch = make_api(tmp_path, clock=lambda: time.time() + CONFIG_TTL + 60)
    later.config("us12941", VpnProtocol.UDP)
    assert fetch.calls == [UDP_CONFIG_URL]


def test_unknown_server(tmp_path: Path) -> None:
    api, _ = make_api(tmp_path)
    assert error_code(lambda: api.config("us1", VpnProtocol.UDP)) is ErrorCode.UNKNOWN_SERVER


def test_network_error_falls_back_to_a_cached_config(tmp_path: Path) -> None:
    path = make_api(tmp_path)[0].config("us12941", VpnProtocol.UDP)
    down = {UDP_CONFIG_URL: FetchError(UDP_CONFIG_URL, None, "timed out")}
    later, _ = make_api(tmp_path, routes=down, clock=lambda: time.time() + CONFIG_TTL + 60)
    assert later.config("us12941", VpnProtocol.UDP) == path


def test_network_error_without_a_cache(tmp_path: Path) -> None:
    down = {UDP_CONFIG_URL: FetchError(UDP_CONFIG_URL, None, "timed out")}
    api, _ = make_api(tmp_path, routes=down)
    assert error_code(lambda: api.config("us12941", VpnProtocol.UDP)) is ErrorCode.API_ERROR


@pytest.mark.parametrize("body", [REAL_UDP + b"up /tmp/x.sh\n", b"\xff\xfe\x00"])
def test_bad_config_is_rejected_and_not_cached(tmp_path: Path, body: bytes) -> None:
    api, _ = make_api(tmp_path, routes={UDP_CONFIG_URL: body})
    assert error_code(lambda: api.config("us12941", VpnProtocol.UDP)) is ErrorCode.INVALID_CONFIG
    assert not (Paths.under(tmp_path).configs_dir / "us12941.udp.ovpn").exists()


def test_tampered_cached_config_is_discarded(tmp_path: Path) -> None:
    path = make_api(tmp_path)[0].config("us12941", VpnProtocol.UDP)
    with path.open("a") as fh:
        fh.write("plugin /tmp/evil.so\n")
    api, fetch = make_api(tmp_path)
    api.config("us12941", VpnProtocol.UDP)
    assert fetch.calls == [UDP_CONFIG_URL]
    assert path.read_bytes() == REAL_UDP


def test_redirect_to_http_is_refused() -> None:
    handler = _HTTPSOnlyRedirects()
    request = urllib.request.Request("https://api.nordvpn.com/v1/servers/countries")
    with pytest.raises(urllib.error.HTTPError, match="non-HTTPS"):
        handler.redirect_request(request, io.BytesIO(), 302, "Found", HTTPMessage(), "http://x/")
    follow = handler.redirect_request(
        request, io.BytesIO(), 302, "Found", HTTPMessage(), "https://api.nordvpn.com/v2"
    )
    assert follow is not None
    assert follow.full_url == "https://api.nordvpn.com/v2"


def test_urllib_fetch_refuses_plain_http() -> None:
    with pytest.raises(FetchError, match="non-HTTPS"):
        urllib_fetch("http://api.nordvpn.com/v1/servers/countries")
