#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""A stand-in for the ``openvpn`` binary that speaks the management protocol.

It reads just enough of the real argv to find the management socket, then plays
the scenario named by FAKE_OPENVPN_SCENARIO:

  ok                   authenticate, report CONNECTED, then idle
  auth_fail            always reject the credentials
  hang                 never get past the hold
  fatal                report a fatal error and exit
  exit_early           exit before opening the management socket
  crash_after_connect  connect, then die
  reconnect            connect, report RECONNECTING, then CONNECTED again

Expected credentials come from FAKE_OPENVPN_USER and FAKE_OPENVPN_PASS. If
FAKE_OPENVPN_LOG is set, a JSON line {"pid": ..., "argv": [...]} is appended to it.
"""

from __future__ import annotations

import json
import os
import shlex
import socket
import sys
import time
from pathlib import Path


class Session:
    def __init__(self, conn: socket.socket, scenario: str) -> None:
        self.conn = conn
        self.reader = conn.makefile("rb")
        self.scenario = scenario

    def send(self, line: str) -> None:
        self.conn.sendall(line.encode() + b"\n")

    def state(self, name: str, desc: str = "", local: str = "", remote: str = "") -> None:
        self.send(f">STATE:{int(time.time())},{name},{desc},{local},{remote},1194,,")

    def command(self) -> list[str] | None:
        raw = self.reader.readline()
        if not raw:
            return None
        words = shlex.split(raw.decode())
        if words[:2] == ["signal", "SIGTERM"]:
            self.send("SUCCESS: signal SIGTERM thrown")
            self.state("EXITING", "SIGTERM")
            raise SystemExit(0)
        self.send(f"SUCCESS: {words[0] if words else ''} done")
        return words

    def wait_for(self, *prefix: str) -> list[str]:
        while (words := self.command()) is not None:
            if words[: len(prefix)] == list(prefix):
                return words
        raise SystemExit(0)  # the management client went away

    def idle(self) -> int:
        while self.command() is not None:
            pass
        return 0

    def run(self) -> int:
        self.send(">INFO:OpenVPN Management Interface Version 5 -- type 'help' for more info")
        self.send(">HOLD:Waiting for hold release:0")
        self.wait_for("hold", "release")
        if self.scenario == "hang":
            return self.idle()
        if self.scenario == "fatal":
            self.send(">FATAL:Cannot open TUN/TAP dev /dev/net/tun: No such file or directory")
            return 1
        self.state("WAIT")
        self.state("AUTH")
        self.send(">PASSWORD:Need 'Auth' username/password")
        user = self.wait_for("username", "Auth")[2]
        password = self.wait_for("password", "Auth")[2]
        expected = (
            os.environ.get("FAKE_OPENVPN_USER", "user"),
            os.environ.get("FAKE_OPENVPN_PASS", "secret"),
        )
        if self.scenario == "auth_fail" or (user, password) != expected:
            self.send(">PASSWORD:Verification Failed: 'Auth'")
            return 1
        self.state("GET_CONFIG")
        self.state("ASSIGN_IP", local="10.8.0.2")
        self.state("CONNECTED", "SUCCESS", "10.8.0.2", "203.0.113.7")
        self.send(">BYTECOUNT:1024,2048")
        if self.scenario == "crash_after_connect":
            time.sleep(0.2)
            os._exit(1)
        if self.scenario == "reconnect":
            self.state("RECONNECTING", "ping-restart")
            time.sleep(0.1)
            self.state("CONNECTED", "SUCCESS", "10.8.0.2", "203.0.113.7")
        return self.idle()


def main(argv: list[str]) -> int:
    scenario = os.environ.get("FAKE_OPENVPN_SCENARIO", "ok")
    log = os.environ.get("FAKE_OPENVPN_LOG")
    if log:
        with Path(log).open("a") as fh:
            fh.write(json.dumps({"pid": os.getpid(), "argv": argv}) + "\n")
    if scenario == "exit_early":
        return 1
    path = argv[argv.index("--management") + 1]
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)
    conn, _ = server.accept()
    return Session(conn, scenario).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
