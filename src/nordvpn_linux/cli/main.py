# SPDX-License-Identifier: GPL-3.0-only
"""``nordvpn``: the unprivileged command-line client."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from nordvpn_linux import __version__
from nordvpn_linux.cli.client import Client, DaemonUnavailableError
from nordvpn_linux.cli.ui import Spinner, Style, render_countries, render_settings, render_status
from nordvpn_linux.errors import (
    EXIT_CANCELLED,
    EXIT_DAEMON_UNREACHABLE,
    EXIT_OK,
    EXIT_USAGE,
    ErrorCode,
    NordVPNError,
    exit_code_for,
)
from nordvpn_linux.paths import DEFAULT_SOCKET
from nordvpn_linux.protocol import Command, Event, JSONObject

SERVICE_CREDENTIALS_HELP = """\
NordVPN's OpenVPN servers need your *service credentials*, not your account email and password.
Find them at https://my.nordaccount.com -> NordVPN -> "Set up NordVPN manually"."""

HINTS: dict[ErrorCode, str] = {
    ErrorCode.PERMISSION_DENIED: (
        "add yourself to the 'nordvpn' group, then log out and back in:\n"
        "    sudo usermod -aG nordvpn $USER"
    ),
    ErrorCode.NOT_LOGGED_IN: "log in first: nordvpn login",
    ErrorCode.AUTH_FAILED: (
        "check your service credentials (not your account password), then run: nordvpn login"
    ),
    ErrorCode.INVALID_TARGET: "list available countries with: nordvpn countries",
    ErrorCode.UNKNOWN_SERVER: "list available countries with: nordvpn countries",
    ErrorCode.TUNNEL_FAILED: "see the daemon log: journalctl -u nordvpnd",
    ErrorCode.INTERNAL: "see the daemon log: journalctl -u nordvpnd",
}

Handler = Callable[[Client, argparse.Namespace], int]


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Handler = args.handler
    try:
        return handler(Client(args.socket), args)
    except KeyboardInterrupt:
        print(file=sys.stderr)
        _error("cancelled")
        return EXIT_CANCELLED
    except DaemonUnavailableError as exc:
        _error(
            f"cannot reach the NordVPN daemon: {exc}",
            "is it running? check: systemctl status nordvpnd",
        )
        return EXIT_DAEMON_UNREACHABLE
    except NordVPNError as exc:
        _error(exc.message, HINTS.get(exc.code))
        return exit_code_for(exc.code)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nordvpn", description="Unofficial NordVPN client for Linux, built on OpenVPN."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--socket", type=Path, default=DEFAULT_SOCKET, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    login = commands.add_parser("login", help="save your NordVPN service credentials")
    login.add_argument("--username", help="service username (prompted for if omitted)")
    login.add_argument(
        "--password-stdin", action="store_true", help="read the password from standard input"
    )
    login.set_defaults(handler=cmd_login)

    logout = commands.add_parser("logout", help="disconnect and forget the saved credentials")
    logout.set_defaults(handler=cmd_logout)

    connect = commands.add_parser("connect", aliases=["c"], help="connect to NordVPN")
    connect.add_argument(
        "target",
        nargs="?",
        help='country code (us), country name ("united states") or server (us1234); '
        "default: the nearest server",
    )
    connect.set_defaults(handler=cmd_connect)

    disconnect = commands.add_parser("disconnect", aliases=["d"], help="disconnect from NordVPN")
    disconnect.set_defaults(handler=cmd_disconnect)

    status = commands.add_parser("status", aliases=["s"], help="show the connection status")
    status.add_argument("--json", action="store_true", help="machine-readable output")
    status.set_defaults(handler=cmd_status)

    countries = commands.add_parser("countries", help="list the countries you can connect to")
    output = countries.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="machine-readable output")
    output.add_argument("--plain", action="store_true", help="country codes only, one per line")
    countries.set_defaults(handler=cmd_countries)

    settings = commands.add_parser("settings", help="show the current settings")
    settings.add_argument("--json", action="store_true", help="machine-readable output")
    settings.set_defaults(handler=cmd_settings)

    set_ = commands.add_parser("set", help="change a setting")
    keys = set_.add_subparsers(dest="key", required=True, metavar="<setting>")
    keys.add_parser("protocol", help="OpenVPN transport").add_argument(
        "value", choices=["udp", "tcp"]
    )
    keys.add_parser("dns", help="use NordVPN's DNS while connected").add_argument(
        "value", choices=["on", "off"]
    )
    set_.set_defaults(handler=cmd_set)
    return parser


