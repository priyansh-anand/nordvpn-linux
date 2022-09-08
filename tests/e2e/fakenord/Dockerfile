# SPDX-License-Identifier: GPL-3.0-only
FROM debian:12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends openvpn openssl python3 iproute2 \
 && rm -rf /var/lib/apt/lists/*
COPY . /fakenord
RUN chmod 0755 /fakenord/*.sh
ENTRYPOINT ["/fakenord/entrypoint.sh"]
