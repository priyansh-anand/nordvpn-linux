# Architecture

```mermaid
flowchart TB
    subgraph user["Unprivileged user"]
        cli["nordvpn CLI<br/>cli/main.py · cli/client.py"]
    end

    subgraph root["root (systemd: nordvpnd.service)"]
        server["daemon/server.py<br/>framing · peer auth (SO_PEERCRED)"]
        service["daemon/service.py<br/>commands · one lock"]
        nordapi["daemon/nordapi.py<br/>API + CDN over HTTPS · caches"]
        ovpn["daemon/ovpn.py<br/>directive allowlist"]
        store["daemon/store.py<br/>credentials 0600 · settings"]
        tunnel["daemon/tunnel.py<br/>OpenVPN process + state machine"]
        dns["daemon/dns.py<br/>resolvectl nordtun"]
        openvpn(["openvpn --dev nordtun"])
    end

    subgraph internet["Internet"]
        nord[("NordVPN API / CDN")]
    end

    cli -- "JSON lines over /run/nordvpn/nordvpnd.sock (0660 root:nordvpn)" --> server
    server --> service
    service --> store
    service --> nordapi
    service --> tunnel
    service --> dns
    nordapi --> ovpn
    nordapi -- HTTPS --> nord
    tunnel -- "management socket (/run/nordvpn/private, 0700)" --> openvpn
```

## Protocol

Each message is one JSON object on one line, UTF-8, at most 64 KiB (`protocol.py`).

- Request: `{"v": 1, "id": N, "cmd": "...", "args": {...}}`
- Progress event (only during `connect`): `{"v": 1, "id": N, "event": "state", "state": "...", "detail": "..."}`
- Final response: `{"v": 1, "id": N, "ok": true, "result": {...}}` or `{"v": 1, "id": N, "ok": false, "error": {"code": "...", "message": "..."}}`

Commands: `status`, `connect {target}`, `disconnect`, `login {username, password}`, `logout`, `countries`, `settings.get`, `settings.set {key, value}`. If the client hangs up during a `connect`, the daemon cancels the attempt. Every other command runs to completion.

## Connecting

```mermaid
sequenceDiagram
    autonumber
    participant CLI as nordvpn
    participant D as nordvpnd
    participant API as NordVPN API / CDN
    participant O as openvpn

    CLI->>D: connect {target}
    D->>D: parse target (nearest / country / hostname), reject anything else
    opt target is "nearest" and a tunnel is up
        D->>O: signal SIGTERM (so the lookup sees the real IP)
    end
    D->>API: recommendations (load-aware)
    API-->>D: hostname
    D->>API: download .ovpn (cached 7 days, re-validated on every load)
    D->>D: allowlist-validate the config
    opt a tunnel is still up
        D->>O: signal SIGTERM (only now, so a failed lookup keeps it)
    end
    D->>O: start with a fixed argv
    D->>O: hold release · answer the Auth prompt
    O-->>D: >STATE: … CONNECTED
    D-->>CLI: progress events …
    D->>D: resolvectl: point nordtun's DNS at NordVPN
    D-->>CLI: status (CONNECTED)
```

## Tunnel states

```mermaid
stateDiagram-v2
    [*] --> DISCONNECTED
    DISCONNECTED --> CONNECTING: start
    CONNECTING --> CONNECTED: >STATE CONNECTED
    CONNECTED --> RECONNECTING: >STATE RECONNECTING
    RECONNECTING --> CONNECTED: >STATE CONNECTED
    CONNECTING --> FAILED: auth failure · fatal · timeout · cancel · OpenVPN exit
    CONNECTED --> FAILED: fatal · OpenVPN exit
    RECONNECTING --> FAILED: auth failure · fatal · OpenVPN exit
    FAILED --> DISCONNECTED: reported, last_error kept
    CONNECTED --> DISCONNECTED: stop
    RECONNECTING --> DISCONNECTED: stop
```

`FAILED` is reported, and then the tunnel returns to `DISCONNECTED` with `last_error` set, which `status` shows. Teardown always runs to completion, even if the request that started it is cancelled.

## Testing

- Unit tests cover each module.
- Integration tests run the real server and service in-process, driving `tests/fakes/fake_openvpn.py` over a real management socket.
- The e2e tests (`tests/e2e`) install the real `.deb` in a systemd container and connect through real OpenVPN to a fake NordVPN container.
