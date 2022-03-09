# SPDX-License-Identifier: GPL-3.0-only
"""``nordvpnd``: the privileged NordVPN daemon, normally started by systemd."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from collections.abc import Sequence
from pathlib import Path

from nordvpn_linux import __version__
from nordvpn_linux.daemon.config import ConfigError, DaemonConfig, load_config
from nordvpn_linux.daemon.dns import DnsConfigurator
from nordvpn_linux.daemon.nordapi import NordAPI
from nordvpn_linux.daemon.peercred import Authorizer, group_authorizer
from nordvpn_linux.daemon.server import Server
from nordvpn_linux.daemon.service import Service
from nordvpn_linux.daemon.store import CredentialStore, SettingsStore
from nordvpn_linux.daemon.tunnel import Tunnel
from nordvpn_linux.paths import DEFAULT_CONFIG_FILE, GROUP, Paths

log = logging.getLogger("nordvpnd")

EX_CONFIG = 78  # sysexits.h: configuration error


def build_service(
    config: DaemonConfig,
    paths: Paths,
    *,
    api: NordAPI | None = None,
    tunnel: Tunnel | None = None,
    dns: DnsConfigurator | None = None,
) -> Service:
    return Service(
        api=api or NordAPI(api_base=config.api_base, configs_base=config.configs_base, paths=paths),
        tunnel=tunnel or Tunnel(openvpn=config.openvpn, management_socket=paths.management_socket),
        dns=dns or DnsConfigurator(config.dns_servers),
        credentials=CredentialStore(paths.credentials_file),
        settings=SettingsStore(paths.settings_file),
        connect_timeout=config.connect_timeout,
    )


def prepare_directories(paths: Paths) -> None:
    """Create the daemon's directories. systemd normally does this; this is a fallback."""
    for directory in (paths.state_dir, paths.cache_dir, paths.configs_dir, paths.runtime_dir):
        directory.mkdir(parents=True, exist_ok=True)
    paths.state_dir.chmod(0o700)
    paths.private_dir.mkdir(mode=0o700, exist_ok=True)
    paths.private_dir.chmod(0o700)  # mkdir's mode is filtered by the umask


async def run(
    config: DaemonConfig,
    paths: Paths,
    *,
    authorizer: Authorizer,
    group: str | None,
    service: Service | None = None,
    stop: asyncio.Event | None = None,
    install_signal_handlers: bool = True,
) -> None:
    prepare_directories(paths)
    service = service or build_service(config, paths)
    server = Server(
        path=paths.socket,
        dispatcher=service,
        authorizer=authorizer,
        group=group,
        mode=0o660 if group else 0o600,
    )
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    signals = (signal.SIGTERM, signal.SIGINT) if install_signal_handlers else ()
    for signum in signals:
        loop.add_signal_handler(signum, stop.set)
    await server.start()
    log.info("nordvpnd %s ready", __version__)
    try:
        await stop.wait()
    finally:
        log.info("shutting down")
        await server.close()
        await service.shutdown()
        for signum in signals:
            loop.remove_signal_handler(signum)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nordvpnd", description="NordVPN daemon (runs as root, normally under systemd)."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_FILE, help="config file")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"nordvpnd: invalid configuration: {exc}", file=sys.stderr)
        return EX_CONFIG
    logging.basicConfig(
        level=config.log_level.upper(),
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if os.geteuid() != 0:
        log.error("nordvpnd must run as root; it is normally started by systemd")
        return 1
    try:
        asyncio.run(run(config, Paths(), authorizer=group_authorizer(GROUP), group=GROUP))
    except (RuntimeError, OSError) as exc:
        log.critical("nordvpnd could not start: %s", exc)
        return 1
    return 0
