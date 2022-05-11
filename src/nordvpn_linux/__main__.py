# SPDX-License-Identifier: GPL-3.0-only
"""Entry point for ``python -m nordvpn_linux`` and the ``nordvpn.pyz`` zipapp.

The first argument picks the program: ``daemon`` runs nordvpnd; ``cli`` (or
anything else) runs the nordvpn client. Imports are deferred so the CLI never
loads daemon code.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if args[:1] == ["daemon"]:
        from nordvpn_linux.daemon.main import main as daemon_main

        return daemon_main(args[1:])
    if args[:1] == ["cli"]:
        args = args[1:]
    from nordvpn_linux.cli.main import main as cli_main

    return cli_main(args)


if __name__ == "__main__":
    sys.exit(main())
