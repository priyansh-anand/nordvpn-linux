# SPDX-License-Identifier: GPL-3.0-only
"""Top-level entry point of nordvpn.pyz; propagates the exit status."""

import sys

from nordvpn_linux.__main__ import main

sys.exit(main())
