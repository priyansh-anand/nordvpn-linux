#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# After removal: let systemd forget the unit. The group and /etc/nordvpn are kept.
set -e
if [ -d /run/systemd/system ]; then
    systemctl daemon-reload || true
fi
