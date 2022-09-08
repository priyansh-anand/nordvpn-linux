#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# Trust the fake NordVPN's CA, shared through the pki volume.
set -eu
for _ in $(seq 60); do
    [ -f /pki/ca.crt ] && break
    sleep 1
done
cp /pki/ca.crt /usr/local/share/ca-certificates/fakenord.crt
update-ca-certificates
