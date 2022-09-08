#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# Fake NordVPN: real OpenVPN servers (UDP + TCP) plus a fake API/CDN.
set -eu
/fakenord/make-pki.sh /pki
mkdir -p /dev/net
[ -c /dev/net/tun ] || mknod /dev/net/tun c 10 200
openvpn --config /fakenord/server.conf --proto udp --port 1194 --dev tun0 \
    --server 10.8.0.0 255.255.255.0 --daemon ovpn-udp --log /var/log/ovpn-udp.log
openvpn --config /fakenord/server.conf --proto tcp-server --port 1443 --dev tun1 \
    --server 10.9.0.0 255.255.255.0 --daemon ovpn-tcp --log /var/log/ovpn-tcp.log
exec python3 /fakenord/api.py
