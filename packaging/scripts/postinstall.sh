#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# After install or upgrade: create the group, then (re)start the daemon.
set -e
if command -v systemd-sysusers >/dev/null 2>&1; then
    systemd-sysusers nordvpn.conf
fi
if [ -d /run/systemd/system ]; then
    systemctl daemon-reload
    systemctl enable nordvpnd.service
    systemctl restart nordvpnd.service
fi
echo "nordvpn-linux: add yourself to the 'nordvpn' group, then log in again:"
echo "    sudo usermod -aG nordvpn \$USER"