def cmd_login(client: Client, args: argparse.Namespace) -> int:
    if args.password_stdin and not args.username:
        _error("--password-stdin needs --username")
        return EXIT_USAGE
    if not args.password_stdin:
        print(SERVICE_CREDENTIALS_HELP, file=sys.stderr)
    try:
        username = (args.username or input("Service username: ")).strip()
        if args.password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
        else:
            password = getpass.getpass("Service password: ")
    except EOFError:
        _error("no credentials entered")
        return EXIT_USAGE
    if not username or not password:
        _error("a username and a password are required")
        return EXIT_USAGE
    client.call(Command.LOGIN, {"username": username, "password": password})
    print("Logged in. Connect with: nordvpn connect")
    return EXIT_OK


def cmd_logout(client: Client, args: argparse.Namespace) -> int:
    client.call(Command.LOGOUT)
    print("Logged out.")
    return EXIT_OK


def cmd_connect(client: Client, args: argparse.Namespace) -> int:
    with Spinner("Connecting to NordVPN") as spinner:

        def on_event(event: Event) -> None:
            if event.detail:
                spinner.update(event.detail[:1].upper() + event.detail[1:])

        status = client.call(
            Command.CONNECT, {"target": args.target}, on_event=on_event, timeout=None
        )
    server = str(status.get("server") or "NordVPN")
    where = f"{server} ({status['country']})" if status.get("country") else server
    print(f"Connected to {Style(sys.stdout).bold(where)}.")
    _warn_about_dns(status)
    return EXIT_OK


def cmd_disconnect(client: Client, args: argparse.Namespace) -> int:
    client.call(Command.DISCONNECT)
    print("Disconnected.")
    return EXIT_OK


def cmd_status(client: Client, args: argparse.Namespace) -> int:
    status = client.call(Command.STATUS)
    print(json.dumps(status, indent=2) if args.json else render_status(status, Style(sys.stdout)))
    return EXIT_OK


def cmd_countries(client: Client, args: argparse.Namespace) -> int:
    countries = client.call(Command.COUNTRIES).get("countries", [])
    if args.json:
        print(json.dumps(countries, indent=2))
    elif args.plain:
        print("\n".join(str(c["code"]) for c in countries))
    else:
        print(render_countries(countries))
    return EXIT_OK


def cmd_settings(client: Client, args: argparse.Namespace) -> int:
    settings = client.call(Command.SETTINGS_GET)
    print(json.dumps(settings, indent=2) if args.json else render_settings(settings))
    return EXIT_OK


def cmd_set(client: Client, args: argparse.Namespace) -> int:
    value: object = args.value == "on" if args.key == "dns" else args.value
    client.call(Command.SETTINGS_SET, {"key": args.key, "value": value})
    print(f"{args.key} set to {args.value}; this applies from the next connection.")
    return EXIT_OK


def _warn_about_dns(status: JSONObject) -> None:
    style = Style(sys.stderr)
    if status.get("dns") == "unavailable":
        message = "systemd-resolved is not running, so DNS queries bypass the VPN"
    elif status.get("dns") == "failed":
        message = "DNS could not be configured and may leak; see: journalctl -u nordvpnd"
    else:
        return
    print(style.yellow(f"warning: {message}"), file=sys.stderr)


def _error(message: str, hint: str | None = None) -> None:
    print(f"nordvpn: {message}", file=sys.stderr)
    if hint:
        print(f"hint: {hint}", file=sys.stderr)
