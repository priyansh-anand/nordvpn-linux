#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# Before removal (not upgrade): stop and disable the daemon.
# deb passes "upgrade" on upgrade; rpm passes 1 (packages remaining) on upgrade.
set -e
case "${1:-}" in
    upgrade|1) exit 0 ;;
esac
if [ -d /run/systemd/system ]; then
    systemctl disable --now nordvpnd.service >/dev/null 2>&1 || true
fi
