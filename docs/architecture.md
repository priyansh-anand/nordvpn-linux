# Architecture

```
 unprivileged user                          root (systemd: nordvpnd.service)
┌───────────────────┐  JSON lines over   ┌─────────────────────────────────────────┐
│ nordvpn (CLI)     │  /run/nordvpn/     │ nordvpnd                                │
│  cli/main.py      │──nordvpnd.sock────▶│  daemon/server.py   peer auth, framing  │
│  cli/client.py    │  0660 root:nordvpn │  daemon/service.py  commands, one lock  │
└───────────────────┘                    │  daemon/nordapi.py  API + CDN (HTTPS)   │
                                         │  daemon/ovpn.py     directive allowlist │
                                         │  daemon/store.py    credentials 0600    │
                                         │  daemon/tunnel.py   OpenVPN + states    │
                                         │     │ management socket (root-only)     │
                                         │     ▼                                   │
                                         │  openvpn --dev nordtun …                │
                                         │  daemon/dns.py      resolvectl nordtun  │
                                         └─────────────────────────────────────────┘
```

## Protocol

Each message is one JSON object on one line, UTF-8, at most 64 KiB (`protocol.py`).

- Request: `{"v": 1, "id": N, "cmd": "...", "args": {...}}`
- Progress event (only during `connect`): `{"v": 1, "id": N, "event": "state", "state": "...", "detail": "..."}`
- Final response: `{"v": 1, "id": N, "ok": true, "result": {...}}` or `{"v": 1, "id": N, "ok": false, "error": {"code": "...", "message": "..."}}`

Commands: `status`, `connect {target}`, `disconnect`, `login {username, password}`, `logout`, `countries`, `settings.get`, `settings.set {key, value}`. If the client hangs up while a request runs, the daemon cancels it.

## Connecting

1. Parse the target (`targets.py`): nearest, a country, or a hostname. Anything else is rejected.
2. Nearest only: tear down any current tunnel, so NordVPN sees your real location.
3. Resolve a server (`nordapi.recommend`), then download and validate its config (`nordapi.config`, cached for 7 days and re-validated on every load).
4. Tear down any current tunnel. This happens only now, so a failed lookup keeps a working connection.
5. Start OpenVPN with a fixed argv and drive it over the management socket: `hold release`, answer the `Auth` prompt, follow `>STATE:`, `>BYTECOUNT:` and `>PASSWORD:`.
6. Once connected, point `nordtun`'s DNS at NordVPN's resolvers with `resolvectl`.

## Tunnel states

```
DISCONNECTED ──start──▶ CONNECTING ──CONNECTED──▶ CONNECTED ◀──▶ RECONNECTING
      ▲                     │                         │
      └──── FAILED ◀────────┴── auth failure / fatal / timeout / cancel / OpenVPN exit
```

`FAILED` is reported, and then the tunnel returns to `DISCONNECTED` with `last_error` set, which `status` shows.

## Testing

- Unit tests cover each module.
- Integration tests run the real server and service in-process, driving `tests/fakes/fake_openvpn.py` over a real management socket.
- The e2e tests (`tests/e2e`) install the real `.deb` in a systemd container and connect through real OpenVPN to a fake NordVPN container.
