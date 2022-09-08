#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# Throwaway PKI for the e2e tests: a CA, the VPN server cert and the HTTPS cert.
set -eu
dir=$1
[ -f "$dir/ca.crt" ] && exit 0
mkdir -p "$dir"
cd "$dir"

openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=fakenord test CA" \
    -keyout ca.key -out ca.crt \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash"

issue() {  # issue NAME COMMON_NAME EXTENSIONS
    openssl req -newkey rsa:2048 -nodes -subj "/CN=$2" -keyout "$1.key" -out "$1.csr"
    printf '%s\n' "$3" > "$1.ext"
    openssl x509 -req -in "$1.csr" -CA ca.crt -CAkey ca.key -CAcreateserial -days 30 \
        -out "$1.crt" -extfile "$1.ext"
}

issue vpn xx1.nordvpn.com "basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid"

issue web api.fakenord.test "basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid
subjectAltName=DNS:api.fakenord.test,DNS:cdn.fakenord.test"

openvpn --genkey secret ta.key
chmod 0644 ca.crt
