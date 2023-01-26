# nordvpn-linux

An unofficial, security-focused NordVPN client for Linux, built on OpenVPN.

```console
$ nordvpn connect us
Connected to us12941 (United States).
$ nordvpn status
Status:     Connected
Server:     us12941 (United States)
Protocol:   UDP
Remote IP:  187.15.89.138
Uptime:     4m 12s
Traffic:    38.2 MiB received, 2.1 MiB sent
DNS:        NordVPN DNS (systemd-resolved)
```

- **Least privilege.** A small root daemon (`nordvpnd`) runs OpenVPN. It accepts only a country or server *name* from members of the `nordvpn` group, and it runs under a hardened systemd unit.
- **No blind trust in downloaded configs.** Every `.ovpn` is checked against an allowlist of OpenVPN directives before it runs, so a tampered config can't run commands as root.
- **Load-aware server choice.** Servers come from NordVPN's recommendations API, not picked at random.
- **DNS goes through the tunnel**, via systemd-resolved.
- **No third-party Python dependencies.**

> Not affiliated with Nord Security. "NordVPN" is a trademark of its owner.

## Requirements

- Linux with systemd
- Python 3.11 or newer
- OpenVPN 2.5 or newer (2.6 recommended)
- systemd-resolved (recommended; without it, DNS queries do not go through the VPN)

Supported: Debian 12+, Ubuntu 24.04+, Fedora 39+, Arch Linux.

## Install

Download the package for your distribution from the [latest release](https://github.com/priyansh-anand/nordvpn-linux/releases/latest) and verify it against `SHA256SUMS`:

```sh
# Debian / Ubuntu
sudo apt install ./nordvpn-linux_2.0.0-1_all.deb
# Fedora
sudo dnf install ./nordvpn-linux-2.0.0-1.noarch.rpm
# Arch Linux
sudo pacman -U ./nordvpn-linux-2.0.0-1-any.pkg.tar.zst && sudo systemctl enable --now nordvpnd
```

Or build from source:

```sh
git clone https://github.com/priyansh-anand/nordvpn-linux.git
cd nordvpn-linux
sudo make install            # PREFIX=/usr/local and DESTDIR=... are supported
```

Then allow your user to control the daemon, and log out and back in:

```sh
sudo usermod -aG nordvpn "$USER"
```

## Log in

OpenVPN needs your NordVPN **service credentials**, which are *not* your account email and password. To find them, go to [Nord Account](https://my.nordaccount.com), open **NordVPN**, choose **Set up NordVPN manually**, and look under **Service credentials**. Then run:

```sh
nordvpn login
# or, non-interactively:
printf '%s\n' "$PASSWORD" | nordvpn login --username "$USERNAME" --password-stdin
```

The daemon stores the credentials in `/var/lib/nordvpn/credentials`, readable only by root.

## Usage

| Command | What it does |
|---|---|
| `nordvpn connect` (`c`) | Connect to the recommended server nearest to you |
| `nordvpn connect us` | Connect to the best server in a country (code or name: `"united kingdom"`, `uk`, `gb`) |
| `nordvpn connect us1234` | Connect to a specific server |
| `nordvpn disconnect` (`d`) | Disconnect |
| `nordvpn status` (`s`) | Show the connection, traffic and DNS state (`--json` for scripts) |
| `nordvpn countries` | List countries (`--plain` for codes only, `--json`) |
| `nordvpn settings` | Show settings |
| `nordvpn set protocol tcp` | Use OpenVPN over TCP (`udp` is the default) |
| `nordvpn set dns off` | Keep the system DNS while connected (not recommended) |
| `nordvpn logout` | Disconnect and forget the credentials |

Exit codes, for scripts:

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | error |
| 2 | bad usage or unknown country/server |
| 3 | daemon not running |
| 4 | not logged in, or credentials rejected |
| 5 | not in the `nordvpn` group |
| 130 | cancelled |

Tab completion is installed for bash, zsh and fish.

## Configuration

`/etc/nordvpn/nordvpnd.toml` documents every option (log level, connect timeout, DNS servers, OpenVPN path). After editing it, run `sudo systemctl restart nordvpnd`.

## Troubleshooting

- **`nordvpn: permission denied`**: run `sudo usermod -aG nordvpn "$USER"`, then log out and back in.
- **`cannot reach the NordVPN daemon`**: check `systemctl status nordvpnd`.
- **Anything else**: the daemon and OpenVPN both log to the journal: `journalctl -u nordvpnd -e`.
- **`status` says DNS is "not protected"**: install and enable systemd-resolved (`sudo systemctl enable --now systemd-resolved`).

## Uninstall

Remove the package (`sudo apt remove nordvpn-linux`, `dnf remove`, `pacman -R`), or run `sudo make uninstall` for source installs. `/etc/nordvpn`, `/var/lib/nordvpn` and the `nordvpn` group are kept. Delete them by hand if you want them gone.

## Upgrading from 1.x

Version 2 is a rewrite and shares nothing with 1.x. Remove 1.x first:

```sh
sudo systemctl disable --now nordvpn-deamon.service
sudo rm -f /etc/systemd/system/nordvpn-deamon.service /bin/nordvpn /bin/nvpn
sudo rm -rf /opt/nordvpn
sed -i '/nvpn_completion.sh/d' ~/.bashrc
```

1.x stored your password in a world-readable file (`/opt/nordvpn/login`). If you used it on a shared machine, change your NordVPN password.

## Security

See [SECURITY.md](SECURITY.md) for the threat model and how to report a vulnerability privately.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The design is described in [docs/architecture.md](docs/architecture.md).

## License

[GPL-3.0-only](LICENSE)
