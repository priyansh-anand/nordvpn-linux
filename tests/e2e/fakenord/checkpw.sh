#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# OpenVPN auth-user-pass-verify (via-file): line 1 is the username, line 2 the password.
set -eu
{ read -r user; read -r pass; } < "$1"
[ "$user" = "e2e-user" ] && [ "$pass" = "e2e-pass" ]
