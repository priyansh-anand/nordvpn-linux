# Contributing

## Setup

You need [uv](https://docs.astral.sh/uv/) and Docker (Docker is only needed for packages and end-to-end tests).

```sh
make dev                    # create .venv with the dev tools
uvx pre-commit install      # optional: lint on commit
```

## Checks

| Command | What it runs |
|---|---|
| `make fmt` | ruff fixes + formatting |
| `make lint` | ruff lint + format check |
| `make typecheck` | mypy --strict |
| `make test` | unit + integration tests; fails if daemon coverage drops below 90% |
| `make shellcheck` | shellcheck on every shell script |
| `make e2e` | builds the .deb and runs the Docker end-to-end suite |

Unit and integration tests run on Linux and macOS without root. The daemon is tested in-process against `tests/fakes/fake_openvpn.py`, a stand-in that speaks OpenVPN's management protocol. The e2e suite runs real OpenVPN against a fake NordVPN (`tests/e2e/fakenord`), so no NordVPN account is needed. Set `E2E_KEEP=1` to leave the stack running for debugging, and `E2E_SOAK_SECONDS` to shorten the long-session test.

Before a release, also run a live smoke test by hand: install the `.deb` on a real machine or VM, then log in with real service credentials, connect, check that `curl https://ipinfo.io/ip` shows a NordVPN address, and disconnect.

## Conventions

- Stdlib only at runtime. A new runtime dependency needs a very good reason, because the daemon runs as root.
- New OpenVPN directives go into the allowlist only after checking the manual for anything that runs code or touches files.
- Every `.py` file starts with `# SPDX-License-Identifier: GPL-3.0-only`.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:` and so on).
- User-visible changes go into `CHANGELOG.md` under `## [Unreleased]`.

## Releasing

1. Bump `__version__` in `src/nordvpn_linux/__init__.py`.
2. Move the `Unreleased` changelog entries under `## [X.Y.Z] - YYYY-MM-DD`.
3. Commit, tag `vX.Y.Z` and push the tag. `release.yml` builds and publishes the packages.
