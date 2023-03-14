# Security Policy

## Supported versions

Only the latest 2.x release receives security fixes. 1.x is unsupported and has a known local privilege escalation, so upgrade.

## Reporting a vulnerability

Please report privately, not in a public issue:

- GitHub: **Security → Report a vulnerability** on this repository, or
- email pr1y4nsh@protonmail.com.

Include the version, your distribution, and steps to reproduce. You should get a reply within a week.

## Threat model

`nordvpnd` runs as root, because OpenVPN needs `CAP_NET_ADMIN`. The design limits what that privilege can be used for:

| Actor | Can | Cannot |
|---|---|---|
| Any local user | nothing: `/run/nordvpn` is `0750 root:nordvpn` | reach the daemon socket |
| Member of `nordvpn` | log in/out; connect to "nearest", a country or a server hostname; change protocol/DNS | name a file, pass OpenVPN options, or read stored credentials |
| Network attacker | observe traffic | tamper with API or config downloads (HTTPS with certificate verification; redirects to plain HTTP are refused) |

Controls:

1. **Intent-only requests.** Connect targets are validated against a strict grammar (`targets.py`). Paths can never reach the daemon.
2. **Config allowlist.** Every downloaded `.ovpn`, whether fresh or cached, must use only allowlisted directives (`daemon/ovpn.py`); `up`, `plugin`, `script-security` and similar are rejected. `remote` and `verify-x509-name` must match the requested server.
3. **Fixed OpenVPN command line.** No shell; `--script-security 1` and the management settings override the config.
4. **Credentials.** They are stored `0600 root` with atomic writes, passed to OpenVPN only over a root-only management socket, and never logged or returned.
5. **Peer checks.** Filesystem permissions are the primary gate. `SO_PEERCRED` is also checked on every connection and logged with the uid.
6. **systemd sandbox.** Only `CAP_NET_ADMIN`; read-only filesystem apart from the daemon's own directories; restricted address families and system calls; no new privileges. The e2e suite requires a `systemd-analyze security` exposure score of 4.0 or lower.
7. **Import hygiene.** The launchers run `python3 -I` on a root-owned zipapp. There are no third-party runtime dependencies.

Out of scope: a malicious root user, a compromised NordVPN API or CDN serving a validly-shaped config for a server you asked for, and traffic leaks while *disconnected* (there is no kill switch yet).
