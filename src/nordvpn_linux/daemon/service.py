# SPDX-License-Identifier: GPL-3.0-only
"""What each IPC command does: the daemon's behaviour behind the socket."""

from __future__ import annotations

import asyncio
import logging

from nordvpn_linux.daemon.dns import DnsConfigurator, DnsStatus
from nordvpn_linux.daemon.nordapi import NordAPI, ServerInfo
from nordvpn_linux.daemon.server import EventSink
from nordvpn_linux.daemon.store import Credentials, CredentialStore, SettingsStore, VpnProtocol
from nordvpn_linux.daemon.tunnel import DEVICE, Tunnel, TunnelInfo, TunnelState
from nordvpn_linux.errors import ErrorCode, NordVPNError
from nordvpn_linux.protocol import Command, JSONObject, Request
from nordvpn_linux.targets import Country, Host, Nearest, Target, parse_target

log = logging.getLogger(__name__)

_UP = (TunnelState.CONNECTED, TunnelState.RECONNECTING)


def status_payload(info: TunnelInfo, dns: DnsStatus) -> JSONObject:
    error = info.last_error
    return {
        "state": info.state.value,
        "server": info.server or None,
        "country": info.country or None,
        "protocol": info.protocol or None,
        "remote_ip": info.remote_ip or None,
        "connected_since": info.connected_since.isoformat() if info.connected_since else None,
        "rx_bytes": info.rx_bytes,
        "tx_bytes": info.tx_bytes,
        "dns": dns.value,
        "last_error": {"code": error.code.value, "message": error.message} if error else None,
    }


class Service:
    """Implements every command. One lock serialises everything that changes state."""

    def __init__(
        self,
        *,
        api: NordAPI,
        tunnel: Tunnel,
        dns: DnsConfigurator,
        credentials: CredentialStore,
        settings: SettingsStore,
        connect_timeout: float,
    ) -> None:
        self._api = api
        self._tunnel = tunnel
        self._dns = dns
        self._credentials = credentials
        self._settings = settings
        self._connect_timeout = connect_timeout
        self._lock = asyncio.Lock()
        self._dns_status = DnsStatus.DISABLED

    async def handle(self, request: Request, emit: EventSink) -> JSONObject:
        args = request.args
        match request.cmd:
            case Command.STATUS:
                return self.status()
            case Command.CONNECT:
                return await self.connect(args.get("target"), emit)
            case Command.DISCONNECT:
                return await self.disconnect()
            case Command.LOGIN:
                return await self.login(args.get("username"), args.get("password"))
            case Command.LOGOUT:
                return await self.logout()
            case Command.COUNTRIES:
                return await self.countries()
            case Command.SETTINGS_GET:
                return self._settings.load().to_json()
            case Command.SETTINGS_SET:
                return await self.set_setting(args.get("key"), args.get("value"))
        raise NordVPNError(ErrorCode.BAD_REQUEST, f"unsupported command {request.cmd!r}")

    def status(self) -> JSONObject:
        info = self._tunnel.snapshot()
        return status_payload(info, self._dns_status if info.state in _UP else DnsStatus.DISABLED)

    async def connect(self, raw_target: object, emit: EventSink) -> JSONObject:
        target = parse_target(raw_target)  # reject bad input before touching anything
        async with self._lock:
            credentials = self._credentials.load()
            if credentials is None:
                raise NordVPNError(ErrorCode.NOT_LOGGED_IN, "you are not logged in")
            settings = self._settings.load()
            remove_listener = self._tunnel.add_listener(
                lambda state, detail: emit(state.value, detail)
            )
            try:
                if isinstance(target, Nearest) and self._tunnel.active:
                    await self._teardown()  # "nearest" must be judged from our real IP
                emit(TunnelState.CONNECTING.value, "finding a server")
                server = await asyncio.to_thread(self._resolve, target, settings.protocol)
                emit(TunnelState.CONNECTING.value, f"downloading the config for {server.hostname}")
                config = await asyncio.to_thread(
                    self._api.config, server.hostname, settings.protocol
                )
                if self._tunnel.active:
                    await self._teardown()  # only now: a failed lookup keeps the old tunnel
                await self._tunnel.connect(
                    config=config,
                    server=server.hostname,
                    country=server.country,
                    protocol=settings.protocol.value,
                    credentials=credentials,
                    timeout=self._connect_timeout,
                )
                self._dns_status = (
                    await self._dns.apply(DEVICE) if settings.dns else DnsStatus.DISABLED
                )
            finally:
                remove_listener()
            return self.status()

    def _resolve(self, target: Target, protocol: VpnProtocol) -> ServerInfo:
        if isinstance(target, Host):
            return ServerInfo(target.name, self._api.country_name_for_host(target.name))
        country = self._api.find_country(target.query) if isinstance(target, Country) else None
        return self._api.recommend(country, protocol)

    async def disconnect(self) -> JSONObject:
        async with self._lock:
            await self._teardown()
            return self.status()

    async def login(self, username: object, password: object) -> JSONObject:
        credentials = Credentials.from_untrusted(username, password)
        async with self._lock:
            await asyncio.to_thread(self._credentials.save, credentials)
        log.info("service credentials updated")
        return {}

    async def logout(self) -> JSONObject:
        async with self._lock:
            await self._teardown()
            self._credentials.clear()
        log.info("service credentials removed")
        return {}

    async def countries(self) -> JSONObject:
        countries = await asyncio.to_thread(self._api.countries)
        return {"countries": [{"code": c.code, "name": c.name} for c in countries]}

    async def set_setting(self, key: object, value: object) -> JSONObject:
        async with self._lock:
            return self._settings.update(key, value).to_json()

    async def shutdown(self) -> None:
        async with self._lock:
            await self._teardown()

    async def _teardown(self) -> None:
        if self._dns_status is DnsStatus.APPLIED:
            await self._dns.revert(DEVICE)
        self._dns_status = DnsStatus.DISABLED
        await self._tunnel.stop()
