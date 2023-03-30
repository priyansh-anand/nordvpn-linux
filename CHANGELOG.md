# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [2.0.0] - 2023-03-30

A ground-up rewrite. Remove 1.x before installing (see "Upgrading from 1.x" in the README).

### Security

- Fixed a local privilege escalation. Any local user could make the root daemon run OpenVPN with a config of their choosing, and so run arbitrary commands, through the world-writable `/run/nordvpn.sock`. The daemon now accepts only a country or server name, only from members of the `nordvpn` group, and validates every config against a directive allowlist.
- Credentials are stored root-only and handed to OpenVPN over its management interface. They used to sit in a world-readable, world-writable file.
- The configuration is no longer world-writable. Downloads are HTTPS-only, including redirects.
- The nearest-country lookup no longer uses plain-HTTP ip-api.com.
- The daemon runs under a hardened systemd unit (only `CAP_NET_ADMIN`, read-only filesystem, restricted system calls).

### Fixed

- Long sessions no longer freeze once OpenVPN's unread log output fills a pipe.
- DNS now goes through the tunnel (via systemd-resolved); it used to leak.
- Connecting while already connected now replaces the tunnel cleanly, and a failed switch keeps the working one.

### Changed

- Servers are chosen by NordVPN's load-aware recommendations API. The 25 MB config zip and `sync-ovpn` are gone.
- `login` asks for NordVPN *service credentials* and supports `--username` / `--password-stdin`.
- Added `countries`, `settings`, `set protocol`, `set dns` and `status --json`.
- Exit codes are stable and documented; errors come with hints.
- Bash, zsh and fish completions.
- Installed from .deb, .rpm or Arch packages, or `make install`. No more `pip3 install` into system Python.

### Removed

- `sync-ovpn`, `install.sh`, `uninstall.sh`, the `/opt/nordvpn` layout and the `nvpn` alias.

## [1.3] - 2021-03-15

- Bash completion; moved `requirements.txt` and the service file to `misc/`.

## [1.2]

- README, license, `/opt/nordvpn` install location.

## [1.1]

- Ctrl-C stops a connection attempt.
